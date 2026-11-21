#!/usr/bin/env python3
"""Publish final model products to GitHub Releases and a CORS-readable raw branch."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

# GitHub git repositories reject individual files >100 MiB. Keep raw assets
# below 50 MiB so Git blobs remain portable and reliable.
MAX_CHUNK_BYTES = 45 * 1024 * 1024
MAX_ASSETS = 900
SKIP_PARTS = {
    "restart", "restarts", "checkpoint", "checkpoints", "rsl", "raw",
    "input", "inputs", "logs", "log", "__pycache__", "wrf_diagnostics",
}
PRODUCT_MARKERS = ("release-assets", "products", "product", "publish", "severe", "output")
DATA_SUFFIXES = {
    ".json", ".geojson", ".npz", ".npy", ".nc", ".nc4", ".grib", ".grib2",
    ".grb", ".grb2", ".csv", ".parquet", ".zip", ".gz", ".tar", ".png",
    ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bin", ".dat",
}
FINAL_ARTIFACT_MARKERS = (
    "wrf-final-", "sideral-global-nwp-", "sideral-multimodels-",
)


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def supported(path: str, name: str) -> bool:
    filename = Path(path).name.lower()
    workflow_name = name.lower()
    if not path.startswith(".github/workflows/") or "publish-model-releases" in filename:
        return False
    if any(x in filename for x in ("validate-", "watchdog", "maestro", "launchpad")):
        return False
    return (
        "wrf" in filename
        or "multimodel" in filename
        or "global-nwp" in filename
        or "multimodel" in workflow_name
        or "global nwp" in workflow_name
    )


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "model"


def product_key(path: str, name: str) -> str:
    stem = Path(path).stem
    lowered = stem.lower()
    workflow_name = name.lower()
    if "global-nwp" in lowered or "global nwp" in workflow_name:
        return "global-nwp"
    if "multimodel" in lowered or "multimodel" in workflow_name:
        return "multimodels-05"

    # Generic/manual entry points share the same model-specific Release tags
    # as their dedicated source workflows instead of creating a competing
    # generic "manual" product.
    manual_products = {
        "sideral-brasil-wrf": ("brasil-wrf-21km", False),
        "cbr-wrf": ("cbr-wrf-4km", True),
        "cim-wrf-5km": ("cim-wrf-5km", True),
        "cim-wrf-8km": ("cim-wrf-8km", True),
        "metbr-wrf": ("metbr-wrf-4km", True),
        "tarc-wrf": ("tarc-wrf-3km", True),
    }
    if lowered in manual_products:
        prefix, include_variant = manual_products[lowered]
        source = get("SOURCE_MODEL", "icon").lower() or "icon"
        variant = get("MODEL_VARIANT", "wrf").lower() or "wrf"
        return slug(f"{prefix}-{variant}-{source}" if include_variant else f"{prefix}-{source}")
    return slug(stem)

def command(args: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args[:5]), flush=True)
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def ignored(rel: Path) -> bool:
    for part in rel.parts:
        low = part.lower()
        if low in SKIP_PARTS or "checkpoint" in low or low.startswith("rsl."):
            return True
        if low.startswith(("wrfout_d", "wrfrst_d", "cbr-wrfout-", "tarc-wrfout-", "metbr-wrfout-")):
            return True
    filename = rel.name.lower()
    if filename.startswith(("wrfout", "wrfrst", "rsl.")):
        return True
    if rel.suffix.lower() in {".log", ".tmp", ".cache", ".pyc"}:
        return True
    return False


def final_artifact_directory(path: Path) -> bool:
    name = path.name.lower()
    return any(name.startswith(prefix) for prefix in FINAL_ARTIFACT_MARKERS)


def product_file(path: Path, artifact_root: Path) -> bool:
    rel = path.relative_to(artifact_root)
    if not rel.parts or ignored(rel):
        return False
    dirs = [part.lower() for part in rel.parts[:-1]]
    under_product = any(
        marker in part or part.endswith("_json") or part.endswith("_severe")
        for part in dirs for marker in PRODUCT_MARKERS
    )
    if under_product:
        return True
    return rel.suffix.lower() in DATA_SUFFIXES or rel.name.lower().endswith(".tar.gz")


def collect(root: Path) -> list[tuple[Path, str]]:
    if not root.is_dir():
        raise FileNotFoundError(f"Artifacts directory missing: {root}")

    # Ignore intermediate segment artifacts. They contain checkpoint/raw model
    # data; only the completed workflow's final product artifacts are public.
    artifact_dirs = sorted(
        path for path in root.iterdir() if path.is_dir() and final_artifact_directory(path)
    )
    chosen: dict[str, tuple[Path, int]] = {}
    for artifact_dir in artifact_dirs:
        priority = 2 if "register-run" in artifact_dir.name.lower() else 1
        for path in sorted(artifact_dir.rglob("*")):
            if not path.is_file() or path.is_symlink() or not product_file(path, artifact_dir):
                continue
            logical = path.relative_to(artifact_dir).as_posix()
            prior = chosen.get(logical)
            if prior is None or priority >= prior[1]:
                chosen[logical] = (path, priority)

    return [(path, logical) for logical, (path, _) in sorted(chosen.items())]


def safe_name(logical: str) -> str:
    rel = Path(logical)
    parent = "--".join(slug(part) for part in rel.parts[:-1])
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", rel.stem).strip("-") or "data"
    suffix = rel.suffix
    digest = hashlib.sha256(logical.encode("utf-8")).hexdigest()[:10]
    prefix = f"{parent}--" if parent else ""
    max_stem = max(16, 170 - len(prefix) - len(suffix) - len(digest) - 1)
    return f"{prefix}{stem[:max_stem]}-{digest}{suffix}"


def split_file(source: Path, logical: str, assets_dir: Path) -> tuple[list[dict], dict]:
    size = source.stat().st_size
    filename = safe_name(logical)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    source_hash = hashlib.sha256()
    parts: list[dict] = []
    with source.open("rb") as reader:
        index = 0
        while True:
            block = reader.read(MAX_CHUNK_BYTES)
            if not block:
                break
            index += 1
            asset_name = filename if size <= MAX_CHUNK_BYTES else f"{filename}.part{index:03d}"
            target = assets_dir / asset_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(block)
            source_hash.update(block)
            parts.append({
                "name": asset_name,
                "size": len(block),
                "sha256": hashlib.sha256(block).hexdigest(),
                "contentType": mime,
                "part": index,
            })

    record = {
        "path": logical,
        "size": size,
        "sha256": source_hash.hexdigest(),
        "contentType": mime,
        "parts": parts,
    }
    if len(parts) == 1:
        record["asset"] = parts[0]["name"]
    else:
        record["chunked"] = True
        record["reassemble"] = "Concatenate parts in ascending part order to reconstruct the original file."
    return parts, record


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def publish_raw_branch(repo: str, branch: str, output: Path,
                       manifest: dict, manifest_path: Path) -> str:
    stage = output.parent / "raw-branch"
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "assets").mkdir(parents=True)

    for asset in sorted(output.iterdir()):
        if asset.is_file() and asset.name != "manifest.json":
            shutil.copy2(asset, stage / "assets" / asset.name)

    # Branch is intentionally a one-commit snapshot: force-updating the
    # product-specific branch keeps only the latest model cycle accessible.
    branch_manifest = dict(manifest)
    branch_manifest["storage"] = "raw.githubusercontent.com"
    branch_manifest["rawBaseUrl"] = (
        f"https://raw.githubusercontent.com/{repo}/{branch}"
    )
    for record in branch_manifest["files"]:
        for part in record["parts"]:
            part["url"] = (
                f"{branch_manifest['rawBaseUrl']}/assets/{quote(part['name'])}"
            )
    branch_manifest["manifestUrl"] = f"{branch_manifest['rawBaseUrl']}/manifest.json"
    write_json(stage / "manifest.json", branch_manifest)

    command(["gh", "auth", "setup-git"])
    command(["git", "init", str(stage)])
    command(["git", "-C", str(stage), "config", "user.name", "github-actions[bot]"])
    command([
        "git", "-C", str(stage), "config", "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    ])
    command(["git", "-C", str(stage), "add", "-A"])
    command(["git", "-C", str(stage), "commit", "-m", f"Publish latest {manifest['productId']} data"])
    command(["git", "-C", str(stage), "remote", "add", "origin", f"https://github.com/{repo}.git"])
    command(["git", "-C", str(stage), "push", "--force", "origin", f"HEAD:refs/heads/{branch}"])

    # Verify the public manifest and cross-origin header from the actual branch.
    manifest_url = f"https://raw.githubusercontent.com/{repo}/{branch}/manifest.json"
    request = Request(
        manifest_url,
        headers={"Origin": "https://sideral-browser-check.example", "Cache-Control": "no-cache"},
        method="GET",
    )
    with urlopen(request, timeout=40) as response:
        body = response.read()
        cors = response.headers.get("Access-Control-Allow-Origin", "")
        if response.status != 200:
            raise RuntimeError(f"Raw manifest returned HTTP {response.status}")
        if cors != "*":
            raise RuntimeError(f"raw.githubusercontent.com CORS header is not '*': {cors!r}")
        check = json.loads(body.decode("utf-8"))
        if check.get("productId") != manifest["productId"]:
            raise RuntimeError("Downloaded raw manifest has a different productId.")
    return manifest_url


def existing_release_assets(repo: str, tag: str) -> list[str] | None:
    result = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo, "--json", "assets"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    return [item["name"] for item in json.loads(result.stdout).get("assets", [])]


def publish_release(repo: str, tag: str, title: str, notes_path: Path,
                    asset_paths: list[Path], commit_sha: str) -> None:
    old_assets = existing_release_assets(repo, tag)
    if old_assets is None:
        command([
            "gh", "release", "create", tag, "--repo", repo, "--title", title,
            "--notes-file", str(notes_path), "--prerelease",
            "--target", commit_sha or "main",
        ])
    else:
        keep = {path.name for path in asset_paths}
        for old_name in old_assets:
            if old_name not in keep:
                command(["gh", "release", "delete-asset", tag, old_name, "--repo", repo, "--yes"])
        command([
            "gh", "release", "edit", tag, "--repo", repo, "--title", title,
            "--notes-file", str(notes_path), "--prerelease",
        ])

    if not asset_paths:
        raise RuntimeError("No data assets prepared for Release.")
    for start in range(0, len(asset_paths), 40):
        command([
            "gh", "release", "upload", tag,
            *[str(path) for path in asset_paths[start:start + 40]],
            "--repo", repo, "--clobber",
        ])


def central_supported(path: str, name: str) -> bool:
    """Legacy workflow_run publishing is disabled; producers publish directly."""
    return False

def check() -> int:
    path, name = get("SOURCE_WORKFLOW_PATH"), get("SOURCE_WORKFLOW_NAME")
    enabled = central_supported(path, name)
    print(f"Central Release publishing enabled={enabled}: {path or name}")
    if get("GITHUB_OUTPUT"):
        with open(get("GITHUB_OUTPUT"), "a", encoding="utf-8") as stream:
            stream.write(f"enabled={'true' if enabled else 'false'}\n")
    return 0


def run() -> int:
    repo = get("SOURCE_REPOSITORY", get("GITHUB_REPOSITORY"))
    run_id = get("SOURCE_RUN_ID")
    path, name = get("SOURCE_WORKFLOW_PATH"), get("SOURCE_WORKFLOW_NAME")
    if not repo or not run_id:
        raise RuntimeError("SOURCE_REPOSITORY and SOURCE_RUN_ID are required.")
    if not supported(path, name):
        print(f"Skipping non-model workflow: {path or name}")
        return 0

    artifacts_root = Path(get("SOURCE_ARTIFACTS_DIR", "model-artifacts")).resolve()
    files = collect(artifacts_root)
    if not files:
        raise RuntimeError(
            f"No final product files found for {path or name}; refusing to report a successful Release."
        )
    json_products = [
        logical for _, logical in files
        if Path(logical).suffix.lower() in {".json", ".geojson"}
    ]
    if not json_products:
        raise RuntimeError(
            f"No JSON products found for {path or name}; refusing to publish a data-only Release."
        )
    print(f"Validated {len(json_products)} JSON product(s) among {len(files)} final files.")

    key = product_key(path, name)
    tag = f"sideral-data-{key}-latest"
    title = f"SIDERAL DATA | {key} | latest"
    branch = f"sideral-data-{key}-latest"
    output = Path(get("RELEASE_ASSETS_DIR", "release-assets")).resolve()
    if output.exists():
        shutil.rmtree(output)
    (output / "assets").mkdir(parents=True)

    records, release_assets = [], []
    for source, logical in files:
        parts, record = split_file(source, logical, output / "assets")
        records.append(record)
        release_assets.extend(output / "assets" / part["name"] for part in parts)

    if len(release_assets) + 1 > MAX_ASSETS:
        raise RuntimeError(
            f"Release would contain {len(release_assets) + 1} assets; "
            f"publisher safety limit is {MAX_ASSETS}."
        )

    release_base = f"https://github.com/{repo}/releases/download/{tag}"
    for record in records:
        for part in record["parts"]:
            part["releaseUrl"] = f"{release_base}/{quote(part['name'])}"

    manifest = {
        "schema": "sideral-model-release-v1",
        "productId": key,
        "releaseTag": tag,
        "releaseUrl": f"https://github.com/{repo}/releases/tag/{tag}",
        "releaseApiUrl": f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
        "rawBranch": branch,
        "workflow": {
            "name": name,
            "path": path,
            "runId": run_id,
            "runUrl": get("SOURCE_RUN_URL"),
            "branch": get("SOURCE_BRANCH"),
            "commit": get("SOURCE_COMMIT_SHA"),
            "completedAt": get("SOURCE_COMPLETED_AT"),
        },
        "publishedAt": datetime.now(timezone.utc).isoformat(),
        "fileCount": len(records),
        "assetCount": len(release_assets),
        "files": records,
        "notes": [
            "Os arquivos finais são publicados em uma GitHub Release pública.",
            "Para fetch() no navegador, use os URLs raw.githubusercontent.com presentes em parts.",
            "Os nomes dos ativos são seguros para Windows; timestamps WRF originais ficam dentro dos arquivos.",
            "Arquivos grandes são divididos em partes de até 45 MiB, descritas em parts.",
            "A branch de dados é específica para este produto e mantém apenas a versão mais recente.",
        ],
    }

    manifest_path = output / "manifest.json"
    write_json(manifest_path, manifest)

    raw_manifest_url = publish_raw_branch(
        repo=repo,
        branch=branch,
        output=output / "assets",
        manifest=manifest,
        manifest_path=manifest_path,
    )

    notes = output / "release-notes.md"
    notes.write_text(
        "\n".join([
            f"# {title}", "",
            "Publicação automática dos produtos finais do Sideral Meteorologia.", "",
            f"- Workflow: {name}",
            f"- Execução: {get('SOURCE_RUN_URL')}",
            f"- Commit: {get('SOURCE_COMMIT_SHA')}",
            f"- Arquivos: {len(records)}",
            f"- Manifesto para navegador: {raw_manifest_url}",
            f"- Manifesto anexado ao Release: {release_base}/manifest.json",
            f"- API pública: https://api.github.com/repos/{repo}/releases/tags/{tag}",
            "",
            "A branch raw por produto é o endpoint de leitura JavaScript; a Release é o canal de download/arquivo.",
        ]) + "\n",
        encoding="utf-8",
    )

    # Keep the Release manifest aligned with the browser-readable mirror.
    manifest["rawManifestUrl"] = raw_manifest_url
    write_json(manifest_path, manifest)
    release_assets.append(manifest_path)
    publish_release(repo, tag, title, notes, release_assets, get("SOURCE_COMMIT_SHA"))

    print(
        f"Published {key}: {len(records)} products, raw manifest={raw_manifest_url}, "
        f"Release=https://github.com/{repo}/releases/tag/{tag}"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"check", "publish"}:
        raise SystemExit("Usage: publish_model_release.py check|publish")
    try:
        raise SystemExit(check() if sys.argv[1] == "check" else run())
    except Exception as exc:
        print(f"Release publisher failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

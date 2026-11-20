#!/usr/bin/env python3
"""Publish final Sideral model products as public GitHub Release assets."""
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

MAX_ASSET_BYTES = 1_900_000_000
MAX_ASSETS = 900
SKIP_PARTS = {
    "restart", "restarts", "checkpoint", "checkpoints", "rsl", "raw",
    "input", "inputs", "logs", "log", "__pycache__",
}
PRODUCT_MARKERS = ("release-assets", "products", "product", "publish", "severe", "output")
DATA_SUFFIXES = {
    ".json", ".geojson", ".npz", ".npy", ".nc", ".nc4", ".grib", ".grib2",
    ".grb", ".grb2", ".csv", ".parquet", ".zip", ".gz", ".tar", ".png",
    ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bin", ".dat",
}


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def supported(path: str, name: str) -> bool:
    filename = Path(path).name.lower()
    workflow_name = name.lower()
    if not path.startswith(".github/workflows/") or "publish-model-releases" in filename:
        return False
    if any(x in filename for x in ("validate-", "watchdog", "maestro")):
        return False
    return (
        "wrf" in filename or "multimodel" in filename or "global-nwp" in filename
        or "multimodel" in workflow_name or "global nwp" in workflow_name
    )


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "model"


def product_key(path: str, name: str) -> str:
    stem = Path(path).stem
    if "global-nwp" in stem.lower() or "global nwp" in name.lower():
        return "global-nwp"
    if "multimodel" in stem.lower() or "multimodel" in name.lower():
        return "multimodels-05"
    return slug(stem)


def command(args: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args[:5]), flush=True)
    return subprocess.run(
        args, check=True, text=True,
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
    return rel.suffix.lower() in {".log", ".tmp", ".cache", ".pyc"}


def product_file(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if not rel.parts or ignored(rel):
        return False
    dirs = [part.lower() for part in rel.parts[:-1]]
    artifact = dirs[0] if dirs else ""
    under_product = any(
        marker in part or part.endswith("_json") or part.endswith("_severe")
        for part in dirs for marker in PRODUCT_MARKERS
    )
    final_artifact = any(x in artifact for x in ("final", "product", "global-nwp", "multimodel", "release"))
    return under_product or (final_artifact and path.suffix.lower() in DATA_SUFFIXES)


def collect(root: Path) -> list[tuple[Path, str]]:
    if not root.is_dir():
        raise FileNotFoundError(f"Artifacts directory missing: {root}")
    result, seen = [], set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or not product_file(path, root):
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        rel = path.relative_to(root)
        logical = Path(*rel.parts[1:]) if len(rel.parts) > 1 else rel
        result.append((path, logical.as_posix()))
    return result


def safe_name(logical: str) -> str:
    rel = Path(logical)
    prefix = "--".join(slug(p) for p in rel.parts[:-1])
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", rel.stem).strip("-") or "data"
    suffix = rel.suffix
    digest = hashlib.sha256(logical.encode()).hexdigest()[:10]
    lead = f"{prefix}--" if prefix else ""
    max_stem = max(16, 170 - len(lead) - len(suffix) - len(digest) - 1)
    return f"{lead}{stem[:max_stem]}-{digest}{suffix}"


def write_asset(source: Path, logical: str, output: Path) -> tuple[list[dict], dict]:
    size = source.stat().st_size
    filename = safe_name(logical)
    parts, overall = [], hashlib.sha256()
    with source.open("rb") as reader:
        index = 0
        while True:
            block = reader.read(MAX_ASSET_BYTES)
            if not block:
                break
            index += 1
            asset = filename if size <= MAX_ASSET_BYTES else f"{filename}.part{index:03d}"
            target = output / asset
            target.write_bytes(block)
            overall.update(block)
            item = {
                "name": asset,
                "size": len(block),
                "sha256": hashlib.sha256(block).hexdigest(),
                "contentType": mimetypes.guess_type(asset)[0] or "application/octet-stream",
            }
            parts.append(item)
    record = {"path": logical, "size": size, "sha256": overall.hexdigest(), "parts": parts}
    if len(parts) == 1:
        record["asset"] = parts[0]["name"]
        record["contentType"] = parts[0]["contentType"]
    else:
        record["chunked"] = True
    return parts, record


def existing_assets(repo: str, tag: str) -> list[str] | None:
    result = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo, "--json", "assets"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        return None
    return [x["name"] for x in json.loads(result.stdout).get("assets", [])]


def publish(repo: str, tag: str, title: str, notes: Path,
            assets: list[Path], commit: str) -> None:
    old = existing_assets(repo, tag)
    if old is None:
        command([
            "gh", "release", "create", tag, "--repo", repo, "--title", title,
            "--notes-file", str(notes), "--prerelease", "--target", commit or "main",
        ])
    else:
        keep = {p.name for p in assets}
        for name in old:
            if name not in keep:
                command(["gh", "release", "delete-asset", tag, name, "--repo", repo, "--yes"])
        command([
            "gh", "release", "edit", tag, "--repo", repo, "--title", title,
            "--notes-file", str(notes), "--prerelease",
        ])
    for start in range(0, len(assets), 40):
        command([
            "gh", "release", "upload", tag,
            *[str(x) for x in assets[start:start + 40]],
            "--repo", repo, "--clobber",
        ])


def check() -> int:
    path, name = get("SOURCE_WORKFLOW_PATH"), get("SOURCE_WORKFLOW_NAME")
    enabled = supported(path, name)
    print(f"Release publishing enabled={enabled}: {path or name}")
    if get("GITHUB_OUTPUT"):
        with open(get("GITHUB_OUTPUT"), "a", encoding="utf-8") as f:
            f.write(f"enabled={'true' if enabled else 'false'}\n")
    return 0


def run() -> int:
    repo = get("SOURCE_REPOSITORY", get("GITHUB_REPOSITORY"))
    run_id = get("SOURCE_RUN_ID")
    path, name = get("SOURCE_WORKFLOW_PATH"), get("SOURCE_WORKFLOW_NAME")
    if not supported(path, name):
        print(f"Skipping non-model workflow: {path or name}")
        return 0
    root = Path(get("SOURCE_ARTIFACTS_DIR", "model-artifacts")).resolve()
    files = collect(root)
    if not files:
        print("No final product files detected; no empty Release will be created.")
        return 0

    key = product_key(path, name)
    tag, title = f"sideral-data-{key}-latest", f"SIDERAL DATA | {key} | latest"
    output = Path(get("RELEASE_ASSETS_DIR", "release-assets")).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    copied, records = [], []
    for source, logical in files:
        parts, record = write_asset(source, logical, output)
        records.append(record)
        copied.extend(output / part["name"] for part in parts)
    if len(copied) + 1 > MAX_ASSETS:
        raise RuntimeError(f"Too many assets ({len(copied) + 1}); publisher limit is {MAX_ASSETS}.")

    base = f"https://github.com/{repo}/releases/download/{tag}"
    for record in records:
        for part in record["parts"]:
            part["url"] = f"{base}/{quote(part['name'])}"

    manifest = {
        "schema": "sideral-model-release-v1",
        "productId": key,
        "releaseTag": tag,
        "releaseUrl": f"https://github.com/{repo}/releases/tag/{tag}",
        "releaseApiUrl": f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
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
        "assetCount": len(copied),
        "files": records,
        "notes": [
            "Arquivos finais públicos do Sideral Meteorologia.",
            "Os nomes dos ativos são seguros para download em Windows.",
            "Nomes originais e timestamps WRF permanecem preservados no conteúdo.",
            "Arquivos grandes são divididos em partes listadas em parts.",
        ],
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    copied.append(manifest_path)

    notes = output / "release-notes.md"
    notes.write_text(
        "\n".join([
            f"# {title}", "",
            "Publicação automática dos produtos finais do Sideral Meteorologia.", "",
            f"- Workflow: {name}",
            f"- Execução: {get('SOURCE_RUN_URL')}",
            f"- Commit: {get('SOURCE_COMMIT_SHA')}",
            f"- Arquivos: {len(records)}",
            f"- Manifesto: {base}/manifest.json",
            f"- API pública: https://api.github.com/repos/{repo}/releases/tags/{tag}",
            "",
            "Esta tag estável é atualizada a cada execução concluída com sucesso.",
        ]) + "\n",
        encoding="utf-8",
    )
    publish(repo, tag, title, notes, copied, get("SOURCE_COMMIT_SHA"))
    print(f"Published {key}: {len(records)} files -> {base}/manifest.json")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"check", "publish"}:
        raise SystemExit("Usage: publish_model_release.py check|publish")
    try:
        raise SystemExit(check() if sys.argv[1] == "check" else run())
    except Exception as exc:
        print(f"Release publisher failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

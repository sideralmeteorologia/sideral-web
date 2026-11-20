#!/usr/bin/env python3
"""Transport WRF files through Actions artifacts without exposing ':' filenames.

WRF legitimately emits restart/output names containing timestamps with colons.
The GitHub Actions artifact service rejects those names on Windows-compatible
filesystems. This helper packs each upload's requested paths into a TAR whose
own filename is safe, then restores the original filenames after download.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import tarfile
from pathlib import Path, PurePosixPath


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _patterns_from_env() -> tuple[list[str], list[str]]:
    raw = os.environ.get("WRF_ARTIFACT_PATTERNS", "")
    includes, excludes = [], []
    for line in raw.splitlines():
        pattern = line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        if pattern.startswith("!"):
            excludes.append(pattern[1:])
        else:
            includes.append(pattern)
    return includes, excludes


def pack(workspace: Path, output: Path) -> int:
    workspace = workspace.resolve()
    output = output.resolve()
    includes, excludes = _patterns_from_env()
    selected: set[Path] = set()

    for pattern in includes:
        for match in glob.glob(pattern, root_dir=str(workspace), recursive=True):
            candidate = Path(match)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise RuntimeError(f"Unsafe artifact path match: {match}")
            if ".git" in candidate.parts or ".wrf-artifact-safe" in candidate.parts:
                continue
            full = workspace / candidate
            if not full.exists() and not full.is_symlink():
                continue
            if not _inside(full, workspace):
                raise RuntimeError(f"Artifact path escapes workspace: {match}")
            if full.is_file():
                selected.add(candidate)
            elif full.is_dir():
                for child in full.rglob("*"):
                    if child.is_file() and not child.is_symlink() and _inside(child, workspace):
                        selected.add(child.relative_to(workspace))

    for pattern in excludes:
        for match in glob.glob(pattern, root_dir=str(workspace), recursive=True):
            candidate = Path(match)
            selected = {
                item for item in selected
                if item != candidate and candidate not in item.parents
            }

    # Mirror upload-artifact's rootDirectory rule: use the common directory
    # prefix before the first glob metacharacter in the requested path patterns.
    roots: list[Path] = []
    for pattern in includes:
        normalized = pattern.removeprefix("./").rstrip("/")
        components = Path(normalized).parts
        prefix = []
        has_magic = False
        for component in components:
            if glob.has_magic(component):
                has_magic = True
                break
            prefix.append(component)
        if has_magic:
            root = Path(*prefix) if prefix else Path(".")
        else:
            exact = workspace / Path(normalized)
            root = Path(normalized) if exact.is_dir() else Path(*Path(normalized).parts[:-1])
            if not root.parts:
                root = Path(".")
        roots.append(root)

    if selected:
        common = Path(os.path.commonpath([root.as_posix() for root in roots])) if roots else Path(".")
        archive_paths = {
            item: (item.relative_to(common) if common != Path(".") else item)
            for item in selected
        }
    else:
        archive_paths = {}

    if not selected and os.environ.get("WRF_ARTIFACT_REQUIRE_FILES") == "1":
        raise RuntimeError("No files matched an artifact configured with if-no-files-found: error.")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as archive:
        for source_rel, archive_rel in sorted(
            archive_paths.items(), key=lambda item: item[1].as_posix()
        ):
            source = workspace / source_rel
            if not _inside(source, workspace) or source.is_symlink():
                raise RuntimeError(f"Unsafe artifact source: {source_rel}")
            archive.add(source, arcname=archive_rel.as_posix(), recursive=False)
        if not selected:
            import io
            info = tarfile.TarInfo("__wrf_artifact_empty__.txt")
            info.size = 0
            archive.addfile(info, io.BytesIO(b""))

    print(
        f"Packed {len(selected)} file(s) into {output.name} "
        f"({output.stat().st_size} bytes)"
    )
    return 0


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    members = archive.getmembers()
    for member in members:
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts:
            raise RuntimeError(f"Unsafe TAR member: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise RuntimeError(f"Unsupported TAR member type: {member.name}")
        target = destination.joinpath(*[part for part in name.parts if part not in ("", ".")])
        if not _inside(target, root):
            raise RuntimeError(f"TAR member escapes extraction path: {member.name}")
    archive.extractall(destination, members=members)
    return len(members)


def _extract_bundle(archive_path: Path, destination: Path) -> int:
    with tarfile.open(archive_path, "r:") as archive:
        count = _safe_extract(archive, destination)
    archive_path.unlink(missing_ok=True)
    print(f"Restored {archive_path.name} -> {destination} ({count} members)")
    return count


def unpack_source(source: Path, target: Path, required: bool = False) -> int:
    source = source.resolve()
    target = target.resolve()
    if not source.exists():
        if required:
            raise FileNotFoundError(f"Artifact download directory missing: {source}")
        return 0

    archives = sorted(source.rglob("wrf-payload-*.tar"))
    restored = 0
    for archive in archives:
        relative_parent = archive.parent.relative_to(source)
        destination = target / relative_parent
        restored += _extract_bundle(archive, destination)
    if required and not archives:
        raise FileNotFoundError(f"No WRF payload TAR found under: {source}")
    return restored


def unpack_downloads(downloads_root: Path, workspace: Path) -> int:
    downloads_root = downloads_root.resolve()
    workspace = workspace.resolve()
    if not downloads_root.exists():
        return 0

    restored = 0
    for source in sorted(item for item in downloads_root.iterdir() if item.is_dir()):
        marker = source / ".restore-to"
        if not marker.is_file():
            continue
        relative_target = marker.read_text(encoding="utf-8").strip() or "."
        target_rel = Path(relative_target)
        if target_rel.is_absolute() or ".." in target_rel.parts:
            raise RuntimeError(f"Unsafe artifact restore target: {relative_target}")
        target = workspace if target_rel == Path(".") else workspace / target_rel
        restored += unpack_source(source, target, required=False)
        marker.unlink(missing_ok=True)
    return restored


def unpack_release_artifacts(root: Path) -> int:
    """Restore tar payloads from gh run download's artifact-name directories."""
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Release artifact download root missing: {root}")
    restored = 0
    for artifact_dir in sorted(item for item in root.iterdir() if item.is_dir()):
        restored += unpack_source(artifact_dir, artifact_dir, required=False)
    return restored


def self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="wrf-artifact-bundle-test-") as temp:
        root = Path(temp)
        workspace = root / "workspace"
        downloads = root / "downloads"
        restored = root / "restored"
        (workspace / "cbr_restart").mkdir(parents=True)
        (workspace / "cbr_products").mkdir(parents=True)

        restart_name = "cbr-restart-3-wrfrst_d01_2026-11-20_15:00:00"
        product_name = "metadata.json"
        (workspace / "cbr_restart" / restart_name).write_bytes(b"WRF-RESTART")
        (workspace / "cbr_products" / product_name).write_text('{"ok":true}', encoding="utf-8")

        os.environ["WRF_ARTIFACT_PATTERNS"] = "**/*restart*/**\n**/*products*/**"
        bundle = workspace / ".wrf-artifact-safe" / "wrf-payload-001.tar"
        pack(workspace, bundle)
        assert ":" not in bundle.name

        download_dir = downloads / "d001"
        download_dir.mkdir(parents=True)
        (download_dir / bundle.name).write_bytes(bundle.read_bytes())
        (download_dir / ".restore-to").write_text(".", encoding="utf-8")
        unpack_downloads(downloads, restored)

        actual = restored / "cbr_restart" / restart_name
        assert actual.read_bytes() == b"WRF-RESTART"
        assert (restored / "cbr_products" / product_name).read_text(encoding="utf-8") == '{"ok":true}'
    print("WRF artifact bundle self-test passed (colon timestamp and folder layout preserved).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_pack = sub.add_parser("pack")
    p_pack.add_argument("--workspace", type=Path, default=Path.cwd())
    p_pack.add_argument("--output", type=Path, required=True)
    p_unpack = sub.add_parser("unpack")
    p_unpack.add_argument("--source", type=Path, required=True)
    p_unpack.add_argument("--target", type=Path, required=True)
    p_unpack.add_argument("--required", action="store_true")
    p_downloads = sub.add_parser("unpack-downloads")
    p_downloads.add_argument("--downloads-root", type=Path, required=True)
    p_downloads.add_argument("--workspace", type=Path, default=Path.cwd())
    p_release = sub.add_parser("unpack-release-artifacts")
    p_release.add_argument("--root", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()

    try:
        if args.command == "pack":
            return pack(args.workspace, args.output)
        if args.command == "unpack":
            unpack_source(args.source, args.target, required=args.required)
            return 0
        if args.command == "unpack-downloads":
            unpack_downloads(args.downloads_root, args.workspace)
            return 0
        if args.command == "unpack-release-artifacts":
            unpack_release_artifacts(args.root)
            return 0
        return self_test()
    except Exception as exc:
        print(f"WRF artifact bundle error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

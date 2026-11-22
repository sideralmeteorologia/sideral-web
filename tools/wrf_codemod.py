#!/usr/bin/env python3
"""Idempotent, dry-run capable codemod for embedded WRF scripts."""
from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

SOURCE_MAP = {
    "wrf/run_tarc_checkpoint_segment.sh": "runners/tarc/shared/run_tarc_checkpoint_segment.sh",
    "wrf/run_cim4_checkpoint_segment.sh": "runners/cim5/shared/run_cim4_checkpoint_segment.sh",
    "wrf/run_metbr_checkpoint_segment.sh": "runners/metbr/shared/run_metbr_checkpoint_segment.sh",
    "wrf/run_metbr_gfs_segment.sh": "runners/metbr/gfs/run_metbr_gfs_segment.sh",
    "wrf/run_cbr_checkpoint_segment.sh": "runners/cbr/shared/run_cbr_checkpoint_segment.sh",
    "wrf/run_metbr_source_wrf.sh": "runners/metbr/shared/run_metbr_source_wrf.sh",
    "wrf/run_wrf_restart_segment.sh": "runners/metbr/shared/run_wrf_restart_segment.sh",
    "wrf/prepare_restart_segment.py": "runners/metbr/shared/prepare_restart_segment.py",
}


def replace_embedded_scripts(text: str) -> tuple[str, list[str]]:
    changed: list[str] = []
    replacements = (
        (re.compile(r"timeout-minutes:\s*(?:355|350|360|480)", re.I),
         "timeout-minutes: 330",
         "operational timeout"),
        (re.compile(r"retention-days:\s*7", re.I),
         "retention-days: 1",
         "intermediate artifact retention"),
        (re.compile(r"if-no-files-found:\s*ignore", re.I),
         "if-no-files-found: error",
         "empty artifact policy"),
    )
    for pattern, replacement, label in replacements:
        text, count = pattern.subn(replacement, text)
        if count:
            changed.append(f"{label}: {count} replacement(s)")
    for embedded, source_rel in SOURCE_MAP.items():
        resolved_source_rel = source_rel
        if embedded == "wrf/run_tarc_checkpoint_segment.sh" and "Sudeste" in text:
            resolved_source_rel = "runners/sudeste/shared/run_tarc_checkpoint_segment.sh"
        if embedded == "wrf/prepare_restart_segment.py":
            if "Sudeste" in text:
                resolved_source_rel = "runners/sudeste/shared/prepare_restart_segment.py"
            elif "TARC" in text:
                resolved_source_rel = "runners/tarc/shared/prepare_restart_segment.py"
        source = (ROOT / resolved_source_rel).read_bytes()
        source = source.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        payload = base64.b64encode(source).decode("ascii")
        pattern = re.compile(
            re.escape("printf '%s' '") +
            r"[^']*" +
            re.escape("' | base64 -d > '" + embedded + "'"),
        )
        replacement = "printf '%s' '" + payload + "' | base64 -d > '" + embedded + "'"
        text, count = pattern.subn(replacement, text)
        if count:
            changed.append(f"{embedded}: {count} replacement(s)")
    return text, changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("paths", nargs="*", default=[".github/workflows"])
    args = parser.parse_args()

    targets: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_dir():
            targets.extend(sorted(path.glob("*wrf*.yml")))
        elif path.is_file():
            targets.append(path)

    modified = 0
    for path in targets:
        original = path.read_text(encoding="utf-8")
        updated, changes = replace_embedded_scripts(original)
        if updated != original:
            print(f"{path.relative_to(ROOT)}: " + ", ".join(changes))
            if not args.dry_run:
                path.write_text(updated, encoding="utf-8")
            modified += 1
    print(f"{'Would modify' if args.dry_run else 'Modified'} {modified} workflow(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

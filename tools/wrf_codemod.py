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
}


def replace_embedded_scripts(text: str) -> tuple[str, list[str]]:
    changed: list[str] = []
    sudeste_complete = re.compile(
        r"(  complete:\n(?:.*\n){0,20}?      - name: Checkout repository\n"
        r"        uses: actions/checkout@v4\n"
        r"        with:\n          fetch-depth: 1\n)"
    )
    sudeste_restore = (
        r"\1"
        "      - name: Restore WRF artifacts after checkout (complete)\n"
        "        shell: bash\n"
        "        run: |\n"
        "          if [[ -f \"$GITHUB_WORKSPACE/.github/scripts/wrf_artifact_bundle.py\" ]]; then\n"
        "            python3 \"$GITHUB_WORKSPACE/.github/scripts/wrf_artifact_bundle.py\" unpack-downloads \\\n"
        "              --downloads-root \"$RUNNER_TEMP/wrf-downloads\" \\\n"
        "              --workspace \"$GITHUB_WORKSPACE\"\n"
        "          fi\n"
    )
    text, sudeste_count = sudeste_complete.subn(sudeste_restore, text)
    if sudeste_count:
        changed.append("Sudeste complete checkout restore: repaired")
    if "Restaurar payloads locais dos segmentos Sudeste" in text:
        text = text.replace(
            "      - name: Restaurar payloads locais dos segmentos Sudeste",
            "      - name: Register WRF artifact restore target (16)",
        )
        text = text.replace(
            "          WRF_ARTIFACT_DOWNLOAD_DIR: ${{ runner.temp }}/wrf-downloads/sudeste-segments\n",
            "          WRF_ARTIFACT_DOWNLOAD_DIR: ${{ runner.temp }}/wrf-downloads/sudeste-segments\n"
            "          WRF_ARTIFACT_RESTORE_TO: 'tarc_segment_artifacts'\n",
        )
        changed.append("Sudeste complete restore registration: repaired")
    tarc_register = (
        "          mkdir -p \"$WRF_ARTIFACT_DOWNLOAD_DIR\"\n"
        "          printf '%s\\n' \"$WRF_ARTIFACT_RESTORE_TO\" > \"$WRF_ARTIFACT_DOWNLOAD_DIR/.restore-to\"\n"
    )
    tarc_register_fixed = tarc_register + (
        "          python3 .github/scripts/wrf_artifact_bundle.py unpack-downloads \\\n"
        "            --downloads-root \"$WRF_ARTIFACT_DOWNLOAD_DIR\" \\\n"
        "            --workspace \"$GITHUB_WORKSPACE\"\n"
    )
    if tarc_register in text:
        text = text.replace(tarc_register, tarc_register_fixed)
        changed.append("TARC restore registration: repaired")
    tarc_complete = re.compile(
        r"(  complete:\n(?:.*\n){0,20}?      - name: Checkout repository\n"
        r"        uses: actions/checkout@v4\n"
        r"        with:\n          fetch-depth: 1\n)"
    )
    restore = (
        r"\1"
        "      - name: Restore WRF artifacts after checkout (complete)\n"
        "        shell: bash\n"
        "        run: |\n"
        "          if [[ -f \"$GITHUB_WORKSPACE/.github/scripts/wrf_artifact_bundle.py\" ]]; then\n"
        "            python3 \"$GITHUB_WORKSPACE/.github/scripts/wrf_artifact_bundle.py\" unpack-downloads \\\n"
        "              --downloads-root \"$RUNNER_TEMP/wrf-downloads\" \\\n"
        "              --workspace \"$GITHUB_WORKSPACE\"\n"
        "          fi\n"
    )
    text, tarc_count = tarc_complete.subn(restore, text)
    if tarc_count:
        changed.append("TARC complete checkout restore: repaired")
    metbr_complete = re.compile(
        r"(WRF_ARTIFACT_DOWNLOAD_DIR:\s*\$\{\{\s*runner\.temp\s*\}\}/wrf-downloads/d042\n)"
    )
    text, metbr_count = metbr_complete.subn(
        r"\1          WRF_ARTIFACT_RESTORE_TO: metbr_segment_artifacts\n",
        text,
    )
    if metbr_count:
        changed.append("METBR complete restore target: repaired")
    corrupt = "        run: python3 .github/scripts/restor      - name: Reunir WRFOUTs locais da rodada completa"
    repaired = (
        "        run: python3 .github/scripts/restore_wrf_runtime.py\n"
        "      - name: Reunir WRFOUTs locais da rodada completa"
    )
    if corrupt in text:
        text = text.replace(corrupt, repaired)
        changed.append("corrupt complete-step boundary: repaired")
    for embedded, source_rel in SOURCE_MAP.items():
        source = (ROOT / source_rel).read_bytes()
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
        if changes:
            print(f"{path.relative_to(ROOT)}: " + ", ".join(changes))
            if not args.dry_run:
                path.write_text(updated, encoding="utf-8")
            modified += 1
    print(f"{'Would modify' if args.dry_run else 'Modified'} {modified} workflow(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

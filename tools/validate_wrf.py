#!/usr/bin/env python3
"""Run the embedded WRF clone validator without invoking Actions."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    workflow_dir = ROOT / ".github" / "workflows"
    validator_path = workflow_dir / "validate-wrf-runner-clones.yml"
    validator = yaml.load(validator_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    step = next(
        step for step in validator["jobs"]["validate"]["steps"]
        if step.get("name") == "Validate all original and cloned WRF workflows"
    )
    command = step["run"]
    marker = "python - <<'PY'\n"
    source = command.split(marker, 1)[1].rsplit("\nPY", 1)[0]
    exec(compile(source, str(validator_path), "exec"), {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

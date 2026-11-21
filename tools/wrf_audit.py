#!/usr/bin/env python3
"""Static audit for SIDERAL WRF workflows."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def audit(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    findings = []

    def add(rule: str, severity: str, evidence: str) -> None:
        findings.append({
            "rule": rule,
            "severity": severity,
            "file": str(path.relative_to(ROOT)),
            "evidence": evidence,
        })

    if re.search(r"if-no-files-found:\s*ignore", text, re.I):
        add("R001", "critical", "artifact upload may publish an empty run")
    if re.search(r"retention-days:\s*(?:[2-9]|[1-9][0-9])", text, re.I):
        add("R002", "high", "intermediate artifact retention exceeds one day")
    if re.search(r":\s*#\s*(?:artifact-only|checkpoint handled)", text, re.I):
        add("R003", "critical", "migration residue is present")
    if re.search(r"\b(?:awscli|r2-objects\.json|R2/|bucket)\b", text, re.I):
        add("R004", "high", "deprecated R2/AWS reference is present")
    if re.search(r"continue-on-error:\s*true", text, re.I):
        add("R005", "critical", "failure is explicitly masked")
    if re.search(r"\|\|\s*true", text, re.I):
        add("R006", "critical", "shell failure may be masked")
    for timeout in re.findall(r"timeout-minutes:\s*(\d+)", text):
        value = int(timeout)
        if value > 330:
            add("R007", "high", f"job timeout {value} exceeds operational target 330")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", default=[".github/workflows"])
    parser.add_argument("--json", dest="json_output", action="store_true")
    args = parser.parse_args()

    targets: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_dir():
            targets.extend(sorted(path.glob("*.yml")))
        elif path.is_file():
            targets.append(path)

    findings = [item for path in targets for item in audit(path)]
    if args.json_output:
        print(json.dumps({"count": len(findings), "findings": findings}, indent=2))
    else:
        for item in findings:
            print(f"{item['severity'].upper()} {item['rule']} {item['file']}: {item['evidence']}")
        print(f"TOTAL: {len(findings)} findings across {len(targets)} files")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Extract all base64-embedded scripts from GitHub Actions workflow YAML files
and write them to the wrf/ directory as standalone files."""
import base64
import os
import re
import sys

WORKFLOWS_DIR = ".github/workflows"
OUT_DIR = "wrf"

# Pattern: printf '%s' 'BASE64' | base64 -d > 'wrf/run_xxx.sh'
# The base64 blob is inside single quotes after printf '%s' '
# We capture the target path and the base64 content.
LINE_RE = re.compile(
    r"printf\s+'%s'\s+'([A-Za-z0-9+/=\s]+?)'\s*\|\s*base64\s+-d\s*>\s*'([^']+)'"
)

def extract_from_file(path):
    results = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    for m in LINE_RE.finditer(content):
        b64 = m.group(1).replace("\n", "").replace(" ", "")
        target = m.group(2)
        try:
            data = base64.b64decode(b64)
            results.append((target, data))
        except Exception as e:
            print(f"WARN: failed to decode {target} in {path}: {e}", file=sys.stderr)
    return results

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    seen = {}
    for fname in sorted(os.listdir(WORKFLOWS_DIR)):
        if not fname.endswith(".yml"):
            continue
        fpath = os.path.join(WORKFLOWS_DIR, fname)
        for target, data in extract_from_file(fpath):
            if target in seen and seen[target] == data:
                continue
            if target in seen:
                print(f"WARN: duplicate {target} with different content in {fname}", file=sys.stderr)
                continue
            seen[target] = data
            out_path = os.path.join(OUT_DIR, os.path.basename(target))
            with open(out_path, "wb") as out:
                out.write(data)
            print(f"OK {out_path} ({len(data)} bytes) from {fname}")

    print(f"\nTotal unique scripts extracted: {len(seen)}")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""Validate product JSON files before Release publication."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    args = parser.parse_args()
    root = Path(args.root)
    if not root.is_dir():
        print(f"ERROR: diretório inexistente: {root}", file=sys.stderr)
        return 1
    files = sorted(root.rglob("*.json"))
    if not files:
        print(f"ERROR: nenhum JSON encontrado em {root}", file=sys.stderr)
        return 1
    for path in files:
        if path.stat().st_size < 2:
            print(f"ERROR: arquivo vazio: {path}", file=sys.stderr)
            return 1
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"ERROR: JSON inválido: {path}: {exc}", file=sys.stderr)
            return 1
    print(f"OK: {len(files)} JSON(s) válido(s) em {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

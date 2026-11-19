#!/usr/bin/env python3
"""Validate the independent WRF runner layout before merging."""
from pathlib import Path
import re
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RUNNERS = {"wrf2", "icon", "gfs", "ecmwf"}
ENGINES = ("cbr-wrf.yml", "cim-wrf-5km.yml", "cim-wrf-8km.yml", "metbr-wrf.yml", "sideral-brasil-wrf.yml", "sideral-sudeste-wrf.yml", "tarc-wrf.yml")
errors = []
for path in sorted(WORKFLOWS.glob("*.yml")):
    content = path.read_text(encoding="utf-8")
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        errors.append(f"{path.relative_to(ROOT)}: YAML inválido: {exc}")
    if "base64 -d" in content.lower() or "SIDERAL_PAYLOAD_" in content:
        errors.append(f"{path.relative_to(ROOT)}: payload Base64 ainda embutido")
    for source in re.findall(r'cp "((?:runners)/[^"]+)" "wrf/[^"]+"', content):
        if not (ROOT / source).is_file():
            errors.append(f"{path.relative_to(ROOT)}: fonte ausente: {source}")
for runner in RUNNERS:
    path = WORKFLOWS / f"{runner}-runner.yml"
    if not path.is_file():
        errors.append(f"Runner ausente: {path.relative_to(ROOT)}")
        continue
    content = path.read_text(encoding="utf-8")
    if "workflow_dispatch:" not in content:
        errors.append(f"{path.name}: workflow_dispatch ausente")
    if runner == "wrf2":
        if "default: icon" not in content or "wrf2" not in content:
            errors.append("wrf2-runner: seleção de fonte ou variante WRF2 ausente")
    elif f"source_model: {runner}" not in content:
        errors.append(f"{path.name}: fonte {runner.upper()} não está fixada")
for filename in ENGINES:
    path = WORKFLOWS / filename
    if not path.is_file():
        errors.append(f"Motor ausente: {filename}")
        continue
    content = path.read_text(encoding="utf-8")
    if "workflow_call:" not in content:
        errors.append(f"{filename}: workflow_call ausente")
    if "workflow_dispatch:" in content:
        errors.append(f"{filename}: despacho manual combinado ainda ativo")
    if "Load WRF parameters from versioned profile" not in content:
        errors.append(f"{filename}: carregamento do perfil WRF ausente")
for profile in sorted((ROOT / "runners" / "parameters").glob("*.env")):
    for line_no, line in enumerate(profile.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        if "=" not in line or not re.fullmatch(r"[A-Z][A-Z0-9_]*=.*", line):
            errors.append(f"{profile.relative_to(ROOT)}:{line_no}: variável inválida")
if not (ROOT / "runners" / "multimodels-05" / "engine.zip").is_file():
    errors.append("Pacote multimodelo versionado ausente")
if errors:
    print("\n".join(f"ERROR: {e}" for e in errors))
    sys.exit(1)
print("OK: 4 runners independentes, 7 motores reutilizáveis, perfis WRF e fontes versionadas.")

#!/usr/bin/env python3
"""Validate runner separation, source files, profiles and shell syntax."""
from pathlib import Path
import re
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RUNNERS = {"wrf2", "icon", "gfs", "ecmwf"}
ENGINES = (
    "cbr-wrf.yml", "cim-wrf-5km.yml", "cim-wrf-8km.yml",
    "metbr-wrf.yml", "sideral-brasil-wrf.yml",
    "sideral-sudeste-wrf.yml", "tarc-wrf.yml",
)
REQUIRED_PROFILES = {
    "cbr.env": {"WRF_TARGET_RESOLUTION_KM", "WRF_DX_METERS", "WRF_DY_METERS", "WRF_E_WE", "WRF_E_SN", "WRF_TIME_STEP", "WRF_HISTORY_INTERVAL_MINUTES", "WRF_MPI_PROCS", "WRF_REF_LAT", "WRF_REF_LON", "WRF_STAND_LON"},
    "cim5.env": {"WRF_TARGET_RESOLUTION_KM", "WRF_DX_METERS", "WRF_DY_METERS", "WRF_E_WE", "WRF_E_SN", "WRF_TIME_STEP", "WRF_HISTORY_INTERVAL_MINUTES", "WRF_MPI_PROCS", "WRF_REF_LAT", "WRF_REF_LON", "WRF_STAND_LON"},
    "cim8.env": {"WRF_TARGET_RESOLUTION_KM", "WRF_DX_METERS", "WRF_DY_METERS", "WRF_E_WE", "WRF_E_SN", "WRF_TIME_STEP", "WRF_HISTORY_INTERVAL_MINUTES", "WRF_REF_LAT", "WRF_REF_LON", "WRF_STAND_LON", "WRF_RUN_HOURS", "WRF_START_HOUR", "WRF_END_HOUR"},
    "metbr.env": {"WRF_TARGET_RESOLUTION_KM", "WRF_DX_METERS", "WRF_DY_METERS", "WRF_E_WE", "WRF_E_SN", "WRF_TIME_STEP", "WRF_HISTORY_INTERVAL_MINUTES", "WRF_MPI_PROCS", "WRF_REF_LAT", "WRF_REF_LON", "WRF_STAND_LON"},
    "brasil.env": {"WRF_TARGET_RESOLUTION_KM", "WRF_DX_METERS", "WRF_DY_METERS", "WRF_E_WE", "WRF_E_SN", "WRF_GRID_X", "WRF_GRID_Y", "WRF_TIME_STEP", "WRF_HISTORY_INTERVAL_MINUTES", "WRF_REF_LAT", "WRF_REF_LON", "WRF_STAND_LON", "WRF_RUN_HOURS", "WRF_START_HOUR", "WRF_END_HOUR"},
    "sudeste-4km.env": {"WRF_TARGET_RESOLUTION_KM", "WRF_DX_METERS", "WRF_DY_METERS", "WRF_E_WE", "WRF_E_SN", "WRF_TIME_STEP", "WRF_HISTORY_INTERVAL_MINUTES", "WRF_MPI_PROCS", "WRF_REF_LAT", "WRF_REF_LON", "WRF_STAND_LON"},
    "sudeste-5km.env": {"WRF_TARGET_RESOLUTION_KM", "WRF_DX_METERS", "WRF_DY_METERS", "WRF_E_WE", "WRF_E_SN", "WRF_TIME_STEP", "WRF_HISTORY_INTERVAL_MINUTES", "WRF_MPI_PROCS", "WRF_REF_LAT", "WRF_REF_LON", "WRF_STAND_LON"},
    "tarc.env": {"WRF_TARGET_RESOLUTION_KM", "WRF_DX_METERS", "WRF_DY_METERS", "WRF_E_WE", "WRF_E_SN", "WRF_TIME_STEP", "WRF_HISTORY_INTERVAL_MINUTES", "WRF_MPI_PROCS", "WRF_REF_LAT", "WRF_REF_LON", "WRF_STAND_LON"},
}
PHYSICAL_KEYS = (
    "WRF_TARGET_RESOLUTION_KM", "WRF_DX_METERS", "WRF_DY_METERS",
    "WRF_E_WE", "WRF_E_SN", "WRF_TIME_STEP",
    "WRF_HISTORY_INTERVAL_MINUTES", "WRF_MPI_PROCS",
    "WRF_REF_LAT", "WRF_REF_LON", "WRF_STAND_LON",
)
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
    if path.name in ENGINES:
        if "workflow_call:" not in content:
            errors.append(f"{path.name}: workflow_call ausente")
        if "workflow_dispatch:" in content:
            errors.append(f"{path.name}: despacho manual combinado ainda ativo")
        if re.search(r"^  schedule:", content, re.MULTILINE) or "github.event.schedule" in content:
            errors.append(f"{path.name}: agendamento/seleção por cron deve ficar no runner específico")
        if "Load WRF parameters from versioned profile" not in content:
            errors.append(f"{path.name}: carregamento do perfil WRF ausente")

for runner in RUNNERS:
    path = WORKFLOWS / f"{runner}-runner.yml"
    if not path.is_file():
        errors.append(f"Runner ausente: {path.relative_to(ROOT)}")
        continue
    content = path.read_text(encoding="utf-8")
    if "workflow_dispatch:" not in content:
        errors.append(f"{path.name}: workflow_dispatch ausente")
    if "schedule:" not in content:
        errors.append(f"{path.name}: agendamento próprio ausente")
    if runner == "wrf2":
        if "default: icon" not in content or "wrf2" not in content:
            errors.append("wrf2-runner: seleção de fonte ou variante WRF2 ausente")
    elif f"source_model: {runner}" not in content:
        errors.append(f"{path.name}: fonte {runner.upper()} não está fixada")

profiles_dir = ROOT / "runners" / "parameters"
for filename, required in REQUIRED_PROFILES.items():
    path = profiles_dir / filename
    if not path.is_file():
        errors.append(f"Perfil ausente: {path.relative_to(ROOT)}")
        continue
    variables = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        if "=" not in line or not re.fullmatch(r"[A-Z][A-Z0-9_]*=.*", line):
            errors.append(f"{path.relative_to(ROOT)}:{line_no}: variável inválida")
            continue
        variables.add(line.split("=", 1)[0])
    missing = sorted(required - variables)
    if missing:
        errors.append(f"{filename}: parâmetros WRF ausentes: {', '.join(missing)}")

for script in sorted((ROOT / "runners").rglob("*.sh")):
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    if result.returncode:
        errors.append(f"{script.relative_to(ROOT)}: Bash inválido: {result.stderr.strip()[:300]}")
    source = script.read_text(encoding="utf-8", errors="replace")
    for line_no, line in enumerate(source.splitlines(), 1):
        for key in PHYSICAL_KEYS:
            if re.search(rf"\b{key}\s*=\s*['\"]?-?\d+(?:\.\d+)?['\"]?(?=\s|$)", line):
                errors.append(f"{script.relative_to(ROOT)}:{line_no}: {key} fixo no executor; use o perfil WRF")

engine_zip = ROOT / "runners" / "multimodels-05" / "engine.zip"
if not engine_zip.is_file() or engine_zip.stat().st_size == 0:
    errors.append("Pacote multimodelo versionado ausente")

if errors:
    print("\n".join(f"ERROR: {e}" for e in errors))
    sys.exit(1)
print("OK: runners separados, agendamentos isolados, perfis WRF completos, fontes versionadas e Bash válido.")

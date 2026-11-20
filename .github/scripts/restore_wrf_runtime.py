#!/usr/bin/env python3
"""Restore region/model-specific WRF runtime files from the versioned runners tree."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = ROOT / "runners"
WRF = ROOT / "wrf"


def detect_profile() -> str:
    family = os.getenv("FAMILY", "").strip().lower()
    workflow = os.getenv("GITHUB_WORKFLOW", "").lower()
    resolution = (
        os.getenv("RESOLUTION_KM")
        or os.getenv("WRF_TARGET_RESOLUTION_KM")
        or os.getenv("WRF_EXPECTED_RESOLUTION_KM")
        or ""
    ).strip()

    if family in {"cbr", "cim", "metbr", "tarc", "brasil"}:
        if family == "cim":
            return "cim8" if resolution == "8" else "cim5"
        return family
    if family in {"sudeste", "sideral-sudeste"} or "sudeste" in workflow:
        return "sudeste"
    if "metbr" in workflow:
        return "metbr"
    if "cbr" in workflow:
        return "cbr"
    if "cim" in workflow:
        return "cim8" if "8 km" in workflow or resolution == "8" else "cim5"
    if "tarc" in workflow:
        return "tarc"
    if "brasil" in workflow:
        return "brasil"
    raise SystemExit(
        "Não foi possível identificar o perfil WRF. "
        f"FAMILY={family!r}; GITHUB_WORKFLOW={workflow!r}"
    )


def copy_flat(source: Path, destination: Path) -> int:
    count = 0
    if not source.is_dir():
        return count
    for item in sorted(source.iterdir()):
        if item.is_file():
            target = destination / item.name
            shutil.copy2(item, target)
            count += 1
        elif item.is_dir() and item.name == "bin":
            shutil.copytree(item, destination / item.name, dirs_exist_ok=True)
    return count


def main() -> None:
    profile = detect_profile()
    source_model = (
        os.getenv("SOURCE_MODEL")
        or os.getenv("METBR_SOURCE_MODEL")
        or os.getenv("MODEL")
        or "icon"
    ).strip().lower()
    variant = os.getenv("MODEL_VARIANT", "wrf").strip().lower()
    base = RUNNERS / profile

    if not (base / "shared").is_dir():
        raise SystemExit(f"Diretório compartilhado do runner não existe: {base / 'shared'}")
    if not (base / source_model).is_dir():
        raise SystemExit(
            f"Fonte {source_model!r} não existe para o perfil {profile}: {base / source_model}"
        )

    WRF.mkdir(parents=True, exist_ok=True)
    copied = 0
    copied += copy_flat(base / "shared", WRF)
    copied += copy_flat(base / source_model, WRF)

    if variant == "wrf2":
        copied += copy_flat(base / "wrf2", WRF)

    # Sudeste/TARC and a few older profiles share the same WRF2-compatible
    # front-end wrapper; keep the region-specific core copied above.
    if not (WRF / "extract_wrf_severe.py").exists():
        fallback = RUNNERS / "cim5" / "shared" / "extract_wrf_severe.py"
        if fallback.is_file():
            shutil.copy2(fallback, WRF / fallback.name)
            copied += 1

    required = []
    if source_model == "icon":
        required.append("Vtable.ICONp")
    elif source_model == "ecmwf":
        required.append("Vtable.ECMWF_OPEN")
    elif source_model == "gfs":
        required.append("Vtable.GFS_SOIL")
    # Alguns runners regionais reutilizam a Vtable ICON mantida no perfil CIM.
    # O conteúdo é idêntico e continua separado do executável/modelo regional.
    if source_model == "icon" and not (WRF / "Vtable.ICONp").is_file():
        for candidate in (
            RUNNERS / "cim5" / "icon" / "Vtable.ICONp",
            RUNNERS / "tarc" / "icon" / "Vtable.ICONp",
        ):
            if candidate.is_file():
                shutil.copy2(candidate, WRF / "Vtable.ICONp")
                copied += 1
                break

    missing = [name for name in required if not (WRF / name).is_file()]
    if missing:
        raise SystemExit(
            f"Runtime incompleto para {profile}/{source_model}: "
            + ", ".join(missing)
        )

    print(
        f"WRF runtime restaurado: perfil={profile}, fonte={source_model}, "
        f"variante={variant}, arquivos_copiados={copied}"
    )


if __name__ == "__main__":
    main()

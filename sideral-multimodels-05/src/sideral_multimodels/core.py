from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
import numpy as np

MODEL_IDS = ("ecmwf", "gfs", "icon")
FIELD_NAMES = ("t2m", "d2m", "u10", "v10", "msl", "tp6h")
FIELD_UNITS = {
    "t2m": "degC", "d2m": "degC", "u10": "m s-1", "v10": "m s-1",
    "msl": "hPa", "tp6h": "mm",
}
AGREEMENT_SCALES = {"t2m": 4.0, "d2m": 5.0, "u10": 5.0, "v10": 5.0, "msl": 8.0, "tp6h": 8.0}


def parse_hours(text: str | Iterable[int] | None, max_hour: int = 168, interval: int = 6) -> list[int]:
    if text is None or str(text).strip() == "":
        values = list(range(0, max_hour + 1, interval))
    elif isinstance(text, str):
        try:
            values = [int(part.strip()) for part in text.split(",") if part.strip()]
        except ValueError as exc:
            raise ValueError("Horas inválidas. Use formato como 0,6,12,24") from exc
    else:
        values = [int(value) for value in text]
    if not values:
        raise ValueError("Informe pelo menos uma hora de previsão")
    if len(set(values)) != len(values):
        raise ValueError("Há horas de previsão duplicadas")
    values = sorted(values)
    if any(value < 0 or value > max_hour for value in values):
        raise ValueError(f"As horas devem estar entre 0 e {max_hour}")
    if any(value % interval for value in values):
        raise ValueError(f"As horas devem respeitar o intervalo de {interval} h")
    if values[0] != 0:
        raise ValueError("Inclua a hora 0 para permitir a normalização da precipitação acumulada")
    return values


def native_forecast_horizon(model: str, cycle: str) -> int:
    """Horizonte máximo conhecido por modelo/ciclo, em horas.

    Valores alinhados aos horizontes operacionais dos produtos públicos:
    - ECMWF IFS Open Data: 144 h para 06/18Z; 360 h para 00/12Z.
    - NOAA GFS: até 384 h nos ciclos globais de 6 horas.
    - DWD ICON Global: 120 h para 06/18Z; 180 h para 00/12Z.

    O limite efetivo do produto ainda respeita `forecast.max_hour`.
    """
    model = str(model).strip().lower()
    cycle = str(cycle).strip().zfill(2)
    if cycle not in {"00", "06", "12", "18"}:
        raise ValueError(f"Ciclo inválido para horizonte: {cycle}")
    if model == "ecmwf":
        return 144 if cycle in {"06", "18"} else 360
    if model == "gfs":
        return 384
    if model == "icon":
        return 120 if cycle in {"06", "18"} else 180
    raise ValueError(f"Modelo desconhecido para horizonte: {model}")


def limit_hours_to_common_horizon(
    hours: Iterable[int],
    cycle: str,
    models: Iterable[str],
    minimum_models: int = 2,
    configured_max_hour: int = 168,
) -> list[int]:
    """Limita os leads ao horizonte no qual podem contribuir N modelos.

    Para um consenso mínimo de dois modelos, é possível continuar após o fim
    de um terceiro modelo; por exemplo, 06Z fica limitado a F144 (ECMWF+GFS),
    enquanto ICON termina corretamente em F120. Com três modelos obrigatórios,
    esse mesmo ciclo fica limitado a F120.
    """
    selected = [str(model).strip().lower() for model in models]
    if not selected:
        raise ValueError("Nenhum modelo selecionado")
    if minimum_models < 1 or minimum_models > len(selected):
        raise ValueError("minimum_models_per_cell deve estar entre 1 e o número de modelos selecionados")
    limits = sorted(
        (min(int(configured_max_hour), native_forecast_horizon(model, cycle)) for model in selected),
        reverse=True,
    )
    common_horizon = limits[minimum_models - 1]
    effective = [int(hour) for hour in hours if int(hour) <= common_horizon]
    if not effective or effective[0] != 0:
        raise ValueError("O horizonte comum resultou sem previsões úteis; inclua F000 e revise a configuração")
    return effective


def resolve_run(date_text: str | None, cycle_text: str | None, delay_hours: int = 12) -> tuple[str, str]:
    date_text = (date_text or "").strip().replace("-", "")
    cycle_text = (cycle_text or "").strip().replace("Z", "").replace("z", "")
    if date_text or cycle_text:
        if not (len(date_text) == 8 and date_text.isdigit() and cycle_text in {"00", "06", "12", "18"}):
            raise ValueError("Informe data YYYYMMDD e ciclo 00, 06, 12 ou 18 juntos")
        datetime.strptime(date_text, "%Y%m%d")
        return date_text, cycle_text
    now = datetime.now(timezone.utc) - timedelta(hours=delay_hours)
    cycle_hour = (now.hour // 6) * 6
    run = now.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)
    return run.strftime("%Y%m%d"), run.strftime("%H")


def make_target_grid(resolution: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    if resolution <= 0:
        raise ValueError("A resolução deve ser positiva")
    latitudes = np.round(np.arange(-90.0, 90.0 + resolution / 2, resolution), 6)
    longitudes = np.round(np.arange(-180.0, 180.0, resolution), 6)
    return latitudes, longitudes


def combine_arrays(arrays: list[np.ndarray], minimum_models: int = 2, agreement_scale: float = 4.0) -> dict[str, np.ndarray]:
    """Combina valores disponíveis; agreement é índice de dispersão, não probabilidade calibrada."""
    if not arrays:
        raise ValueError("Nenhum campo de modelo foi fornecido")
    stack = np.stack([np.asarray(array, dtype=np.float32) for array in arrays], axis=0)
    finite = np.isfinite(stack)
    count = finite.sum(axis=0).astype(np.uint8)
    total = np.where(finite, stack, 0.0).sum(axis=0, dtype=np.float64)
    mean = np.divide(total, count, out=np.full(count.shape, np.nan, dtype=np.float32), where=count >= minimum_models).astype(np.float32)
    squared = np.where(finite, (stack - mean) ** 2, 0.0).sum(axis=0, dtype=np.float64)
    variance = np.divide(squared, count, out=np.full(count.shape, np.nan, dtype=np.float32), where=count >= minimum_models)
    spread = np.sqrt(np.maximum(variance, 0.0)).astype(np.float32)
    agreement = (100.0 * np.exp(-spread / max(float(agreement_scale), 1e-6))).astype(np.float32)
    agreement[count < minimum_models] = np.nan
    return {"mean": mean, "spread": spread, "nmodels": count, "agreement": agreement}


def raw_path(root: str | Path, model: str, date: str, cycle: str, lead: int) -> Path:
    return Path(root) / model / f"{date}{cycle}" / f"f{lead:03d}.grib2"


def icon_grid_path(root: str | Path, date: str, cycle: str) -> Path:
    """Arquivo com as coordenadas (CLAT/CLON) da grade icosaédrica nativa do ICON.

    É invariante no tempo para uma mesma rodada: o ICON global não publica
    latitude/longitude dentro de cada arquivo de campo (ecCodes não resolve
    coordenadas para gridType='unstructured_grid'), então essas coordenadas
    são baixadas uma única vez por rodada e reaproveitadas para todos os leads.
    """
    return Path(root) / "icon" / f"{date}{cycle}" / "grid.grib2"

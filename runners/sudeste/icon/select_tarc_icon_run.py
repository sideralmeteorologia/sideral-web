#!/usr/bin/env python3
"""Select an ICON run only after the TARC-required files actually exist."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import time
from pathlib import Path

import requests

BASE = "https://opendata.dwd.de/weather/nwp/v1/m/icon"
UA = "Sideral-TARC-run-selector/1.0"
PRESSURE_LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50]
PRESSURE_FIELDS = {"t": "T", "u": "U", "v": "V", "relhum": "RELHUM", "fi": "FI"}
SURFACE_FIELDS = {"t_2m": "T_2M", "relhum_2m": "RELHUM_2M", "u_10m": "U_10M", "v_10m": "V_10M", "ps": "PS", "pmsl": "PMSL"}


def run_stamp(date: str, cycle: str) -> str:
    parsed = dt.datetime.strptime(date + cycle.zfill(2), "%Y%m%d%H")
    return parsed.strftime("%Y-%m-%dT%H") + "%3A00"


def pressure_url(date: str, cycle: str, step: int, folder: str, level: int, token: str) -> str:
    level_pa = level * 100
    return (
        f"{BASE}/p/{token}/lvt1/100/lv1/{level_pa}/r/{run_stamp(date, cycle)}"
        f"/s/PT{step:03d}H00M.grib2"
    )


def surface_url(date: str, cycle: str, step: int, folder: str, token: str) -> str:
    return (
        f"{BASE}/p/{token}/r/{run_stamp(date, cycle)}"
        f"/s/PT{step:03d}H00M.grib2"
    )


def exists(url: str) -> bool:
    for attempt in range(1, 5):
        try:
            with requests.Session() as session:
                session.headers.update({"User-Agent": UA, "Cache-Control": "no-cache"})
                with session.get(url, headers={"Range": "bytes=0-0"}, timeout=20, stream=True) as response:
                    status = response.status_code
                    if status in (200, 206):
                        return True
                    if status in (401, 403, 404, 410):
                        return False
                    if (status in (408, 425, 429) or 500 <= status <= 599) and attempt < 4:
                        time.sleep(attempt * 2)
                        continue
                    return False
        except (requests.Timeout, requests.ConnectionError):
            if attempt < 4:
                time.sleep(attempt * 2)
                continue
            return False
        except requests.RequestException:
            return False
    return False


def check_urls(urls: list[str], workers: int = 16) -> list[str]:
    missing: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for url, ok in zip(urls, pool.map(exists, urls)):
            if not ok:
                missing.append(url)
    return missing


def check_run(date: str, cycle: str, steps: list[int]) -> tuple[bool, str]:
    urls: list[str] = []
    stamp = run_stamp(date, cycle)
    for step in steps:
        for token in PRESSURE_FIELDS.values():
            for level in PRESSURE_LEVELS:
                urls.append(
                    f"{BASE}/p/{token}/lvt1/100/lv1/{level * 100}/r/{stamp}/s/PT{step:03d}H00M.grib2"
                )
        for token in SURFACE_FIELDS.values():
            urls.append(f"{BASE}/p/{token}/r/{stamp}/s/PT{step:03d}H00M.grib2")

    missing = check_urls(urls, workers=24)
    if missing:
        return False, "campo requerido pelo downloader ausente: " + missing[0].rsplit("/", 1)[-1]
    return True, f"{len(urls)} campos/níveis completos em todos os passos"


def candidate_runs(now: dt.datetime, count: int) -> list[dt.datetime]:
    base = now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0)
    return [base - dt.timedelta(hours=6 * i) for i in range(count)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-hour", type=int, required=True)
    parser.add_argument("--end-hour", type=int, required=True)
    parser.add_argument("--date", help="Legacy mode: validate only this exact ICON source run")
    parser.add_argument("--cycle", help="Legacy mode: validate only this exact ICON source run")
    parser.add_argument("--target-date", help="Target WRF valid date; select an available earlier ICON cycle")
    parser.add_argument("--target-cycle", help="Target WRF valid cycle (00/06/12/18)")
    parser.add_argument("--max-back", type=int, default=8)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.start_hour < 0 or args.end_hour < args.start_hour:
        raise SystemExit("Intervalo ICON invalido")
    if args.start_hour % 3 or args.end_hour % 3:
        raise SystemExit("Inicio/fim ICON precisam ser multiplos de 3 horas")
    if bool(args.date) != bool(args.cycle):
        raise SystemExit("--date e --cycle precisam ser informados juntos")
    if bool(args.target_date) != bool(args.target_cycle):
        raise SystemExit("--target-date e --target-cycle precisam ser informados juntos")
    if args.date and args.target_date:
        raise SystemExit("Use --date/--cycle ou --target-date/--target-cycle, nao ambos")

    forecast_steps = list(range(args.start_hour, args.end_hour + 1, 3))
    if not forecast_steps:
        raise SystemExit("Nenhum passo ICON solicitado")

    selected: tuple[str, str, int] | None = None
    target: dt.datetime | None = None

    if args.target_date:
        try:
            target = dt.datetime.strptime(
                args.target_date + args.target_cycle.zfill(2), "%Y%m%d%H"
            ).replace(tzinfo=dt.timezone.utc)
        except ValueError as exc:
            raise SystemExit(f"Data/ciclo alvo ICON invalido: {exc}") from exc
        if target.hour not in (0, 6, 12, 18):
            raise SystemExit("Ciclo alvo ICON precisa ser 00, 06, 12 ou 18Z")

        now = dt.datetime.now(dt.timezone.utc)
        latest = min(
            now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0),
            target,
        )
        candidates = [
            latest - dt.timedelta(hours=6 * i)
            for i in range(max(1, args.max_back))
        ]

        for source_run in candidates:
            age_hours = (now - source_run).total_seconds() / 3600.0
            if age_hours < -0.1 or age_hours > 18.0:
                continue
            offset_hours = int((target - source_run).total_seconds() // 3600)
            if offset_hours < 0 or offset_hours % 3:
                continue
            source_steps = [hour + offset_hours for hour in forecast_steps]
            date, cycle = source_run.strftime("%Y%m%d"), source_run.strftime("%H")
            print(
                f"ICON probe: fonte {date} {cycle}Z +{offset_hours}h; "
                f"validade WRF {target:%Y%m%d %H}Z; passos fonte={source_steps}",
                flush=True,
            )
            ok, reason = check_run(date, cycle, source_steps)
            if ok:
                selected = (date, cycle, offset_hours)
                print(f"ICON probe: fonte aprovada {date} {cycle}Z — {reason}", flush=True)
                break
            print(f"ICON probe: rejeitando {date} {cycle}Z — {reason}", flush=True)

        if selected is None:
            raise SystemExit(
                f"Nenhum ciclo ICON completo encontrado para a validade "
                f"{target:%Y%m%d %H}Z nos ultimos {max(1, args.max_back)} ciclos"
            )

    elif args.date:
        source_run = dt.datetime.strptime(
            args.date + args.cycle.zfill(2), "%Y%m%d%H"
        ).replace(tzinfo=dt.timezone.utc)
        date, cycle = source_run.strftime("%Y%m%d"), source_run.strftime("%H")
        print(f"ICON probe: validando ciclo fixado {date} {cycle}Z; passos={forecast_steps}", flush=True)
        ok, reason = check_run(date, cycle, forecast_steps)
        if not ok:
            raise SystemExit(f"RUN ICON fixado {date}{cycle} incompleto: {reason}")
        selected = (date, cycle, 0)

    else:
        now = dt.datetime.now(dt.timezone.utc)
        candidates = candidate_runs(now, max(1, args.max_back))
        for source_run in candidates:
            age_hours = (now - source_run).total_seconds() / 3600.0
            if age_hours < -0.1 or age_hours > 18.0:
                continue
            date, cycle = source_run.strftime("%Y%m%d"), source_run.strftime("%H")
            print(f"ICON probe: testando {date} {cycle}Z; passos={forecast_steps}", flush=True)
            ok, reason = check_run(date, cycle, forecast_steps)
            if ok:
                selected = (date, cycle, 0)
                print(f"ICON probe: RUN completo {date} {cycle}Z — {reason}", flush=True)
                break
            print(f"ICON probe: rejeitando {date} {cycle}Z — {reason}", flush=True)
        if selected is None:
            raise SystemExit("Nenhum RUN ICON completo encontrado nos ciclos recentes")

    source_date, source_cycle, offset_hours = selected
    valid_date = target.strftime("%Y%m%d") if target else source_date
    valid_cycle = target.strftime("%H") if target else source_cycle

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(
        f"RUN_DATE={valid_date}\n"
        f"RUN_CYCLE={valid_cycle}\n"
        f"SOURCE_MODEL=icon\n"
        f"ICON_SOURCE_DATE={source_date}\n"
        f"ICON_SOURCE_CYCLE={source_cycle}\n"
        f"ICON_OFFSET_HOURS={offset_hours}\n",
        encoding="utf-8",
    )
    tmp.replace(out)


if __name__ == "__main__":
    main()

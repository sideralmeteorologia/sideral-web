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
    return (
        f"{BASE}/p/{token}/lvt1/100/lv1/{level * 100}/r/{run_stamp(date, cycle)}"
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
    parser.add_argument("--date", help="If supplied, validate only this pinned run")
    parser.add_argument("--cycle", help="If supplied, validate only this pinned run")
    parser.add_argument("--max-back", type=int, default=8)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.start_hour < 0 or args.end_hour < args.start_hour:
        raise SystemExit("Intervalo ICON invalido")
    if args.start_hour % 3 or args.end_hour % 3:
        raise SystemExit("Inicio/fim ICON precisam ser multiplos de 3 horas")
    if bool(args.date) != bool(args.cycle):
        raise SystemExit("--date e --cycle precisam ser informados juntos")
    steps = list(range(args.start_hour, args.end_hour + 1, 3))
    if not steps:
        raise SystemExit("Nenhum passo ICON solicitado")

    if args.date:
        candidates = [dt.datetime.strptime(args.date + args.cycle.zfill(2), "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)]
        pinned = True
    else:
        now = dt.datetime.now(dt.timezone.utc)
        candidates = candidate_runs(now, max(1, args.max_back))
        candidates = [run for run in candidates if -0.1 <= (now - run).total_seconds() / 3600.0 <= 18.0]
        pinned = False

    selected = None
    for run in candidates:
        date, cycle = run.strftime("%Y%m%d"), run.strftime("%H")
        print(f"ICON probe: testando {date} {cycle}Z; passos={steps}", flush=True)
        ok, reason = check_run(date, cycle, steps)
        if ok:
            selected = (date, cycle)
            print(f"ICON probe: RUN completo {date} {cycle}Z — {reason}", flush=True)
            break
        print(f"ICON probe: rejeitando {date} {cycle}Z — {reason}", flush=True)
        if pinned:
            break

    if selected is None:
        if pinned:
            raise SystemExit(f"RUN ICON fixado {args.date}{args.cycle} incompleto; nao sera trocado silenciosamente")
        raise SystemExit("Nenhum RUN ICON completo encontrado nos ciclos recentes")

    date, cycle = selected
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(
        f"RUN_DATE={date}\nRUN_CYCLE={cycle}\nSOURCE_MODEL=icon\n",
        encoding="utf-8",
    )
    tmp.replace(out)


if __name__ == "__main__":
    main()

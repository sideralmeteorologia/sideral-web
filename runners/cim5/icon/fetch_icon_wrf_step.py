#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import random
import tempfile
import time
from pathlib import Path

import requests

# DWD ICON Global v1: uncompressed GRIB2, one field per file.
BASE = "https://opendata.dwd.de/weather/nwp/v1/m/icon"
UA = "SideralMeteorologia-WRF/2.0"
PRESSURE_LEVELS_HPA = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50]
PRESSURE_FIELDS = ("T", "U", "V", "RELHUM", "FI")
SURFACE_FIELDS = ("T_2M", "RELHUM_2M", "U_10M", "V_10M", "PS", "PMSL")
MAX_ATTEMPTS = 5


def run_stamp(date: str, cycle: str) -> str:
    parsed = dt.datetime.strptime(date + cycle, "%Y%m%d%H")
    return parsed.strftime("%Y-%m-%dT%H") + "%3A00"


def pressure_url(date: str, cycle: str, step: int, param: str, level_hpa: int) -> str:
    return (
        f"{BASE}/p/{param}/lvt1/100/lv1/{level_hpa * 100}/r/{run_stamp(date, cycle)}"
        f"/s/PT{step:03d}H00M.grib2"
    )


def surface_url(date: str, cycle: str, step: int, param: str) -> str:
    return (
        f"{BASE}/p/{param}/r/{run_stamp(date, cycle)}"
        f"/s/PT{step:03d}H00M.grib2"
    )


def download_one(url: str, path: Path) -> Path:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        tmp = path.with_name(path.name + ".part")
        try:
            with requests.get(url, headers={"User-Agent": UA}, timeout=(20, 180), stream=True) as response:
                status = response.status_code
                if status == 404:
                    raise RuntimeError(f"ICON v1 campo inexistente (HTTP 404): {url}")
                # 408/425/429 and 5xx are transient; the retry handler below deals with them.
                response.raise_for_status()
                with tmp.open("wb") as out:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            out.write(chunk)
            with tmp.open("rb") as source:
                magic = source.read(4)
            if tmp.stat().st_size < 8 or magic != b"GRIB":
                raise RuntimeError(f"Resposta ICON v1 nao e um GRIB2 valido: {url}")
            tmp.replace(path)
            print(f"OK {url.rsplit('/', 1)[-1]} ({path.stat().st_size / 1024 / 1024:.2f} MiB)", flush=True)
            return path
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            last_error = exc
            tmp.unlink(missing_ok=True)
            if status is not None and 400 <= status < 500 and status not in (408, 425, 429):
                raise RuntimeError(f"ICON v1 HTTP {status} definitivo: {url}") from exc
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            tmp.unlink(missing_ok=True)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        if attempt < MAX_ATTEMPTS:
            delay = min(60, attempt * 5 + random.uniform(0, 2))
            print(f"ICON v1 erro transitorio; tentativa {attempt}/{MAX_ATTEMPTS}; aguardando {delay:.1f}s", flush=True)
            time.sleep(delay)
    raise RuntimeError(f"ICON v1 falhou apos {MAX_ATTEMPTS} tentativas: {url}: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download de um passo ICON Global v1, exclusivamente DWD.")
    parser.add_argument("--date", required=True, help="Data da rodada YYYYMMDD")
    parser.add_argument("--cycle", required=True, help="Ciclo da rodada 00/06/12/18Z")
    parser.add_argument("--step", required=True, type=int, help="Lead time em horas, multiplo de 3")
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    if len(args.date) != 8 or not args.date.isdigit():
        raise SystemExit("--date precisa ser YYYYMMDD")
    cycle = args.cycle.zfill(2)
    if cycle not in {"00", "06", "12", "18"}:
        raise SystemExit("--cycle precisa ser 00, 06, 12 ou 18")
    if args.step < 0 or args.step > 384 or args.step % 3:
        raise SystemExit("--step precisa ser multiplo de 3 entre F000 e F384")
    if args.workers < 1 or args.workers > 24:
        raise SystemExit("--workers precisa estar entre 1 e 24")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    urls = [
        pressure_url(args.date, cycle, args.step, param, level)
        for param in PRESSURE_FIELDS
        for level in PRESSURE_LEVELS_HPA
    ]
    urls.extend(surface_url(args.date, cycle, args.step, param) for param in SURFACE_FIELDS)

    with tempfile.TemporaryDirectory(prefix="sideral-icon-v1-") as temporary_dir:
        tmpdir = Path(temporary_dir)
        jobs = [(url, tmpdir / f"{index:04d}.grib2") for index, url in enumerate(urls)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(download_one, url, path) for url, path in jobs]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        combined = output.with_name(output.name + ".part")
        try:
            with combined.open("wb") as destination:
                for _, part in jobs:
                    with part.open("rb") as source:
                        while True:
                            chunk = source.read(4 * 1024 * 1024)
                            if not chunk:
                                break
                            destination.write(chunk)
            with combined.open("rb") as source:
                magic = source.read(4)
            if combined.stat().st_size < 1_000_000 or magic != b"GRIB":
                raise RuntimeError(f"ICON combinado invalido/pequeno: {combined.stat().st_size} bytes")
            combined.replace(output)
        except Exception:
            combined.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
            raise

    print(f"ICON v1 F{args.step:03d} combinado: {output.stat().st_size / 1024 / 1024:.1f} MiB", flush=True)


if __name__ == "__main__":
    main()

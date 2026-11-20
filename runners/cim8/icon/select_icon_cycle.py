#!/usr/bin/env python3
"""Select a complete recent DWD ICON Global cycle for the legacy GRIB2/BZ2 feed.

The WRF downloader consumes the classic opendata.dwd.de/weather/nwp/icon/grib
products. Validate every required field/level at every requested lead time
before returning a cycle, rather than checking only one surface file.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import sys
import time
import urllib.error
import urllib.request

BASE = "https://opendata.dwd.de/weather/nwp/icon/grib"
UA = "Sideral-ICON-cycle-selector/1.0"
PRESSURE_LEVELS = (1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50)
PRESSURE_FIELDS = {
    "t": "T",
    "u": "U",
    "v": "V",
    "relhum": "RELHUM",
    "fi": "FI",
}
SURFACE_FIELDS = {
    "t_2m": "T_2M",
    "relhum_2m": "RELHUM_2M",
    "u_10m": "U_10M",
    "v_10m": "V_10M",
    "ps": "PS",
    "pmsl": "PMSL",
}


def source_urls(date: str, cycle: str, step: int) -> list[str]:
    stamp = f"{date}{cycle}"
    urls = [
        f"{BASE}/{cycle}/{folder}/icon_global_icosahedral_pressure-level_{stamp}_{step:03d}_{level}_{token}.grib2.bz2"
        for folder, token in PRESSURE_FIELDS.items()
        for level in PRESSURE_LEVELS
    ]
    urls.extend(
        f"{BASE}/{cycle}/{folder}/icon_global_icosahedral_single-level_{stamp}_{step:03d}_{token}.grib2.bz2"
        for folder, token in SURFACE_FIELDS.items()
    )
    return urls


def url_exists(url: str) -> bool:
    for attempt in range(1, 4):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": UA, "Range": "bytes=0-0", "Cache-Control": "no-cache"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status not in (200, 206):
                    return False
                response.read(1)
                return True
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404, 410):
                return False
            if not (exc.code in (408, 425, 429) or 500 <= exc.code <= 599):
                return False
        except (TimeoutError, urllib.error.URLError, OSError):
            pass
        if attempt < 3:
            time.sleep(attempt * 2)
    return False


def cycle_complete(date: str, cycle: str, steps: list[int], workers: int) -> tuple[bool, str]:
    urls = [url for step in steps for url in source_urls(date, cycle, step)]
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    futures = {executor.submit(url_exists, url): url for url in urls}
    try:
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            try:
                ok = future.result()
            except Exception:
                ok = False
            if not ok:
                for pending in futures:
                    if pending is not future:
                        pending.cancel()
                return False, url
        return True, ""
    finally:
        # Requests already running are bounded by the 20 s network timeout.
        executor.shutdown(wait=False, cancel_futures=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-hour", type=int, default=0)
    parser.add_argument("--end-hour", type=int, required=True)
    parser.add_argument("--interval", type=int, default=3)
    parser.add_argument("--max-age-hours", type=int, default=48)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()

    if (
        args.start_hour < 0
        or args.end_hour < args.start_hour
        or args.end_hour > 72
        or args.interval < 1
        or args.start_hour % args.interval
        or args.end_hour % args.interval
        or not 1 <= args.max_age_hours <= 72
        or not 1 <= args.workers <= 48
    ):
        raise SystemExit("Janela/limites ICON invalidos")

    steps = list(range(args.start_hour, args.end_hour + 1, args.interval))
    now = dt.datetime.now(dt.timezone.utc)
    candidate = now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0)
    cutoff = now - dt.timedelta(hours=args.max_age_hours)

    while candidate >= cutoff:
        date, cycle = candidate.strftime("%Y%m%d"), candidate.strftime("%H")
        print(
            f"Validando ICON {date} {cycle}Z: F{args.start_hour:03d}-F{args.end_hour:03d}, "
            f"passo {args.interval} h, {len(steps) * 71} arquivos",
            file=sys.stderr,
            flush=True,
        )
        complete, missing = cycle_complete(date, cycle, steps, args.workers)
        if complete:
            print(f"{date} {cycle}")
            return 0
        print(f"ICON {date} {cycle}Z incompleto; ausente/indisponivel: {missing}", file=sys.stderr)
        candidate -= dt.timedelta(hours=6)

    raise SystemExit("Nenhum ciclo ICON completo encontrado nos ultimos 48 h")


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
import random
import subprocess
import tempfile
import time
from pathlib import Path

from ecmwf.opendata import Client

PRESSURE_LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50]
PRESSURE_PARAMS = ["z", "t", "u", "v", "r"]
SURFACE_PARAMS = ["2t", "2d", "10u", "10v", "sp", "msl"]

MAX_ATTEMPTS = int(os.getenv("ECMWF_MAX_ATTEMPTS", "6"))
BASE_DELAY_SECONDS = float(os.getenv("ECMWF_BASE_DELAY_SECONDS", "15"))
BETWEEN_REQUESTS_SECONDS = float(os.getenv("ECMWF_BETWEEN_REQUESTS_SECONDS", "12"))


def as_utc(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        parsed = dt.datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    if isinstance(code, int):
        return code
    text = str(exc).lower()
    if "too many requests" in text or "429" in text:
        return 429
    for code in (408, 425, 429, *range(500, 600)):
        if str(code) in text:
            return code
    return None


def with_retry(label: str, func):
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(f"ECMWF {label}: tentativa {attempt}/{MAX_ATTEMPTS}")
            return func()
        except Exception as exc:
            last_error = exc
            code = _status_code(exc)
            # ECMWF can briefly return 404 while the newest operational index is
            # propagating. Retry 404 twice only; then let the caller try an older
            # IFS cycle. Never convert a persistent/missing field into a fallback.
            not_yet_published = code == 404 and attempt <= int(os.getenv("ECMWF_404_RETRIES", "2"))
            retryable = (
                not_yet_published
                or code in (408, 425, 429)
                or (code is not None and 500 <= code <= 599)
                or isinstance(exc, (TimeoutError, ConnectionError))
                or type(exc).__name__ in {
                    "Timeout", "ConnectTimeout", "ReadTimeout",
                    "ChunkedEncodingError", "ConnectionError", "ProxyError",
                    "SSLError", "NewConnectionError", "RemoteDisconnected",
                }
            )
            if not retryable or attempt >= MAX_ATTEMPTS:
                raise

            response = getattr(exc, "response", None)
            retry_after = None
            if response is not None:
                headers = getattr(response, "headers", {}) or {}
                raw = headers.get("Retry-After")
                if raw:
                    try:
                        retry_after = float(raw)
                    except (TypeError, ValueError):
                        retry_after = None

            if retry_after is None:
                retry_after = (15.0 * attempt) if code == 404 else BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            delay = min(60.0 if code == 404 else 300.0, retry_after + random.uniform(0.0, 5.0))
            print(
                f"ECMWF {label}: HTTP {code}; aguardando {delay:.1f}s antes de tentar novamente",
                flush=True,
            )
            time.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"ECMWF {label}: falha sem excecao registrada")



def validate_pressure_geopotential(pressure: Path, steps: list[int]) -> None:
    """Require the 13 ECMWF pressure-level geopotential fields at every source lead.

    Some operational IFS files/cycles can lack the pressure-level z field at F000.
    Reject that source cycle here so the caller can try the previous IFS cycle
    instead of failing later in WPS/Metgrid after an expensive download.
    """
    expected = len(PRESSURE_LEVELS)
    with tempfile.TemporaryDirectory(prefix="ecmwf-z-check-", dir=str(pressure.parent)) as temp:
        root = Path(temp)
        all_z = root / "geopotential_all.grib2"
        extracted = subprocess.run(
            ["grib_copy", "-w", "paramId=129", str(pressure), str(all_z)],
            capture_output=True, text=True,
        )
        if extracted.returncode != 0 or not all_z.is_file() or all_z.stat().st_size == 0:
            raise RuntimeError("ECMWF IFS nao retornou geopotencial pressure-level (paramId=129)")
        # Extract z from the large pressure file once; per-step checks now scan
        # only the much smaller geopotential subset.
        for step in steps:
            z_file = root / f"z_{step:03d}.grib2"
            selected = subprocess.run(
                ["grib_copy", "-w", f"stepRange={step}", str(all_z), str(z_file)],
                capture_output=True, text=True,
            )
            if selected.returncode != 0 or not z_file.is_file() or z_file.stat().st_size == 0:
                count = 0
            else:
                counted = subprocess.run(
                    ["grib_count", str(z_file)], capture_output=True, text=True,
                )
                try:
                    count = int(counted.stdout.strip().splitlines()[-1]) if counted.returncode == 0 else 0
                except (ValueError, IndexError):
                    count = 0
            if count != expected:
                raise RuntimeError(
                    f"ECMWF IFS geopotencial incompleto no F{step:03d}: "
                    f"{count}/{expected} niveis pressure-level (paramId=129); "
                    "ciclo rejeitado para tentar uma rodada IFS anterior"
                )
            print(f"ECMWF IFS F{step:03d}: geopotencial completo ({count}/{expected} niveis)", flush=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start-hour", type=int, default=0, help="First WRF forecast hour requested by this segment")
    p.add_argument("--max-hour", type=int, required=True)
    p.add_argument("--hour-offset", type=int, default=0, help="Lead-time offset in hours for matching an older run to target valid times")
    p.add_argument("--output", required=True)
    p.add_argument("--run-env", required=True)
    p.add_argument("--date")
    p.add_argument("--cycle")
    args = p.parse_args()

    if args.start_hour < 0 or args.start_hour % 3:
        raise SystemExit("--start-hour precisa ser multiplo de 3 e >= 0")
    if args.max_hour < args.start_hour or args.max_hour % 3:
        raise SystemExit("--max-hour precisa ser multiplo de 3 e >= --start-hour")
    if args.hour_offset < 0 or args.hour_offset % 3:
        raise SystemExit("--hour-offset precisa ser multiplo de 3 e >= 0")

    client = Client(source="ecmwf", model="ifs")
    steps = list(range(args.start_hour + args.hour_offset, args.max_hour + args.hour_offset + 1, 3))

    if args.date and args.cycle:
        run = dt.datetime.strptime(args.date + args.cycle.zfill(2), "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
    else:
        # Consulta leve para descobrir uma rodada que ja tenha o ultimo passo necessario.
        run = as_utc(
            with_retry(
                "descoberta da rodada",
                lambda: client.latest(type="fc", step=args.max_hour + args.hour_offset, param=["2t"]),
            )
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pressure = output.with_name(output.stem + "_pressure.grib2")
    surface = output.with_name(output.stem + "_surface.grib2")

    common = {
        "date": run.strftime("%Y%m%d"),
        "time": int(run.strftime("%H")),
        "type": "fc",
        "step": steps,
    }

    print("ECMWF IFS rodada:", run.isoformat(), "passos:", steps)
    with_retry(
        "campos de pressao",
        lambda: client.retrieve(
            **common,
            param=PRESSURE_PARAMS,
            levelist=PRESSURE_LEVELS,
            target=str(pressure),
        ),
    )

    # Evita duas recuperacoes pesadas coladas, que favorecem HTTP 429.
    if BETWEEN_REQUESTS_SECONDS > 0:
        print(
            f"ECMWF: aguardando {BETWEEN_REQUESTS_SECONDS:.1f}s entre pressao e superficie",
            flush=True,
        )
        time.sleep(BETWEEN_REQUESTS_SECONDS)

    with_retry(
        "campos de superficie",
        lambda: client.retrieve(
            **common,
            param=SURFACE_PARAMS,
            target=str(surface),
        ),
    )

    if pressure.stat().st_size < 1_000_000:
        raise RuntimeError(f"ECMWF pressure pequeno demais: {pressure.stat().st_size}")
    if surface.stat().st_size < 100_000:
        raise RuntimeError(f"ECMWF surface pequeno demais: {surface.stat().st_size}")
    validate_pressure_geopotential(pressure, steps)

    with output.open("wb") as out:
        out.write(pressure.read_bytes())
        out.write(surface.read_bytes())

    env = Path(args.run_env)
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text(
        f"RUN_DATE={run:%Y%m%d}\n"
        f"RUN_CYCLE={run:%H}\n"
        "SOURCE_MODEL=ecmwf\n",
        encoding="utf-8",
    )

    print(f"ECMWF combinado: {output.stat().st_size / 1024 / 1024:.1f} MiB")
    print(env.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

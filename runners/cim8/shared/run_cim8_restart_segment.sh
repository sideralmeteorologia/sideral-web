#!/usr/bin/env bash
set -euo pipefail

START_HOUR="${1:?Informe a hora inicial do restart}"
END_HOUR="${2:?Informe a hora final do restart}"
INPUT_DIR="${3:-cim8_restart_input}"
ROOT="${GITHUB_WORKSPACE:-$PWD}"
RUN_DIR="$ROOT/wrf_work/run"
IMAGE="dtcenter/wps_wrf:latest"
MPI_PROCS="${WRF_MPI_PROCS:-4}"
TIME_STEP="${WRF_TIME_STEP:-30}"
HISTORY_INTERVAL="${WRF_HISTORY_INTERVAL_MINUTES:-60}"

(( START_HOUR == 21 && END_HOUR == 42 )) || {
  echo "CIM 8 km restart esperado F021-F042; recebido F$START_HOUR-F$END_HOUR" >&2
  exit 2
}
test -d "$INPUT_DIR" || { echo "Checkpoint CIM 8 km ausente: $INPUT_DIR" >&2; exit 3; }
test -d "$RUN_DIR" || { echo "Diretorio WRF apos preparacao de LBC ausente: $RUN_DIR" >&2; exit 4; }
test -s "$INPUT_DIR/run.env" || { echo "run.env ausente no checkpoint CIM 8 km" >&2; exit 5; }
set -a
source "$INPUT_DIR/run.env"
set +a
[[ "${RUN_DATE:-}" =~ ^[0-9]{8}$ ]] || { echo "RUN_DATE invalido no checkpoint: ${RUN_DATE:-}" >&2; exit 6; }
[[ "${RUN_CYCLE:-}" =~ ^(00|06|12|18)$ ]] || { echo "RUN_CYCLE invalido no checkpoint: ${RUN_CYCLE:-}" >&2; exit 7; }
export RUN_DATE RUN_CYCLE

EXPECTED_RST="$(date -u -d "$RUN_DATE $RUN_CYCLE:00 UTC +$START_HOUR hours" '+wrfrst_d01_%Y-%m-%d_%H:%M:%S')"
test -s "$INPUT_DIR/$EXPECTED_RST" || {
  echo "Restart CIM 8 km exato ausente: $INPUT_DIR/$EXPECTED_RST" >&2
  find "$INPUT_DIR" -maxdepth 1 -type f -name 'wrfrst_d01_*' -printf '%f %s bytes\n' >&2 || true
  exit 8
}
test -s "$RUN_DIR/wrfbdy_d01" || { echo "wrfbdy_d01 F021-F042 ausente apos boundary-only" >&2; exit 9; }
test -s "$RUN_DIR/namelist.input" || { echo "namelist.input ausente apos preparacao de LBC" >&2; exit 10; }

mapfile -t PRIOR_OUTPUTS < <(find "$INPUT_DIR" -maxdepth 1 -type f -name 'wrfout_d01_*' -size +0c -print | sort)
(${#PRIOR_OUTPUTS[@]} > 0) || { echo "wrfout F000-F021 ausente no checkpoint CIM 8 km" >&2; exit 11; }
cp -f "${PRIOR_OUTPUTS[@]}" "$RUN_DIR/"
cp -f "$INPUT_DIR/$EXPECTED_RST" "$RUN_DIR/$EXPECTED_RST"
cp -f "$INPUT_DIR/run.env" "$RUN_DIR/sideral-run.env"

python3 - "$RUN_DIR/namelist.input" "$RUN_DATE" "$RUN_CYCLE" "$START_HOUR" "$END_HOUR" "$TIME_STEP" "$HISTORY_INTERVAL" <<'PY'
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re, sys

path = Path(sys.argv[1])
run_date, run_cycle = sys.argv[2], sys.argv[3]
start_h, end_h = int(sys.argv[4]), int(sys.argv[5])
time_step, history = int(sys.argv[6]), int(sys.argv[7])
base = datetime.strptime(run_date + run_cycle, "%Y%m%d%H").replace(tzinfo=timezone.utc)
start, end = base + timedelta(hours=start_h), base + timedelta(hours=end_h)
text = path.read_text(encoding="utf-8")

def put(section: str, key: str, value: object) -> None:
    global text
    pattern = rf"(?m)^\s*{re.escape(key)}\s*=.*$"
    replacement = f" {key} = {value},"
    found = list(re.finditer(pattern, text))
    if len(found) > 1:
        raise SystemExit(f"namelist: {key} aparece {len(found)} vezes")
    if found:
        text = re.sub(pattern, replacement, text, count=1)
        return
    marker = f"&{section}"
    if marker not in text:
        raise SystemExit(f"namelist: secao {marker} ausente")
    text = text.replace(marker, marker + "\n" + replacement, 1)

for key, value in {
    "run_days": 0, "run_hours": end_h-start_h, "run_minutes": 0, "run_seconds": 0,
    "start_year": start.year, "start_month": start.month, "start_day": start.day,
    "start_hour": start.hour, "start_minute": 0, "start_second": 0,
    "end_year": end.year, "end_month": end.month, "end_day": end.day,
    "end_hour": end.hour, "end_minute": 0, "end_second": 0,
    "restart_interval": (end_h-start_h)*60, "history_interval": history,
}.items():
    put("time_control", key, value)
for key, value in {
    "time_step": time_step, "time_step_fract_num": 0, "time_step_fract_den": 1,
}.items():
    put("domains", key, value)
put("time_control", "restart", ".true.")
put("time_control", "override_restart_timers", ".true.")
put("time_control", "write_hist_at_0h_rst", ".true.")
path.write_text(text, encoding="utf-8")
print(f"CIM 8 km restart: {start.isoformat()} -> {end.isoformat()}; dt={time_step} s; history={history} min")
PY

find "$RUN_DIR" -maxdepth 1 -type f -name 'wrfrst_d01_*' ! -name "$EXPECTED_RST" -delete
chmod -R a+rwX "$RUN_DIR"
STARTED_AT="$(date +%s)"
set +e
docker run --rm --entrypoint /bin/bash \
  -e OMPI_ALLOW_RUN_AS_ROOT=1 -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
  -e WRF_MPI_PROCS="$MPI_PROCS" -e EXPECTED_RST="$EXPECTED_RST" \
  -v "$RUN_DIR:/run" "$IMAGE" -lc '
    set -euo pipefail
    cd /run
    test -s "$EXPECTED_RST"
    test -s wrfbdy_d01
    echo "CIM 8 km restart-only F021-F042; MPI=$WRF_MPI_PROCS; restart=$EXPECTED_RST"
    mpirun --allow-run-as-root --oversubscribe --bind-to none \
      -np "$WRF_MPI_PROCS" /comsoftware/wrf/WRF-4.3/main/wrf.exe \
      > rsl.out.cim8-restart 2>&1
    grep -q "SUCCESS COMPLETE WRF" rsl.error.0000
    test -n "$(find . -maxdepth 1 -type f -name "wrfout_d01_*" -size +0c -print -quit)"
  '
STATUS=$?
set -e
echo "CIM8_RESTART_SECONDS=$(($(date +%s)-STARTED_AT))"
if (( STATUS != 0 )); then
  echo "CIM 8 km restart F$START_HOUR-F$END_HOUR falhou: $STATUS" >&2
  tail -n 240 "$RUN_DIR/rsl.out.cim8-restart" >&2 2>/dev/null || true
  for log in "$RUN_DIR"/rsl.error.*; do
    [[ -f "$log" ]] || continue
    echo "===== $(basename "$log") =====" >&2
    tail -n 160 "$log" >&2 || true
  done
  exit "$STATUS"
fi
mapfile -t FINAL_OUTPUTS < <(find "$RUN_DIR" -maxdepth 1 -type f -name 'wrfout_d01_*' -size +0c -print | sort)
(${#FINAL_OUTPUTS[@]} > 0) || { echo "Nenhum wrfout CIM 8 km final produzido" >&2; exit 41; }
echo "CIM 8 km restart concluido; arquivos wrfout totais=${#FINAL_OUTPUTS[@]}"

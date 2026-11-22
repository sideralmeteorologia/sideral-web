#!/usr/bin/env bash
set -euo pipefail

START_HOUR="${1:?Informe a hora inicial do restart}"
END_HOUR="${2:?Informe a hora final do restart}"
RESTART_DIR="${3:?Informe o diretorio do checkpoint}"
ROOT="${GITHUB_WORKSPACE:-$PWD}"
IMAGE="${WRF_IMAGE:-dtcenter/wps_wrf:latest}"
MPI_PROCS="${WRF_MPI_PROCS:-4}"
HISTORY_MINUTES="${WRF_HISTORY_INTERVAL_MINUTES:-60}"
WORK="$ROOT/cim8_restart_work"
CHECKPOINT="$WORK/checkpoint"
RUN_DIR="$WORK/run"
OUTPUT_DIR="$ROOT/wrf_work/run"

(( START_HOUR > 0 && END_HOUR > START_HOUR && END_HOUR <= 72 )) || {
  echo "Intervalo CIM8 restart invalido: F$START_HOUR-F$END_HOUR" >&2
  exit 2
}
[[ "$MPI_PROCS" =~ ^[1-9][0-9]*$ ]] || { echo "WRF_MPI_PROCS invalido: $MPI_PROCS" >&2; exit 2; }
[[ "$HISTORY_MINUTES" =~ ^(60|180)$ ]] || { echo "WRF_HISTORY_INTERVAL_MINUTES invalido: $HISTORY_MINUTES" >&2; exit 2; }
test -d "$RESTART_DIR" || { echo "Checkpoint CIM8 ausente: $RESTART_DIR" >&2; exit 3; }
test -s "$RESTART_DIR/cim8-run.env" || { echo "cim8-run.env ausente no checkpoint" >&2; exit 4; }

# O arquivo é produzido pelo job F000-F021 e fixa a mesma rodada para ambos os segmentos.
set -a
source "$RESTART_DIR/cim8-run.env"
set +a
[[ "${RUN_DATE:-}" =~ ^[0-9]{8}$ ]] || { echo "RUN_DATE invalido no checkpoint: ${RUN_DATE:-}" >&2; exit 5; }
[[ "${RUN_CYCLE:-}" =~ ^(00|06|12|18)$ ]] || { echo "RUN_CYCLE invalido no checkpoint: ${RUN_CYCLE:-}" >&2; exit 5; }

mapfile -t RESTARTS < <(find "$RESTART_DIR" -maxdepth 1 -type f -name 'wrfrst_d01_*' -size +0c -print | sort)
(("${#RESTARTS[@]}" == 1)) || {
  echo "Esperado um único wrfrst_d01_* no checkpoint; encontrados ${#RESTARTS[@]}" >&2
  printf '%s\n' "${RESTARTS[@]}" >&2
  exit 6
}
test -s "$RESTART_DIR/wrfbdy_d01" || { echo "wrfbdy_d01 ausente/vazio no checkpoint" >&2; exit 7; }
test -s "$RESTART_DIR/namelist.input" || { echo "namelist.input ausente no checkpoint" >&2; exit 8; }

EXPECTED_RESTART="$(python3 - "$RUN_DATE" "$RUN_CYCLE" "$START_HOUR" <<'PY'
import datetime as dt, sys
base=dt.datetime.strptime(sys.argv[1]+sys.argv[2], "%Y%m%d%H")
print("wrfrst_d01_"+(base+dt.timedelta(hours=int(sys.argv[3]))).strftime("%Y-%m-%d_%H:%M:%S"))
PY
)"
[[ "${RESTARTS[0]##*/}" == "$EXPECTED_RESTART" ]] || {
  echo "Restart nao corresponde a F$START_HOUR: esperado $EXPECTED_RESTART; recebido ${RESTARTS[0]##*/}" >&2
  exit 9
}

rm -rf "$WORK"
mkdir -p "$CHECKPOINT" "$RUN_DIR"
cp -f "${RESTARTS[0]}" "$CHECKPOINT/$EXPECTED_RESTART"
cp -f "$RESTART_DIR/wrfbdy_d01" "$RESTART_DIR/namelist.input" "$CHECKPOINT/"
chmod -R a+rwX "$WORK"

# Atualiza apenas relógio e flags de restart; preserva toda a física e geometria da primeira etapa.
python3 - "$CHECKPOINT/namelist.input" "$RUN_DATE" "$RUN_CYCLE" "$START_HOUR" "$END_HOUR" "$HISTORY_MINUTES" <<'PY'
import datetime as dt, re, sys
path, run_date, run_cycle, start_h, end_h, history = sys.argv[1:]
start_h, end_h, history = int(start_h), int(end_h), int(history)
base=dt.datetime.strptime(run_date+run_cycle, "%Y%m%d%H")
start=base+dt.timedelta(hours=start_h)
end=base+dt.timedelta(hours=end_h)
hours=end_h-start_h
text=open(path,encoding="utf-8").read()
values={
 "run_days":0, "run_hours":hours, "run_minutes":0, "run_seconds":0,
 "start_year":start.year, "start_month":start.month, "start_day":start.day, "start_hour":start.hour,
 "end_year":end.year, "end_month":end.month, "end_day":end.day, "end_hour":end.hour,
 "restart":".true.", "restart_interval":hours*60, "override_restart_timers":".true.",
 "history_interval":history, "write_hist_at_0h_rst":".false.",
}
for key,value in values.items():
    pattern=rf"(?m)^\s*{re.escape(key)}\s*=.*$"
    replacement=f" {key} = {value},"
    if re.search(pattern,text):
        text,n=re.subn(pattern,replacement,text,count=1)
        if n!=1: raise SystemExit(f"Falha ao atualizar {key}")
    elif key in {"override_restart_timers","write_hist_at_0h_rst"}:
        text=text.replace("&time_control", "&time_control\n"+replacement, 1)
    else:
        raise SystemExit(f"namelist.input nao contem a chave obrigatoria: {key}")
if "restart = .true.," not in text:
    raise SystemExit("restart=.true. nao ficou ativo")
open(path,"w",encoding="utf-8").write(text)
print(f"CIM8 RESTART: F{start_h:03d}->F{end_h:03d}; {hours} horas; inicio={start.isoformat()} fim={end.isoformat()}")
PY

docker pull "$IMAGE"
docker run --rm --entrypoint /bin/bash \
  -e OMPI_ALLOW_RUN_AS_ROOT=1 -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
  -e WRF_MPI_PROCS="$MPI_PROCS" \
  -v "$RUN_DIR:/run" -v "$CHECKPOINT:/checkpoint:ro" "$IMAGE" -lc '
    set -euo pipefail
    cd /run
    cp -a /comsoftware/wrf/WRF-4.3/run/. .
    cp -f /checkpoint/namelist.input ./namelist.input
    cp -f /checkpoint/wrfbdy_d01 ./wrfbdy_d01
    cp -f /checkpoint/wrfrst_d01_* .
    test -s namelist.input
    test -s wrfbdy_d01
    test -s "$(find . -maxdepth 1 -type f -name "wrfrst_d01_*" -size +0c -print -quit)"
    echo "=== CIM 8 KM WRF RESTART F'"$START_HOUR"'-F'"$END_HOUR"' ==="
    START_TS=$(date +%s)
    mpirun --allow-run-as-root --oversubscribe --bind-to none -np "$WRF_MPI_PROCS" /comsoftware/wrf/WRF-4.3/main/wrf.exe > wrf.stdout 2>&1 || {
      STATUS=$?; tail -260 rsl.error.0000 || true; tail -260 wrf.stdout || true; exit "$STATUS";
    }
    END_TS=$(date +%s)
    echo "WRF_RUNTIME_SECONDS=$((END_TS-START_TS))" > wrf-runtime.env
    grep -q "SUCCESS COMPLETE WRF" rsl.error.0000
    test -n "$(find . -maxdepth 1 -type f -name "wrfout_d01_*" -size +0c -print -quit)"
  '

mkdir -p "$OUTPUT_DIR"
shopt -s nullglob
OUTS=("$RUN_DIR"/wrfout_d01_*)
shopt -u nullglob
(("${#OUTS[@]}" > 0)) || { echo "CIM8 restart nao produziu wrfout" >&2; exit 41; }
for file in "${OUTS[@]}"; do
  # Mantém o frame do restart do primeiro segmento se o WRF o repetir.
  cp -n "$file" "$OUTPUT_DIR/" || true
done
cp -f "$RUN_DIR/rsl.error.0000" "$ROOT/wrf_diagnostics/cim8-restart-rsl.error.0000" 2>/dev/null || true
cp -f "$RUN_DIR/wrf-runtime.env" "$ROOT/wrf_diagnostics/cim8-restart-runtime.env" 2>/dev/null || true
echo "CIM8 restart F$START_HOUR-F$END_HOUR concluido; wrfout adicionais: ${#OUTS[@]}"

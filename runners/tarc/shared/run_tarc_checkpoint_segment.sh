#!/usr/bin/env bash
set -euo pipefail

START_HOUR="$1"
END_HOUR="$2"
SEGMENT_INDEX="$3"
COLD_START="$4"
SEGMENT_STARTED_AT="$(date +%s)"

: "$GH_TOKEN"
: "$CHECKPOINT_TAG"
: "$GITHUB_REPOSITORY"

ROOT="$GITHUB_WORKSPACE"
INPUT="$ROOT/tarc_restart_input"
mkdir -p "$INPUT"

(( START_HOUR >= 0 && END_HOUR > START_HOUR && START_HOUR % 3 == 0 && END_HOUR % 3 == 0 && END_HOUR <= 48 )) || {
  echo "F000-F048 TARC: intervalo invalido" >&2
  exit 1
}
case "$COLD_START" in 0|1) ;; *) echo "COLD_START deve ser 1 no F000" >&2; exit 1 ;; esac

source "$ROOT/wrf/ensure_eccodes_tools.sh"
for tool in grib_set grib_copy grib_count; do
  command -v "$tool" >/dev/null || { echo "ecCodes/$tool indisponivel" >&2; exit 10; }
done

chmod +x wrf/run_tarc_checkpoint_segment.sh wrf/run_tarc_icon_wrf.sh wrf/run_tarc_ecmwf_wrf.sh wrf/run_tarc_gfs_wrf.sh wrf/run_tarc_wrf_with_source.sh wrf/run_tarc_restart_segment.sh

export WRF_TARGET_RESOLUTION_KM="${WRF_TARGET_RESOLUTION_KM:-3}"
export WRF_DX_METERS="${WRF_DX_METERS:-3000}" WRF_DY_METERS="${WRF_DY_METERS:-3000}"
export WRF_E_WE="${WRF_E_WE:-361}" WRF_E_SN="${WRF_E_SN:-445}"
export WRF_HISTORY_INTERVAL_MINUTES="${WRF_HISTORY_INTERVAL_MINUTES:-60}"
export WRF_TIME_STEP="${WRF_TIME_STEP:-18}"
export WRF_MPI_PROCS="${WRF_MPI_PROCS:-4}"
export WRF_BOUNDARY_END_HOUR="$END_HOUR"
export WRF_REF_LAT="${WRF_REF_LAT:--28.0}" WRF_REF_LON="${WRF_REF_LON:--53.5}" WRF_STAND_LON="${WRF_STAND_LON:--53.5}"
export WRF_RUN_HOURS=$((END_HOUR-START_HOUR))
export WRF_START_HOUR="$START_HOUR" WRF_END_HOUR="$END_HOUR"


prepare_source() {
  local boundary_only="${1:?Informe 0 para cold start, 1 para LBC de restart}"
  local model="${SOURCE_MODEL:-icon}"
  local runner rc

  case "$model" in
    icon) runner="wrf/run_tarc_icon_wrf.sh" ;;
    ecmwf) runner="wrf/run_tarc_ecmwf_wrf.sh" ;;
    gfs) runner="wrf/run_tarc_gfs_wrf.sh" ;;
    *) echo "SOURCE_MODEL inválido no checkpoint: $model" >&2; return 2 ;;
  esac

  export WRF_BOUNDARY_ONLY="$boundary_only"
  echo "===== SIDERAL/TARC SOURCE FIXED: ${model^^}; boundary_only=$boundary_only ====="
  if bash "$runner"; then
    rc=0
  else
    rc=$?
    echo "ERRO: fonte exclusiva ${model^^} falhou (exit=$rc); nenhuma fonte alternativa será tentada." >&2
    return "$rc"
  fi

  if [[ "$model" == "icon" && -s "$ROOT/tarc-icon-run.env" ]]; then
    source "$ROOT/tarc-icon-run.env"
    export RUN_DATE RUN_CYCLE
    FORCE_RUN_DATE="$RUN_DATE"
    FORCE_RUN_CYCLE="$RUN_CYCLE"
    export FORCE_RUN_DATE FORCE_RUN_CYCLE
    echo "Ciclo ICON validado e fixado: $RUN_DATE $RUN_CYCLE Z"
  fi

  SOURCE_MODEL="$model"
  printf 'RUN_DATE=%s\nRUN_CYCLE=%s\nSOURCE_MODEL=%s\n' "$RUN_DATE" "$RUN_CYCLE" "$SOURCE_MODEL" > tarc-run.env
 : # checkpoint handled by GitHub Actions artifact
}

if [[ "$COLD_START" == "0" ]]; then
  rm -rf "$INPUT"/*
 : # checkpoint handled by GitHub Actions artifact
  source tarc-run.env
 : # checkpoint handled by GitHub Actions artifact
 : # checkpoint handled by GitHub Actions artifact
  mkdir -p "$INPUT/normalized"
  for f in "$INPUT"/tarc-restart-"$START_HOUR"-*; do
    [[ -f "$f" ]] || continue
    cp -f "$f" "$INPUT/normalized/$(basename "$f" | sed -E "s/^tarc-restart-$START_HOUR-//; s/_([0-9]{2})[.]([0-9]{2})[.]([0-9]{2})$/_\1:\2:\3/")"
  done
  cp -f "$INPUT/tarc-namelist.input" "$INPUT/normalized/namelist.input"

  # The previous checkpoint boundary ends at START_HOUR, so build a fresh
  # ICON LBC covering START_HOUR..END_HOUR before restarting WRF.
  export RUN_DATE RUN_CYCLE
  export FORCE_RUN_DATE="$RUN_DATE" FORCE_RUN_CYCLE="$RUN_CYCLE"
  export WRF_TARGET_RESOLUTION_KM="${WRF_TARGET_RESOLUTION_KM:-3}" WRF_DX_METERS="${WRF_DX_METERS:-3000}" WRF_DY_METERS="${WRF_DY_METERS:-3000}"
  export WRF_E_WE="${WRF_E_WE:-361}" WRF_E_SN="${WRF_E_SN:-445}"
  export WRF_HISTORY_INTERVAL_MINUTES="${WRF_HISTORY_INTERVAL_MINUTES:-60}" WRF_TIME_STEP="${WRF_TIME_STEP:-18}" WRF_MPI_PROCS="${WRF_MPI_PROCS:-4}"
  export WRF_START_HOUR="$START_HOUR" WRF_END_HOUR="$END_HOUR"
  export WRF_BOUNDARY_END_HOUR="$END_HOUR" WRF_BOUNDARY_ONLY=1
  echo "TARC: preparando LBC exclusivamente com a fonte selecionada F$START_HOUR-F$END_HOUR"
  BOUNDARY_PREP_STARTED_AT="$(date +%s)"
  prepare_source 1
  echo "TARC_METRIC boundary_prepare_seconds=$(( $(date +%s) - BOUNDARY_PREP_STARTED_AT ))"
  test -s "$ROOT/wrf_work/run/wrfbdy_d01" || { echo "LBC TARC ausente para F$START_HOUR-F$END_HOUR" >&2; exit 27; }
  cp -f "$ROOT/wrf_work/run/wrfbdy_d01" "$INPUT/normalized/wrfbdy_d01"
  test -s "$INPUT/normalized/wrfbdy_d01"
  test -s "$INPUT/normalized/namelist.input"
  export WRF_RESTART_DIR="$INPUT/normalized"
  RESTART_STARTED_AT="$(date +%s)"
  bash wrf/run_tarc_restart_segment.sh "$START_HOUR" "$END_HOUR" "$WRF_RESTART_DIR"
  echo "TARC_METRIC restart_forecast_seconds=$(( $(date +%s) - RESTART_STARTED_AT ))"

  OUTPUT_DIR="$ROOT/tarc_segment_output"
  test -d "$OUTPUT_DIR"
  UPLOAD_DIR="$ROOT/tarc_upload_$SEGMENT_INDEX"
  rm -rf "$UPLOAD_DIR"; mkdir -p "$UPLOAD_DIR"
  for f in "$OUTPUT_DIR"/wrfrst_d01_*; do cp -f "$f" "$UPLOAD_DIR/tarc-restart-$END_HOUR-$(basename "$f")"; done
  for f in "$OUTPUT_DIR"/wrfout_d01_*; do cp -f "$f" "$UPLOAD_DIR/tarc-wrfout-$SEGMENT_INDEX-$(basename "$f")"; done
 : # checkpoint handled by GitHub Actions artifact
else
  python3 - <<'PY'
import datetime as dt, os
now=dt.datetime.now(dt.timezone.utc)
run=now.replace(hour=(now.hour//6)*6, minute=0, second=0, microsecond=0)
if os.environ.get("WRF2_TOMORROW") == "1":
    run += dt.timedelta(hours=24)
open("tarc-run.env","w").write(f"RUN_DATE={run:%Y%m%d}\nRUN_CYCLE={run:%H}\nSOURCE_MODEL={os.environ.get('SOURCE_MODEL','icon')}\nWRF2_TOMORROW={os.environ.get('WRF2_TOMORROW','0')}\n")
PY
  source tarc-run.env
 : # checkpoint handled by GitHub Actions artifact
 : # checkpoint handled by GitHub Actions artifact

  export FORCE_RUN_DATE="$RUN_DATE" FORCE_RUN_CYCLE="$RUN_CYCLE"
  export TARC_ALLOW_RESELECT_ICON=1
  export WRF_BOUNDARY_ONLY=0
  COLD_FORECAST_STARTED_AT="$(date +%s)"
  prepare_source 0
  echo "TARC_METRIC cold_start_forecast_seconds=$(( $(date +%s) - COLD_FORECAST_STARTED_AT ))"
  unset TARC_ALLOW_RESELECT_ICON

  test -s wrf_work/run/wrfinput_d01
  test -s wrf_work/run/wrfbdy_d01
  test -n "$(find wrf_work/run -maxdepth 1 -type f -name 'wrfout_d01_*' -size +0c -print -quit)"
  test -n "$(find wrf_work/run -maxdepth 1 -type f -name 'wrfrst_d01_*' -size +0c -print -quit)"

  for f in wrf_work/run/wrfrst_d01_*; do cp -f "$f" "tarc-restart-$END_HOUR-$(basename "$f")"; done
  for f in wrf_work/run/wrfout_d01_*; do cp -f "$f" "tarc-wrfout-$SEGMENT_INDEX-$(basename "$f")"; done
  for f in wrf_work/run/wrfbdy_d01; do cp -f "$f" "tarc-boundary-3km-$(basename "$f")"; done
  cp -f wrf_work/run/namelist.input tarc-namelist.input
 : # checkpoint handled by GitHub Actions artifact
fi


# Gera produtos 2D compactos para o frontend sem substituir os wrfout nativos.
if [[ "$COLD_START" == "1" ]]; then
  POST_INPUT="$ROOT/wrf_work/run"
else
  POST_INPUT="$ROOT/tarc_segment_output"
fi
if [[ -n "$(find "$POST_INPUT" -maxdepth 1 -type f -name 'wrfout_d01_*' -size +0c -print -quit)" ]]; then
  python3 -m pip install --disable-pip-version-check -q netCDF4 numpy
  PRODUCT_DIR="$ROOT/tarc_products_$SEGMENT_INDEX"
  rm -rf "$PRODUCT_DIR"
  python3 wrf/tarc_postprocess.py "$POST_INPUT"/wrfout_d01_* --output-dir "$PRODUCT_DIR"
  mv "$PRODUCT_DIR/metadata.json" "tarc-products-$SEGMENT_INDEX.json"
 : # checkpoint handled by GitHub Actions artifact
fi

echo "TARC_METRIC segment=F$START_HOUR-F$END_HOUR total_seconds=$(( $(date +%s) - SEGMENT_STARTED_AT ))"
echo "TARC checkpoint F$START_HOUR-F$END_HOUR publicado em $CHECKPOINT_TAG."

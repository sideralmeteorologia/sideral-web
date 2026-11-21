#!/usr/bin/env bash
set -euo pipefail
START_HOUR="${1:?start hour}"
END_HOUR="${2:?end hour}"
SEGMENT_INDEX="${3:?segment index}"
COLD_START="${4:?cold start 1/0}"
ROOT="${GITHUB_WORKSPACE:-$PWD}"
INPUT="$ROOT/metbr_restart_input"
SOURCE_MODEL="${SOURCE_MODEL:-icon}"
MODEL_VARIANT="${MODEL_VARIANT:-wrf}"
WRF2_TOMORROW="${WRF2_TOMORROW:-0}"
CHECKPOINT_TAG="${CHECKPOINT_TAG:?CHECKPOINT_TAG ausente}"
mkdir -p "$INPUT"

[[ "$SOURCE_MODEL" =~ ^(icon|ecmwf|gfs)$ ]] || { echo "SOURCE_MODEL inválido: $SOURCE_MODEL" >&2; exit 2; }
[[ "$MODEL_VARIANT" =~ ^(wrf|wrf2)$ ]] || { echo "MODEL_VARIANT inválido: $MODEL_VARIANT" >&2; exit 2; }
[[ "$COLD_START" == 0 || "$COLD_START" == 1 ]] || { echo "COLD_START inválido" >&2; exit 2; }
(( START_HOUR >= 0 && END_HOUR > START_HOUR && START_HOUR % 3 == 0 && END_HOUR % 3 == 0 && END_HOUR <= 42 )) || { echo "Segmento METBR inválido F${START_HOUR}-F${END_HOUR}" >&2; exit 2; }

source "$ROOT/wrf/ensure_eccodes_tools.sh"
for tool in grib_set grib_copy grib_count; do
  command -v "$tool" >/dev/null || { echo "ecCodes/$tool indisponível" >&2; exit 10; }
done
export WRF_TARGET_RESOLUTION_KM="${WRF_TARGET_RESOLUTION_KM:-4}" WRF_DX_METERS="${WRF_DX_METERS:-4000}" WRF_DY_METERS="${WRF_DY_METERS:-4000}"
export WRF_E_WE="${WRF_E_WE:-300}" WRF_E_SN="${WRF_E_SN:-360}" WRF_HISTORY_INTERVAL_MINUTES="${WRF_HISTORY_INTERVAL_MINUTES:-60}"
export WRF_MPI_PROCS="${WRF_MPI_PROCS:-8}" WRF_TIME_STEP="${WRF_TIME_STEP:-20}"
export WRF_REF_LAT="${WRF_REF_LAT:--28.10}" WRF_REF_LON="${WRF_REF_LON:--53.45}" WRF_STAND_LON="${WRF_STAND_LON:--53.45}"
export WRF_REFLECTIVITY_SOURCE=REFL_10CM_NATIVE WRF_NATIVE_GRID=true WRF_NO_FALLBACK=true
export WRF_RUN_HOURS=$((END_HOUR-START_HOUR)) WRF_START_HOUR="$START_HOUR" WRF_END_HOUR="$END_HOUR"
export SOURCE_MODEL MODEL_VARIANT WRF2_TOMORROW

if [[ "$COLD_START" == "0" ]]; then
  rm -rf "$INPUT"/*
 : # checkpoint handled by GitHub Actions artifact
  test -s "$INPUT/metbr-checkpoint-${START_HOUR}.tar.gz" || { echo "Checkpoint F${START_HOUR} ausente no R2" >&2; exit 20; }
  tar -xzf "$INPUT/metbr-checkpoint-${START_HOUR}.tar.gz" -C "$INPUT"
  test -s "$INPUT/metbr-run.env" || { echo "metbr-run.env ausente no checkpoint" >&2; exit 21; }
  source "$INPUT/metbr-run.env"
  export RUN_DATE RUN_CYCLE
  mkdir -p "$INPUT/normalized"
  mapfile -t RSTS < <(find "$INPUT" -maxdepth 1 -type f -name 'wrfrst_d01_*' -size +0c -print | sort)
  (("${#RSTS[@]}" > 0)) || { echo "wrfrst ausente no checkpoint" >&2; exit 22; }
  cp -f "${RSTS[@]}" "$INPUT/normalized/"
  test -s "$INPUT/wrfbdy_d01" || { echo "wrfbdy ausente no checkpoint" >&2; exit 23; }
  cp -f "$INPUT/wrfbdy_d01" "$INPUT/normalized/wrfbdy_d01"
  test -s "$INPUT/namelist.input" || { echo "namelist.input ausente no checkpoint" >&2; exit 24; }
  cp -f "$INPUT/namelist.input" "$INPUT/normalized/namelist.input"
  export WRF_RESTART_DIR="$INPUT/normalized"
else
  if [[ "$SOURCE_MODEL" == gfs ]]; then
    RUN_DATE=""; RUN_CYCLE=""
    while read -r DATE CYCLE; do
      URL="https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.$DATE/$CYCLE/atmos/gfs.t${CYCLE}z.pgrb2.0p25.f042"
      if curl -fsSL --range 0-0 --connect-timeout 15 --max-time 45 -o /dev/null "$URL"; then RUN_DATE="$DATE"; RUN_CYCLE="$CYCLE"; break; fi
    done < <(python3 - <<'PY'
import datetime as dt
now=dt.datetime.now(dt.timezone.utc)
base=now.replace(hour=(now.hour//6)*6,minute=0,second=0,microsecond=0)
for n in range(24):
    candidate=base-dt.timedelta(hours=6*n)
    print(candidate.strftime('%Y%m%d %H'))
PY
)
    [[ -n "$RUN_DATE" ]] || { echo "Nenhum ciclo GFS com F042 disponível" >&2; exit 25; }
    export FORCE_RUN_DATE="$RUN_DATE" FORCE_RUN_CYCLE="$RUN_CYCLE"
  else
    export FORCE_RUN_DATE="" FORCE_RUN_CYCLE=""
  fi
 : # checkpoint handled by GitHub Actions artifact
fi

if [[ "$SOURCE_MODEL" == gfs ]]; then
  export METBR_COLD_START="$COLD_START" METBR_BOUNDARY_END_HOUR=42
  bash "$ROOT/wrf/run_metbr_gfs_segment.sh"
else
  bash "$ROOT/wrf/run_metbr_source_wrf.sh"
  if [[ "$SOURCE_MODEL" == icon && -s "$ROOT/icon_run.env" ]]; then source "$ROOT/icon_run.env"; fi
  if [[ "$SOURCE_MODEL" == ecmwf && -s "$ROOT/ecmwf_run.env" ]]; then source "$ROOT/ecmwf_run.env"; fi
fi

[[ "${RUN_DATE:-}" =~ ^[0-9]{8}$ ]] || { echo "RUN_DATE inválido após o runner: ${RUN_DATE:-}" >&2; exit 26; }
[[ "${RUN_CYCLE:-}" =~ ^(00|06|12|18)$ ]] || { echo "RUN_CYCLE inválido após o runner: ${RUN_CYCLE:-}" >&2; exit 27; }
export RUN_DATE RUN_CYCLE
printf 'RUN_DATE=%s\nRUN_CYCLE=%s\nSOURCE_MODEL=%s\nMODEL_VARIANT=%s\nWRF2_TOMORROW=%s\n' "$RUN_DATE" "$RUN_CYCLE" "$SOURCE_MODEL" "$MODEL_VARIANT" "$WRF2_TOMORROW" > metbr-run.env

OUTPUT_DIR="$ROOT/wrf_work/run"
if [[ "$SOURCE_MODEL" != gfs && "$COLD_START" == "0" ]]; then
  OUTPUT_DIR="$ROOT/metbr_segment_output"
fi
test -d "$OUTPUT_DIR" || { echo "METBR output directory ausente: $OUTPUT_DIR" >&2; exit 30; }
shopt -s nullglob
OUTS=("$OUTPUT_DIR"/wrfout_d01_*)
RSTS=("$OUTPUT_DIR"/wrfrst_d01_*)
BDYS=("$OUTPUT_DIR"/wrfbdy_d01*)
shopt -u nullglob
(("${#OUTS[@]}" > 0)) || { echo "WRFOUT ausente no segmento F${START_HOUR}-F${END_HOUR}" >&2; exit 31; }
(("${#RSTS[@]}" > 0)) || { echo "WRF restart ausente no segmento F${START_HOUR}-F${END_HOUR}" >&2; exit 32; }
if (("${#BDYS[@]}" == 0)) && [[ "$COLD_START" == "0" ]]; then
  test -s "$INPUT/wrfbdy_d01" || { echo "WRF boundary ausente no restart" >&2; exit 33; }
  BDYS=("$INPUT/wrfbdy_d01")
fi
(("${#BDYS[@]}" > 0)) || { echo "wrfbdy_d01 ausente" >&2; exit 34; }

NAMELIST="$OUTPUT_DIR/namelist.input"
[[ -s "$OUTPUT_DIR/namelist.restart.input" ]] && NAMELIST="$OUTPUT_DIR/namelist.restart.input"
test -s "$NAMELIST" || { echo "namelist checkpoint ausente" >&2; exit 35; }
for f in "${OUTS[@]}"; do
  test -s "$f" || { echo "WRFOUT vazio: $f" >&2; exit 36; }
  cp -f "$f" "metbr-wrfout-$SEGMENT_INDEX-$(basename "$f")"
done

rm -rf checkpoint_pack && mkdir checkpoint_pack
cp -f "${RSTS[@]}" checkpoint_pack/
cp -f "${BDYS[0]}" checkpoint_pack/wrfbdy_d01
cp -f "$NAMELIST" checkpoint_pack/namelist.input
cp -f metbr-run.env checkpoint_pack/metbr-run.env
tar -czf "metbr-checkpoint-$END_HOUR.tar.gz" -C checkpoint_pack .
test -s "metbr-checkpoint-$END_HOUR.tar.gz"
 : # checkpoint handled by GitHub Actions artifact
 : # checkpoint handled by GitHub Actions artifact
echo "METBR $SOURCE_MODEL $MODEL_VARIANT F$START_HOUR-F$END_HOUR: checkpoint salvo no R2."

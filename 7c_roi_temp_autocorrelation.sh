#!/usr/bin/env bash
# ============================================================
# compute_roi_autocorrelation.sh
# ------------------------------------------------------------
# AR(1) = lag-1 sample autocorrelation coefficient. Computed directly from each ROI's timeseries 
# Autocorrelation: can be used to calculate how each ROI's signal changes over time (how timeseries points relates to its own).
# Can be useful as a descriptive comparison since denoising changes the temporal structure of what's left in the signal.
#
# Input: a folder of {roi}_timeseries.txt files, (as produced by 5_extract_timeseries_tsnr.sh - one value per line, one file per ROI).
#
# Dependencies: none beyond standard awk/bash.
# ============================================================

set -uo pipefail

# ---------- CONFIGURATION ----------
TS_DIR="/path/to/analysis_output/timeseries"    #EDIT: run per branch
OUT_DIR="/path/to/qc_checks/temporal_autocorr"     #EDIT
OUTFILE="ar1_timeseries.tsv"
# -----------------------------------

if [[ ! -d "${TS_DIR}" ]]; then
    echo "ERROR: timeseries directory not found: ${TS_DIR}"
    exit 1
fi

if [[ -z "$(ls -A "${TS_DIR}"/*_timeseries.txt 2>/dev/null)" ]]; then
    echo "ERROR: no *_timeseries.txt files found in ${TS_DIR}"
    exit 1
fi

mkdir -p "${OUT_DIR}"
OUTPATH="${OUT_DIR}/${OUTFILE}"

if [[ -f "${OUTPATH}" ]]; then
    echo "ERROR: output already exists: ${OUTPATH}"
    echo "Delete/rename it first, or change OUTFILE, then rerun."
    exit 1
fi

echo -e "ROI\tAR1" > "${OUTPATH}"

echo "Computing lag-1 autocorrelation (AR1) per ROI..."
for TS in "${TS_DIR}"/*_timeseries.txt; do
  ROI=$(basename "${TS}" _timeseries.txt)

  AR1=$(awk '
  { x[NR]=$1; sum+=$1 }
  END {
    if (NR < 2) { print "NA"; exit }
    mean = sum / NR
    for (i=1;i<NR;i++) {
      num += (x[i]-mean)*(x[i+1]-mean)
      den += (x[i]-mean)*(x[i]-mean)
    }
    den += (x[NR]-mean)*(x[NR]-mean)
    if (den == 0) {
      print "NA"
    } else {
      printf "%.4f", num/den
    }
  }' "${TS}")

  echo -e "  ${ROI}: AR1 = ${AR1}"
  echo -e "${ROI}\t${AR1}" >> "${OUTPATH}"
done

echo ""
echo "\u2713 AR(1) results written to: ${OUTPATH}"

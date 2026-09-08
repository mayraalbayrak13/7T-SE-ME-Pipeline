#!/usr/bin/env bash
# ============================================================
# 7b_motion_qc_report.sh
# ------------------------------------------------------------
#
# Computes mean framewise displacement (FD) from fMRIPrep confounds.tsv file and flags any subject/run above a threshold (default 0.5).
#
# ============================================================

set -uo pipefail

# ---------- CONFIGURATION ----------
FILES=(
  "/path/to/fmriprep_output/sub-*/func/*_desc-confounds_timeseries.tsv" #EDIT
)

OUT_DIR="/path/to/qc_checks/motion_qc"  #EDIT

# FD threshold to flag (mm)
THRESHOLD=0.5  #EDIT
# -----------------------------------

mkdir -p "${OUT_DIR}"
OUT_TXT="${OUT_DIR}/motion_qc_report.txt"
OUT_CSV="${OUT_DIR}/motion_qc_summary.csv"

echo "file,mean_fd_mm" > "${OUT_CSV}"
: > "${OUT_TXT}"

compute_fd_confounds() {
  local tsv="$1"
  awk -v IGNORECASE=1 '
    BEGIN{FS="\t"; col=-1}
    NR==1{
      for(i=1;i<=NF;i++){
        gsub(/\r/,"",$i)
        if(tolower($i) ~ /framewise_displacement/){col=i; break}
      }
      if(col<0){print "NA"; exit}
      next
    }
    {
      if(col>0){
        v=$col; gsub(/^[ \t]+|[ \t]+$/,"",v)
        if(v=="" || v=="NA" || v=="nan") next
        sum+=v; n++
      }
    }
    END{
      if(n==0){print "NA"; exit}
      printf("%.6f\n", sum/n)
    }
  ' "$tsv"
}

echo "=== Motion QC ==="
for f in "${FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "Missing file: $f"
    echo "$f,NA" >> "${OUT_CSV}"
    continue
  fi

  meanfd=$(compute_fd_confounds "$f")
  echo "$f,$meanfd" >> "${OUT_CSV}"

  if [[ "$meanfd" == "NA" ]]; then
    echo "File: $f — mean FD: NA (framewise_displacement column not found or empty)" >> "${OUT_TXT}"
  else
    printf "File: %s — mean FD: %.4f mm\n" "$f" "$meanfd" >> "${OUT_TXT}"
    awk -v v="$meanfd" -v th="$THRESHOLD" 'BEGIN{if(v>th)exit 0;exit 1}' && {
      printf "  >>> FLAG: mean FD (%.3f mm) > %.2f mm\n" "$meanfd" "$THRESHOLD" >> "${OUT_TXT}"
    }
  fi
  echo "" >> "${OUT_TXT}"
done

echo "✓ Motion QC complete"
echo "CSV summary:  $OUT_CSV"
echo "Text report:  $OUT_TXT"

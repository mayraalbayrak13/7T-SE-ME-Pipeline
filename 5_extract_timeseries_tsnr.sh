#!/bin/bash
# =============================================================================
# 5_extract_timeseries_tsnr.sh
# =============================================================================
# Takes the  final pipeline output (masked, MNI-space, confound-regressed BOLD for SE or ME) and:
#   1. Extracts ROI timeseries for each mask in MASK_DIR
#   2. Calculates whole-brain tSNR
#   3. (Optional) Runs basic sanity checks: zero-timeseries detection,  alignment vs. MNI reference
#
# Run it once per branch, pointing INPUT_BOLD at the preprocessed output, with a different OUTPUT_DIR/PIPELINE_LABEL each time.
# Masks are analysis-specific, not something this repo assumes. This project's masks are provided in the repo.
# Masks must be in the same space as INPUT_BOLD (MNI).

# This is data preparation for downstream analysis (timeseries + tSNR), the correlation/functional-connectivity analysis is a separate script.
#
# Dependencies: FSL (fslmeants, fslmaths, fslstats, fslinfo on PATH)
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION - EDIT HERE
# =============================================================================

INPUT_BOLD="/path/to/confound_regression_output/regressed_bold.nii.gz"  #EDIT

OUTPUT_DIR="/path/to/analysis_output"  #EDIT
PIPELINE_LABEL=$(basename "$(dirname "${OUTPUT_DIR}")" | sed 's/_processing$//')

# Directory of ROI mask images (.nii.gz) to extract timeseries from.
MASK_DIR="/path/to/Masks_MNI2009/masks"  #EDIT

# --- Sanity checks (optional) ---
RUN_SANITY_CHECKS="no"  #"yes" or "no"

# MNI reference image, only needed if RUN_SANITY_CHECKS="yes" (alignment  check). Must be the same template wtih fMRIPrep
MNI_REF="/path/to/MNI152NLin2009cAsym_res-02_T1w.nii.gz"  #EDIT

# =============================================================================
# END CONFIGURATION
# =============================================================================

if [[ ! -f "${INPUT_BOLD}" ]]; then
    echo "ERROR: Input BOLD not found: ${INPUT_BOLD}"
    exit 1
fi

if [[ ! -d "${MASK_DIR}" ]] || [[ -z "$(ls -A "${MASK_DIR}"/*.nii.gz 2>/dev/null)" ]]; then
    echo "ERROR: No masks found in ${MASK_DIR}"
    exit 1
fi

TIMESERIES_DIR="${OUTPUT_DIR}/timeseries"
TSNR_DIR="${OUTPUT_DIR}/tsnr"
mkdir -p "${TIMESERIES_DIR}"
mkdir -p "${TSNR_DIR}"

echo "=== Timeseries extraction & tSNR: ${PIPELINE_LABEL} ==="
echo "Input:  ${INPUT_BOLD}"
echo "Output: ${OUTPUT_DIR}"
echo ""

# =============================================================================
# STEP 1: ROI TIMESERIES EXTRACTION
# =============================================================================

echo "Step 1: Extracting ROI timeseries..."

for MASK in "${MASK_DIR}"/*.nii.gz; do
    MASK_BASENAME=$(basename "${MASK}" .nii.gz)
    TIMESERIES_OUT="${TIMESERIES_DIR}/${MASK_BASENAME}_timeseries.txt"

    if [[ -f "${TIMESERIES_OUT}" ]]; then
        echo "  Skipping ${MASK_BASENAME} (already exists)"
    else
        echo "  Processing ROI: ${MASK_BASENAME}"
        fslmeants -i "${INPUT_BOLD}" -m "${MASK}" -o "${TIMESERIES_OUT}"

        if [[ -f "${TIMESERIES_OUT}" ]]; then
            echo "    \u2713 Saved"
        else
            echo "    ERROR: Failed"
        fi
    fi
done

# =============================================================================
# STEP 2: WHOLE-BRAIN tSNR CALCULATION
# =============================================================================

echo ""
echo "Step 2: Calculating whole-brain tSNR..."

TSNR_MAP="${TSNR_DIR}/tsnr.nii.gz"
TSNR_STATS="${TSNR_DIR}/tsnr_stats.txt"
TSNR_CSV="${TSNR_DIR}/tsnr_stats.csv"

if [[ -f "${TSNR_MAP}" ]] && [[ -f "${TSNR_STATS}" ]]; then
    echo "  tSNR results already exist - skipping"
    MEAN_TSNR=$(grep "Mean tSNR:" "${TSNR_STATS}" | awk '{print $3}')
else
    TMEAN="${TSNR_DIR}/tmean_temp.nii.gz"
    TSTD="${TSNR_DIR}/tstd_temp.nii.gz"

    fslmaths "${INPUT_BOLD}" -Tmean "${TMEAN}"
    fslmaths "${INPUT_BOLD}" -Tstd "${TSTD}"
    fslmaths "${TMEAN}" -div "${TSTD}" "${TSNR_MAP}"

    MEAN_TSNR=$(fslstats "${TSNR_MAP}" -M)
    STD_TSNR=$(fslstats "${TSNR_MAP}" -S)
    MEDIAN_TSNR=$(fslstats "${TSNR_MAP}" -P 50)
    MIN_TSNR=$(fslstats "${TSNR_MAP}" -R | awk '{print $1}')
    MAX_TSNR=$(fslstats "${TSNR_MAP}" -R | awk '{print $2}')

    cat > "${TSNR_STATS}" << EOF
Whole-Brain tSNR Analysis Results
=================================
Pipeline: ${PIPELINE_LABEL}
Date: $(date)

Input:  ${INPUT_BOLD}
Output: ${TSNR_DIR}

Whole-brain tSNR statistics (MNI space):
  Mean tSNR:   ${MEAN_TSNR}
  Std tSNR:    ${STD_TSNR}
  Median tSNR: ${MEDIAN_TSNR}
  Min tSNR:    ${MIN_TSNR}
  Max tSNR:    ${MAX_TSNR}
EOF

    echo "pipeline,mean_tsnr,std_tsnr,median_tsnr,min_tsnr,max_tsnr" > "${TSNR_CSV}"
    echo "${PIPELINE_LABEL},${MEAN_TSNR},${STD_TSNR},${MEDIAN_TSNR},${MIN_TSNR},${MAX_TSNR}" >> "${TSNR_CSV}"

    rm -f "${TMEAN}" "${TSTD}"
    echo "  \u2713 tSNR completed (Mean = ${MEAN_TSNR})"
fi

# =============================================================================
# STEP 3: SANITY CHECKS (optional)
#  - Detect all-zero/mostly-zero timeseries files
#  - Alignment check: header match, center-of-mass distance vs MNI reference
# =============================================================================

if [[ "${RUN_SANITY_CHECKS}" == "yes" ]]; then
    echo ""
    echo "Step 3: Running sanity checks..."

    # --- Check timeseries files for mostly-zero outputs ---
    echo "  Checking timeseries for mostly-zero outputs..."
    ZERO_COUNT=0
    TOTAL_FILES=0
    for f in "${TIMESERIES_DIR}"/*_timeseries.txt; do
        [[ ! -f "$f" ]] && continue
        TOTAL_FILES=$((TOTAL_FILES+1))
        read total nonzero < <(awk '{
            for(i=1;i<=NF;i++){ if($i != 0) nz++ }
            lines++
          } END { print lines, (nz) }' "$f")
        if [[ -z "$total" || "$total" -le 0 ]]; then
            echo "    WARNING: empty timeseries file: $(basename "$f")"
            ZERO_COUNT=$((ZERO_COUNT+1))
        else
            frac=$(awk -v nz="$nonzero" -v tot="$total" 'BEGIN{ if(tot==0) print 0; else printf("%.6f", nz/tot) }')
            cmp=$(awk -v a="$frac" 'BEGIN{ if(a<0.01) print 1; else print 0 }')
            if [[ "$cmp" -eq 1 ]]; then
                echo "    WARNING: mostly-zero timeseries: $(basename "$f")  nonzero_frac=${frac}"
                ZERO_COUNT=$((ZERO_COUNT+1))
            fi
        fi
    done
    echo "    ${TOTAL_FILES} files scanned, ${ZERO_COUNT} flagged"

    # --- Alignment check vs MNI reference ---
    if [[ -f "${MNI_REF}" ]]; then
        echo "  Checking alignment vs MNI reference..."
        read img_cx img_cy img_cz <<< $(fslstats "${INPUT_BOLD}" -c)
        read ref_cx ref_cy ref_cz <<< $(fslstats "${MNI_REF}" -c)
        dist=$(awk -v x1="$img_cx" -v y1="$img_cy" -v z1="$img_cz" \
                   -v x2="$ref_cx" -v y2="$ref_cy" -v z2="$ref_cz" \
                   'BEGIN{ dx=x1-x2; dy=y1-y2; dz=z1-z2; printf("%.3f", sqrt(dx*dx+dy*dy+dz*dz)) }')
        echo "    Center-of-mass distance to MNI reference (mm): ${dist}"
        echo "    (Large values, e.g. >20-30mm, may indicate a registration problem)"
    else
        echo "  Skipping alignment check — MNI_REF not found: ${MNI_REF}"
    fi
fi

# =============================================================================
# SUMMARY
# =============================================================================

echo ""
echo "=== Complete: ${PIPELINE_LABEL} ==="
echo "  Timeseries: ${TIMESERIES_DIR}"
echo "  tSNR stats: ${TSNR_STATS}"
echo "  tSNR CSV:   ${TSNR_CSV}"
echo ""
echo "Next step: functional connectivity / correlation analysis (separate script)"

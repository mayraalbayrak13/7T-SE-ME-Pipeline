#!/bin/bash
# =============================================================================
# 2c_tedana_native_to_mni.sh
# =============================================================================
# Normalizes TEDANA's native-space denoised output to MNI space
# Uses fMRIPrep's own T1->MNI and func->T1 transforms (already produced after running fMRIPrep).
# Keeps ANTs as its own dependency point.
#
# Output is written into a NEW subfolder inside the TEDANA output directory
# Does NOT replace TEDANA's native-space output.
# Point 3_pre_confound_regression.py script's --bold-dir at this script's output folder for the ME branch.
#
# Dependencies: ANTs (antsApplyTransforms on PATH — e.g. `conda activate ants`)
#
# Usage:
#   ./2c_tedana_native_to_mni.sh
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION - EDIT HERE
# =============================================================================

# Native-space TEDANA denoised output
TEDANA_NATIVE_BOLD="/path/to/tedana_output/sub-*/*_space-Native_desc-denoised_bold.nii.gz"  #EDIT

# fMRIPrep transforms (found in fmriprep_output)
TRANSFORM_T1_TO_MNI="/path/to/fmriprep_output/sub-*/anat/*_from-T1w_to-MNI152NLin2009cAsym_mode-image_xfm.h5"    #EDIT
TRANSFORM_FUNC_TO_T1="/path/to/fmriprep_output/sub-*/func/*_from-boldref_to-T1w_mode-image_desc-coreg_xfm.txt"    #EDIT

# MNI reference image (must match the space fMRIPrep normalized to ( e.g. MNI152NLin2009cAsym)
# Same template also available via TemplateFlow (https://www.templateflow.org/) if you don't already have a local copy.
MNI_REF="/path/to/Masks_MNI2009/MNI2009/MNI2009_2mm.nii.gz" #EDIT


OUTPUT_SUBDIR_NAME="tedana_mni_reg"  #EDIT (if you want a different subfolder name that will be created under tedana_output)

# =============================================================================
# END CONFIGURATION
# =============================================================================

for f in "$TEDANA_NATIVE_BOLD" "$TRANSFORM_T1_TO_MNI" "$TRANSFORM_FUNC_TO_T1" "$MNI_REF"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR: required file not found: $f"
        exit 1
    fi
done

if ! command -v antsApplyTransforms &> /dev/null; then
    echo "ERROR: antsApplyTransforms not found on PATH"
    echo "  #EDIT: activate your ANTs environment first, e.g.:"
    echo "    module load Miniforge3"
    echo "    conda activate ants"
    exit 1
fi

TEDANA_DIR=$(dirname "${TEDANA_NATIVE_BOLD}")
OUTPUT_DIR="${TEDANA_DIR}/${OUTPUT_SUBDIR_NAME}"

# Derive output filename from the input, swapping space-Native for the MNI space
INPUT_BASENAME=$(basename "${TEDANA_NATIVE_BOLD}")
OUTPUT_BASENAME="${INPUT_BASENAME/space-Native/space-MNI152NLin2009cAsym}"

if [[ "${OUTPUT_BASENAME}" == "${INPUT_BASENAME}" ]]; then
    echo "WARNING: input filename does not contain 'space-Native' — could not"
    echo "  auto-rename output. Using a generic name instead."
    OUTPUT_BASENAME="mni_$(basename "${TEDANA_NATIVE_BOLD}")"
fi

OUTPUT_BOLD="${OUTPUT_DIR}/${OUTPUT_BASENAME}"

if [[ -f "${OUTPUT_BOLD}" ]]; then
    echo "ERROR: output already exists: ${OUTPUT_BOLD}"
    echo "Delete/rename it first, or change OUTPUT_SUBDIR_NAME, then rerun."
    exit 1
fi

mkdir -p "${OUTPUT_DIR}"

echo "=== TEDANA native -> MNI normalization ==="
echo "  Input:      ${TEDANA_NATIVE_BOLD}"
echo "  T1->MNI:    ${TRANSFORM_T1_TO_MNI}"
echo "  func->T1:   ${TRANSFORM_FUNC_TO_T1}"
echo "  MNI ref:    ${MNI_REF}"
echo "  Output:     ${OUTPUT_BOLD}"
echo ""
echo "Running antsApplyTransforms..."

antsApplyTransforms -d 3 -e 3 -v 1 \
    -i "${TEDANA_NATIVE_BOLD}" \
    -r "${MNI_REF}" \
    -t "${TRANSFORM_T1_TO_MNI}" \
    -t "${TRANSFORM_FUNC_TO_T1}" \
    -o "${OUTPUT_BOLD}" \
    -n Linear

if [[ -f "${OUTPUT_BOLD}" ]]; then
    echo "✓ Normalization completed"
    echo ""
    echo "Point 3_pre_confound_regression.py's --bold-dir at:"
    echo "  ${OUTPUT_DIR}"
    echo "(it looks up *_desc-denoised_bold.nii.gz by subject ID, same as"
    echo "it already does for raw TEDANA output — no code changes needed there)"
else
    echo "ERROR: antsApplyTransforms did not produce expected output"
    exit 1
fi

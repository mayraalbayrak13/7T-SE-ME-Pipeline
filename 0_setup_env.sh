#!/bin/bash
# =============================================================================
# setup_env.sh
# =============================================================================
# Loads all modules/environments needed across the pipeline (FSL, Python,
# MATLAB, R) in one step. Must be SOURCED, not executed directly.
#
# Usage:
#   source setup_env.sh
#
# Order matters:
#   - FSL must load before the Python venv is activated, or FSL's own
#     bundled python3 shadows the venv's python3.
#   - The venv activation must be the LAST command in this script, it
#     prepends its own bin/ to PATH, so whatever runs last "wins" front
#     position. Module loads after venv activation can silently push the
#     venv's python3 out of first place.
#
# ANTs is NOT included here: it has a separate conda environment, activate manually  with `conda activate ants` only when running 2c_tedana_native_to_mni.sh.
# =============================================================================

module purge

# --- FSL ---
module load FSL/6.0.7.17
source $FSLDIR/etc/fslconf/fsl.sh

# --- MATLAB ---
module load MATLAB/2023a

# --- R ---
module load R/4.3.2-gfbf-2023a

# --- Python (module + venv activation  MUST BE LAST) ---
module load Python/3.11.3-GCCcore-12.3.0
source /path/to/bin

echo "=== Environment loaded ==="
echo "FSL:    $(which fslmaths)"
echo "Python: $(which python3)"
echo "MATLAB: $(which matlab)"
echo "R:      $(which Rscript)"
echo "==========================="

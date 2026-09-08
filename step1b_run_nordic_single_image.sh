#!/bin/bash
# =========================================================================
# 1b_run_nordic_single_image.sh
# -------------------------------------------------------------------------
# Submission wrapper for step1a_run_nordic_singleimage.m
# Dependencies: MATLAB with NORDIC_Raw on path (set inside the .m script)
#
# Usage (local):
#   ./run_nordic_singleimage.sh
#
# Usage (cluster, example from our FMRIB setup - adapt to your own scheduler, e.g. sbatch/qsub):
#   fsl_sub -q short -R 64 /path/to/run_nordic_singleimage.sh
# =========================================================================

# #EDIT: remove or replace this line if MATLAB is already on your PATH
module load MATLAB

# #EDIT: update this path to wherever you've placed the repo
SCRIPT_DIR="/path/to/scripts"

matlab -batch "run('${SCRIPT_DIR}/step1a_run_nordic_single_image.m')"

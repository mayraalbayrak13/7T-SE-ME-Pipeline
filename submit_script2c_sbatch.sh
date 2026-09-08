#!/bin/bash
#SBATCH -A oxcin-neuroscope.prj
#SBATCH -p short
#SBATCH -J tedana_to_mni
#SBATCH -o /path/to/tedana_output/sub-01/logs/slurm_%j.out
#SBATCH -e /path/to/tedana_output/sub-01/logs/slurm_%j.err
#SBATCH -c 2
#SBATCH --mem=64G

module purge
module load Miniforge3/24.11.3-0

unset CONDA_SHLVL
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate base
conda activate ants

which antsApplyTransforms   # sanity check in .out log

cd /path/to/scripts
bash 2c_tedana_native_to_mni.sh

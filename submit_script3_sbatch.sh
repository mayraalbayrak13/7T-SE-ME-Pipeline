#!/bin/bash
#SBATCH -A oxcin-neuroscope.prj
#SBATCH -p short
#SBATCH -J pre_confound_regression
#SBATCH -o /path/to/pre_reg_output/logs/slurm_%j.out
#SBATCH -e /path/to/pre_reg_output/logs/slurm_%j.err
#SBATCH -c 4
#SBATCH --mem=32G

module purge
module load FSL/6.0.7.17
source $FSLDIR/etc/fslconf/fsl.sh
module load Python/3.11.3-GCCcore-12.3.0
source /path/to/fmri_pipeline_env/bin/activate

cd /path/to/scripts
python3 3_pre_confound_regression.py

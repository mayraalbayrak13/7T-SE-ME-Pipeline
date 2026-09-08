#!/bin/bash
#SBATCH -A oxcin-neuroscope.prj
#SBATCH -p short
#SBATCH -J confound_regression
#SBATCH -o /path/to/confound_regression_output/logs/slurm_%j.out
#SBATCH -e /path/to/confound_regression_output/logs/slurm_%j.err
#SBATCH -c 4
#SBATCH --mem=32G

module purge
module load Python/3.11.3-GCCcore-12.3.0
source /path/to/fmri_pipeline_env/bin/activate

cd /path/to/scripts
python3 4_run_confound_regression.py

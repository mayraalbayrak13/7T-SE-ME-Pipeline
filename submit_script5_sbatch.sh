#!/bin/bash
#SBATCH -A oxcin-neuroscope.prj
#SBATCH -p short
#SBATCH -J timeseries_tsnr
#SBATCH -o /path/to/analysis_output/logs/slurm_%j.out
#SBATCH -e /path/to/analysis_output/logs/slurm_%j.err
#SBATCH -c 4
#SBATCH --mem=32G

module purge
module load FSL/6.0.7.17
source $FSLDIR/etc/fslconf/fsl.sh

cd /path/to/scripts
bash 5_extract_timeseries_tsnr.sh

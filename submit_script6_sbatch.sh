#!/bin/bash
#SBATCH -A oxcin-neuroscope.prj
#SBATCH -p short
#SBATCH -J correlations
#SBATCH -o /path/to/qc_checks/logs/slurm_%j.out
#SBATCH -e /path/to/qc_checks/logs/slurm_%j.err
#SBATCH -c 2
#SBATCH --mem=8G

module purge
module load R/4.3.2-gfbf-2023a

cd /path/to/scripts
Rscript 6_run_correlations.R

#!/bin/bash
#SBATCH -A oxcin-neuroscope.prj
#SBATCH -p short
#SBATCH -J nordic
#SBATCH -o /path/to/NORDIC/logs/slurm_%j.out
#SBATCH -e /path/to/NORDIC/logs/slurm_%j.err
#SBATCH -c 4
#SBATCH --mem=64G

module purge
module load MATLAB/2023a

matlab -batch "run('/path/to/scripts/step1a_run_nordic_single_image.m')"

#!/bin/bash
# =============================================================================
# 2a_run_fmriprep_bmrc.sh
# =============================================================================
# BMRC (Slurm) variant of 2a_run_fmriprep.sh. Logic/config layout is
# identical to the FMRIB version  only the job submission mechanism has
# changed (fsl_sub -> sbatch/Slurm). See 2a_run_fmriprep.sh for the
# FMRIB/fsl_sub version.
#
# Submits one or more fMRIPrep jobs via sbatch (SE or ME  run this script
# separately for each; fMRIPrep itself doesn't distinguish SE/ME, that's
# determined by which BIDS directory you point it at).
#
# Participant args: ./2a_run_fmriprep_bmrc.sh [participant_labels...]
#   - No arguments: processes ALL participants in each dataset
#   - With arguments: processes only specified participants (e.g., sub-001 sub-002)
# =============================================================================



# =============================================================================
# CONFIGURATION SECTION - EDIT HERE
# =============================================================================

# --- Slurm settings ---
SLURM_ACCOUNT="oxcin-neuroscope.prj"   # #EDIT: confirm with `id -gn` (usually groupname.prj)
SLURM_PARTITION="short"                 # #EDIT: "short" (30h) or "long" (10 days)  fMRIPrep runs can be long, consider "long"
SLURM_CPUS=8                            # #EDIT: matches --nthreads/--omp-nthreads below

# --- Global fMRIPrep Settings ---
GROUP_DIR="/well/oxcin-neuroscope/users/lmd076"                        # #EDIT
SINGULARITY_IMAGE="${GROUP_DIR}/singularity/fmriprep-25.1.3.simg"      # #EDIT: pin your fMRIPrep version
FS_LICENSE_DIR="${GROUP_DIR}/freesurfer"                                # #EDIT

# Number of fMRIPrep jobs to submit (1-4)
NUM_JOBS=1  # #EDIT

# --- fMRIPrep Processing Options ---
OUTPUT_SPACES="MNI152NLin2009cAsym:res-2"  # #EDIT if you need a different output space
SKIP_FREESURFER="yes"  # #EDIT
ME_OUTPUT_ECHOS="no"   # #EDIT

# =============================================================================
# JOB 1 CONFIGURATION
# =============================================================================
BIDS_DIR_1="/path/to/BIDS"    # #EDIT
OUTPUT_DIR_1="/path/to/fmriprep_output"  # #EDIT

# =============================================================================
# JOB 2 CONFIGURATION (Leave empty if not needed)
# =============================================================================
BIDS_DIR_2=""
OUTPUT_DIR_2=""

# =============================================================================
# JOB 3 CONFIGURATION (Leave empty if not needed)
# =============================================================================
BIDS_DIR_3=""
OUTPUT_DIR_3=""

# =============================================================================
# JOB 4 CONFIGURATION (Leave empty if not needed)
# =============================================================================
BIDS_DIR_4=""
OUTPUT_DIR_4=""

# =============================================================================



# =============================================================================
# AUTOMATION SECTION - DO NOT EDIT BELOW
# =============================================================================

PARTICIPANT_ARGS=""
if [[ $# -gt 0 ]]; then
    PARTICIPANT_ARGS="--participant-label $*"
fi

OPTIONAL_ARGS=""
if [[ "${SKIP_FREESURFER}" == "yes" ]]; then
    OPTIONAL_ARGS="${OPTIONAL_ARGS} --fs-no-reconall"
fi
if [[ "${ME_OUTPUT_ECHOS}" == "yes" ]]; then
    OPTIONAL_ARGS="${OPTIONAL_ARGS} --me-output-echos"
fi

if [[ ! -f "${SINGULARITY_IMAGE}" ]]; then
    echo "ERROR: Singularity image not found at ${SINGULARITY_IMAGE}"
    exit 1
fi
if [[ ! -f "${FS_LICENSE_DIR}/license.txt" ]]; then
    echo "ERROR: FreeSurfer license not found at ${FS_LICENSE_DIR}/license.txt"
    echo "  Get one from: https://fmriprep.org/en/latest/usage.html#the-freesurfer-license"
    exit 1
fi

# Function to submit a single fMRIPrep job via sbatch
submit_fmriprep_job() {
    local JOB_NUM=$1
    local BIDS_DIR=$2
    local OUTPUT_DIR=$3

    if [[ -z "${BIDS_DIR}" ]] || [[ ! -d "${BIDS_DIR}" ]]; then
        echo "Job ${JOB_NUM}: BIDS directory not found or empty - skipping"
        return
    fi

    if [[ -z "${OUTPUT_DIR}" ]]; then
        echo "Job ${JOB_NUM}: Output directory not specified - skipping"
        return
    fi

    local PARENT_DIR=$(dirname "${OUTPUT_DIR}")
    local WORK_DIR="${PARENT_DIR}/fmriprep_work"
    local LOG_DIR="${OUTPUT_DIR}/logs"

    mkdir -p "${OUTPUT_DIR}" "${WORK_DIR}" "${LOG_DIR}"

    echo "Submitting Job ${JOB_NUM} to Slurm..."

    JOB_SCRIPT="${LOG_DIR}/fmriprep_job${JOB_NUM}_submit.sh"
    cat > "${JOB_SCRIPT}" << SLURMEOF
#!/bin/bash
#SBATCH -A ${SLURM_ACCOUNT}
#SBATCH -p ${SLURM_PARTITION}
#SBATCH -J fmriprep_job${JOB_NUM}
#SBATCH -o ${LOG_DIR}/job${JOB_NUM}_%j.out
#SBATCH -e ${LOG_DIR}/job${JOB_NUM}_%j.err
#SBATCH -c ${SLURM_CPUS}

module purge

echo "Job ${JOB_NUM}: Starting fMRIPrep at \$(date)"

apptainer run --cleanenv \\
  -B ${BIDS_DIR}:/data:ro \\
  -B ${OUTPUT_DIR}:/out \\
  -B ${WORK_DIR}:/work \\
  -B ${FS_LICENSE_DIR}:/fs_license \\
  ${SINGULARITY_IMAGE} \\
    /data /out participant \\
    --fs-license-file /fs_license/license.txt \\
    --output-spaces ${OUTPUT_SPACES} \\
    --nthreads ${SLURM_CPUS} \\
    --omp-nthreads ${SLURM_CPUS} \\
    --no-msm \\
    ${OPTIONAL_ARGS} \\
    ${PARTICIPANT_ARGS} \\
    -w /work

echo "Job ${JOB_NUM}: fMRIPrep completed at \$(date)"
SLURMEOF

    sbatch "${JOB_SCRIPT}"

    echo "Job ${JOB_NUM} submitted successfully"
}

echo "=== Starting fMRIPrep Submission (BMRC/Slurm) ==="
echo "Number of jobs configured: ${NUM_JOBS}"
echo "Output spaces: ${OUTPUT_SPACES}"
echo "Skip FreeSurfer: ${SKIP_FREESURFER}"
echo "ME output echos: ${ME_OUTPUT_ECHOS}"
echo "Slurm account: ${SLURM_ACCOUNT}"
echo "Slurm partition: ${SLURM_PARTITION}"
echo ""

for I in $(seq 1 ${NUM_JOBS}); do
    if [[ ${I} -le 4 ]]; then
        eval BIDS_DIR=\$BIDS_DIR_${I}
        eval OUTPUT_DIR=\$OUTPUT_DIR_${I}

        submit_fmriprep_job ${I} "${BIDS_DIR}" "${OUTPUT_DIR}"
    fi
done

echo ""
echo "=== All configured jobs submitted ==="
echo ""
echo "Check job status with: squeue -u \$(whoami)"
echo "After jobs complete, check before proceeding to the next pipeline stage:"
echo "  - {OUTPUT_DIR}/logs/*.err   (errors)"
echo "  - {OUTPUT_DIR}/logs/*.out   (full run log  fmaps, start/finish)"
echo "  - {OUTPUT_DIR}/sub-XX.html (registration quality, warnings)"
echo "  - {OUTPUT_DIR}/sub-XX/func/*desc-preproc_bold.nii.gz (visually inspect)"

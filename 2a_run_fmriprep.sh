#!/bin/bash
# =============================================================================
#  2a_run_fmriprep - Run FMRIPREP Script (Cluster Submission)
# =============================================================================
# Submits one (or more) fMRIPrep jobs to the cluster for SE or ME
# Disclaimer - run this script separately for SE or ME and ensure pointed BIDS directory only contains images for the specific SE or ME acquisition!
#
# Jobs are submitted independently - if input missing, skips to next job
# Creates work and log folders automatically
#
# Participant args: ./run_fmriprep.sh [participant_labels...]
#   - No arguments: processes ALL participants in each dataset
#   - With arguments: processes only specified participants (e.g., sub-001 sub-002)
#
# Cluster note: this script uses fsl_sub (FMRIB cluster scheduler)
# EDIT the submit_fmriprep_job() function below if using a different scheduler (e.g. sbatch/qsub)
# =============================================================================


# =============================================================================
# CONFIGURATION SECTION - EDIT HERE
# =============================================================================

# --- Global fMRIPrep Settings ---
SCRATCH_DIR="/path/to/scratch"                                    
SINGULARITY_IMAGE="${SCRATCH_DIR}/singularity/fmriprep-25.1.3.simg"  #EDIT: pin your fMRIPrep version
FS_LICENSE_DIR="${SCRATCH_DIR}/freesurfer"                        #EDIT according to the location of your dependencies

# Number of fMRIPrep jobs to submit (1-4)
NUM_JOBS=1  

# --- fMRIPrep Processing Options ---
# Output spaces (comma-separated, no spaces)
# Options: MNI152NLin2009cAsym:res-1, MNI152NLin2009cAsym:res-2, MNI152NLin6Asym, T1w
OUTPUT_SPACES="MNI152NLin2009cAsym:res-2"  #EDIT if you need a different output space

# Skip FreeSurfer reconstruction? (yes/no) - Default: yes
SKIP_FREESURFER="yes"  #Freesurfer is high-compute and takes a substantial time to run

# Output multi-echo data separately? (yes/no) - Default: no
ME_OUTPUT_ECHOS="no" #EDIT: change to yes if running for multi-echo data

# =============================================================================
# JOB 1 CONFIGURATION
# =============================================================================
BIDS_DIR_1=""    #EDIT: give full path to BIDS folder
OUTPUT_DIR_1=""  #EDIT: give full path to fmriprep_output folder, change to ME_processing when needed

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

# Build participant arguments from command line
PARTICIPANT_ARGS=""
if [[ $# -gt 0 ]]; then
    PARTICIPANT_ARGS="--participant-label $*"
fi

# Build fMRIPrep optional arguments
OPTIONAL_ARGS=""
if [[ "${SKIP_FREESURFER}" == "yes" ]]; then
    OPTIONAL_ARGS="${OPTIONAL_ARGS} --fs-no-reconall"
fi
if [[ "${ME_OUTPUT_ECHOS}" == "yes" ]]; then
    OPTIONAL_ARGS="${OPTIONAL_ARGS} --me-output-echos"
fi

# Validate global requirements
if [[ ! -f "${SINGULARITY_IMAGE}" ]]; then
    echo "ERROR: Singularity image not found at ${SINGULARITY_IMAGE}"
    exit 1
fi
if [[ ! -f "${FS_LICENSE_DIR}/license.txt" ]]; then
    echo "ERROR: FreeSurfer license not found at ${FS_LICENSE_DIR}/license.txt"
    echo "  Get one from: https://fmriprep.org/en/latest/usage.html#the-freesurfer-license"
    exit 1
fi

# Function to submit a single fMRIPrep job
# #EDIT: this function calls fsl_sub - replace with your own scheduler's submission command if not using fsl_sub.
# Everything above and below this function (path validation, apptainer invocation) does not need to change.
submit_fmriprep_job() {
    local JOB_NUM=$1
    local BIDS_DIR=$2
    local OUTPUT_DIR=$3
    
    # Check if BIDS directory exists
    if [[ -z "${BIDS_DIR}" ]] || [[ ! -d "${BIDS_DIR}" ]]; then
        echo "Job ${JOB_NUM}: BIDS directory not found or empty - skipping"
        return
    fi
    
    # Check if output directory path is provided
    if [[ -z "${OUTPUT_DIR}" ]]; then
        echo "Job ${JOB_NUM}: Output directory not specified - skipping"
        return
    fi
    
    # Auto-generate work and log directories from output directory
    local PARENT_DIR=$(dirname "${OUTPUT_DIR}")
    local WORK_DIR="${PARENT_DIR}/fmriprep_work"
    local LOG_DIR="${OUTPUT_DIR}/logs"
    
    # Create all necessary directories
    mkdir -p "${OUTPUT_DIR}" "${WORK_DIR}" "${LOG_DIR}"
    
    echo "Submitting Job ${JOB_NUM} to cluster..."
    
    fsl_sub -q short -l "${LOG_DIR}" bash -c "
set -e
echo 'Job ${JOB_NUM}: Starting fMRIPrep at \$(date)'

apptainer run --cleanenv \
  -B ${BIDS_DIR}:/data:ro \
  -B ${OUTPUT_DIR}:/out \
  -B ${WORK_DIR}:/work \
  -B ${FS_LICENSE_DIR}:/fs_license \
  ${SINGULARITY_IMAGE} \
    /data /out participant \
    --fs-license-file /fs_license/license.txt \
    --output-spaces ${OUTPUT_SPACES} \
    --nthreads 8 \
    --omp-nthreads 8 \
    --no-msm \
    ${OPTIONAL_ARGS} \
    ${PARTICIPANT_ARGS} \
    -w /work

echo 'Job ${JOB_NUM}: fMRIPrep completed at \$(date)'
"
    
    echo "Job ${JOB_NUM} submitted successfully"
}

# Submit jobs based on NUM_JOBS
echo "=== Starting fMRIPrep Submission ==="
echo "Number of jobs configured: ${NUM_JOBS}"
echo "Output spaces: ${OUTPUT_SPACES}"
echo "Skip FreeSurfer: ${SKIP_FREESURFER}"
echo "ME output echos: ${ME_OUTPUT_ECHOS}"
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
echo "After jobs complete, check before proceeding to the next pipeline stage:"
echo "  - {OUTPUT_DIR}/logs/*.e   (errors)"
echo "  - {OUTPUT_DIR}/logs/*.o   (full run log — fmaps, start/finish)"
echo "  - {OUTPUT_DIR}/sub-XX.html (registration quality, warnings)"
echo "  - {OUTPUT_DIR}/sub-XX/func/*desc-preproc_bold.nii.gz (visually inspect)"

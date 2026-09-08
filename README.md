# 7T SE vs ME fMRI Processing Pipeline

## About this repository

This pipeline was built for a project comparing single-echo (SE) and
multi-echo (ME) resting-state acquisition protocols at 7T, using fMRIPrep-based
preprocessing, TEDANA denoising for the ME branch, and a set of comparison/QC
metrics (tSNR, ROI correlations, motion, temporal autocorrelation, TEDANA
component statistics). It started as a working set of scripts for that project's
own data, folder structure, and analysis needs, and has since been generalized
for public reuse. There are multiple opportunities throughout the pipeline for individualised configuration,
a consistent organisation of folder and script order, error handling, and documentation.

It is shared here both as a record of what was actually done for the comparison project,
and as a starting point for anyone interested in comparing SE and ME acquisitions at 7T (or
adapting the individual stages for other fMRI processing needs).

---

## 1. Scope and design 

- **No master script.** Every stage is standalone, run manually in
  sequence. This is deliberate and lets the researcher inspect each stage's output (e.g. registration quality, mask coverage, log
  warnings).
- **Single-subject-per-invocation.** No batch looping is built in. Any loops would need to be built in separately.
- **Full paths in scripts.** Every script takes explicit, full paths via
  a `#EDIT`-marked config block (or CLI flags). §4 documents the folder
  structure actually used for this project, as a starting template.
- **Resting-state by default.** Confound strategy defaults assume
  resting-state data; a couple of scripts retain task-fMRI options for use.

---

## 2. Scripts & Cluster-based use

Two sets of cluster-submission scripts exist:

- **FMRIB-style (`fsl_sub`)** — the originals, used during initial development
  on the FMRIB cluster (e.g. `2a_run_fmriprep.sh`, `step1b_run_nordic_single_image.sh`).
- **Slurm-style (`sbatch`)** — `submit_script*_sbatch.sh` files, adapted for
  Slurm-based clusters.

**You need the `sbatch` versions if your cluster uses Slurm** (check with your
cluster's documentation, or simply whether `sbatch`/`squeue` are the commands
your admins tell you to use). If your cluster uses `fsl_sub` or a different
scheduler entirely, use the plain scripts and either submit them via your own
scheduler's job-wrapping convention, or run them interactively if lightweight
enough (see below).

**Not every step needs cluster submission.** Steps that only read small text
files (motion QC, ROI autocorrelation, correlations, the aggregate summary)
are lightweight and fine to run directly in a terminal. Steps that load or
process a full 4D brain volume (masking, confound regression, tSNR, TEDANA,
NORDIC, fMRIPrep itself) can need substantially more memory than an
interactive session provides and these are the ones the `sbatch` wrappers exist
for.

---

## 3. Dependencies

| Tool | Used by | Notes |
|---|---|---|
| **fMRIPrep** (Apptainer/Singularity container) | `2a` | Version pinned in the script's `SINGULARITY_IMAGE` path — check and update for your own install. |
| **TEDANA** (Python package) | `2b` | `pip install tedana`, not auto-installed. Pin a version for reproducibility. |
| **ANTs** | `2c` | `antsApplyTransforms` |
| **FSL** | `3`, `5`, `7b`\* | `fslmaths`, `fslmeants`, `fslstats` |
| **MATLAB** | NORDIC step | Image Processing + Signal Processing toolboxes |
| **R** | `6` | Base R only |
| **Python** (3.10+) | `2b`, `3`, `4`, `7a`, `8` | `pandas`, `numpy`, `scipy`, `nibabel`, `tedana`, `scikit-learn`, `matplotlib` |

\* `7b` reads directly from fMRIPrep's `confounds.tsv` (plain text parsing) —
listed here for consistency with the other QC scripts, not a hard FSL
dependency for that one specifically.

Recommended: a dedicated Python virtual environment, kept separate from any
tool (e.g. FSL) that bundles its own internal Python — activating a venv
*after* loading other tools, not before, avoids one silently shadowing the
other.

---

## 4. Recommended folder structure

```
SE_processing/
├── NORDIC_output/              (optional)
├── fmriprep_output/
├── pre_reg_output/
├── confound_regression_output/
├── analysis_output/
│   ├── timeseries/
│   ├── tsnr/
│   └── correlation/
└── qc_checks/
    ├── qc_correlations/
    ├── motion_qc/
    └── temporal_autocorr/

ME_processing/
├── NORDIC_output/               (optional)
├── fmriprep_output/
├── tedana_output/
│   └── sub-XX/
│       └── <mni-normalized-subfolder>/   (from 2c, name configurable)
├── pre_reg_output/
├── confound_regression_output/
├── analysis_output/
│   ├── timeseries/
│   ├── tsnr/
│   └── correlation/
└── qc_checks/
    ├── qc_correlations/
    ├── motion_qc/
    ├── temporal_autocorr/
    └── tedana_component_summary.{txt,csv}

comparison_summary/              (output of 8_aggregate_summary.py)
├── comparison_summary.csv
├── ar1_comparison.csv
└── plots/

masks/                           (bundled with this repo — see §7)
```

Create output folders (and their `logs/` subfolders, if using the `sbatch`
scripts) before running — schedulers need the log directory to already exist
at job submission time.

---

## 5. Scripts and contents

### `0_setup_env.sh`
**Purpose:** Loads every module/environment this pipeline needs (FSL, MATLAB,
R, Python + venv) in one `source`-able step, in the specific order that avoids
tools interfering with each other.
**Method:** Sequential `module load` calls, ending with Python venv activation
last — venv activation modifies `PATH` in a way that must come after
everything else, or tools like FSL (which bundle their own internal Python)
can silently shadow the venv's `python3`.
**Usage:** `source 0_setup_env.sh` (must run with source command).
**Modifiable:** module version strings, the venv path.

### `step1a_run_nordic_single_image.m` + `step1b_run_nordic_single_image.sh`
**Purpose:** Runs NORDIC thermal noise denoising on the BOLD image, before any preprocessing.
**Method:** Calls `NIFTI_NORDIC` (from the [NORDIC_Raw](https://github.com/SteenMoeller/NORDIC_Raw)
repo — Vizioli et al. 2021), which uses MP-PCA-based denoising informed by the
phase image to separate thermal noise from signal.
**Inputs:** magnitude BOLD + phase (`part-phase`) BOLD, same acquisition.
**Output:** denoised `.nii` (uncompressed — NORDIC's own output format;
compress to `.nii.gz` before feeding into BIDS-based tools downstream).
**Modifiable:** `NORDIC_REPO_PATH`, `fn_magn_in`, `fn_phase_in`, `fn_out`,
`OUTPUT_DIR`, and the NORDIC parameters `ARG.temporal_phase`/
`ARG.phase_filter_width` (see NORDIC_Raw's own documentation for what these
control).
**Note:** the `.m` file is named `step1a_...` rather than `1a_...` because
MATLAB's `run()` cannot execute a script whose filename starts with a digit.

### `2a_run_fmriprep.sh` (+ `submit_script2a_sbatch.sh`)
**Purpose:** Submits fMRIPrep as a container job. Run once per branch
— SE or ME is determined entirely by which BIDS directory you point it at, and if you've ME processing within the fMRIPrep commands.
**Method:** Standard fMRIPrep preprocessing (Esteban et al. 2019) — motion
correction, susceptibility distortion correction, coregistration to T1w, and
normalization to MNI space — run via `apptainer run` on a pinned fMRIPrep
container image.
**Modifiable:** `SINGULARITY_IMAGE` (version), `FS_LICENSE_DIR`,
`OUTPUT_SPACES` (which MNI template/resolution), `SKIP_FREESURFER`,
`ME_OUTPUT_ECHOS` (must be `yes` for the ME branch — this is what makes
fMRIPrep output per-echo native-space files for TEDANA to use). Script currently has up to 4
`BIDS_DIR_n`/`OUTPUT_DIR_n` job submission slots.
**Note:** Batch/cluster submission is essentially always for this step as 
fMRIPrep is resource-intensive and long-running (at least 2 hours).

### `2b_run_tedana.py` (+ `submit_script2b_sbatch.sh`)
**Purpose (step 2, ME only):** Runs TEDANA on fMRIPrep's native-space
multi-echo output.
**Method:** TE-dependence multi-echo ICA (Kundu et al. 2012/2013; DuPre et al.
2021, the `tedana` package) — decomposes the multi-echo timeseries into
components and classifies them as BOLD-like (TE-dependent) or non-BOLD/noise
(TE-independent) based on their signal decay behavior across echoes.

Script auto-finds native-space per-echo files,
groups them by acquisition, and reads echo times from the BIDS JSON sidecars
(explicitly excluding `part-phase` JSONs, which would otherwise double-count
echoes if NORDIC was used upstream).
**Modifiable:** `MASK_PATH` (`None` = TEDANA's own auto-mask, matching its
default behavior; `"fmriprep"` = use fMRIPrep's brain mask instead — worth
trying if you see signal dropout in deep/inferior brain regions),
`TEDANA_TREE` (decision tree — `minimal`/`kundu`/`kundu-decision-tree`),
`TEDANA_TEDPCA`, `TEDANA_FITTYPE`, `TEDANA_GSCONTROL`.
**Usage:** `python3 2b_run_tedana.py --process` (the `--process` flag forces
direct execution — required when calling it from a Slurm wrapper).

### `2c_tedana_native_to_mni.sh` (+ `submit_script2c_sbatch.sh`)
**Purpose (step 2, ME only):** Normalizes TEDANA's native-space output to MNI
space, using fMRIPrep's own T1→MNI and func→T1w transforms (no separate
registration step needed — fMRIPrep already produces these).
**Method:** `antsApplyTransforms`, composing the func→T1w affine and the
T1w→MNI transform (fMRIPrep's own `.h5` bundle, containing both an affine and
a displacement field component).
**Output:** written into a **new subfolder** inside the TEDANA output
directory — never overwrites TEDANA's native-space output.
**Modifiable:** `TEDANA_NATIVE_BOLD`, `TRANSFORM_T1_TO_MNI`,
`TRANSFORM_FUNC_TO_T1`, `MNI_REF` (the resampling target grid — see the note
below), `OUTPUT_SUBDIR_NAME`.
**Note:** either a standalone MNI152NLin2009cAsym template file
or one of fMRIPrep's own MNI-space outputs can work here, but they are not
guaranteed to share an identical voxel grid just because they're nominally
"the same template" — verify with `fslinfo`/`fslhd` (dimensions, pixdims, and
`sto_xyz` matrix) that your chosen `MNI_REF` matches the grid of the mask
you'll use downstream before trusting the output.

### `3_pre_confound_regression.py` (+ `submit_script3_sbatch.sh`)
**Purpose:** Extracts fMRIPrep's confound regressors and produces a
matched brain-masked BOLD image, in one pass, for either branch.
**Method — confounds:** builds a confound design from fMRIPrep's
`confounds.tsv`, per a chosen strategy (see below), computing any missing
squared/derivative motion terms if they aren't already present.
**Method — masking:** locates the correct fMRIPrep brain mask (constrained to
a specific space via `MASK_SPACE_TAG`, since fMRIPrep writes masks in
multiple spaces under near-identical filenames — an unconstrained match can
silently grab the wrong one) and applies it via `fslmaths -mas`, with an
explicit dimension check beforehand so a mismatch fails with a clear message.
**Branch handling:** for SE, the BOLD to mask is found in the same folder as
the confounds (`--input-dir`). For ME, `--bold-dir` should point at the
TEDANA output root — the script looks specifically inside the MNI-normalized
subfolder produced by `2c` (`ME_MNI_SUBDIR`, must match `2c`'s
`OUTPUT_SUBDIR_NAME`), never falling back to native-space output.
**Confound strategies:**
- `conf24` — 24-parameter motion model (6 rigid-body + derivatives + squared
  + derivative-squared). A default conservative approach, for both branches.
- `conf24_acompcor` — adds aCompCor components + cosine drift regressors.
- `conf24_phy` — adds mean CSF/WM signal instead of aCompCor components.
**Output formats:** default output includes a header row (real column names)
— deliberately, since a headerless numeric file can be misdetected as "has a
header" by naive downstream parsing if the first row happens to contain
values that don't look like a header. `--feat-output` additionally produces a
headerless version, for use with FSL FEAT specifically (which requires the file to be headerless).
**Modifiable:** `INPUT_DIR`, `BOLD_DIR`, `OUTPUT_DIR`, `STRATEGY`,
`MASK_SPACE_TAG`, `ME_MNI_SUBDIR`, `N_ACOMPCOR`, `INCLUDE_GLOBAL_SIGNAL`,
`INCLUDE_NSS`, `MASK_ENABLED`, `FEAT_OUTPUT_ENABLED`.

### `4_run_confound_regression.py` (+ `submit_script4_sbatch.sh`)
**Purpose:** Final nuisance regression — the analysis-ready output
for both branches.
**Method:** fits a GLM (intercept + confound regressors, via pseudoinverse) to
every relevant voxel and writes the residuals back as a 4D image, restoring
the original mean signal intensity per voxel.
**Masking:** `--mask` is optional. If omitted (the expected case, since the
input is already masked by script 3), voxels are inferred directly from
non-zero BOLD values, rather than requiring the same mask path to be typed
again.
**Note:** the common fMRIPrep off-by-one case, where the
confound file has exactly one fewer row than the BOLD has timepoints (a zero
row is prepended).
**Modifiable:** `BOLD`, `TSV`, `BRAIN_MASK` (optional), `OUTPUT_DIR`,
`OUTPUT_NAME`.

### `5_extract_timeseries_tsnr.sh` (+ `submit_script5_sbatch.sh`)
**Purpose:** ROI timeseries extraction and whole-brain tSNR, from the
final regressed output. By this stage SE and ME outputs are the same shape (masked, MNI-space,
confound-regressed).
**Method:** `fslmeants` per mask in `MASK_DIR`; tSNR computed as
temporal-mean divided by temporal-standard-deviation (`fslmaths -Tmean`,
`-Tstd`, then division), summarized via `fslstats`.
**Optional sanity checks:** flags timeseries files that are entirely or
mostly zero (a likely sign of a masking/registration problem), and reports
center-of-mass distance to an MNI reference as a rough alignment check.
**Modifiable:** `INPUT_BOLD`, `OUTPUT_DIR`, `MASK_DIR`, `RUN_SANITY_CHECKS`,
`MNI_REF`.

### `6_run_correlations.R`
**Purpose:** ROI-to-ROI correlation analysis — this project's
specific analysis structure, not a generic tool (see note below).
**Method:** for each ROI, computes the Pearson correlation between its left
and right hemisphere timeseries (a symmetry check), and separately, the
correlation between each ROI's mean bilateral timeseries and the mean
bilateral corpus callosum (CC) timeseries — CC is used here as a reference signal for a QC-style check, not a region of primary
interest.
**Output split:** left-right correlations go to `analysis_output/correlation`
(a primary result); ROI-vs-CC correlations go to `qc_checks/qc_correlations`
(a QC/sanity check, not a connectivity finding).
**This project's ROI set** (`ROI_NAMES`): CC, M1, V1, VTA, VTASN, VS — see §7
for the actual bundled masks, which include a few additional regions not yet
wired into this default list (PCC, VMPFC) — update `ROI_NAMES` and the
left/right pairing logic if you want those included in this analysis too.
**If reusing for a different project:** update `ROI_NAMES` and, if your
analysis doesn't use a CC-style reference-signal QC check, remove or adapt
that section directly — this script was intentionally left specific rather
than generalized, unlike the rest of the pipeline.
**Modifiable:** `PIPELINE_RUNS` (list of timeseries folders, one per branch),
`ROI_NAMES`.

### `7a_tedana_component_summary.py`
**Purpose (QC, ME only):** Summarizes TEDANA's own component classification
table into a readable report.
**Method:** reads TEDANA's `desc-tedana_metrics.tsv`, counts
accepted/rejected components, and sums the `variance explained` column
separately for each classification — giving "variance retained" (accepted)
and "variance removed" (rejected) as distinct numbers (not to be
confused with TEDANA's own run-log figure "variance explained by
decomposition," which is a total across all components, not noise-specific).
**Output:** a `.txt` report plus a machine-readable `.csv` sidecar (used by
`8_aggregate_summary.py`).
**Usage:** `python3 7a_tedana_component_summary.py --metrics-tsv <path> --output <path>`
(CLI arguments, no config block to edit).

### `7b_motion_qc.sh`
**Purpose (QC):** Mean framewise displacement (FD) per subject/run, from
fMRIPrep's own `confounds.tsv`.
**Method:** locates the `framewise_displacement` column and averages it
(fMRIPrep computes FD itself; this script doesn't recompute it from raw
motion parameters).
**Modifiable:** `FILES` (list of confounds.tsv paths), `OUT_DIR`,
`THRESHOLD` (FD value above which a run is flagged).

### `7c_roi_temp_autocorrelation.sh`
**Purpose (QC):** Lag-1 autocorrelation (AR1) per ROI timeseries — a
descriptive measure of how smoothly/slowly each ROI's residual signal changes
over time and how the timeseries is correlated to itself.
**Method:** for each `{roi}_timeseries.txt` file, computes the sample lag-1
autocorrelation coefficient directly (pure signal statistics, no FSL/ANTs
tool involved).
**Why it might be useful for an SE/ME comparison:** denoising changes the temporal
structure of what's left in the residual signal — NORDIC removes largely
temporally uncorrelated thermal noise, while TEDANA's component
rejection is based on a genuinely different criterion (TE-dependence), so
comparing AR1 between branches is a way to see whether/how that difference
in denoising approach shows up in the residual signal's temporal smoothness.
Purely descriptive — no threshold in this script implies "good" or "bad."
**Modifiable:** `TS_DIR`, `OUT_DIR`, `OUTFILE`.

### `8_aggregate_summary.py`
**Purpose (Summary):** Pulls every QC/comparison metric from both branches
into one wide comparison table, a separate long-format AR1 table, and a set
of comparison plots.
**Method:** reads each branch's already-computed output files (tSNR CSV,
motion QC CSV, LR/QC correlation CSVs, AR1 TSV, TEDANA component CSV for ME,
and BOLD JSON sidecars for TR/TE/volume count) — performs no new computation
of its own, purely aggregates. Missing files are reported clearly and filled
as `NA` rather than causing a failure, so this can be run with only one
branch's data present, or re-run as more stages complete.
**Modifiable:** `ROI_NAMES`, `BRANCHES` (one entry per branch: `root`,
`bold_json` list, `final_bold`, optional `manual_te_ms` override if EchoTime
isn't present in a JSON sidecar — common for single-echo acquisitions),
`OUTPUT_DIR`.

---

## 6. Masks and templates (`masks/`)

Bundled with this repo:
- **Bilateral ROI masks** (left/right pairs): CC, M1, PCC, V1, VMPFC, VS, VTA,
  VTASN — MNI152NLin2009cAsym, 2mm. A `bilateral/` subfolder contains combined
  left+right versions of these.
- **MNI2009 reference files** (`MNI2009/`): 2mm whole-head template, 2mm brain
  (skull-stripped), and its brain mask.
- **Schaefer 2018 200-parcel atlas**, provided in both MNI2009 and FSL's
  MNI152 2mm space.

These masks are specific to this project's regions of interest provided as
a starting point/example. `6_run_correlations.R`'s `ROI_NAMES` currently only wires in a
subset of what's bundled here (CC, M1, V1, VTA, VTASN, VS) — update it if you
want other/different regions in that analysis. Masks must be in the same
space/resolution as your final pipeline output for `5_extract_timeseries_tsnr.sh`
to work correctly — verify with `fslinfo` if using your own.

---

## 7. Known error points

- **fMRIPrep brain masks exist in multiple spaces under near-identical
  filenames** (native/T1w and each requested output space). An unconstrained
  filename match can silently pick the wrong-space mask — `3`'s
  `MASK_SPACE_TAG` exists specifically to prevent this.
- **Two independently-sourced "MNI-space" files are not guaranteed to share a
  voxel grid**, even at the same nominal resolution — verify with
  `fslinfo`/`fslhd` before trusting a masking/registration step that combines
  them.
- **TEDANA's file discovery can double-count echo JSONs** if `part-phase`
  sidecars (from NORDIC) are present in the BIDS directory — `2b` explicitly
  excludes these.
- **MATLAB script filenames can error if started with a digit** — this is why the
  NORDIC `.m` script uses a `step1a_` prefix rather than `1a_`, unlike every
  other script here.
- **A crashed job can leave a partial/corrupt output file behind.** Several
  scripts skip re-processing if output already exists — this check can't tell
  a genuinely completed file from a partial one. Check for and remove
  suspicious partial outputs after any crash, before re-running.
- **When submitting via Slurm, conda environments need `conda.sh` sourced
  explicitly** (`source "$(conda info --base)/etc/profile.d/conda.sh"`)
  rather than relying on `conda init`'s shell hook, since `sbatch` jobs
  typically don't source `~/.bashrc` the way an interactive login shell does.

---

## 8. Deliberately out of scope

- **FSL/FEAT/MELODIC preprocessing branch** — explored during development but excluded to keep the repo focused on a single-tool (fMRIPrep) comparison.
- **Physio (PNM)-based confound regression** — if a physio-based regression needed to be added to this pipeline it would be via FSL FEAT (which natively supports
  voxelwise confound regressors, unlike the matrix-based GLM in script 4). The PNM steps would need to be observed and FEAT-friendly confounds file output would be needed. These would be input to FEAT along with the BOLD image to achieve confound regression through fsl tools.

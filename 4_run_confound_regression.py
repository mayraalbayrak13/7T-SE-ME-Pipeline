#!/usr/bin/env python3
"""
4_run_confound_regression.py
==============================
Fits a GLM (intercept + confound regressors) to each voxel and writes the residuals (confound-regressed BOLD) to disk. This is the final step in both the SE and ME branches of the preprocessing pipeline.

Expected upstream step: 3_pre_confound_regression.py, which produces both the extracted confound file (--tsv) and an already brain-masked BOLD (--bold) in one pass.

Mask handling
-------------
  --mask is OPTIONAL.
    - If provided: voxels are selected from the mask (mask > 0), same as before.
	  Useful if running this script standalone on BOLD data that hasn't already been masked.
    - If omitted (default): voxels to process are inferred directly from the previously masked BOLD image 

Other technicalities
---------------------
Confounds are used EXACTLY as provided (filtering and selection belongs in 3_pre_confound_regression.py). 
This script only fits and removes whatever regressors are in the file, plus an intercept term.

Handles the common fMRIPrep off-by-one case automatically (if the confound file has exactly one fewer row than the BOLD has timepoints).
A zero row is prepended (assumes the missing row corresponds to TR=0, e.g. a dropped first-derivative row).

Usage examples
--------------
  # Standard use — no mask needed, BOLD is already masked by script #3
  python3 4_run_confound_regression.py \\
      --bold /path/to/{prefix}_desc-masked_bold.nii.gz \\
      --tsv  /path/to/rest_conf24.txt \\
      --output-dir /path/to/output

  # Standalone use on unmasked data — mask explicitly required
  python3 4_run_confound_regression.py \\
      --bold /path/to/unmasked_bold.nii.gz \\
      --tsv  /path/to/rest_conf24.txt \\
      --mask /path/to/brain_mask.nii.gz \\
      --output-dir /path/to/output

  # Dry run (validate inputs without running regression)
  python3 4_run_confound_regression.py --bold X --tsv Y --output-dir O --dry-run

  # Submit to cluster
  python3 4_run_confound_regression.py --bold X --tsv Y --output-dir O --use-cluster

Dependencies: numpy, pandas, nibabel, scipy
"""

from __future__ import annotations
import os
import sys
import argparse
import subprocess
import traceback
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import nibabel as nb
from scipy import linalg

# =============================================================================
# CONFIGURATION — edit defaults here, or override via CLI flags
# =============================================================================

CONFIG = {
    "BOLD":"/path/to/pre_reg_output/*_desc-masked_bold.nii.gz",  #EDIT 
    "TSV":"/path/to/pre_reg_output/rest_conf24.txt",                     #EDIT 
    "BRAIN_MASK":  None,  #optional, default is None 
    "OUTPUT_DIR":"/path/to/confound_regression_output",                     #EDIT
    "OUTPUT_NAME":"regressed_bold.nii.gz",  #EDIT if you want a different filename

    "USE_CLUSTER": True,   	#EDIT
    "CLUSTER_QUEUE": "short",  	#EDIT: adapt to your scheduler's queue naming
    "CLUSTER_MEMORY_GB": 32,   	#EDIT
}

# =============================================================================
# END CONFIGURATION
# =============================================================================


# =============================================================================
# Logging
# =============================================================================

def log(msg, logfile=None):
    msg = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(msg)
    if logfile:
        logfile.write(msg + "\n")
        logfile.flush()

def err(msg, logfile=None):
    msg = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ERROR: {msg}"
    print(msg, file=sys.stderr)
    if logfile:
        logfile.write(msg + "\n")
        logfile.flush()


# =============================================================================
# LOAD CONFOUNDS (auto-detect header, fix off-by-one length)
# =============================================================================

def load_confounds(tsv_path: Path, nt_bold: int, logfile=None) -> pd.DataFrame:
    df = pd.read_csv(tsv_path, sep="\t")

    # Detect header vs no-header (numeric column names → no header)
    if all(str(c).isdigit() for c in df.columns):
        log("Detected NO HEADER → using raw matrix", logfile)
        df = pd.read_csv(tsv_path, sep="\t", header=None)
    else:
        log("Detected HEADER → using labeled TSV", logfile)

    log(f"Confounds shape: {df.shape}", logfile)
    log(f"BOLD timepoints: {nt_bold}", logfile)

    if df.shape[0] == nt_bold:
        pass
    elif df.shape[0] == nt_bold - 1:
        log("Confounds has one fewer row than BOLD → prepending zero row (TR=0)", logfile)
        zero_row = pd.DataFrame([[0.0] * df.shape[1]], columns=df.columns)
        df = pd.concat([zero_row, df], ignore_index=True)
    else:
        raise ValueError(
            f"Mismatch: confounds rows ({df.shape[0]}) != BOLD timepoints ({nt_bold})"
        )

    return df


# =============================================================================
# DESIGN MATRIX
# =============================================================================

def build_design_matrix(df: pd.DataFrame) -> np.ndarray:
    X = df.fillna(0.0).to_numpy(dtype=np.float32)
    X = np.hstack((np.ones((X.shape[0], 1), dtype=np.float32), X))  # intercept
    return X


# =============================================================================
# VOXEL SELECTION
# =============================================================================

def get_voxel_mask(bold_data: np.ndarray, mask_img=None, logfile=None) -> np.ndarray:
    """
    Determine which voxels to process.
      If mask_img is given: use mask > 0 (explicit mask mode).
      Otherwise: infer from the BOLD data itself — any voxel whose
        timeseries isn't all-zero. Correct as long as upstream masking
        (3_pre_confound_regression.py) already zeroed the background,
        which is the expected input for this script.
    """
    if mask_img is not None:
        log("Using provided --mask", logfile)
        return np.asarray(mask_img.dataobj) > 0
    else:
        log("No --mask provided — inferring brain voxels from non-zero BOLD "
            "timeseries (expects BOLD already masked upstream)", logfile)
        nonzero = np.any(bold_data != 0, axis=-1)
        return nonzero


# =============================================================================
# REGRESSION
# =============================================================================

def regress_bold(bold_img, X, mask_img=None, logfile=None):
    data = np.asarray(bold_img.dataobj, dtype=np.float32)
    nx, ny, nz, nt = data.shape
    flat = data.reshape(-1, nt)

    mask = get_voxel_mask(data, mask_img, logfile)
    vox_idx = np.where(mask.reshape(-1))[0]

    log(f"Voxels to process: {len(vox_idx)}", logfile)
    log(f"Regressors: {X.shape[1]} (including intercept)", logfile)

    if len(vox_idx) == 0:
        raise ValueError(
            "No non-zero voxels found in BOLD data (and no --mask given). "
            "Check that the BOLD image is genuinely masked/non-empty, or "
            "provide --mask explicitly."
        )

    pinv = linalg.pinv(X)
    cleaned = np.zeros_like(flat)

    for i in vox_idx:
        y = flat[i, :]
        beta = pinv.dot(y)
        resid = y - X.dot(beta)
        resid += np.mean(y)  # restore mean signal intensity
        cleaned[i, :] = resid

    return nb.Nifti1Image(
        cleaned.reshape(nx, ny, nz, nt),
        affine=bold_img.affine,
        header=bold_img.header
    )


# =============================================================================
# PROCESS
# =============================================================================

def process(bold_path: Path, tsv_path: Path, mask_path: Path | None,
            output_dir: Path, output_name: str, dry_run: bool = False) -> bool:

    required = [("BOLD", bold_path), ("Confounds TSV", tsv_path)]
    if mask_path is not None:
        required.append(("Brain mask", mask_path))

    for label, path in required:
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")

    out_bold = output_dir / output_name
    log_file = output_dir / "nuisance_regression.log"

    if out_bold.exists():
        raise FileExistsError(
            f"Output already exists: {out_bold}\n"
            "Delete/rename it first, or change OUTPUT_NAME/--output-name, then rerun."
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        print(f"[DRY RUN] Would regress:\n"
              f"  BOLD:   {bold_path}\n"
              f"  TSV:    {tsv_path}\n"
              f"  Mask:   {mask_path if mask_path else '(none — inferred from non-zero BOLD voxels)'}\n"
              f"  Output: {out_bold}")
        return True

    logfile = open(log_file, "w")

    try:
        log("=== NUISANCE REGRESSION ===", logfile)

        bold_img = nb.load(str(bold_path))
        nt = bold_img.shape[3]

        df = load_confounds(tsv_path, nt, logfile)
        X = build_design_matrix(df)

        mask_img = nb.load(str(mask_path)) if mask_path is not None else None

        log("Running regression...", logfile)
        cleaned = regress_bold(bold_img, X, mask_img, logfile)

        nb.save(cleaned, str(out_bold))
        log(f"Saved: {out_bold}", logfile)

        return True

    except Exception as e:
        err(str(e), logfile)
        traceback.print_exc(file=logfile)
        return False

    finally:
        logfile.close()


# =============================================================================
# CLUSTER
# =============================================================================

def running_on_cluster() -> bool:
    return any(v in os.environ for v in ["SGE_TASK_ID", "SLURM_JOB_ID"])

def submit_to_cluster(cfg: dict) -> None:
    """
    Example submission via fsl_sub (our FMRIB cluster scheduler).
    #EDIT: replace with your own scheduler's submission command
    (e.g. sbatch/qsub) if not using fsl_sub.
    """
    script = Path(__file__).resolve()
    # Re-pass all original argv except --use-cluster to avoid resubmission loop
    passthrough = [a for a in sys.argv[1:] if a != "--use-cluster"]
    cmd = [
        "fsl_sub",
        "-q", cfg["CLUSTER_QUEUE"],
        "-R", str(cfg["CLUSTER_MEMORY_GB"]),
        "python3", str(script)
    ] + passthrough
    print("Submitting:", " ".join(cmd))
    subprocess.check_call(cmd)


# =============================================================================
# ENTRY
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Regress user-supplied confounds out of a BOLD image.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--bold", help="Path to BOLD image")
    parser.add_argument("--tsv", help="Path to confound file (TSV with header, or headerless .txt)")
    parser.add_argument("--mask", default=None,
                        help="Path to brain mask (OPTIONAL — omit if BOLD is already masked, "
                             "e.g. output of 3_pre_confound_regression.py)")
    parser.add_argument("--output-dir", help="Output directory")
    parser.add_argument("--output-name", default=None,
                        help=f"Output filename (default: {CONFIG['OUTPUT_NAME']})")
    parser.add_argument("--use-cluster", action="store_true", help="Submit via fsl_sub")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs and print what would run, without regressing")
    args = parser.parse_args()

    bold        = Path(args.bold) if args.bold else Path(CONFIG["BOLD"])
    tsv         = Path(args.tsv) if args.tsv else Path(CONFIG["TSV"])
    mask_raw    = args.mask if args.mask is not None else CONFIG["BRAIN_MASK"]
    mask        = Path(mask_raw) if mask_raw else None
    out_dir     = Path(args.output_dir) if args.output_dir else Path(CONFIG["OUTPUT_DIR"])
    output_name = args.output_name if args.output_name else CONFIG["OUTPUT_NAME"]

    if args.use_cluster and not running_on_cluster():
        submit_to_cluster(CONFIG)
        return 0

    try:
        ok = process(bold, tsv, mask, out_dir, output_name, dry_run=args.dry_run)
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        err(str(e))
        return 1

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

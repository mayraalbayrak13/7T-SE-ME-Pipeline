#!/usr/bin/env python3
"""
3_pre_confound_regression.py
==============================

Extracts fMRIPrep confound regressors AND produces a brain-masked BOLD image, so this script's output is everything 4_run_confound_regression.py needs.

Recommended usage:
  Resting state → --analysis-type rest  --strategy conf24
  (This project's default is conf24 for both branches, it is also a conservative option.)

Confound file output — TWO possible formats, controlled by --feat-output:
  DEFAULT (script-led regression, outputs with a header)

  OPTIONAL (--feat-output, for use in FEAT): NO header, tab-separated numeric only - FEAT requires this exact format.

Masked BOLD output: {prefix}_desc-masked_bold.nii.gz

Two BOLD-matching modes
------------------------
  SE (default): the BOLD to mask is found in the same folder as the
    confounds TSV (--input-dir), matched by shared filename prefix.
    This is fMRIPrep's own preprocessed output ({prefix}*_desc-preproc_bold.nii.gz).

  ME (--bold-dir provided): the BOLD to mask is TEDANA's output AFTER MNI
    normalization. This script looks ONLY inside {bold_dir}/{subject_id}/{me_mni_subdir}/
    (default subfolder name: "tedana_mni_reg") and does NOT fall back to
    TEDANA's native-space output.

Confound Regression Strategies
----------
  conf24
      24-parameter motion model: 6 rigid body params + derivatives + squared
      + derivative-squared. The most widely used motion-only strategy.

  conf24_acompcor
      conf24 + top N aCompCor components + cosine drift regressors.
      aCompCor captures structured WM/CSF noise orthogonally to motion.
      Cosines implement an effective ~128s highpass filter.
      → More aggressive denoising can be appropriate when you have no signal model to protect.

  conf24_phy
      conf24 + mean CSF + mean WM signals (+ global signal if --global-signal).
      A simpler physiological noise model using mean tissue signals rather than
      PCA components. Less recommended than conf24_acompcor but widely used in
      older literature.
      → USE IF you need to match a specific published pipeline, or aCompCor
        components are unavailable in your confounds file.

Usage examples
--------------
  # SE branch, script-led regression (default — header included)
  python3 3_pre_confound_regression.py \\
      --input-dir /path/to/fmriprep_output/sub-01/func \\
      --output-dir /path/to/confounds \\
      --analysis-type rest \\
      --strategy conf24

  # ME branch, script-led regression
  python3 3_pre_confound_regression.py \\
      --input-dir /path/to/fmriprep_output/sub-01/func \\
      --bold-dir /path/to/tedana_output \\
      --output-dir /path/to/confounds \\
      --analysis-type rest \\
      --strategy conf24

  # Also produce a FEAT-compatible (headerless) confound file
  python3 3_pre_confound_regression.py \\
      --input-dir /path/to/fmriprep_output/sub-01/func \\
      --output-dir /path/to/confounds \\
      --analysis-type rest \\
      --strategy conf24 \\
      --feat-output

  # To output confounds only:
  python3 3_pre_confound_regression.py --input-dir X --output-dir O --no-mask

  # Dry run to inspect files without processing
  python3 3_pre_confound_regression.py --input-dir /path/to/func --dry-run

  # Submit to cluster
  python3 3_pre_confound_regression.py --input-dir /path/to/func --use-cluster --queue short

Dependencies: pandas, nibabel; FSL (fslmaths) on PATH if masking is enabled (default)
"""

import os
import sys
import argparse
import logging
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

import pandas as pd

# =============================================================================
# CONFIGURATION — EDIT HERE
# =============================================================================

INPUT_DIR  = "/path/to/fmriprep_output/sub-*/func"    #EDIT, specify under SE or ME branch for proper folder structure
BOLD_DIR   = None                                      #EDIT: set for ME branch (tedana_output root); leave None for SE
OUTPUT_DIR = "/path/to/pre_reg_output"               #EDIT, specify under SE or ME branch for proper folder structure

ANALYSIS_TYPE  = "rest"         # "task" or "rest" — this project is resting-state
STRATEGY       = "conf24"       # "conf24", "conf24_acompcor", "conf24_phy"

INCLUDE_GLOBAL_SIGNAL = False   # EDIT to add global_signal regressor
N_ACOMPCOR            = 5       # Number of aCompCor components (used by conf24_acompcor)
INCLUDE_NSS           = True    # Non-steady-state outlier regressors (first few TRs)

FEAT_OUTPUT_ENABLED = False     # EDIT to also produce a headerless FEAT-compatible confound file

MASK_ENABLED = True             # EDIT: produce a masked BOLD alongside confounds
FMRIPREP_MASK_PATTERN_SUFFIX = "_desc-brain_mask.nii.gz"
SE_BOLD_PATTERN_SUFFIX       = "_desc-preproc_bold.nii.gz"
ME_BOLD_GLOB                 = "*_desc-denoised_bold.nii.gz"
ME_MNI_SUBDIR                = "tedana_mni_reg"  # DISCLAIMER - must match OUTPUT_SUBDIR_NAME in 2c_tedana_native_to_mni.sh

# fMRIPrep writes brain masks in multiple spaces with the SAME filename
# suffix (native/T1w and each --output-spaces entry). This constrains mask
# lookup to one specific space, matching what 2a_run_fmriprep.sh actually
# requests (OUTPUT_SPACES). Without this, an unconstrained glob can match
# the wrong-space mask silently.
MASK_SPACE_TAG = "MNI152NLin2009cAsym_res-2"  # EDIT: must match OUTPUT_SPACES in 2a_run_fmriprep.sh

USE_CLUSTER = False
CLUSTER_QUEUE  = "short"    # EDIT: adapt to your scheduler's queue naming
CLUSTER_MEMORY = 18  #in GB

# =============================================================================
# END CONFIGURATION
# =============================================================================

# --- Motion parameter column names ---
_MOTION_BASE   = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z']
_MOTION_DERIV  = [f'{c}_derivative1'        for c in _MOTION_BASE]
_MOTION_SQ     = [f'{c}_power2'             for c in _MOTION_BASE]
_MOTION_DSQ    = [f'{c}_derivative1_power2' for c in _MOTION_BASE]
_MOTION_24     = _MOTION_BASE + _MOTION_DERIV + _MOTION_SQ + _MOTION_DSQ


def setup_logging(output_dir: Path, level: str = "INFO") -> Path:
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"confound_extraction_{datetime.now():%Y%m%d_%H%M%S}.log"

    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fh = logging.FileHandler(log_file)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    return log_file


def ensure_motion_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Compute any missing squared / derivative motion terms from available columns.
    First-row NaN in derivative columns (expected) is filled with 0.
    Returns updated df and list of computed column names.
    """
    computed = []

    for col in _MOTION_DERIV:
        if col in df.columns:
            df[col] = df[col].fillna(0.0)

    for base, sq in zip(_MOTION_BASE, _MOTION_SQ):
        if sq not in df.columns and base in df.columns:
            df[sq] = df[base] ** 2
            computed.append(sq)

    for deriv, dsq in zip(_MOTION_DERIV, _MOTION_DSQ):
        if dsq not in df.columns and deriv in df.columns:
            df[dsq] = df[deriv].fillna(0.0) ** 2
            computed.append(dsq)

    if computed:
        logging.debug(f"  Computed {len(computed)} missing motion terms: {computed}")

    return df, computed


def build_confound_columns(df: pd.DataFrame, strategy: str, cfg: dict) -> list[str]:
    """
    Return ordered list of confound column names for the chosen strategy.
    Only columns that exist in df are included; missing ones are warned.
    """
    desired = list(_MOTION_24)

    if strategy == "conf24_acompcor":
        n = cfg["n_acompcor"]
        acomp = [f"a_comp_cor_{i:02d}" for i in range(n)]
        desired += acomp
        cosines = sorted(c for c in df.columns if c.startswith("cosine"))
        desired += cosines

    elif strategy == "conf24_phy":
        desired += ["csf", "white_matter"]

    if cfg["global_signal"]:
        for col in ["global_signal", "global_signal_derivative1", "global_signal_power2"]:
            if col not in desired:
                desired.append(col)

    if cfg["include_nss"]:
        nss = sorted(c for c in df.columns if c.startswith("non_steady_state_outlier"))
        desired += nss

    seen, ordered = set(), []
    for c in desired:
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    available = [c for c in ordered if c in df.columns]
    missing   = [c for c in ordered if c not in df.columns]

    if missing:
        logging.warning(f"  Columns requested but not found: {missing}")

    return available


def unique_path(path: Path) -> Path:
    """Append _1, _2, ... if path already exists. (Intentional: allows re-running
    with different parameter sweeps without manual renaming.)"""
    if not path.exists():
        return path
    i = 1
    while True:
        candidate = path.with_stem(f"{path.stem}_{i}")
        if not candidate.exists():
            return candidate
        i += 1


def get_prefix(confound_file: Path) -> str:
    """Strip the fMRIPrep confounds suffix to get the shared acquisition prefix."""
    return confound_file.name.replace("_desc-confounds_timeseries.tsv", "")


def get_subject_id(name: str) -> str | None:
    import re
    m = re.search(r"(sub-[^_]+)", name)
    return m.group(1) if m else None


def find_mask(input_dir: Path, prefix: str, space_tag: str = MASK_SPACE_TAG) -> Path | None:
    """
    Locate fMRIPrep's brain mask matching this acquisition prefix, CONSTRAINED
    to a specific space. fMRIPrep outputs masks in multiple spaces (native/T1w
    and each --output-spaces entry) all sharing the same "_desc-brain_mask.nii.gz"
    suffix — without this constraint, an unconstrained glob can match the
    wrong-space (e.g. native) mask silently, which will fail (or worse,
    misalign without erroring) when applied to an MNI-space BOLD image.
    """
    matches = sorted(input_dir.glob(f"{prefix}*space-{space_tag}*{FMRIPREP_MASK_PATTERN_SUFFIX}"))
    return matches[0] if matches else None


def find_bold_to_mask(input_dir: Path, bold_dir: str | None, prefix: str,
                       me_mni_subdir: str = ME_MNI_SUBDIR) -> Path | None:
    """
    Locate the BOLD file to mask.
      SE mode (bold_dir is None): same folder as confounds, prefix-matched.
      ME mode (bold_dir given): looks ONLY inside {bold_dir}/{subject_id}/{me_mni_subdir}/
        — i.e. the MNI-normalized output from 2c_tedana_native_to_mni.sh.
        Does NOT fall back to TEDANA's native-space output: this pipeline's
        ME branch always masks/regresses in MNI space (matching the SE
        branch's own MNI-space masking), so native-space TEDANA output is
        never the correct input here. If the MNI subfolder is missing, this
        errors clearly rather than silently picking the wrong file.
    """
    if bold_dir is None:
        matches = sorted(input_dir.glob(f"{prefix}*{SE_BOLD_PATTERN_SUFFIX}"))
        return matches[0] if matches else None
    else:
        subject_id = get_subject_id(prefix)
        if subject_id is None:
            logging.error(f"  Could not extract subject ID from prefix: {prefix}")
            return None

        mni_dir = Path(bold_dir) / subject_id / me_mni_subdir
        if not mni_dir.exists():
            logging.error(
                f"  MNI-normalized TEDANA output not found: {mni_dir}\n"
                f"  Run 2c_tedana_native_to_mni.sh first — this script does not "
                f"use TEDANA's native-space output directly."
            )
            return None

        matches = sorted(mni_dir.glob(ME_BOLD_GLOB))
        if len(matches) > 1:
            logging.warning(
                f"  Multiple MNI-normalized BOLD files found in {mni_dir}: "
                f"{[m.name for m in matches]} — using first match."
            )
        return matches[0] if matches else None


def check_fsl_available() -> bool:
    return shutil.which("fslmaths") is not None


def check_grids_match(bold_path: Path, mask_path: Path) -> tuple[bool, str]:
    """
    Compare BOLD and mask spatial dimensions before calling fslmaths, so a
    grid mismatch fails with a clear, specific message instead of an opaque
    fslmaths core dump. Returns (match, message).
    """
    try:
        import nibabel as nb
    except ImportError:
        # nibabel not available — skip the check rather than hard-failing
        # the whole script over a diagnostic-only dependency.
        return True, "nibabel not available — skipped grid check"

    bold_img = nb.load(str(bold_path))
    mask_img = nb.load(str(mask_path))

    bold_shape = bold_img.shape[:3]
    mask_shape = mask_img.shape[:3]

    if bold_shape != mask_shape:
        return False, (
            f"Grid mismatch: BOLD is {bold_shape} ({bold_path.name}), "
            f"mask is {mask_shape} ({mask_path.name}). "
            f"These must match exactly for masking to work. Common causes: "
            f"mask picked up from the wrong space (check MASK_SPACE_TAG), or "
            f"BOLD normalized to a different template/resolution than the mask."
        )

    return True, "Grids match"


def run_masking(bold_path: Path, mask_path: Path, out_path: Path) -> bool:
    """Run fslmaths -mas to produce a brain-masked BOLD image."""
    grids_ok, grid_msg = check_grids_match(bold_path, mask_path)
    if not grids_ok:
        logging.error(f"  {grid_msg}")
        return False

    cmd = ["fslmaths", str(bold_path), "-mas", str(mask_path), str(out_path)]
    logging.info(f"  Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"  fslmaths failed: {e.stderr}")
        return False


def process_file(confound_file: Path, output_dir: Path, input_dir: Path,
                 bold_dir: str | None, analysis_type: str, strategy: str,
                 mask_enabled: bool, cfg: dict, me_mni_subdir: str,
                 feat_output_enabled: bool, mask_space_tag: str) -> dict | None:
    """
    Extract confounds from one fMRIPrep TSV, and (if enabled) produce a
    matched masked BOLD image. Returns a summary dict on success, None on failure.
    """
    try:
        df = pd.read_csv(confound_file, sep="\t")
        logging.info(f"  Loaded: {confound_file.name}  ({df.shape[0]} TRs, {df.shape[1]} columns)")

        df, _ = ensure_motion_columns(df)

        columns = build_confound_columns(df, strategy, cfg)
        if not columns:
            logging.error("  No confound columns available — skipping.")
            return None

        matrix = df[columns].fillna(0.0)

        ana_tag  = "task" if analysis_type == "task" else "rest"

        # Default output: WITH header — deliberately avoids the ambiguity
        # that caused a real bug when headerless script output was fed into
        # naive header-detection downstream (see module docstring).
        out_path = unique_path(output_dir / f"{ana_tag}_{strategy}.txt")
        matrix.to_csv(out_path, sep="\t", index=False, header=True)

        feat_out_path = None
        if feat_output_enabled:
            feat_out_path = unique_path(output_dir / f"{ana_tag}_{strategy}_feat.txt")
            matrix.to_csv(feat_out_path, sep="\t", index=False, header=False)

        breakdown = {
            "motion":   sum(1 for c in columns if any(m in c for m in ("trans_", "rot_"))),
            "acompcor": sum(1 for c in columns if "a_comp_cor" in c),
            "cosine":   sum(1 for c in columns if "cosine" in c),
            "physio":   sum(1 for c in columns if c in ("csf", "white_matter", "global_signal")),
            "nss":      sum(1 for c in columns if "non_steady_state" in c),
        }
        logging.info(f"  \u2192 {out_path.name} (header)"
                     + (f"  +  {feat_out_path.name} (FEAT, no header)" if feat_out_path else "")
                     + f"  |  {len(columns)} regressors  "
                     f"| motion={breakdown['motion']} aCompCor={breakdown['acompcor']} "
                     f"cosines={breakdown['cosine']} physio={breakdown['physio']} nss={breakdown['nss']}")

        result = {"input": str(confound_file), "output": str(out_path),
                  "feat_output": str(feat_out_path) if feat_out_path else None,
                  "n_trs": df.shape[0], "n_regressors": len(columns), "breakdown": breakdown,
                  "masked_bold": None}

        # --- Masking ---
        if mask_enabled:
            prefix = get_prefix(confound_file)

            mask_path = find_mask(input_dir, prefix, mask_space_tag)
            if mask_path is None:
                logging.error(
                    f"  Could not find brain mask for prefix '{prefix}' with space "
                    f"tag '{mask_space_tag}' in {input_dir} — skipping masking. "
                    f"Check MASK_SPACE_TAG matches OUTPUT_SPACES used in 2a_run_fmriprep.sh."
                )
                return result

            bold_path = find_bold_to_mask(input_dir, bold_dir, prefix, me_mni_subdir)
            if bold_path is None:
                logging.error(f"  Could not find BOLD to mask for prefix '{prefix}' — skipping masking.")
                return result

            masked_out = unique_path(output_dir / f"{prefix}_desc-masked_bold.nii.gz")
            if masked_out.exists():
                logging.info(f"  Skipping masking — output already exists: {masked_out.name}")
                result["masked_bold"] = str(masked_out)
            else:
                logging.info(f"  Masking: {bold_path.name} with {mask_path.name}")
                if run_masking(bold_path, mask_path, masked_out):
                    logging.info(f"  \u2192 {masked_out.name}")
                    result["masked_bold"] = str(masked_out)
                else:
                    logging.error("  Masking failed.")

        return result

    except Exception:
        logging.exception(f"  Failed to process {confound_file.name}")
        return None


def process_directory(input_dir: str, bold_dir: str | None, output_dir: str,
                      analysis_type: str, strategy: str, mask_enabled: bool,
                      cfg: dict, me_mni_subdir: str, feat_output_enabled: bool,
                      mask_space_tag: str) -> dict:

    in_path  = Path(input_dir)
    out_path = Path(output_dir)

    if not in_path.exists():
        logging.error(f"Input directory not found: {input_dir}")
        sys.exit(1)

    if mask_enabled and not check_fsl_available():
        logging.error("Masking enabled but 'fslmaths' not found on PATH. "
                      "Make sure FSL is installed and sourced, or run with --no-mask.")
        sys.exit(1)

    if bold_dir is not None and not Path(bold_dir).exists():
        logging.error(f"BOLD directory not found: {bold_dir}")
        sys.exit(1)

    out_path.mkdir(parents=True, exist_ok=True)

    files = sorted(in_path.glob("*_desc-confounds_timeseries.tsv"))
    if not files:
        logging.warning(f"No confounds TSV files found in {input_dir}")
        return {}

    logging.info(f"Found {len(files)} confound file(s)\n")

    summary = {"total": len(files), "ok": 0, "failed": 0, "skipped": 0, "results": []}

    for f in files:
        logging.info(f"Processing: {f.name}")

        ana_tag  = "task" if analysis_type == "task" else "rest"
        check    = out_path / f"{ana_tag}_{strategy}.txt"

        if check.exists():
            logging.info(f"  Skipping — confound output already exists: {check.name}\n")
            summary["skipped"] += 1
            continue

        result = process_file(f, out_path, in_path, bold_dir, analysis_type, strategy,
                              mask_enabled, cfg, me_mni_subdir, feat_output_enabled,
                              mask_space_tag)
        if result:
            summary["ok"] += 1
            summary["results"].append(result)
        else:
            summary["failed"] += 1
        logging.info("")

    return summary


def running_on_cluster() -> bool:
    return any(v in os.environ for v in ("SGE_TASK_ID", "SLURM_JOB_ID", "PBS_JOBID", "LSB_JOBID"))


def submit_to_cluster(queue: str, memory_gb: int, output_dir: str) -> None:
    """
    Example submission via fsl_sub (our FMRIB cluster scheduler).
    #EDIT: replace with your own scheduler's submission command
    (e.g. sbatch/qsub) if not using fsl_sub.
    """
    log_dir = Path(output_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    script  = Path(__file__).resolve()
    passthrough = [a for a in sys.argv[1:] if a != "--use-cluster"]
    cmd = ["fsl_sub", "-q", queue, f"-R {memory_gb}", "-l", str(log_dir),
           "python3", str(script)] + passthrough
    logging.info(f"Submitting to cluster: {' '.join(cmd)}")
    subprocess.check_call(cmd)
    logging.info("Cluster submission successful — exiting.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract fMRIPrep confound regressors and produce a matched masked BOLD image",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument("--input-dir",      default=None, help="fMRIPrep func/ directory (confounds TSVs + mask live here)")
    parser.add_argument("--bold-dir",       default=None, help="TEDANA output root (ME branch only). Omit for SE.")
    parser.add_argument("--output-dir",     default=None, help="Output directory")
    parser.add_argument("--analysis-type",  default=None, choices=["task", "rest"])
    parser.add_argument("--strategy",       default=None,
                        choices=["conf24", "conf24_acompcor", "conf24_phy"])

    parser.add_argument("--global-signal",    action="store_true", default=None,
                        help="Include global signal regressor (explicit opt-in)")
    parser.add_argument("--no-global-signal", action="store_true", default=None,
                        help="Explicitly exclude global signal regressor (overrides CONFIG default)")
    parser.add_argument("--n-acompcor",     type=int, default=None,
                        help=f"Number of aCompCor components (default: {N_ACOMPCOR})")
    parser.add_argument("--no-nss",         action="store_true",
                        help="Exclude non-steady-state outlier regressors")

    parser.add_argument("--mask",           dest="mask_enabled", action="store_true", default=None,
                        help="Enable masking (default)")
    parser.add_argument("--no-mask",        dest="mask_enabled", action="store_false", default=None,
                        help="Disable masking — confounds only")

    parser.add_argument("--me-mni-subdir",  default=None,
                        help=f"Subfolder name under {{bold_dir}}/{{subject_id}}/ containing "
                             f"MNI-normalized TEDANA output from 2c_tedana_native_to_mni.sh "
                             f"(default: {ME_MNI_SUBDIR})")

    parser.add_argument("--mask-space-tag", default=None,
                        help=f"Space tag used to select the correct fMRIPrep brain mask "
                             f"(e.g. 'MNI152NLin2009cAsym_res-2') — must match OUTPUT_SPACES "
                             f"in 2a_run_fmriprep.sh (default: {MASK_SPACE_TAG})")

    parser.add_argument("--feat-output",    dest="feat_output_enabled", action="store_true", default=None,
                        help="Also produce a headerless FEAT-compatible confound file "
                             "({ana_tag}_{strategy}_feat.txt)")
    parser.add_argument("--no-feat-output", dest="feat_output_enabled", action="store_false", default=None,
                        help="Do not produce the FEAT-compatible file (default)")

    parser.add_argument("--use-cluster",    action="store_true")
    parser.add_argument("--queue",          default=CLUSTER_QUEUE)
    parser.add_argument("--memory-gb",      type=int, default=CLUSTER_MEMORY)

    parser.add_argument("--dry-run",        action="store_true")
    parser.add_argument("--log-level",      default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()

    input_dir     = args.input_dir     or INPUT_DIR
    bold_dir      = args.bold_dir      or BOLD_DIR
    output_dir    = args.output_dir    or OUTPUT_DIR
    analysis_type = args.analysis_type or ANALYSIS_TYPE
    strategy      = args.strategy      or STRATEGY
    mask_enabled  = args.mask_enabled  if args.mask_enabled is not None else MASK_ENABLED
    me_mni_subdir = args.me_mni_subdir or ME_MNI_SUBDIR
    mask_space_tag = args.mask_space_tag or MASK_SPACE_TAG
    feat_output_enabled = (args.feat_output_enabled if args.feat_output_enabled is not None
                           else FEAT_OUTPUT_ENABLED)

    if args.no_global_signal:
        global_signal = False
    elif args.global_signal:
        global_signal = True
    else:
        global_signal = INCLUDE_GLOBAL_SIGNAL

    cfg = {
        "global_signal": global_signal,
        "n_acompcor":    args.n_acompcor if args.n_acompcor is not None else N_ACOMPCOR,
        "include_nss":   not args.no_nss,
    }

    log_file = setup_logging(Path(output_dir), args.log_level)

    if args.use_cluster and not running_on_cluster():
        submit_to_cluster(args.queue, args.memory_gb, output_dir)
        return 0

    logging.info("=" * 65)
    logging.info("CONFOUND EXTRACTION + MASKING — CONFIGURATION")
    logging.info("=" * 65)
    logging.info(f"  Strategy      : {strategy}")
    logging.info(f"  Analysis type : {analysis_type}")
    logging.info(f"  Input dir     : {input_dir}")
    logging.info(f"  BOLD dir (ME) : {bold_dir or '(SE mode — BOLD found in input-dir)'}")
    if bold_dir:
        logging.info(f"  ME MNI subdir : {me_mni_subdir}  (expects {{bold_dir}}/{{subject}}/{me_mni_subdir}/)")
    logging.info(f"  Output dir    : {output_dir}")
    logging.info(f"  Masking       : {mask_enabled}")
    if mask_enabled:
        logging.info(f"  Mask space tag: {mask_space_tag}  (constrains which fMRIPrep mask is used)")
    logging.info(f"  FEAT output   : {feat_output_enabled}")
    logging.info(f"  Global signal : {cfg['global_signal']}")
    logging.info(f"  aCompCor N    : {cfg['n_acompcor']}  (used by conf24_acompcor)")
    logging.info(f"  NSS regressors: {cfg['include_nss']}")
    logging.info("=" * 65 + "\n")

    if analysis_type == "task" and strategy == "conf24_acompcor":
        logging.warning("conf24_acompcor includes cosine regressors which may correlate with "
                        "slow task designs — consider conf24 for task fMRI.")
    if analysis_type == "task" and cfg["global_signal"]:
        logging.warning("Global signal regression in task fMRI can remove BOLD signal "
                        "correlated with your design — ensure this is intentional.")

    if args.dry_run:
        files = sorted(Path(input_dir).glob("*_desc-confounds_timeseries.tsv"))
        logging.info(f"Dry run — {len(files)} file(s) found in {input_dir}:")
        for f in files:
            prefix = get_prefix(f)
            logging.info(f"  {f.name}")
            if mask_enabled:
                mask = find_mask(Path(input_dir), prefix, mask_space_tag)
                bold = find_bold_to_mask(Path(input_dir), bold_dir, prefix, me_mni_subdir)
                logging.info(f"    mask: {mask if mask else 'NOT FOUND'}")
                logging.info(f"    bold to mask: {bold if bold else 'NOT FOUND'}")
                if mask and bold:
                    grids_ok, grid_msg = check_grids_match(bold, mask)
                    logging.info(f"    grid check: {grid_msg}")
        return 0

    summary = process_directory(input_dir, bold_dir, output_dir, analysis_type, strategy,
                                mask_enabled, cfg, me_mni_subdir, feat_output_enabled,
                                mask_space_tag)

    logging.info("=" * 65)
    logging.info("SUMMARY")
    logging.info("=" * 65)
    logging.info(f"  Total files : {summary.get('total', 0)}")
    logging.info(f"  Successful  : {summary.get('ok', 0)}")
    logging.info(f"  Failed      : {summary.get('failed', 0)}")
    logging.info(f"  Skipped     : {summary.get('skipped', 0)}")
    logging.info(f"  Log file    : {log_file}")
    logging.info("=" * 65)

    return 0 if summary.get("failed", 0) == 0 else 3


if __name__ == "__main__":
    sys.exit(main())

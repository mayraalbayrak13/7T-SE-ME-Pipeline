#!/usr/bin/env python3
"""
run_tedana.py
==============
Runs TEDANA (multi-echo denoising) on native-space fMRIPrep echo outputs.

Finds multi-echo fMRIPrep outputs, reads EchoTimes from BIDS JSONs, and runs
tedana in native space as intended. Make sure BIDS folder does not have any part-phase images or their JSON files.

Dependencies:
  - tedana (pip install tedana — NOT installed automatically by this script;
    pin a version in your environment
  - FSL (only if using MASK_PATH="fmriprep" or a custom mask path — no FSL
    calls happen directly in this script, but masks are expected to come
    from fMRIPrep/FSL output)

Usage (submit to cluster; default action if USE_CLUSTER=True):
    python run_tedana.py

Usage (run processing directly on the current machine/node):
    python run_tedana.py --process

Usage (dry run to check file discovery without running tedana):
    python run_tedana.py --dry-run

Note on Custom Mask use
-------------------------------
By default, tedana auto-generates its own brain mask from the echo data.
We found this can drop signal in deep/inferior regions (e.g. VTA, brainstem)
under some acquisition conditions. Passing an explicit mask (typically
fMRIPrep's own brain mask) helps to avoid this. MASK_PATH below controls this:
  None        — let tedana auto-generate its mask 
  "fmriprep"  — auto-locate subject's fMRIPrep brain mask
  "/path/..." — use one specific mask file for ALL subjects
"""

from __future__ import annotations
import os
import sys
import re
import json
import glob
import argparse
import traceback
from pathlib import Path
from datetime import datetime

# =====================================================
# CONFIGURATION — EDIT THIS SECTION
# =====================================================
CONFIG = {
    # --- Required paths ---
    "BIDS_DIR":     "/full/path/to/BIDS",                
    "FMRIPREP_DIR": "/full/path/to/fmriprep_output",      
    "OUTPUT_DIR":   "/full/path/to/tedana_output",        

    # --- Custom Mask (see note above) ---
    #EDIT: None is tedana's own default. If you see signal dropout in certain brain regions, try "fmriprep".
    "MASK_PATH": None,  # None | "fmriprep" | "/path/to/mask.nii.gz"
    "FMRIPREP_MASK_PATTERN": "*_desc-brain_mask.nii.gz",  # Edit if naming differs

    # --- TEDANA parameters ---
    "TEDANA_TREE": "minimal",
    # "minimal"             - most conservative
    # "kundu"               - standard tedana tree (balanced)
    # "kundu-decision-tree" - original Kundu tree (more aggressive)

    "TEDANA_TEDPCA": "kic",
    # "kic"   - Kundu's method (default, balanced)
    # "aic"   - Akaike Information Criterion (keeps MORE components)
    # "mdl"   - Minimum Description Length (keeps FEWER components)
    # "kundu" - original Kundu method

    "TEDANA_FITTYPE": "curvefit",
    # "curvefit" - non-linear curve fitting (default, more robust)
    # "loglin"   - log-linear fitting (faster, less robust)

    "TEDANA_GSCONTROL": None,
    # None       - no global signal regression (default)
    # [mir, gsr] - apply global signal methods (rarely needed)

    # --- File discovery ---
    # Native-space preprocessed echo files (no "space-" tag in filename)
    "ECHO_GLOB": "*_echo-*_desc-preproc_bold.nii.gz",
    "EXCLUDE_IF_CONTAINS": ["space-"],
    "OUTPUT_PREFIX_TASK": "rest",  #EDIT: cosmetic prefix for output filenames

    # --- Cluster settings ---
    "USE_CLUSTER": True,  #EDIT: if True, submits via fsl_sub unless --process is used
    "QUEUE": "short",     #EDIT: adapt to your scheduler's queue naming
    "MEMORY_GB": 48,      

    "LOG_DIR": "logs",  #created inside OUTPUT_DIR
}

# =====================================================
# LOGGING & UTILITIES
# =====================================================
def log_print(*args, **kwargs):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}]", *args, **kwargs)
    sys.stdout.flush()

def eprint(*args, **kwargs):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] ERROR:", *args, file=sys.stderr, **kwargs)
    sys.stderr.flush()

def ensure_dir(p: str | Path) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p

def check_paths(cfg: dict) -> None:
    """Ensure required directories exist and are accessible."""
    log_print("Checking required paths...")
    for key in ["FMRIPREP_DIR", "BIDS_DIR", "OUTPUT_DIR"]:
        path = cfg[key]
        log_print(f"  {key}: {path}")
        if not Path(path).exists():
            eprint(f"Required path not found for {key}: {path}")
            sys.exit(1)
        log_print(f"  \u2713 {key} exists")

def find_native_echoes(cfg: dict) -> list[Path]:
    """Find native-space echo files."""
    log_print("Searching for native-space echo files...")
    pattern = os.path.join(cfg["FMRIPREP_DIR"], "**", cfg["ECHO_GLOB"])
    log_print(f"  Search pattern: {pattern}")

    candidates = glob.glob(pattern, recursive=True)
    log_print(f"  Found {len(candidates)} candidate files")

    out = []
    excluded = []
    for f in candidates:
        name = os.path.basename(f)
        if any(tag in name for tag in cfg["EXCLUDE_IF_CONTAINS"]):
            excluded.append(name)
            continue
        if "_echo-" in name:
            out.append(Path(f))
            log_print(f"    \u2713 {name}")
        else:
            log_print(f"    - {name} (no _echo- pattern)")

    if excluded:
        log_print(f"  Excluded {len(excluded)} files containing {cfg['EXCLUDE_IF_CONTAINS']}")
        for ex in excluded[:3]:
            log_print(f"    - {ex}")

    log_print(f"  Final count: {len(out)} native echo files")
    return sorted(out)

def group_by_acquisition(echo_files: list[Path]) -> dict[str, list[Path]]:
    """Group echo files by acquisition prefix (everything before '_echo-')."""
    log_print("Grouping echo files by acquisition...")
    groups = {}
    for p in echo_files:
        m = re.search(r"(.*)_echo-", p.name)
        if not m:
            eprint(f"Skipping file without expected '_echo-' pattern: {p.name}")
            continue
        acq = m.group(1)
        groups.setdefault(acq, []).append(p)

    for k in groups:
        groups[k] = sorted(groups[k])
        log_print(f"  {k}: {len(groups[k])} echoes")

    return groups

def find_bids_jsons_for_acq(bids_dir: str | Path, acq_prefix: str) -> list[Path]:
    pattern = os.path.join(str(bids_dir), "**", f"*{acq_prefix}*_bold.json")
    results = [Path(p) for p in glob.glob(pattern, recursive=True)]
    log_print(f"    Found {len(results)} JSON files for {acq_prefix}")
    return results

def read_echo_times_ms(json_paths: list[Path]) -> list[float]:
    echo_times = []
    for jp in json_paths:
        try:
            with open(jp, "r") as f:
                data = json.load(f)
            et = data.get("EchoTime", None)
            if et is None:
                raise ValueError("EchoTime missing from JSON")
            echo_time_ms = float(et) * 1000.0
            echo_times.append(echo_time_ms)
            log_print(f"      {jp.name}: {echo_time_ms:.1f}ms")
        except Exception as exc:
            eprint(f"Reading EchoTime from {jp}: {exc}")
            return []

    echo_times.sort()
    return echo_times

def extract_subject_id(acq_prefix: str) -> str | None:
    m = re.search(r"(sub-[^_]+)", acq_prefix)
    return m.group(1) if m else None

def find_mask_for_subject(cfg: dict, subject_id: str, echo_path: Path) -> str | None:
    """Resolve MASK_PATH ('fmriprep', explicit path, or None) into an actual file."""
    mask_setting = cfg["MASK_PATH"]

    if mask_setting is None:
        log_print("  Using tedana auto-generated mask")
        return None

    if mask_setting == "fmriprep":
        mask_pattern = cfg["FMRIPREP_MASK_PATTERN"]
        search_dir = echo_path.parent
        mask_files = list(search_dir.glob(mask_pattern))

        if not mask_files:
            search_dir = echo_path.parent.parent
            mask_files = list(search_dir.glob(mask_pattern))

        if mask_files:
            mask_path = str(mask_files[0])
            log_print(f"  Using fMRIPrep mask: {Path(mask_path).name}")
            return mask_path
        else:
            eprint(f"  Could not find fMRIPrep mask matching '{mask_pattern}' for {subject_id}")
            eprint(f"  Searched in: {search_dir}")
            return None

    # explicit path
    if Path(mask_setting).exists():
        log_print(f"  Using custom mask: {mask_setting}")
        return str(mask_setting)
    else:
        eprint(f"  Mask file not found: {mask_setting}")
        return None

# =====================================================
# PROCESSING
# =====================================================
def test_tedana_import() -> bool:
    """Confirm tedana is installed before doing anything else."""
    try:
        import tedana
        log_print(f"\u2713 tedana imported successfully (version: {getattr(tedana, '__version__', 'unknown')})")
        return True
    except ImportError:
        eprint(
            "tedana is not installed. Install it before running this script:\n"
            "  pip install tedana\n"
            "(pin a version in your environment for reproducibility)"
        )
        return False
    except Exception as exc:
        eprint(f"Failed to import tedana: {exc}")
        return False

def expected_output_exists(out_dir: Path, prefix: str) -> Path | None:
    """Check whether this acquisition's tedana output already exists."""
    candidate = out_dir / f"{prefix}_desc-denoised_bold.nii.gz"
    return candidate if candidate.exists() else None

def run_tedana_for_acq(acq_prefix: str, echo_paths: list[Path], echo_times_ms: list[float], cfg: dict) -> bool:
    """Run tedana for one acquisition."""
    log_print(f"Processing acquisition: {acq_prefix}")

    try:
        from tedana import workflows
    except Exception as exc:
        eprint(f"Failed to import tedana workflows: {exc}")
        return False

    sub = extract_subject_id(acq_prefix)
    if not sub:
        eprint(f"Could not determine subject ID from prefix: {acq_prefix}")
        return False

    if len(echo_paths) != len(echo_times_ms):
        eprint(f"Mismatch for {acq_prefix}: {len(echo_paths)} echo files vs {len(echo_times_ms)} echo times")
        return False

    for i, echo_path in enumerate(echo_paths):
        if not echo_path.exists():
            eprint(f"Echo file does not exist: {echo_path}")
            return False
        try:
            file_size = echo_path.stat().st_size
            log_print(f"  Echo {i+1}: {echo_path.name} ({file_size/1e6:.1f}MB)")
        except Exception as exc:
            eprint(f"Cannot read echo file {echo_path}: {exc}")
            return False

    mask_path = find_mask_for_subject(cfg, sub, echo_paths[0])

    out_dir = Path(cfg["OUTPUT_DIR"]) / sub
    ensure_dir(out_dir)
    log_print(f"  Output directory: {out_dir}")

    clean_sub = sub.replace("sub-", "")
    prefix = f"sub-{clean_sub}_task-{cfg['OUTPUT_PREFIX_TASK']}_space-Native"
    log_print(f"  Output prefix: {prefix}")

    existing = expected_output_exists(out_dir, prefix)
    if existing:
        log_print(f"  Skipping — output already exists: {existing}")
        return True

    log_print(f"\n  TEDANA PARAMETERS:")
    log_print(f"    Decision tree:  {cfg['TEDANA_TREE']}")
    log_print(f"    TEDPCA method:  {cfg['TEDANA_TEDPCA']}")
    log_print(f"    Fit type:       {cfg['TEDANA_FITTYPE']}")
    log_print(f"    GS control:     {cfg['TEDANA_GSCONTROL']}")
    log_print(f"    Mask:           {'Auto-generated' if mask_path is None else Path(mask_path).name}")

    try:
        log_print(f"\n  Running tedana with {len(echo_paths)} echoes...")
        log_print(f"    Echo times (ms): {echo_times_ms}\n")

        workflows.tedana_workflow(
            [str(p) for p in echo_paths],
            echo_times_ms,
            out_dir=str(out_dir),
            prefix=prefix,
            mask=mask_path,
            tree=cfg["TEDANA_TREE"],
            tedpca=cfg["TEDANA_TEDPCA"],
            fittype=cfg["TEDANA_FITTYPE"],
            gscontrol=cfg["TEDANA_GSCONTROL"],
            verbose=True,
        )
        log_print(f"\u2713 tedana completed successfully for {acq_prefix}")
        return True
    except Exception as exc:
        eprint(f"tedana failed for {acq_prefix}: {exc}")
        eprint("Full traceback:")
        traceback.print_exc()
        return False

def dry_run(cfg: dict) -> int:
    """Check file discovery and mask resolution without running tedana."""
    log_print("=== DRY RUN MODE ===")

    echo_files = find_native_echoes(cfg)
    if not echo_files:
        eprint("No native-space echo files found")
        return 2

    groups = group_by_acquisition(echo_files)
    if not groups:
        eprint("Found echo files but could not group by acquisition prefixes")
        return 3

    for acq_prefix, echo_paths in groups.items():
        log_print(f"\nChecking acquisition: {acq_prefix}")

        jsons = find_bids_jsons_for_acq(cfg["BIDS_DIR"], acq_prefix)
        if not jsons:
            eprint(f"  No matching BIDS JSONs found for '{acq_prefix}'")
            continue

        echo_times_ms = read_echo_times_ms(jsons)
        if not echo_times_ms:
            eprint(f"  No valid EchoTime values found for '{acq_prefix}'")
            continue

        sub = extract_subject_id(acq_prefix)
        find_mask_for_subject(cfg, sub, echo_paths[0])

        log_print(f"  \u2713 Ready for processing: {len(echo_paths)} echoes, {len(echo_times_ms)} echo times")

    log_print("\n=== DRY RUN COMPLETE ===")
    return 0

def process_all(cfg: dict) -> int:
    log_print("=== STARTING TEDANA PROCESSING ===")
    log_print(f"Python version: {sys.version}")

    log_print("\n=== CONFIGURATION ===")
    log_print(f"Decision tree: {cfg['TEDANA_TREE']}")
    log_print(f"TEDPCA method: {cfg['TEDANA_TEDPCA']}")
    log_print(f"Mask strategy: {cfg['MASK_PATH']}")
    log_print("=" * 50 + "\n")

    if not test_tedana_import():
        return 1

    echo_files = find_native_echoes(cfg)
    if not echo_files:
        eprint("No native-space echo files found. Expected files like "
               "'*_echo-1_desc-preproc_bold.nii.gz' WITHOUT a 'space-' tag.")
        return 2

    groups = group_by_acquisition(echo_files)
    if not groups:
        eprint("Found echo files but could not group by acquisition prefixes.")
        return 3

    success_count = 0
    total_count = len(groups)

    for acq_prefix, echo_paths in groups.items():
        log_print(f"\n--- Processing {acq_prefix} ---")

        jsons = find_bids_jsons_for_acq(cfg["BIDS_DIR"], acq_prefix)
        if not jsons:
            eprint(f"No matching BIDS JSONs found for acquisition '{acq_prefix}'")
            continue

        echo_times_ms = read_echo_times_ms(jsons)
        if not echo_times_ms:
            eprint(f"No valid EchoTime values found in JSONs for '{acq_prefix}'")
            continue

        success = run_tedana_for_acq(acq_prefix, echo_paths, echo_times_ms, cfg)
        if success:
            success_count += 1

    log_print(f"\n=== PROCESSING COMPLETE ===")
    log_print(f"Successful: {success_count}/{total_count} acquisitions")

    return 0 if success_count == total_count else 4

# =====================================================
# CLUSTER SUBMISSION
# =====================================================
def submit_self_via_fsl_sub(cfg: dict, script_path: Path) -> int:
    """
    Example submission via fsl_sub (our FMRIB cluster scheduler).
    #EDIT: replace with your own scheduler's submission command
    (e.g. sbatch/qsub) if not using fsl_sub.
    """
    log_dir = ensure_dir(Path(cfg["OUTPUT_DIR"]) / cfg["LOG_DIR"])
    queue = cfg["QUEUE"]
    memory = cfg["MEMORY_GB"]

    cmd = [
        "fsl_sub",
        "-q", queue,
        "-R", str(memory),
        "-l", str(log_dir),
        "bash", "-c",
        f"cd {os.getcwd()} && python3 {str(script_path)} --process"
    ]

    log_print(f"Submitting job with command: {' '.join(cmd)}")
    log_print(f"  Memory requested: {memory}GB")

    try:
        import subprocess
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        job_id = result.stdout.strip()
        log_print(f"\u2713 Job submitted successfully: {job_id}")
        log_print(f"  Logs will be written to: {log_dir}")
        return 0
    except subprocess.CalledProcessError as e:
        eprint(f"fsl_sub command failed with return code {e.returncode}")
        eprint(f"  stdout: {e.stdout}")
        eprint(f"  stderr: {e.stderr}")
        return 1
    except Exception as exc:
        eprint(f"Cluster submission failed: {exc}")
        return 1

# =====================================================
# MAIN
# =====================================================
def main():
    ap = argparse.ArgumentParser(description="TEDANA native-space pipeline (multi-echo denoising).")
    ap.add_argument("--process", action="store_true", help="Run processing now (intended for compute node).")
    ap.add_argument("--dry-run", action="store_true", help="Check file discovery without running tedana.")
    args = ap.parse_args()

    log_print("=== TEDANA PIPELINE STARTING ===")

    try:
        check_paths(CONFIG)
        ensure_dir(CONFIG["OUTPUT_DIR"])
    except Exception as exc:
        eprint(f"Setup failed: {exc}")
        sys.exit(1)

    if args.dry_run:
        sys.exit(dry_run(CONFIG))

    if args.process or not CONFIG["USE_CLUSTER"]:
        try:
            code = process_all(CONFIG)
            log_print("=== PIPELINE FINISHED ===")
            sys.exit(code)
        except Exception as exc:
            eprint(f"Processing failed with unexpected error: {exc}")
            traceback.print_exc()
            sys.exit(1)

    script_path = Path(__file__).resolve()
    try:
        rc = submit_self_via_fsl_sub(CONFIG, script_path)
        sys.exit(rc)
    except Exception as exc:
        eprint(f"Submission failed: {exc}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

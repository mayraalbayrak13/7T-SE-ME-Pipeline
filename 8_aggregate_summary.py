#!/usr/bin/env python3
"""
8_aggregate_summary.py
========================
Aggregates SE and ME branch outputs (tSNR, motion QC, LR/QC correlations,
AR(1), TEDANA component summary, and acquisition parameters from BOLD JSON
sidecars) into one comparison table, plus a separate long-format AR(1)
table and a set of simimple comparison plots.

Reads only and does not modify anything upstream. Missing inputs are
reported clearly and filled as NA rather than causing a hard failure, so
this can be run and re-run as pipeline stages complete (e.g. run with just
SE filled in while ME is still processing).

All paths below OTHER than 'root', 'bold_json', and 'final_bold' are
derived automatically from 'root', following the fixed folder structure
used throughout this pipeline:
  {root}/analysis_output/tsnr/tsnr_stats.csv
  {root}/analysis_output/correlation/correlation_summary_{label}.csv
  {root}/qc_checks/motion_qc/motion_qc_summary.csv
  {root}/qc_checks/qc_correlations/qc_correlation_summary_{label}.csv
  {root}/qc_checks/temporal_autocorr/ar1_timeseries.tsv
  {root}/qc_checks/tedana_component_summary.csv   (ME only)

'label' (used to find branch-specific correlation files, and shown in
plots/tables) is auto-derived from the root folder name  e.g.
"SE_processing" -> "SE", "SE_SCAN" -> "SE_SCAN". No manual label needed.

Usage:
  1. Fill in BRANCHES below with real paths for whichever branch(es) you
     currently have processed  SE only, ME only, or both.
  2. Optional: fill in "manual_te_ms" per branch if EchoTime isn't found
     in the BOLD JSON (e.g. some SE JSONs don't carry it) overrides
     whatever JSON parsing found, or fills the field if it was NA.
  3. Run: python3 8_aggregate_summary.py
  4. Output: comparison_summary.csv, ar1_comparison.csv, and plots/ under
     OUTPUT_DIR.

Dependencies: pandas, nibabel, matplotlib
"""

import sys
import json
import re
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# =============================================================================
# CONFIGURATION  EDIT HERE
# =============================================================================

ROI_NAMES = ["M1", "V1", "VTA", "VTASN", "VS"]  #EDIT if using different masks (excludes CC, the reference)

# #EDIT: fill in whichever branch(es) you currently have data for.
BRANCHES = {
    "SE": {
        "root": "/path/to/SE_branch",  #EDIT
        "bold_json": [
            "/path/to/fmriprep_output/sub-*/func/*_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.json",  #EDIT, full path/name
        ],
        "final_bold": "/path/to/confound_regression_output/regressed_bold.nii.gz",  #EDIT
    },
    "ME": {
        "root": "",  #EDIT
        "bold_json": [
            "",  #EDIT
            "",  #EDIT
            "",  #EDIT
        ],
        "final_bold": "",  #EDIT
    },
}

OUTPUT_DIR = "/path/to/comparison_summary"  #EDIT

# =============================================================================
# END CONFIGURATION
# =============================================================================


def warn(msg: str) -> None:
    print(f"  WARNING: {msg}")


def derive_label(root: Path) -> str:
    """Auto-derive a short label from the branch root folder name
    (e.g. 'SE_processing' -> 'SE', 'SE_SCAN' -> 'SE_SCAN')."""
    name = root.name
    stripped = re.sub(r"_processing$", "", name)
    return stripped


def read_bold_json_params(json_paths: list[str]) -> dict:
    """
    Reads RepetitionTime (assumed identical across echoes) and EchoTime
    (one per echo  comma-joined if multiple) from BOLD JSON sidecars.
    Missing files/keys are reported and filled with NA rather than failing.
    """
    tr = None
    echo_times = []

    for jp in json_paths:
        p = Path(jp)
        if not p.exists():
            warn(f"BOLD JSON not found: {p}")
            continue
        with open(p) as f:
            meta = json.load(f)

        if tr is None:
            tr = meta.get("RepetitionTime")
            if tr is None:
                warn(f"RepetitionTime not found in {p.name}")

        et = meta.get("EchoTime")
        if et is None:
            warn(f"EchoTime not found in {p.name}")
        else:
            echo_times.append(round(et * 1000, 2))  # seconds -> ms

    return {
        "tr_sec": tr if tr is not None else "NA",
        "te_ms": ",".join(str(t) for t in echo_times) if echo_times else "NA",
    }


def read_n_vols(bold_path: str) -> str:
    p = Path(bold_path)
    if not p.exists():
        warn(f"Final BOLD not found (skipping n_vols): {p}")
        return "NA"
    try:
        import nibabel as nb
        img = nb.load(str(p))  # header-only read, does not load full data into memory
        return img.shape[3] if len(img.shape) >= 4 else "NA"
    except Exception as e:
        warn(f"Could not read n_vols from {p}: {e}")
        return "NA"


def read_tsnr(root: Path) -> dict:
    path = root / "analysis_output" / "tsnr" / "tsnr_stats.csv"
    if not path.exists():
        warn(f"tSNR CSV not found: {path}")
        return {"tsnr_mean": "NA", "tsnr_std": "NA", "tsnr_median": "NA"}
    df = pd.read_csv(path)
    row = df.iloc[0]
    return {
        "tsnr_mean": row.get("mean_tsnr", "NA"),
        "tsnr_std": row.get("std_tsnr", "NA"),
        "tsnr_median": row.get("median_tsnr", "NA"),
    }


def read_motion_qc(root: Path) -> str:
    path = root / "qc_checks" / "motion_qc" / "motion_qc_summary.csv"
    if not path.exists():
        warn(f"Motion QC CSV not found: {path}")
        return "NA"
    df = pd.read_csv(path)
    valid = df[df["mean_fd_mm"] != "NA"]
    if valid.empty:
        warn(f"No valid mean_fd_mm values in {path}")
        return "NA"
    vals = pd.to_numeric(valid["mean_fd_mm"], errors="coerce").dropna()
    if len(vals) == 0:
        return "NA"
    if len(vals) > 1:
        warn(f"Multiple motion QC rows found in {path}  averaging {len(vals)} values")
    return round(vals.mean(), 4)


def read_correlations(root: Path, label: str) -> dict:
    """Returns {roi}_LR_corr and {roi}_vs_CC_corr for each ROI in ROI_NAMES."""
    result = {}

    lr_path = root / "analysis_output" / "correlation" / f"correlation_summary_{label}.csv"
    if lr_path.exists():
        lr_df = pd.read_csv(lr_path)
        for roi in ROI_NAMES:
            match = lr_df[lr_df["analysis"] == f"{roi}_LR"]
            result[f"{roi}_LR_corr"] = match["correlation"].iloc[0] if not match.empty else "NA"
    else:
        warn(f"LR correlation CSV not found: {lr_path}")
        for roi in ROI_NAMES:
            result[f"{roi}_LR_corr"] = "NA"

    qc_path = root / "qc_checks" / "qc_correlations" / f"qc_correlation_summary_{label}.csv"
    if qc_path.exists():
        qc_df = pd.read_csv(qc_path)
        for roi in ROI_NAMES:
            match = qc_df[qc_df["analysis"] == f"mean_{roi}_vs_mean_CC"]
            result[f"{roi}_vs_CC_corr"] = match["correlation"].iloc[0] if not match.empty else "NA"
    else:
        warn(f"QC (ROI-CC) correlation CSV not found: {qc_path}")
        for roi in ROI_NAMES:
            result[f"{roi}_vs_CC_corr"] = "NA"

    return result


def read_ar1(root: Path, label: str) -> pd.DataFrame:
    path = root / "qc_checks" / "temporal_autocorr" / "ar1_timeseries.tsv"
    if not path.exists():
        warn(f"AR1 file not found: {path}")
        return pd.DataFrame(columns=["branch", "roi", "ar1"])
    df = pd.read_csv(path, sep="\t")
    df = df.rename(columns={"ROI": "roi", "AR1": "ar1"})
    df.insert(0, "branch", label)
    return df


def read_tedana_summary(root: Path) -> dict:
    path = root / "qc_checks" / "tedana_component_summary.csv"
    if not path.exists():
        warn(f"TEDANA component summary CSV not found: {path}")
        return {
            "tedana_total_components": "NA",
            "tedana_pct_accepted": "NA",
            "tedana_variance_removed_pct": "NA",
        }
    df = pd.read_csv(path)
    row = df.iloc[0]
    return {
        "tedana_total_components": row.get("total_components", "NA"),
        "tedana_pct_accepted": row.get("pct_accepted", "NA"),
        "tedana_variance_removed_pct": row.get("variance_removed_pct", "NA"),
    }


def build_summary_table() -> tuple[pd.DataFrame, dict]:
    rows = []
    labels = {}
    for branch_key, cfg in BRANCHES.items():
        if not cfg["root"]:
            warn(f"Branch '{branch_key}' has no root configured yet  skipping")
            continue
        root = Path(cfg["root"])
        if not root.exists():
            warn(f"Branch root not found, skipping entirely: {root}")
            continue
        label = derive_label(root)
        labels[branch_key] = label
        print(f"\nProcessing branch: {branch_key} (label: {label})")
        row = {"branch": label}
        row.update(read_bold_json_params(cfg["bold_json"]))

        # Manual TE override  use if JSON parsing didn't find EchoTime
        # (e.g. SE JSONs that don't carry it), or if you just want to
        # enter it directly. Uses .get() so this key is optional in
        # BRANCHES config  leave it out or set to None/"" to skip.
        manual_te = cfg.get("manual_te_ms")
        if manual_te:
            row["te_ms"] = manual_te

        row["n_vols"] = read_n_vols(cfg["final_bold"])
        row.update(read_tsnr(root))
        row["mean_fd_mm"] = read_motion_qc(root)
        row.update(read_correlations(root, label))
        if branch_key == "ME":
            row.update(read_tedana_summary(root))
        else:
            row["tedana_total_components"] = "NA"
            row["tedana_pct_accepted"] = "NA"
            row["tedana_variance_removed_pct"] = "NA"
        rows.append(row)
    return pd.DataFrame(rows), labels


def build_ar1_table(labels: dict) -> pd.DataFrame:
    frames = []
    for branch_key, cfg in BRANCHES.items():
        if branch_key not in labels:
            continue
        frames.append(read_ar1(Path(cfg["root"]), labels[branch_key]))
    if not frames:
        return pd.DataFrame(columns=["branch", "roi", "ar1"])
    return pd.concat(frames, ignore_index=True)


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def make_plots(summary_df: pd.DataFrame, ar1_df: pd.DataFrame, plots_dir: Path) -> None:
    if summary_df.empty:
        warn("No branches processed successfully  skipping plots")
        return

    plots_dir.mkdir(parents=True, exist_ok=True)
    branches_present = list(summary_df["branch"])
    width = 0.35 if len(branches_present) > 1 else 0.6

    # --- tSNR comparison ---
    fig, ax = plt.subplots(figsize=(5, 4))
    vals = _numeric(summary_df.set_index("branch")["tsnr_mean"])
    ax.bar(vals.index, vals.values)
    ax.set_ylabel("Whole-brain tSNR (mean)")
    ax.set_title("tSNR comparison")
    fig.tight_layout()
    fig.savefig(plots_dir / "tsnr_comparison.png", dpi=150)
    plt.close(fig)

    # --- LR correlation grouped bar ---
    fig, ax = plt.subplots(figsize=(7, 4))
    x = range(len(ROI_NAMES))
    for i, label in enumerate(branches_present):
        vals = [_numeric(summary_df[summary_df["branch"] == label][f"{roi}_LR_corr"]).iloc[0] for roi in ROI_NAMES]
        offset = [xi + i * width for xi in x] if len(branches_present) > 1 else list(x)
        ax.bar(offset, vals, width, label=label)
    tick_pos = [xi + width / 2 for xi in x] if len(branches_present) > 1 else list(x)
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(ROI_NAMES)
    ax.set_ylabel("Left-Right correlation (r)")
    ax.set_title("ROI Left-Right correlation")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / "lr_correlation_comparison.png", dpi=150)
    plt.close(fig)

    # --- Mean-ROI-vs-CC grouped bar (QC) ---
    fig, ax = plt.subplots(figsize=(7, 4))
    for i, label in enumerate(branches_present):
        vals = [_numeric(summary_df[summary_df["branch"] == label][f"{roi}_vs_CC_corr"]).iloc[0] for roi in ROI_NAMES]
        offset = [xi + i * width for xi in x] if len(branches_present) > 1 else list(x)
        ax.bar(offset, vals, width, label=label)
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(ROI_NAMES)
    ax.set_ylabel("Correlation with mean CC (r)")
    ax.set_title("ROI vs Corpus Callosum correlation (QC)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / "roi_vs_cc_comparison.png", dpi=150)
    plt.close(fig)

    # --- AR(1) grouped bar ---
    if not ar1_df.empty:
        fig, ax = plt.subplots(figsize=(7, 4))
        rois = sorted(ar1_df["roi"].unique())
        xr = range(len(rois))
        ar1_branches = list(ar1_df["branch"].unique())
        ar1_width = 0.35 if len(ar1_branches) > 1 else 0.6
        for i, label in enumerate(ar1_branches):
            sub = ar1_df[ar1_df["branch"] == label].set_index("roi")
            vals = [_numeric(sub["ar1"]).get(r, float("nan")) for r in rois]
            offset = [xi + i * ar1_width for xi in xr] if len(ar1_branches) > 1 else list(xr)
            ax.bar(offset, vals, ar1_width, label=label)
        ar1_tick_pos = [xi + ar1_width / 2 for xi in xr] if len(ar1_branches) > 1 else list(xr)
        ax.set_xticks(ar1_tick_pos)
        ax.set_xticklabels(rois, rotation=45, ha="right")
        ax.set_ylabel("AR(1)")
        ax.set_title("Temporal autocorrelation (AR1) by ROI")
        ax.legend()
        fig.tight_layout()
        fig.savefig(plots_dir / "ar1_comparison.png", dpi=150)
        plt.close(fig)
    else:
        warn("No AR1 data available  skipping AR1 plot")

    # --- TEDANA accepted/rejected (ME only) ---
    me_rows = summary_df[summary_df["tedana_pct_accepted"] != "NA"]
    if not me_rows.empty:
        pct_accepted = float(me_rows["tedana_pct_accepted"].iloc[0])
        fig, ax = plt.subplots(figsize=(4, 4))
        ax.pie([pct_accepted, 100 - pct_accepted],
              labels=["Accepted", "Rejected"], autopct="%1.1f%%")
        ax.set_title("TEDANA component classification")
        fig.tight_layout()
        fig.savefig(plots_dir / "tedana_components.png", dpi=150)
        plt.close(fig)


def main():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_csv = output_dir / "comparison_summary.csv"
    ar1_csv = output_dir / "ar1_comparison.csv"

    if summary_csv.exists() or ar1_csv.exists():
        print(f"ERROR: Output already exists in {output_dir}\n"
              "Delete/rename existing files first, or change OUTPUT_DIR, then rerun.", file=sys.stderr)
        sys.exit(1)

    print("=== Building comparison summary ===")
    summary_df, labels = build_summary_table()

    if summary_df.empty:
        print("\nERROR: No branches were successfully processed  check BRANCHES paths above.", file=sys.stderr)
        sys.exit(1)

    summary_df.to_csv(summary_csv, index=False)
    print(f"\nSaved: {summary_csv}")

    print("\n=== Building AR(1) comparison table ===")
    ar1_df = build_ar1_table(labels)
    ar1_df.to_csv(ar1_csv, index=False)
    print(f"Saved: {ar1_csv}")

    print("\n=== Generating plots ===")
    make_plots(summary_df, ar1_df, output_dir / "plots")
    print(f"Saved plots to: {output_dir / 'plots'}")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()

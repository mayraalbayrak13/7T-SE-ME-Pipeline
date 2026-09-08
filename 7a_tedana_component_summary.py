#!/usr/bin/env python3
"""
7a_tedana_component_summary.py
=============================
Summarizes a TEDANA component metrics table (desc-tedana_metrics.tsv) into a plain-text report: 
- total ICA components
- accepted/rejected counts and proportions
- variance explained/removed by classification

"Variance removed" here means the summed 'variance explained' across all REJECTED components
(fraction of variance in the optimally combined data attributed to components tedana classified as noise)
This is read directly from the per-component metrics table TEDANA process outputs.

Also writes a machine-readable CSV sidecar (same name, .csv extension) alongside
the .txt report, for downstream scripts (e.g. 8_aggregate_summary.py) to read
structured values without parsing prose text.

Usage:
  python3 path/to/7a_tedana_component_summary.py \
      --metrics-tsv /path/to/tedana_output/sub-01_..._desc-tedana_metrics.tsv \
      --output /path/to/qc_checks/tedana_component_summary.txt

Dependencies: pandas
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

REQUIRED_COLUMNS = ["Component", "classification", "variance explained"]


def summarize(metrics_path: Path) -> dict:
    df = pd.read_csv(metrics_path, sep="\t")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Metrics file is missing expected column(s): {missing}\n"
            f"Found columns: {list(df.columns)}"
        )

    total = len(df)
    accepted = df[df["classification"] == "accepted"]
    rejected = df[df["classification"] == "rejected"]

    # Any classification other than accepted/rejected (e.g. "ignored", if
    # present in a given tedana version/tree) is flagged rather than silently
    # dropped from the counts.
    other = df[~df["classification"].isin(["accepted", "rejected"])]

    n_accepted = len(accepted)
    n_rejected = len(rejected)
    n_other = len(other)

    pct_accepted = 100 * n_accepted / total if total > 0 else float("nan")
    pct_rejected = 100 * n_rejected / total if total > 0 else float("nan")

    var_accepted = accepted["variance explained"].sum()
    var_rejected = rejected["variance explained"].sum()
    var_total = df["variance explained"].sum()

    tag_counts = None
    if "classification_tags" in df.columns:
        tag_counts = (
            rejected["classification_tags"]
            .dropna()
            .value_counts()
        )

    return {
        "total": total,
        "n_accepted": n_accepted,
        "n_rejected": n_rejected,
        "n_other": n_other,
        "pct_accepted": pct_accepted,
        "pct_rejected": pct_rejected,
        "var_accepted": var_accepted,
        "var_rejected": var_rejected,
        "var_total": var_total,
        "tag_counts": tag_counts,
    }


def write_report(stats: dict, metrics_path: Path, output_path: Path) -> None:
    lines = []
    lines.append("TEDANA Component Selection Summary")
    lines.append("=" * 40)
    lines.append(f"Date: {datetime.now():%Y-%m-%d %H:%M:%S}")
    lines.append(f"Source: {metrics_path}")
    lines.append("")
    lines.append(f"Total ICA components:      {stats['total']}")
    lines.append(f"Accepted:                  {stats['n_accepted']}  ({stats['pct_accepted']:.1f}%)")
    lines.append(f"Rejected:                  {stats['n_rejected']}  ({stats['pct_rejected']:.1f}%)")
    if stats["n_other"] > 0:
        lines.append(f"Other classification:      {stats['n_other']}  (not accepted or rejected — check manually)")
    lines.append("")
    lines.append("Variance explained (of optimally combined data):")
    lines.append(f"  Retained (accepted components):  {stats['var_accepted']:.2f}%")
    lines.append(f"  Removed (rejected components):   {stats['var_rejected']:.2f}%")
    lines.append(f"  Total (all components):          {stats['var_total']:.2f}%")
    lines.append("")
    lines.append("Note: 'variance removed' = sum of 'variance explained' across")
    lines.append("rejected components only — distinct from tedana's run-log figure")
    lines.append("'Variance explained by decomposition', which is the TOTAL across")
    lines.append("all components (accepted + rejected combined), not noise-specific.")

    if stats["tag_counts"] is not None and len(stats["tag_counts"]) > 0:
        lines.append("")
        lines.append("Rejection reasons (classification_tags, rejected components only):")
        for tag, count in stats["tag_counts"].items():
            lines.append(f"  {tag}: {count}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    print(f"\nSaved: {output_path}")


def write_csv(stats: dict, output_path: Path) -> None:
    """Machine-readable sidecar, same base name as the .txt report."""
    csv_path = output_path.with_suffix(".csv")

    row = {
        "total_components": stats["total"],
        "n_accepted": stats["n_accepted"],
        "n_rejected": stats["n_rejected"],
        "n_other": stats["n_other"],
        "pct_accepted": round(stats["pct_accepted"], 2),
        "pct_rejected": round(stats["pct_rejected"], 2),
        "variance_retained_pct": round(stats["var_accepted"], 2),
        "variance_removed_pct": round(stats["var_rejected"], 2),
        "variance_total_pct": round(stats["var_total"], 2),
    }

    df = pd.DataFrame([row])
    df.to_csv(csv_path, index=False)
    print(f"Saved: {csv_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metrics-tsv", required=True,
                        help="Path to TEDANA's desc-tedana_metrics.tsv")
    parser.add_argument("--output", required=True,
                        help="Path for the output summary .txt file (a matching .csv is also written)")
    args = parser.parse_args()

    metrics_path = Path(args.metrics_tsv)
    output_path = Path(args.output)
    csv_path = output_path.with_suffix(".csv")

    if not metrics_path.exists():
        print(f"ERROR: metrics file not found: {metrics_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        print(f"ERROR: Output already exists: {output_path}\n"
              "Delete/rename it first, or choose a different --output, then rerun.", file=sys.stderr)
        sys.exit(1)
    if csv_path.exists():
        print(f"ERROR: Output already exists: {csv_path}\n"
              "Delete/rename it first, or choose a different --output, then rerun.", file=sys.stderr)
        sys.exit(1)

    try:
        stats = summarize(metrics_path)
        write_report(stats, metrics_path, output_path)
        write_csv(stats, output_path)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

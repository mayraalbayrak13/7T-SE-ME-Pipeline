#!/usr/bin/env Rscript
# ===============================================================
# 6_run_correlations.R
# ===============================================================
# ROI-to-ROI correlation/QC analysis (left-right and mean-ROI-vs-mean-CC).
#
# This script is intentionally specific to this project's own ROI set
# (CC, M1, V1, VTA, VTASN, VS) and analysis structure (left-right symmetry
# checks, mean-ROI-vs-mean-CC connectivity)
# If reusing for a different ROI set, update ROI_NAMES and the correlation logic below directly.
#
# Expects timeseries files named {roi}_timeseries.txt (one value per line), as produced by 5_extract_timeseries_tsnr.sh.
#
# Output is split into two locations:
#   Left-Right correlations      -> {analysis_output}/correlation
#   Mean-ROI-vs-mean-CC (QC)     -> {branch_root}/qc_checks/qc_correlations
#
# Pipeline label (used in output filenames/console text) is auto-derived
# from the branch folder name itself and nor manually set — avoids a label drifting out of sync with the actual path.
# ===============================================================

# -----------------------------
# CONFIGURATION - EDIT
# -----------------------------

# EDIT: one ts_dir per pipeline output you want correlations for — this is
# the timeseries folder produced by 5_extract_timeseries_tsnr.sh.
PIPELINE_RUNS <- list(
  list(ts_dir = "/path/to/analysis_output/timeseries"),  #EDIT
  list(ts_dir = "/path/to/analysis_output/timeseries")   #EDIT
)

ROI_NAMES <- c("CC", "M1", "V1", "VTA", "VTASN", "VS")  #EDIT if using different masks
# -----------------------------
# -----------------------------

# --- Build ROI pairs (left/right per ROI, excluding CC which is the reference) ---
ROI_PAIRS <- list()
for (roi in ROI_NAMES) {
  if (roi != "CC") ROI_PAIRS[[roi]] <- c(paste0(roi, "_left"), paste0(roi, "_right"))
}
ALL_ROIS <- unlist(lapply(ROI_NAMES, function(roi) c(paste0(roi, "_left"), paste0(roi, "_right"))))

# --- Utility functions ---
load_timeseries <- function(roi_name, ts_dir) {
  path <- file.path(ts_dir, paste0(roi_name, "_timeseries.txt"))
  if (!file.exists(path)) {
    message("    WARNING: Missing ", path)
    return(NULL)
  }
  scan(path, what=numeric(), quiet=TRUE)
}

calculate_mean_timeseries <- function(roi_list, ts_dir) {
  all_data <- lapply(roi_list, load_timeseries, ts_dir=ts_dir)
  all_data <- Filter(Negate(is.null), all_data)
  if (length(all_data) == 0) return(NULL)
  lengths <- sapply(all_data, length)
  if (length(unique(lengths)) > 1) {
    message("    WARNING: Unequal timeseries lengths for ", paste(roi_list, collapse=", "))
    return(NULL)
  }
  rowMeans(do.call(cbind, all_data), na.rm=TRUE)
}

run_correlation <- function(x, y, name1, name2, label) {
  if (is.null(x) || is.null(y)) return(NULL)
  if (length(x) != length(y)) {
    message("    ERROR: Length mismatch ", name1, " vs ", name2)
    return(NULL)
  }
  rtest <- cor.test(x, y, method="pearson")
  r <- as.numeric(rtest$estimate); p <- rtest$p.value
  message(sprintf("    %-25s r=%0.3f p=%0.3g", label, r, p))
  list(analysis=label, roi1=name1, roi2=name2, r=r, p=p, n_timepoints=length(x))
}

write_results_block <- function(results, out_dir, label, title, filename_tag) {
  dir.create(out_dir, showWarnings=FALSE, recursive=TRUE)

  results_file <- file.path(out_dir, paste0(filename_tag, "_results_", label, ".txt"))
  sink(results_file)
  cat(title, "\n")
  cat(paste(rep("=", nchar(title)), collapse=""), "\n")
  cat("Pipeline:", label, "\n")
  cat("Date:", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "\n\n")

  if (length(results) == 0) {
    cat("  No correlations computed\n\n")
  } else {
    for (r in results) {
      cat("Analysis:", r$analysis, "\n")
      cat("  ROIs:", r$roi1, "vs", r$roi2, "\n")
      cat("  Correlation (r):", round(r$r, 4), "\n")
      cat("  P-value:", format(r$p, scientific=TRUE, digits=3), "\n")
      cat("  Timepoints:", r$n_timepoints, "\n\n")
    }
  }
  sink()
  cat("  \u2713 Results written:", results_file, "\n")

  csv_file <- file.path(out_dir, paste0(filename_tag, "_summary_", label, ".csv"))
  if (length(results) > 0) {
    df <- do.call(rbind, lapply(results, function(x) data.frame(
      pipeline = label,
      analysis = x$analysis,
      roi1 = x$roi1,
      roi2 = x$roi2,
      correlation = round(x$r, 4),
      p_value = x$p,
      n_timepoints = x$n_timepoints,
      stringsAsFactors = FALSE
    )))
    write.csv(df, csv_file, row.names = FALSE)
    cat("  \u2713 CSV summary written:", csv_file, "\n")
  }
}

# -----------------------------
# MAIN: iterate configured pipeline runs
# -----------------------------
for (run in PIPELINE_RUNS) {
  ts_dir <- run$ts_dir

  if (!dir.exists(ts_dir)) {
    cat("\n  Timeseries folder not found — skipping:", ts_dir, "\n")
    next
  }

  analysis_dir <- dirname(ts_dir)          # e.g. .../SE_processing/analysis_output
  branch_dir   <- dirname(analysis_dir)    # e.g. .../SE_processing

  # Auto-derive label from the branch folder name (e.g. "SE_processing" -> "SE")
  label <- sub("_processing$", "", basename(branch_dir))

  cat("\n====================================================\n")
  cat("=== PROCESSING PIPELINE:", label, "===\n")
  cat("Timeseries folder:", ts_dir, "\n")

  corr_out_dir <- file.path(analysis_dir, "correlation")
  qc_out_dir   <- file.path(branch_dir, "qc_checks", "qc_correlations")

  cat("LR correlation output:", corr_out_dir, "\n")
  cat("QC (ROI-CC) output:   ", qc_out_dir, "\n")

  lr_results <- list()
  mean_results <- list()

  # LEFT-RIGHT correlations (excluding CC)
  cat("\n  -- Left-Right correlations --\n")
  for (roi in names(ROI_PAIRS)) {
    pair <- ROI_PAIRS[[roi]]
    left_ts <- load_timeseries(pair[1], ts_dir)
    right_ts <- load_timeseries(pair[2], ts_dir)
    res <- run_correlation(left_ts, right_ts, pair[1], pair[2], paste0(roi, "_LR"))
    if (!is.null(res)) lr_results[[length(lr_results)+1]] <- res
  }

  # MEAN ROI vs MEAN CC correlations (QC)
  cat("\n  -- Mean ROI vs Mean CC correlations (QC) --\n")
  mean_cc <- calculate_mean_timeseries(c("CC_left","CC_right"), ts_dir)
  if (is.null(mean_cc)) {
    cat("    ERROR: Could not calculate mean CC timeseries; skipping mean-vs-CC correlations\n")
  } else {
    for (roi in names(ROI_PAIRS)) {
      mean_roi <- calculate_mean_timeseries(ROI_PAIRS[[roi]], ts_dir)
      res <- run_correlation(mean_roi, mean_cc, paste0("mean_", roi), "mean_CC", paste0("mean_", roi, "_vs_mean_CC"))
      if (!is.null(res)) mean_results[[length(mean_results)+1]] <- res
    }
  }

  if (length(lr_results) == 0 && length(mean_results) == 0) {
    cat("  No valid correlations calculated for", label, "\n")
    next
  }

  cat("\n")
  write_results_block(lr_results, corr_out_dir, label,
                      "Left-Right ROI Correlation Results", "correlation")

  cat("\n")
  write_results_block(mean_results, qc_out_dir, label,
                      "Mean ROI vs Mean CC Correlation Results (QC)", "qc_correlation")
}

cat("\n=== ALL DONE ===\n")

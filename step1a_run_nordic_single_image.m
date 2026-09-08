% =========================================================================
% NORDIC Denoising - Single Functional Image
% -------------------------------------------------------------------------
% Runs NORDIC thermal noise denoising (NIFTI_NORDIC) on one BOLD run.
%
% Dependencies:
%   - MATLAB (tested with R2020a+; needs Image Processing + Signal
%     Processing toolboxes, per NORDIC_Raw requirements)
%   - NORDIC_Raw repo: https://github.com/SteenMoeller/NORDIC_Raw
%
% Input requirements:
%   - Magnitude BOLD image (.nii.gz accepted directly)
%   - Phase BOLD image (.nii.gz accepted directly), same acquisition,
%     part-phase
%
% Output:
%   - Denoised image written to OUTPUT_DIR, named <fn_out>.nii
%     NOTE: NORDIC always outputs uncompressed .nii, regardless of input
%     format. Compress to .nii.gz afterward if replacing BIDS files
%     (gzip, or see later pipeline step).
% =========================================================================

set(0, 'DefaultFigureVisible', 'off');

%% #EDIT: paths — update these for your system and dataset
NORDIC_REPO_PATH = '/path/to/NORDIC_Raw';                    % location of cloned NORDIC_Raw repo
fn_magn_in       = '/path/to/bold';             % magnitude BOLD image
fn_phase_in      = '/path/to/part-phase';  % phase BOLD image
fn_out           = 'sub-01_nordic';                            % output filename (no extension)
OUTPUT_DIR       = '/path/to/nordic_output';                   % output folder (created if missing), differentiate between SE_processing or ME_processing when needed

%% Setup
if ~isfolder(NORDIC_REPO_PATH)
    error(['NORDIC_Raw repo not found at: %s\n' ...
           'Clone it from https://github.com/SteenMoeller/NORDIC_Raw ' ...
           'and update NORDIC_REPO_PATH above.'], NORDIC_REPO_PATH);
end
addpath(genpath(NORDIC_REPO_PATH));

% Check inputs exist before doing anything
if ~isfile(fn_magn_in)
    error('Magnitude input not found: %s', fn_magn_in);
end
if ~isfile(fn_phase_in)
    error('Phase input not found: %s', fn_phase_in);
end

% Ensure output directory exists (NORDIC does NOT create it)
if ~isfolder(OUTPUT_DIR)
    mkdir(OUTPUT_DIR);
    fprintf('Created output directory: %s\n', OUTPUT_DIR);
end

% Check whether output already exists — avoid silent overwrite
expected_output = fullfile(OUTPUT_DIR, [fn_out '.nii']);
if isfile(expected_output)
    error(['Output already exists: %s\n' ...
           'Delete/rename it first, or change fn_out, then rerun.'], expected_output);
end

%% NORDIC parameters
% See NORDIC_Raw documentation for full parameter descriptions:
% https://github.com/SteenMoeller/NORDIC_Raw
ARG.temporal_phase      = 1;   % phase filtering mode
ARG.phase_filter_width  = 10;  % width of temporal phase filter
ARG.DIROUT              = [OUTPUT_DIR filesep];  % trailing separator required —
                                                  % NORDIC concatenates this directly
                                                  % with fn_out, it does NOT treat
                                                  % this as a folder to join via fullfile

disp('Running NORDIC with parameters:');
disp(ARG);

%% Run
NIFTI_NORDIC(fn_magn_in, fn_phase_in, fn_out, ARG);

disp('NORDIC completed successfully.');
fprintf('Output written to: %s (.nii, uncompressed)\n', expected_output);

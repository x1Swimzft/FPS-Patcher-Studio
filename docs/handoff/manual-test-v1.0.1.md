# Manual Test Checklist — v1.0.1

**Status: ยังไม่ได้ตรวจ (not executed).** Every result cell is intentionally blank.
A human tester must run the steps and record PASS, FAIL or N/A plus notes.
Do not mark an item PASS from code inspection alone.

- **Branch:** `fix/v1.0.1`
- **Version under test:** metadata is still `1.0.0` until release approval; record the
  actual artifact name and SHA-256 below.
- **Scope:** the seven runtime settings wired in v1.0.1, two-stage Ctrl+C, updater
  response cleanup, readiness-label localization, and the v1.0.1 documentation fixes.
- **Reference tests:** `tests/test_settings_wired.py`,
  `tests/test_preflight_and_updater.py`, `tests/test_platform_profiles.py`,
  `tests/test_cli.py` and `tests/test_ffmpeg_lifecycle.py` (automated coverage; not a
  substitute for these steps).

## 1. Environment and build provenance

| # | Check / step | Expected | Result | Notes |
|---|---|---|---|---|
| E1 | Record Windows edition/version and architecture. | Windows 10/11 x64 recorded. | | |
| E2 | Record display scaling (100%, 125%, 150%, 200%). | Scaling recorded; test the shipped default first. | | |
| E3 | Record the artifact under test: installer or portable folder, file name, SHA-256. | Name and hash match `release/FPSPatcherStudio-v1.0.1.sha256` after the release build exists. | | |
| E4 | Record FFmpeg/ffprobe source and version. | Bundled or explicitly selected build recorded. | | |
| E5 | Start from a clean settings file (or note the existing settings used). | Settings path and starting state recorded. | | |

## 2. Settings wiring

Use a short real clip that patches successfully, plus one deliberately invalid file
for the `stop_on_error` case. Record the settings file path so results are reproducible.

### 2.1 `verify_after`

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| S1.1 | Enable `verify_after`, patch one clip. | Patch succeeds; verification messages appear in the activity log. | | |
| S1.2 | Disable `verify_after`, patch the same clip to a new output. | Patch succeeds; both post-patch verifier messages are absent. | | |
| S1.3 | Compare output playback/probe result with S1.1. | Output is still playable and has the expected stream metadata. | | |

### 2.2 `backup_original`

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| S2.1 | Create an output file, enable `backup_original`, patch to that exact destination. | Existing destination is copied to `<name>.bak` before replacement. | | |
| S2.2 | Run the same patch again with the same destination. | A new backup (`<name>.1.bak` or next free suffix) is created; the first `.bak` is unchanged. | | |
| S2.3 | Repeat with `backup_original` disabled and an existing destination. | No new `.bak` file is created. | | |
| S2.4 | Verify the backup bytes match the pre-patch destination. | SHA-256 of backup equals the original file. | | |

### 2.3 `stop_on_error`

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| S3.1 | Enable `stop_on_error`; queue one invalid file followed by valid files; start the batch. | Batch stops at the first failure; later files are not started. | | |
| S3.2 | Disable `stop_on_error`; run the same queue. | Remaining valid files are processed after the failure. | | |
| S3.3 | Repeat S3.1 from the CLI (`--cli patch ...`). | CLI returns 1 and does not process later inputs. | | |

### 2.4 `extra_ffmpeg_args`

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| S4.1 | Enter a harmless argument pair (for example `-threads 2`); patch a clip. | Patch succeeds; the extra arguments are passed before the output path (check the FFmpeg command log). | | |
| S4.2 | Enter an argument that only works as a separate token (for example `-metadata comment="manual test"`); patch a clip. | Argument is tokenised correctly; no shell is involved. | | |
| S4.3 | Enter malformed quoting (for example a lone `"`); attempt a patch. | Patch is rejected with a clear settings/argument error; no FFmpeg run starts and no output is written. | | |
| S4.4 | Enter shell metacharacters (for example `; calc`); attempt a patch. | Tokens are treated as FFmpeg arguments, not shell commands; no external program starts. | | |
| S4.5 | Clear the field and patch a clip. | Behavior matches the pre-v1.0.1 default. | | |

### 2.5 `log_to_file`

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| S5.1 | Enable `log_to_file`, start the app, run one patch, close the app. | A rotating log file is created/updated in the documented log location. | | |
| S5.2 | Disable `log_to_file`, restart, run one patch, close the app. | No new log file is created and the existing log is not appended to. | | |
| S5.3 | Repeat S5.1 from the CLI. | CLI honors the same setting. | | |

### 2.6 `confirm_overwrite`

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| S6.1 | Enable `confirm_overwrite`; patch a clip whose output already exists in the GUI. | A confirmation dialog names the affected file(s); Cancel leaves the existing output untouched. | | |
| S6.2 | Repeat and confirm. | The existing output is replaced (subject to `backup_original`). | | |
| S6.3 | Disable `confirm_overwrite`; patch over an existing output. | No prompt; replacement follows the other overwrite settings. | | |
| S6.4 | Enable `confirm_overwrite`; use `--quick-patch` on a file whose output exists. | No dialog blocks the unattended run; output is auto-renamed. | | |
| S6.5 | Enable `confirm_overwrite`; let the watch folder process a file whose output exists. | No dialog blocks the watcher; output is auto-renamed. | | |
| S6.6 | Run the CLI with `--overwrite` and with the default auto-rename. | `--overwrite` is treated as explicit consent; the default never overwrites. | | |

### 2.7 `notify_done`

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| S7.1 | Set `notify_done=none`; finish a manual batch and a watch batch. | No sound and no toast (default behavior). | | |
| S7.2 | Set `notify_done=sound`; finish a manual batch. | A system sound plays once. | | |
| S7.3 | Set `notify_done=toast`; finish a manual batch. | A toast appears with the batch summary (or is documented as suppressed by Windows). | | |
| S7.4 | Repeat S7.2 and S7.3 for a watch-folder batch. | The selected notification fires after the watch batch, not per file. | | |
| S7.5 | Cancel a manual batch with each mode; then cancel a watch batch. | Manual cancel fires no completion notification. Watch cancel may fire the watch-cancel notification when a mode is selected; record the observed behavior. | | |

### 2.8 `preserve_mtime` (known limitation)

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| S8.1 | Note that `preserve_mtime` remains persisted but unwired in v1.0.1. | No claim of working behavior; do not report a failure as a v1.0.1 regression. | | |

## 3. Two-stage Ctrl+C

Run the CLI from cmd/PowerShell with a clip long enough to observe FFmpeg. Keep Task
Manager (Details tab) open and filter for `ffmpeg`/`ffprobe`.

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| C1 | Start a patch; press Ctrl+C once. | Cancel is requested once; the run stops; exit code is 130. | | |
| C2 | After C1, inspect temp/output files. | `.part`/preflight temp files for that run are gone; the previous output is intact. | | |
| C3 | Start a patch; simulate a stuck child (or use the unresponsive-child test fixture); press Ctrl+C twice. | First press requests cancel; second press force-kills the process tree after the grace period. | | |
| C4 | After C3, check Task Manager and the output folder. | No surviving `ffmpeg`/`ffprobe` child; temp files cleaned; exit status is reported. | | |
| C5 | Press Ctrl+C while idle at the CLI prompt or after completion. | No crash; behavior matches the documented CLI contract. | | |

## 4. Updater error handling

HTTP status-specific closure is covered by automated tests; these steps check the
user-visible failure path.

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| U1 | Disconnect the network and run the update check. | A clear "update check failed" message; the app remains usable; no traceback dialog. | | |
| U2 | Restore the network and run the update check against a published release. | Update information is shown normally. | | |
| U3 | Use a release endpoint with no published release (HTTP 404). | Treated as "no update", not an error. | | |
| U4 | Simulate HTTP 403/500 or a timeout with a local test harness. | An `UpdateError` is shown; no leaked response/socket warning appears in logs. | | |

## 5. Readiness labels (English and Thai)

Select a profile with all checks available (TikTok is a good default) and use a clip
with known metadata.

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| L1 | Set language to English; hover the readiness badge. | All check labels are readable English names (Container, Video codec, Resolution / aspect ratio, Frame rate, Duration, File size, Audio, Bitrate, Color / HDR, Probe as applicable). | | |
| L2 | Click the badge and inspect the Activity Console lines. | Localized labels appear in the log; statuses remain translated. | | |
| L3 | Open the inspector readiness popover. | The same localized labels appear. | | |
| L4 | Switch to Thai without restarting; repeat L1–L3. | Every label is Thai; no raw `readiness_check_*` key is visible. | | |
| L5 | Remove probe data (or select a file while probing); inspect the `Probe` check. | The fallback/unknown label is localized; no key leaks. | | |

## 6. Documentation spot-check

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| D1 | Open `README.md` Getting Started. | Methods are ordered 1 (prebuilt), 2 (source), 3 (headless CLI). | | |
| D2 | Read the build-artifact names in `README.md`. | They use `v1.0.0`, not `v0.7.0` (update to `v1.0.1` only after the release build is approved). | | |
| D3 | Run the README ruff command. | `uv run ruff check src tests tools` passes. | | |
| D4 | Compare the README one-folder size with a fresh measurement. | 323,001,846 bytes / 308.0 MiB / 189 files, or the newly measured value is recorded honestly. | | |
| D5 | Search the Nuitka checklist and release notes for `--cli score`. | `score` is present in the CLI documentation. | | |
| D6 | Read the v1.0.1 CHANGELOG/RELEASE_NOTES sections. | Settings wiring, the `notify_done=none` default, and the `preserve_mtime` limitation are stated clearly. | | |

## 7. Core regression smoke

| # | Step | Expected | Result | Notes |
|---|---|---|---|---|
| R1 | Launch the app; switch theme and language. | Window is usable; no crash or missing translation. | | |
| R2 | Drag in a clip; probe it and check the readiness badge/popover. | Metadata and readiness render correctly. | | |
| R3 | Patch the clip with the default preset. | Output is created, playable and verified. | | |
| R4 | Test the watch folder with one new file. | Exactly one batch, one output, no backlog storm. | | |
| R5 | Install/uninstall the Explorer verb and quick-patch one file. | Verb works; output is correct; uninstall removes it. | | |
| R6 | Test 125% scaling (and 150%/200% if available). | No clipped controls or unreadable dialogs. | | |
| R7 | Close the app during/after a batch. | Clean shutdown; no orphaned child processes. | | |

## 8. Sign-off

| Field | Value |
|---|---|
| Tester | |
| Date | |
| Artifact / SHA-256 | |
| Windows build / scaling | |
| Overall result (PASS / FAIL) | |
| Blocking failures (IDs) | |
| Follow-up notes | |

**Rules:** one result per row; use N/A only when the step cannot run in the test
environment, and explain why. A row without a result is still **not verified**.

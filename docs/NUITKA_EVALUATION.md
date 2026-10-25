# Nuitka Evaluation (roadmap 4.1)

**Status: NOT RUN in this environment — script and checklist ready.**
**Date:** 2026-10-25 · **App version:** 1.0.0 · **Current release backend:** PyInstaller 6.x
(`build/fps_patcher.spec`, driven by `build/release.ps1`).

| Check | Result on this machine |
| --- | --- |
| Windows | yes |
| `cl.exe` on PATH | **no** |
| Visual Studio / Build Tools install | **none** (`vswhere.exe` absent, no `Program Files\Microsoft Visual Studio`) |
| PyInstaller | not installed in the project venv (`uv run --with pyinstaller` fetches it) |
| Inno Setup 7 | present (`C:\Program Files\Inno Setup 7\ISCC.exe`) |
| Nuitka build attempted | **no** — no C compiler, so no size, cold-start or AV number below is measured |

Nothing in this document is a measurement of the Qt build. Earlier revisions of this file
carried Tk-era numbers (`--enable-plugin=tk-inter`, CustomTkinter, "0 false positives",
"~32 MB", "0.4.0.0") that no longer describe this project; they have been removed.

## 1. Why Nuitka is on the roadmap

- Native C/C++ output instead of a PyInstaller bootloader + embedded bytecode.
- Harder to decompile.
- Standard MSVC PE headers, which is the usual argument for fewer heuristic AV hits.

The last point is **not a guarantee**: an unsigned Nuitka EXE can still be flagged, and
"0/70 on VirusTotal" is not something this project can promise. The real mitigation is
**Authenticode code signing** (see `docs/CODE_SIGNING_POLICY.md` and
`docs/SIGNPATH_APPLICATION.md`), independent of the packaging backend.

## 2. Qt-era compatibility notes

| Area | Concern | Handling |
| --- | --- | --- |
| PySide6 6.12 | Qt plugins (`platforms/qwindows.dll`, styles, imageformats) and `shiboken6` | `--enable-plugin=pyside6` (Nuitka's official plugin); verify the GUI starts, not just the CLI |
| App assets | `src/fps_patcher/ui/assets` (fonts/icons) resolved relative to the package | `--include-package-data=fps_patcher` + explicit `--include-data-dir` |
| Pillow | thumbnail decoding | normally auto-detected; check `thumbnails` on a real video |
| `ctypes` / `winreg` | DWM backdrop, Job Objects, Explorer verb, console attach | stdlib, no extra flags; test the registry verb on a real machine |
| `subprocess` | FFmpeg/FFprobe, PowerShell toast | external binaries are **not** bundled; FFmpeg is located at runtime as today |
| Tcl/Tk | removed from the project in the Qt cutover | no `tk-inter` plugin, no Tk data |

The current PyInstaller spec excludes Tcl/Tk/CustomTkinter/TkinterDnD2/pywinstyles; the
Nuitka script does not need those exclusions because the dependencies are gone.

## 3. Build script (separate from the release pipeline)

`build/build_nuitka.ps1`:

- dry run by default (prints the exact command and exits 0); without MSVC it prints the
  command and exits 3 so automation can tell "not run" from "ran";
- `-Run` builds, `-SkipSmokeTest` skips the 6-second launch check;
- fetches Nuitka with `uv run --with nuitka --with zstandard`, so `pyproject.toml`,
  `uv.lock` and the PyInstaller spec are untouched (reversible by deleting `dist\nuitka`);
- output: `dist\nuitka\FPSPatcherStudio.dist\`, not `dist\FPSPatcherStudio` and never `release\`;
- refuses to fall back to MinGW — a MinGW PE is not the artifact this evaluation is about;
- reads the version from `src/fps_patcher/__init__.py` (no duplicated version literal);
- `--windows-console-mode=disable` keeps the windowed GUI; the CLI reattaches to the parent
  console (`src/fps_patcher/cli.py::attach_console`).

```powershell
powershell -ExecutionPolicy Bypass -File build\build_nuitka.ps1        # dry run
powershell -ExecutionPolicy Bypass -File build\build_nuitka.ps1 -Run   # real build
```

## 4. Checklist for a machine with MSVC

1. Install **Build Tools for Visual Studio 2022** → workload *Desktop development with C++*
   (MSVC v143 + Windows 10/11 SDK). Open *x64 Native Tools Command Prompt for VS 2022*.
2. `powershell -ExecutionPolicy Bypass -File build\build_nuitka.ps1 -Run`
3. Record the real wall-clock build time (cold and warm) — do not reuse the old 6–15 min claim.
4. Launch `dist\nuitka\FPSPatcherStudio.dist\FPSPatcherStudio.exe`:
   - main window appears, theme applies, queue row paints;
   - add a clip, probe, readiness badge and inspector popover work;
   - patch one real clip end-to-end (FFmpeg located, output verified);
   - `--quick-patch <clip>` from Explorer and from a terminal;
   - `--cli probe <clip> --json` and `--cli patch <clip> --json` print to the parent console;
   - watch folder switch + Explorer verb install/uninstall on a real account;
   - toast appears (or is documented as suppressed by Windows).
5. Measure: on-disk size of the `.dist` folder, cold-start to usable window (3 runs, median),
   peak RSS during a patch, and compare against the PyInstaller `dist\FPSPatcherStudio`.
6. Scan the **unsigned** binary on VirusTotal only as a diagnostic. Record the exact
   date/engine count; never publish "0/70". Re-scan after signing.

## 5. Decision rule and current decision

Switch the release pipeline to Nuitka only if **all** of the following hold:

1. every smoke test in §4 passes on a clean Windows 10/11 machine;
2. a real patch, quick-patch and CLI run succeed from the Nuitka build;
3. the build is reproducible on CI or a documented workstation, and the PyInstaller
   fallback still exists until a signed Nuitka release has shipped once;
4. size/cold-start are not materially worse than PyInstaller (record the numbers).

**Decision today: keep PyInstaller.** Nuitka has not been built or measured here, so the
first condition cannot be met. This is a "not evaluated", not a "failed" result. The script
and checklist make the evaluation repeatable when a machine with MSVC is available.

## 6. Known risks if Nuitka is adopted later

- PySide6 plugin coverage can lag Qt releases; pin `pyside6==6.12.0` (already pinned).
- Cold builds are much slower than PyInstaller; release.ps1 assumes a <1 minute build.
- `--standalone` folder layout differs, so `installer.iss` and the ZIP step would need a
  `-Backend nuitka` branch — deliberately **not** added yet.
- AV reputation still depends on signing and download reputation, not on the compiler.

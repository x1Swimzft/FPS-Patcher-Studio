# PyInstaller spec — one-folder, windowed build.
# Run from project root: uv run --with pyinstaller pyinstaller build/fps_patcher.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH injected by PyInstaller)

datas = (
    collect_data_files("customtkinter")
    + collect_data_files("tkinterdnd2")
    + [(str(ROOT / "src" / "fps_patcher" / "ui" / "assets"), "fps_patcher/ui/assets")]
)
binaries = [(str(p), "bin") for p in (ROOT / "bin").glob("*.exe")]

a = Analysis(  # noqa: F821
    [str(ROOT / "src" / "fps_patcher" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    binaries=binaries,
    hiddenimports=["tkinterdnd2", "pywinstyles"],
    excludes=["unittest", "test"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FPSPatcherStudio",
    console=False,
    upx=False,  # UPX-packed binaries trigger AV heuristics
    icon=str(ROOT / "build" / "app.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
    manifest=str(ROOT / "build" / "fps_patcher.manifest"),
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="FPSPatcherStudio")  # noqa: F821

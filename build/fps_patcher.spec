# PyInstaller spec — one-folder, windowed build.
# Requires PyInstaller >= 6.10 (PySide6 6.12 Qt hooks) and PySide6 6.12.0.
# Run from project root: uv run --with pyinstaller pyinstaller build/fps_patcher.spec --noconfirm
import importlib.util
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH injected by PyInstaller)

datas = [(str(ROOT / "src" / "fps_patcher" / "ui" / "assets"), "fps_patcher/ui/assets")]
binaries = [(str(p), "bin") for p in (ROOT / "bin").glob("*.exe")]

# Qt plugins the widgets app needs. Do not collect the whole PySide6 tree: the
# WebEngine/Pdf wheels are ~250 MB and none of their plugins are used.
QT_PLUGINS = {
    "platforms": {"qwindows.dll", "qoffscreen.dll", "qminimal.dll"},
    "styles": {"qmodernwindowsstyle.dll", "qwindowsvistastyle.dll"},
    "imageformats": {"qgif.dll", "qico.dll", "qjpeg.dll", "qsvg.dll", "qtiff.dll", "qwebp.dll"},
}

# DLLs pulled in only as dependencies of pruned plugins (qpdf, virtual keyboard).
QT_DROP_DLLS = {
    "qt6pdf.dll",
    "qt6qml.dll",
    "qt6qmlmeta.dll",
    "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll",
    "qt6quick.dll",
    "qt6virtualkeyboard.dll",
    "qt6opengl.dll",
}

_qt_spec = importlib.util.find_spec("PySide6")
QT_PLUGINS_DIR = (
    Path(_qt_spec.origin).parent / "plugins" if _qt_spec and _qt_spec.origin else None
)


def _keep_qt_plugin(dest: str) -> bool:
    """Keep only the plugin types/names in QT_PLUGINS; other binaries untouched."""
    parts = Path(dest).parts
    if len(parts) < 4 or parts[0].lower() != "pyside6" or parts[1] != "plugins":
        return True
    return parts[2] in QT_PLUGINS and parts[-1].lower() in QT_PLUGINS[parts[2]]


def _keep_qt_binary(dest: str) -> bool:
    return _keep_qt_plugin(dest) and Path(dest).name.lower() not in QT_DROP_DLLS


a = Analysis(  # noqa: F821
    [str(ROOT / "src" / "fps_patcher" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    binaries=binaries,
    excludes=[
        "unittest",
        "test",
        # Tk is not imported by the Qt runtime; keep Tcl/Tk and its addons out of the build.
        "tkinter",
        "_tkinter",
        "customtkinter",
        "tkinterdnd2",
        "pywinstyles",
        # PySide6 addons/WebEngine are not imported; exclude them so hooks cannot
        # pull their DLLs or plugin trees into the one-folder build.
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuick3D",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtDesigner",
        "PySide6.QtNetworkAuth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtGraphs",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtTextToSpeech",
        "PySide6.QtWebChannel",
        "PySide6.QtWebSockets",
        "PySide6.QtScxml",
        "PySide6.QtTest",
    ],
)

# Qt hooks collect every plugin for the imported Qt modules; prune to the set above
# and add missing platform/style/imageformat DLLs if the hooks skipped them.
existing = {entry[0] for entry in a.binaries}
a.binaries = [entry for entry in a.binaries if _keep_qt_binary(entry[0])]
if QT_PLUGINS_DIR is not None:
    for sub, names in QT_PLUGINS.items():
        for name in sorted(names):
            src = QT_PLUGINS_DIR / sub / name
            dest = f"PySide6/plugins/{sub}/{name}"
            if src.is_file() and dest not in existing:
                a.binaries.append((dest, str(src), "BINARY"))

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

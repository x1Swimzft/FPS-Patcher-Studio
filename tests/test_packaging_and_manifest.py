"""Automated packaging, version consistency, and Windows manifest validation tests."""

import ast
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import fps_patcher

ROOT = Path(__file__).resolve().parent.parent


def test_versions_in_sync() -> None:
    """Verify version numbers match across all packaging and metadata files."""
    app_version = fps_patcher.__version__
    assert app_version, "FPS Patcher Studio version must not be empty"

    # 1. pyproject.toml
    pyproject_path = ROOT / "pyproject.toml"
    assert pyproject_path.exists(), "pyproject.toml missing"
    pyproject_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    assert pyproject_data["project"]["version"] == app_version

    # 2. build/installer.iss
    iss_path = ROOT / "build" / "installer.iss"
    assert iss_path.exists(), "build/installer.iss missing"
    iss_text = iss_path.read_text(encoding="utf-8")
    m_iss = re.search(r'#define\s+AppVersion\s+"([^"]+)"', iss_text)
    assert m_iss is not None, "AppVersion define not found in installer.iss"
    assert m_iss.group(1) == app_version

    # 3. build/version_info.txt
    vi_path = ROOT / "build" / "version_info.txt"
    assert vi_path.exists(), "build/version_info.txt missing"
    vi_text = vi_path.read_text(encoding="utf-8")
    expected_quad = tuple(int(x) for x in app_version.split(".")) + (0,)
    assert f"filevers={expected_quad}" in vi_text
    assert f"prodvers={expected_quad}" in vi_text
    assert f"'FileVersion', '{app_version}.0'" in vi_text
    assert f"'ProductVersion', '{app_version}.0'" in vi_text

    # 4. build/fps_patcher.manifest
    manifest_path = ROOT / "build" / "fps_patcher.manifest"
    assert manifest_path.exists(), "build/fps_patcher.manifest missing"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert f'version="{app_version}.0"' in manifest_text


def test_spec_file_syntax_and_manifest_configuration() -> None:
    """Verify PyInstaller spec syntax, UPX disablement, and asInvoker manifest."""
    spec_path = ROOT / "build" / "fps_patcher.spec"
    assert spec_path.exists(), "build/fps_patcher.spec missing"
    spec_text = spec_path.read_text(encoding="utf-8")

    # 1. Syntax check
    ast.parse(spec_text, filename=str(spec_path))

    # 2. UPX must be disabled (AV heuristics safety)
    assert "upx=False" in spec_text

    # 3. Manifest file referenced
    assert "fps_patcher.manifest" in spec_text

    # 4. Manifest XML content validation
    manifest_path = ROOT / "build" / "fps_patcher.manifest"
    manifest_tree = ET.parse(manifest_path)
    root = manifest_tree.getroot()

    # XML namespace handling
    ns = {
        "asmv1": "urn:schemas-microsoft-com:asm.v1",
        "asmv3": "urn:schemas-microsoft-com:asm.v3",
        "compat": "urn:schemas-microsoft-com:compatibility.v1",
    }

    # Verify execution level is asInvoker
    req_level = root.find(".//asmv3:requestedExecutionLevel", ns)
    assert req_level is not None, "requestedExecutionLevel element not found"
    assert req_level.attrib.get("level") == "asInvoker"
    assert req_level.attrib.get("uiAccess") == "false"

    # Verify Windows 10/11 compatibility GUID present
    # Windows 10/11 GUID: {8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}
    supported_os_elements = root.findall(".//compat:supportedOS", ns)
    supported_ids = [el.attrib.get("Id") for el in supported_os_elements]
    assert "{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}" in supported_ids


def test_required_assets_exist_and_non_empty() -> None:
    """Verify fonts, icons, and graphical assets exist and are non-empty."""
    assets_dir = ROOT / "src" / "fps_patcher" / "ui" / "assets"
    assert assets_dir.is_dir(), f"Asset directory missing: {assets_dir}"

    # App icons
    app_ico = assets_dir / "app.ico"
    assert app_ico.exists() and app_ico.stat().st_size > 0, "app.ico missing or empty"
    build_ico = ROOT / "build" / "app.ico"
    assert build_ico.exists() and build_ico.stat().st_size > 0, "build/app.ico missing or empty"

    app_png = assets_dir / "app_icon.png"
    assert app_png.exists() and app_png.stat().st_size > 0, "app_icon.png missing or empty"

    # Fonts directory
    fonts_dir = assets_dir / "fonts"
    assert fonts_dir.is_dir(), f"Fonts directory missing: {fonts_dir}"
    font_files = list(fonts_dir.glob("*.ttf"))
    assert len(font_files) >= 4, f"Expected at least 4 TTF fonts, found {len(font_files)}"

    for font_file in font_files:
        assert font_file.stat().st_size > 10000, f"Font file suspiciously small: {font_file.name}"


def test_inno_setup_privileges_and_architecture() -> None:
    """Verify Inno Setup is configured for lowest privileges (non-admin) and 64-bit."""
    iss_path = ROOT / "build" / "installer.iss"
    iss_text = iss_path.read_text(encoding="utf-8")

    assert "PrivilegesRequired=lowest" in iss_text
    assert "ArchitecturesAllowed=x64compatible" in iss_text
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in iss_text

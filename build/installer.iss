; Inno Setup script for FPS Patcher Studio. Build via build\release.ps1 (passes /DAppVersion=x.y.z).
#ifndef AppVersion
  #define AppVersion "0.3.5"
#endif
#ifndef AppPublisher
  #define AppPublisher "FPS Patcher Studio"
#endif

[Setup]
AppId={{6D1B6C0E-3F58-4C5E-9E0B-FPSPATCHERSTUDIO}
AppName=FPS Patcher Studio
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=FPS Patcher Studio Setup
VersionInfoProductName=FPS Patcher Studio
VersionInfoProductVersion={#AppVersion}.0
DefaultDirName={autopf}\FPS Patcher Studio
DefaultGroupName=FPS Patcher Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=FPSPatcherStudio-v{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=app.ico
UninstallDisplayIcon={app}\app.ico
SetupLogging=yes
#ifdef SignEnabled
; Requires ISCC /Sfpssign="<command> $f" (release.ps1 -Sign passes it).
SignTool=fpssign
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\FPSPatcherStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "app.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\FPS Patcher Studio"; Filename: "{app}\FPSPatcherStudio.exe"; IconFilename: "{app}\app.ico"
Name: "{autodesktop}\FPS Patcher Studio"; Filename: "{app}\FPSPatcherStudio.exe"; IconFilename: "{app}\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\FPSPatcherStudio.exe"; Description: "Launch FPS Patcher Studio"; Flags: nowait postinstall skipifsilent

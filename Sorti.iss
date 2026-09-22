; Sorti v1.1.0 — Inno Setup 6 installer
; ---------------------------------------------------------------------------
; Packs a PyInstaller *onedir* build into Sorti-Setup-v1.1.0.exe (~120 MB).
;
; Prerequisites
;   1. Inno Setup 6.2+  https://jrsoftware.org/isinfo.php
;   2. A directory build at dist\Sorti\  (NOT the 366 MB onefile Sorti.exe)
;      See Sorti.onedir.spec — run:
;          pyinstaller Sorti.onedir.spec --noconfirm
;   3. Sorti.ico in the repo root (same folder as this script)
;
; Compile
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" Sorti.iss
;
; Output
;   dist-installer\Sorti-Setup-v1.1.0.exe
; ---------------------------------------------------------------------------

#define MyAppName        "Sorti"
#define MyAppVersion     "1.1.0"
#define MyAppPublisher   "suedawg"
#define MyAppURL         "https://github.com/suedawg/Sorti"
#define MyAppExeName     "Sorti.exe"
#define MyAppId          "{{8F3C2A91-7D4E-4B6A-9C11-50A711000001}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
AppCopyright=Copyright (C) 2026 {#MyAppPublisher}

; Students on locked-down lab PCs can install without admin.
; "dialog" lets them opt into Program Files if they have elevation.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
DisableReadyPage=no
AllowNoIcons=yes
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
WizardStyle=modern
WizardSizePercent=120
SetupIconFile=Sorti.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}

OutputDir=dist-installer
OutputBaseFilename=Sorti-Setup-v{#MyAppVersion}
OutputManifestFile=Sorti-Setup-manifest.txt

; Close a running Sorti so the upgrade can overwrite binaries.
CloseApplications=yes
CloseApplicationsFilter=Sorti.exe
RestartApplications=no
MinVersion=10.0
UsedUserAreasWarning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce
Name: "startmenu";   Description: "Create a &Start Menu shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
; Entire PyInstaller onedir tree (dist\Sorti\Sorti.exe + _internal\ ...)
Source: "dist\Sorti\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; App icon next to the exe so shortcuts and Explorer stay crisp
Source: "Sorti.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\Sorti.ico"; Comment: "Academic document sorter"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\Sorti.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\Sorti.ico"; Tasks: desktopicon; Comment: "Academic document sorter"
Name: "{userstartmenu}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\Sorti.ico"; Tasks: startmenu; Comment: "Academic document sorter"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Portable metadata lives next to the exe at runtime; wipe it on uninstall.
Type: filesandordirs; Name: "{app}\.sorti"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not FileExists(ExpandConstant('{src}\..\dist\Sorti\Sorti.exe'))
     and not FileExists(ExpandConstant('{src}\dist\Sorti\Sorti.exe')) then
  begin
    { Compile-time layout is checked by the [Files] source; this is a runtime courtesy. }
  end;
end;

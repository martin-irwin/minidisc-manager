; Inno Setup script for MiniDisc Manager. Built by installer\build_installer.ps1, which passes SrcDist (the PyInstaller output
; folder), BuildDir (where icon.ico is) and AppVersion on the command line.
#ifndef AppVersion
  #define AppVersion "0.9.0"
#endif
#ifndef SrcDist
  #error SrcDist is not defined: run installer\build_installer.ps1
#endif
#ifndef BuildDir
  #define BuildDir "."
#endif
#define AppName "MiniDisc Manager"
#define AppExe "MiniDisc Manager.exe"
#define AppSrc ".."

[Setup]
AppId={{FE67DC56-A4A8-4039-802F-BE4A7F278537}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} (test build)
AppPublisher=Vinny Powell
AppCopyright=Copyright (c) 2026 Vinny Powell
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=MiniDisc-Manager-Setup-{#AppVersion}
SetupIconFile={#BuildDir}\icon-setup.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=yes
LZMAUseSeparateProcess=yes
LicenseFile={#AppSrc}\LICENSE.txt
InfoBeforeFile={#BuildDir}\info.txt
DisableWelcomePage=no
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} setup

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
; the program (PyInstaller output: the exe and its _internal folder, which holds runtime\, helper\, ui\ and the libraries)
Source: "{#SrcDist}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; the guides and licence notices, also at the top of the install folder where they are easy to find
Source: "{#AppSrc}\DRIVER-SETUP.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppSrc}\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppSrc}\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppSrc}\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppSrc}\LICENSES\*"; DestDir: "{app}\LICENSES"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\USB driver setup guide"; Filename: "{app}\DRIVER-SETUP.html"
Name: "{group}\Read me"; Filename: "{app}\README.txt"
Name: "{group}\Licences and notices"; Filename: "{app}\THIRD-PARTY-NOTICES.txt"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\DRIVER-SETUP.html"; Description: "Open the USB driver setup guide (needed once per recorder)"; Flags: postinstall shellexec skipifsilent
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: postinstall nowait skipifsilent unchecked

[Code]
const
  WebView2Id = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

// The window needs Microsoft's Edge WebView2 Runtime (included with Windows 11). Look for it in the places it registers itself.
function WebView2Version(): String;
var
  v: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WebView2Id, 'pv', v) then Result := v;
  if (Result = '') and RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2Id, 'pv', v) then Result := v;
  if (Result = '') and RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + WebView2Id, 'pv', v) then Result := v;
  if Result = '0.0.0.0' then Result := '';
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if WebView2Version() = '' then
    MsgBox('MiniDisc Manager needs the Microsoft Edge WebView2 Runtime, which was not found on this PC.' + #13#10 + #13#10 +
           'Windows 11 includes it. On Windows 10, install the "Evergreen Standalone Installer" from:' + #13#10 +
           'https://developer.microsoft.com/microsoft-edge/webview2/' + #13#10 + #13#10 +
           'You can install MiniDisc Manager now and add WebView2 afterwards.', mbInformation, MB_OK);
end;

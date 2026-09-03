; Per-user installer only. It distributes the complete PyInstaller onedir output.
#define AppName "Risk Assessment Heat Map"
#define AppExeName "RiskAssessmentHeatMap.exe"

[Setup]
AppId={{F4B850A3-50D4-4EB2-BE7D-1EFBF77A1DAB}
AppName={#AppName}
AppVersion=1.0
DefaultDirName={localappdata}\Programs\RiskAssessmentHeatMap
DefaultGroupName=Risk Assessment Heat Map
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\installer-output
OutputBaseFilename=RiskAssessmentHeatMap-Setup
; Output file: installer-output\RiskAssessmentHeatMap-Setup.exe
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\{#AppExeName}
; Inno Setup creates unins000.exe in {app} and the Windows uninstall entry.

[Files]
Source: "{#SourcePath}\..\dist\RiskAssessmentHeatMap\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Risk Assessment Heat Map"; Filename: "{app}\{#AppExeName}"
Name: "{autoprograms}\Risk Assessment Heat Map\Uninstall Risk Assessment Heat Map"; Filename: "{uninstallexe}"

[Code]
function WebView2RuntimeInstalled: Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(HKLM64, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
    or RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
end;

function InitializeSetup(): Boolean;
begin
  Result := WebView2RuntimeInstalled;
  if not Result then begin
    Log('Microsoft Edge WebView2 Runtime is required. Install it from https://developer.microsoft.com/microsoft-edge/webview2/.');
    if not WizardSilent then
      MsgBox('Microsoft Edge WebView2 Runtime is required. Install it from https://developer.microsoft.com/microsoft-edge/webview2/ and run this setup again.', mbError, MB_OK);
  end;
end;

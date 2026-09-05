; Per-user installer only. It distributes the complete PyInstaller onedir output.
#define AppName "Risk Assessment Heat Map"
#define AppExeName "RiskAssessmentHeatMap.exe"
#ifndef DistRoot
  #define DistRoot SourcePath + "\..\dist\RiskAssessmentHeatMap"
#endif

[Setup]
AppId={{F4B850A3-50D4-4EB2-BE7D-1EFBF77A1DAB}
AppName={#AppName}
AppVersion=1.2.1
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
Source: "{#DistRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Embedded prerequisite only. It is extracted to {tmp} and separately elevated when required.
Source: "{#SourcePath}\cache\VC_redist.x64-14.50.35719.exe"; Flags: dontcopy

[InstallDelete]
; Only obsolete packaged libraries: preserve application state and report directories.
Type: filesandordirs; Name: "{app}\_internal\matplotlib"
Type: filesandordirs; Name: "{app}\_internal\contourpy"
Type: filesandordirs; Name: "{app}\_internal\kiwisolver"
Type: filesandordirs; Name: "{app}\_internal\dateutil"
Type: files; Name: "{app}\_internal\cv2\opencv_videoio_ffmpeg*.dll"

[Icons]
Name: "{group}\Risk Assessment Heat Map"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall Risk Assessment Heat Map"; Filename: "{uninstallexe}"

[Code]
function WebView2RuntimeInstalled: Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(HKLM64, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
    or RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
end;

function VCRuntimeAtLeast145035719: Boolean;
var
  Installed, Major, Minor, Bld, Rbld: Cardinal;
  Key: String;
begin
  Key := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  Result :=
    (RegQueryDWordValue(HKLM64, Key, 'Installed', Installed) or
     RegQueryDWordValue(HKLM32, Key, 'Installed', Installed)) and
    (RegQueryDWordValue(HKLM64, Key, 'Major', Major) or
     RegQueryDWordValue(HKLM32, Key, 'Major', Major)) and
    (RegQueryDWordValue(HKLM64, Key, 'Minor', Minor) or
     RegQueryDWordValue(HKLM32, Key, 'Minor', Minor)) and
    (RegQueryDWordValue(HKLM64, Key, 'Bld', Bld) or
     RegQueryDWordValue(HKLM32, Key, 'Bld', Bld)) and
    (RegQueryDWordValue(HKLM64, Key, 'Rbld', Rbld) or
     RegQueryDWordValue(HKLM32, Key, 'Rbld', Rbld)) and
    (Installed = 1) and
    ((Major > 14) or
     ((Major = 14) and (Minor > 50)) or
     ((Major = 14) and (Minor = 50) and (Bld > 35719)) or
     ((Major = 14) and (Minor = 50) and (Bld = 35719) and (Rbld >= 0)));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  RedistPath: String;
begin
  Result := '';
  if VCRuntimeAtLeast145035719 then begin
    Log('Microsoft Visual C++ Redistributable 14.50.35719 or newer is already installed.');
    exit;
  end;

  ExtractTemporaryFile('VC_redist.x64-14.50.35719.exe');
  RedistPath := ExpandConstant('{tmp}\VC_redist.x64-14.50.35719.exe');
  Log('Installing the signed Microsoft Visual C++ Redistributable prerequisite with separate elevation.');
  if not ShellExec('runas', RedistPath, '/install /quiet /norestart', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) then begin
    Result := 'Microsoft Visual C++ Redistributable installation was cancelled or could not start.';
    exit;
  end;
  if (ResultCode <> 0) and (ResultCode <> 3010) and (ResultCode <> 1638) then begin
    Result := Format('Microsoft Visual C++ Redistributable installation failed (exit code %d).', [ResultCode]);
    exit;
  end;
  if ResultCode = 3010 then
    NeedsRestart := True;
  if not VCRuntimeAtLeast145035719 then
    Result := 'Microsoft Visual C++ Redistributable 14.50.35719 or newer was not detected after setup.';
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

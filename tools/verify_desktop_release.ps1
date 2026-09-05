[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$DistPath,
    [Parameter(Mandatory=$true)][string]$InstallerPath,
    [Parameter(Mandatory=$true)][string]$PreviousInstallerPath,
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$ReportPath
)
$ErrorActionPreference = 'Stop'
$releaseRepo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$releaseDist = (Resolve-Path -LiteralPath $DistPath).Path
$releaseInstaller = (Resolve-Path -LiteralPath $InstallerPath).Path
$releasePrevious = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
$releasePython = (Resolve-Path -LiteralPath $PythonExe).Path
$releaseReport = [IO.Path]::GetFullPath($ReportPath)
. (Join-Path $releaseRepo 'tools\verify_desktop_package.ps1') -DistPath $releaseDist -InstallerPath $releaseInstaller -FunctionsOnly

$releaseKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{F4B850A3-50D4-4EB2-BE7D-1EFBF77A1DAB}_is1'
if (Test-Path -LiteralPath $releaseKey) { throw 'EXISTING_INSTALLATION_USE_DISPOSABLE_WINDOWS_ACCOUNT' }
$releaseToken = [guid]::NewGuid().ToString('N')
$releaseRoot = Join-Path ([IO.Path]::GetTempPath()) ('rahm-release-' + $releaseToken)
if (Test-Path -LiteralPath $releaseRoot) { throw 'UNSAFE_EXISTING_TEST_ROOT' }
New-Item -ItemType Directory -Path $releaseRoot | Out-Null
[IO.File]::WriteAllText((Join-Path $releaseRoot 'acceptance-marker.txt'), $releaseToken)
$releaseInstallRoot = Join-Path $releaseRoot 'program'
$releaseGroupName = 'Risk Assessment Heat Map'
$releaseGroupRoot = Join-Path $env:APPDATA ('Microsoft\Windows\Start Menu\Programs\' + $releaseGroupName)
$releaseLegacyShortcutPaths = @(
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Risk Assessment Heat Map.lnk'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Risk Assessment Heat Map\Risk Assessment Heat Map.lnk'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Risk Assessment Heat Map\Uninstall Risk Assessment Heat Map.lnk')
)
$releaseShortcutBackup = @{}
foreach($path in $releaseLegacyShortcutPaths) {
    if (Test-Path -LiteralPath $path -PathType Leaf) { $releaseShortcutBackup[$path]=[IO.File]::ReadAllBytes($path) }
}
$releaseOriginalAppData = $env:LOCALAPPDATA
$env:LOCALAPPDATA = Join-Path $releaseRoot 'user-state'
$releaseStateTool = Join-Path $releaseRepo 'tools\synthetic_install_state.py'
$releaseResults = [Collections.Generic.List[object]]::new()

function Assert-ReleaseState {
    & $releasePython $releaseStateTool check $releaseRoot $releaseToken
    if ($LASTEXITCODE -ne 0) { throw 'SYNTHETIC_STATE_VERIFICATION_FAILED' }
}
function Install-Release([string]$Exe, [string]$Phase) {
    $log = Join-Path $releaseRoot ($Phase + '-installer-log.txt')
    Invoke-BoundedInstaller $Exe @('/VERYSILENT','/SUPPRESSMSGBOXES',"/DIR=$releaseInstallRoot","/LOG=$log") 'INSTALL' $log $releaseInstallRoot {
        (Test-Path -LiteralPath (Join-Path $releaseInstallRoot 'unins000.exe')) -and (Test-InnoLog $log 'Installation process succeeded.')
    }
    $entry = Get-ItemProperty -LiteralPath $releaseKey
    if ([IO.Path]::GetFullPath($entry.InstallLocation).TrimEnd('\') -ne $releaseInstallRoot) { throw 'INSTALL_REGISTRY_PATH_MISMATCH' }
    $shortcut = if($Phase -eq 'previous-install') { $releaseLegacyShortcutPaths[0] } else { Join-Path $releaseGroupRoot 'Risk Assessment Heat Map.lnk' }
    if (-not (Test-Path -LiteralPath $shortcut)) { throw 'SHORTCUT_MISSING' }
    Invoke-ExactSmoke (Join-Path $releaseInstallRoot 'RiskAssessmentHeatMap.exe')
    Assert-ReleaseState
    $releaseResults.Add(@{phase=$Phase;status='passed';version=$entry.DisplayVersion;smoke='passed';state_and_credential='preserved';shortcut='present'})
    Write-Output "INSTALL_ACCEPTANCE_OK phase=$Phase version=$($entry.DisplayVersion)"
}
function Assert-InstalledFiles {
    foreach($file in Get-ChildItem -LiteralPath $releaseDist -File -Recurse) {
        $relative = $file.FullName.Substring($releaseDist.Length+1)
        $installed = Join-Path $releaseInstallRoot $relative
        if (-not (Test-Path -LiteralPath $installed) -or (Get-FileHash -LiteralPath $installed).Hash -ne (Get-FileHash -LiteralPath $file.FullName).Hash) { throw "INSTALLED_HASH_MISMATCH file=$relative" }
    }
}
function Uninstall-Release([string]$Phase) {
    $log = Join-Path $releaseRoot ($Phase + '-uninstaller-log.txt')
    $uninstaller = Join-Path $releaseInstallRoot 'unins000.exe'
    Invoke-BoundedInstaller $uninstaller @('/VERYSILENT','/SUPPRESSMSGBOXES',"/LOG=$log") 'UNINSTALL' $log $releaseInstallRoot {
        (Test-DirectoryAbsentOrEmpty $releaseInstallRoot) -and (Test-InnoLog $log 'Uninstallation process succeeded.')
    }
    if (Test-Path -LiteralPath $releaseKey) { throw 'UNINSTALL_REGISTRY_REMAINS' }
    foreach($path in $releaseLegacyShortcutPaths) {
        if(Test-Path -LiteralPath $path) { throw 'UNINSTALL_SHORTCUT_REMAINS' }
    }
    Assert-ReleaseState
    $releaseResults.Add(@{phase=$Phase;status='passed';program='removed';registration='removed';shortcuts='removed';state_and_credential='preserved'})
    Write-Output "UNINSTALL_ACCEPTANCE_OK phase=$Phase"
}

$releasePassed = $false
try {
    & $releasePython $releaseStateTool seed $releaseRoot $releaseToken
    if ($LASTEXITCODE -ne 0) { throw 'SYNTHETIC_STATE_SEED_FAILED' }
    Install-Release $releaseInstaller 'clean-install'
    Assert-InstalledFiles
    Uninstall-Release 'clean-uninstall'
    Install-Release $releasePrevious 'previous-install'
    Install-Release $releaseInstaller 'upgrade'
    Assert-InstalledFiles
    $legacy = @('_internal\matplotlib','_internal\contourpy','_internal\kiwisolver','_internal\dateutil')
    foreach($relative in $legacy) {
        if (Test-Path -LiteralPath (Join-Path $releaseInstallRoot $relative)) { throw "UPGRADE_LEGACY_FILES_REMAIN component=$relative" }
    }
    if (Get-ChildItem -LiteralPath (Join-Path $releaseInstallRoot '_internal\cv2') -Filter 'opencv_videoio_ffmpeg*.dll' -File) { throw 'UPGRADE_LEGACY_VIDEO_DLL_REMAINS' }
    Uninstall-Release 'upgrade-uninstall'
    $releasePassed = $true
} finally {
    try {
        if (Test-Path -LiteralPath (Join-Path $releaseInstallRoot 'unins000.exe')) { Uninstall-Release 'cleanup-uninstall' }
    } finally {
        & $releasePython $releaseStateTool cleanup $releaseRoot $releaseToken
        $releaseCredentialCleanupCode=$LASTEXITCODE
        $env:LOCALAPPDATA = $releaseOriginalAppData
        foreach($path in $releaseLegacyShortcutPaths) {
            if($releaseShortcutBackup.ContainsKey($path)) {
                New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
                [IO.File]::WriteAllBytes($path, $releaseShortcutBackup[$path])
            }
        }
        $report = @{passed=($releasePassed -and $releaseCredentialCleanupCode -eq 0);synthetic_credential_removed=($releaseCredentialCleanupCode -eq 0);installer_sha256=(Get-FileHash -LiteralPath $releaseInstaller).Hash;previous_installer_sha256=(Get-FileHash -LiteralPath $releasePrevious).Hash;phases=@($releaseResults.ToArray());log_directory=$releaseRoot;existing_installation_modified=$false}
        New-Item -ItemType Directory -Path (Split-Path -Parent $releaseReport) -Force | Out-Null
        $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $releaseReport -Encoding utf8
        if($releaseCredentialCleanupCode -ne 0) { throw 'SYNTHETIC_CREDENTIAL_CLEANUP_FAILED' }
    }
}
if ($releasePassed) { Write-Output "RELEASE_INSTALL_UPGRADE_UNINSTALL_OK report=$releaseReport" }

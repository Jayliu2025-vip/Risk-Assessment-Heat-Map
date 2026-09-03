[CmdletBinding()]
param([string]$DistPath, [string]$InstallerPath)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($DistPath)) { $DistPath = Join-Path $RepoRoot 'dist\RiskAssessmentHeatMap' }
if ([string]::IsNullOrWhiteSpace($InstallerPath)) { $InstallerPath = Join-Path $RepoRoot 'installer-output\RiskAssessmentHeatMap-Setup.exe' }
$DistPath = [System.IO.Path]::GetFullPath($DistPath)
$InstallerPath = [System.IO.Path]::GetFullPath($InstallerPath)
$OnedirExe = Join-Path $DistPath 'RiskAssessmentHeatMap.exe'
if (-not (Test-Path -LiteralPath $OnedirExe -PathType Leaf)) { throw "ONEDIR_NOT_FOUND $OnedirExe" }

function Invoke-ExactSmoke([string]$Exe) {
    $base = [System.IO.Path]::GetTempPath()
    $id = [guid]::NewGuid().ToString('N')
    $stdout = Join-Path $base "rahm-smoke-$id.out"
    $stderr = Join-Path $base "rahm-smoke-$id.err"
    try {
        $process = Start-Process -FilePath $Exe -ArgumentList '--synthetic-smoke' -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -Wait
        $result = if (Test-Path -LiteralPath $stdout) { [System.IO.File]::ReadAllText($stdout) } else { '' }
        $errors = if (Test-Path -LiteralPath $stderr) { [System.IO.File]::ReadAllText($stderr) } else { '' }
        if ($process.ExitCode -ne 0 -or $errors -ne '' -or $result -ne "PACKAGED_DESKTOP_SMOKE_OK`n") { throw 'PACKAGED_SMOKE_FAILED' }
    } finally {
        if (Test-Path -LiteralPath $stdout) { Remove-Item -LiteralPath $stdout -Force }
        if (Test-Path -LiteralPath $stderr) { Remove-Item -LiteralPath $stderr -Force }
    }
}

function Invoke-BoundedInstaller([string]$Exe, [string[]]$Arguments, [string]$Phase, [string]$LogPath, [scriptblock]$CompletionProbe) {
    $process = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru
    $deadline = (Get-Date).AddSeconds(300)
    while ((Get-Date) -lt $deadline) {
        if (& $CompletionProbe) { return }
        Start-Sleep -Milliseconds 250
    }
    $process.Refresh()
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    $tail = if (Test-Path -LiteralPath $LogPath) { (Get-Content -LiteralPath $LogPath -Tail 20) -join "`n" } else { '(installer log unavailable)' }
    if ($Phase -eq 'INSTALL') { throw "INSTALL_TIMEOUT installer_log_tail=$tail" }
    throw "UNINSTALL_TIMEOUT installer_log_tail=$tail"
}

function Test-InnoLog([string]$LogPath, [string]$SuccessMarker) {
    if (-not (Test-Path -LiteralPath $LogPath -PathType Leaf)) { return $false }
    try {
        $body = [System.IO.File]::ReadAllText($LogPath)
        return $body.Contains($SuccessMarker) -and $body.Contains('Log closed.')
    } catch { return $false }
}

Invoke-ExactSmoke $OnedirExe
Write-Output "ONEDIR_SHA256 $((Get-FileHash -LiteralPath $OnedirExe -Algorithm SHA256).Hash)"
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) { Write-Error 'INSTALLER_NOT_BUILT'; exit 2 }
$installRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('rahm-installed-smoke-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $installRoot) { throw 'UNSAFE_EXISTING_INSTALL_PATH' }
$installLog = Join-Path ([System.IO.Path]::GetTempPath()) ('rahm-installer-log-' + [guid]::NewGuid().ToString('N') + '.log')
$installedExe = Join-Path $installRoot 'RiskAssessmentHeatMap.exe'
$uninstallLog = Join-Path ([System.IO.Path]::GetTempPath()) ('rahm-uninstaller-log-' + [guid]::NewGuid().ToString('N') + '.log')
$verified = $false
try {
    Invoke-BoundedInstaller $InstallerPath @('/VERYSILENT', '/SUPPRESSMSGBOXES', "/DIR=$installRoot", "/LOG=$installLog") 'INSTALL' $installLog { (Test-Path -LiteralPath $installedExe -PathType Leaf) -and (Test-Path -LiteralPath (Join-Path $installRoot 'unins000.exe') -PathType Leaf) -and (Test-InnoLog $installLog 'Installation process succeeded.') }
    Invoke-ExactSmoke $installedExe
    $uninstaller = Join-Path $installRoot 'unins000.exe'
    Invoke-BoundedInstaller $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', "/LOG=$uninstallLog") 'UNINSTALL' $uninstallLog { ((-not (Test-Path -LiteralPath $installRoot)) -or (-not (Get-ChildItem -LiteralPath $installRoot -Force | Select-Object -First 1))) -and (Test-InnoLog $uninstallLog 'Uninstallation process succeeded.') }
    $running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $installedExe -and $_.ProcessId -ne $PID }
    if ($running) { throw 'PROCESS_STILL_RUNNING' }
    if ((Test-Path -LiteralPath $installRoot) -and (Get-ChildItem -LiteralPath $installRoot -Force | Select-Object -First 1)) { throw 'INSTALL_DIRECTORY_NOT_REMOVED' }
    $verified = $true
} finally {
    if ($verified -and (Test-Path -LiteralPath $installRoot)) { Remove-Item -LiteralPath $installRoot -Force }
    if ($verified -and (Test-Path -LiteralPath $installLog)) { Remove-Item -LiteralPath $installLog -Force }
    if ($verified -and (Test-Path -LiteralPath $uninstallLog)) { Remove-Item -LiteralPath $uninstallLog -Force }
}
Write-Output "INSTALLER_SHA256 $((Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash)"

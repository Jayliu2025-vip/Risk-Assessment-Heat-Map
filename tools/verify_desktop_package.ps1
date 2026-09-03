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

Invoke-ExactSmoke $OnedirExe
Write-Output "ONEDIR_SHA256 $((Get-FileHash -LiteralPath $OnedirExe -Algorithm SHA256).Hash)"
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) { Write-Error 'INSTALLER_NOT_BUILT'; exit 2 }
$installRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('rahm-installed-smoke-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $installRoot) { throw 'UNSAFE_EXISTING_INSTALL_PATH' }
& $InstallerPath '/VERYSILENT' '/SUPPRESSMSGBOXES' "/DIR=$installRoot"
if ($LASTEXITCODE -ne 0) { throw 'INSTALL_FAILED' }
$installedExe = Join-Path $installRoot 'RiskAssessmentHeatMap.exe'
Invoke-ExactSmoke $installedExe
$uninstaller = Join-Path $installRoot 'unins000.exe'
& $uninstaller '/VERYSILENT' '/SUPPRESSMSGBOXES'
if ($LASTEXITCODE -ne 0) { throw 'UNINSTALL_FAILED' }
if (Get-Process -Name 'RiskAssessmentHeatMap' -ErrorAction SilentlyContinue) { throw 'PROCESS_STILL_RUNNING' }
if ((Test-Path -LiteralPath $installRoot) -and (Get-ChildItem -LiteralPath $installRoot -Force | Select-Object -First 1)) { throw 'INSTALL_DIRECTORY_NOT_REMOVED' }
if (Test-Path -LiteralPath $installRoot) { Remove-Item -LiteralPath $installRoot -Force }
Write-Output "INSTALLER_SHA256 $((Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash)"

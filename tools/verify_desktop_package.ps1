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

function Get-ChildProcess([int]$RootProcessId) {
    $all = @(Get-CimInstance Win32_Process)
    $seen = [System.Collections.Generic.HashSet[int]]::new()
    $pending = [System.Collections.Generic.Queue[int]]::new()
    $pending.Enqueue($RootProcessId)
    $result = @()
    while ($pending.Count -gt 0) {
        $parent = $pending.Dequeue()
        foreach ($candidate in $all | Where-Object { $_.ParentProcessId -eq $parent }) {
            if ($seen.Add([int]$candidate.ProcessId)) {
                $result += $candidate
                $pending.Enqueue([int]$candidate.ProcessId)
            }
        }
    }
    return $result
}

function Get-VerifiedRunProcess([int]$RootProcessId, [string]$ExpectedExe, [string]$InstallRoot = '', [string]$LogPath = '', [int[]]$BaselineProcessIds = @()) {
    $all = @(Get-CimInstance Win32_Process)
    $candidates = @(Get-ChildProcess $RootProcessId)
    $root = Get-CimInstance Win32_Process -Filter "ProcessId=$RootProcessId" -ErrorAction SilentlyContinue
    if ($root) { $candidates += $root }
    $candidates += @($all | Where-Object {
        $_.ExecutablePath -eq $ExpectedExe -or
        ($LogPath -and ([string]$_.CommandLine).Contains("/LOG=$LogPath"))
    })
    $seen = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($candidate in $candidates) {
        if (-not $seen.Add([int]$candidate.ProcessId) -or $BaselineProcessIds -contains [int]$candidate.ProcessId) { continue }
        $command = [string]$candidate.CommandLine
        $isExactExe = $candidate.ExecutablePath -eq $ExpectedExe
        $isTempExe = $candidate.ExecutablePath -and ([System.IO.Path]::GetFullPath($candidate.ExecutablePath)).StartsWith([System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()), [System.StringComparison]::OrdinalIgnoreCase)
        $hasExactRunToken = $LogPath -and $command.Contains("/LOG=$LogPath") -and ($command.Contains("/DIR=$InstallRoot") -or $command.Contains($ExpectedExe))
        $isExactInstallerChild = $isTempExe -and $hasExactRunToken
        if ($isExactExe -or $isExactInstallerChild) {
            $candidate
        }
    }
}

function Stop-VerifiedRunProcesses([int]$RootProcessId, [string]$ExpectedExe, [string]$InstallRoot = '', [string]$LogPath = '', [int[]]$BaselineProcessIds = @()) {
    $targets = @(Get-VerifiedRunProcess $RootProcessId $ExpectedExe $InstallRoot $LogPath $BaselineProcessIds)
    foreach ($target in $targets) {
        Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
    }
    foreach ($target in $targets) {
        Wait-Process -Id $target.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    }
}

function Invoke-ExactSmoke([string]$Exe) {
    $base = [System.IO.Path]::GetTempPath()
    $id = [guid]::NewGuid().ToString('N')
    $stdout = Join-Path $base "rahm-smoke-$id.out"
    $stderr = Join-Path $base "rahm-smoke-$id.err"
    $process = $null
    $baselineProcessIds = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $Exe } | ForEach-Object { [int]$_.ProcessId })
    try {
        $process = Start-Process -FilePath $Exe -ArgumentList '--synthetic-smoke' -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
        $deadline = (Get-Date).AddSeconds(120)
        while ((Get-Date) -lt $deadline -and -not $process.HasExited) {
            Start-Sleep -Milliseconds 100
            $process.Refresh()
        }
        if (-not $process.HasExited) {
            Stop-VerifiedRunProcesses $process.Id $Exe '' '' $baselineProcessIds
            throw 'SMOKE_TIMEOUT'
        }
        $process.WaitForExit()
        $result = if (Test-Path -LiteralPath $stdout) { [System.IO.File]::ReadAllText($stdout) } else { '' }
        $errors = if (Test-Path -LiteralPath $stderr) { [System.IO.File]::ReadAllText($stderr) } else { '' }
        $outBytes = if (Test-Path -LiteralPath $stdout) { (Get-Item -LiteralPath $stdout).Length } else { 0 }
        $errBytes = if (Test-Path -LiteralPath $stderr) { (Get-Item -LiteralPath $stderr).Length } else { 0 }
        if ($process.ExitCode -ne 0 -or $errors -ne '' -or $result -ne "PACKAGED_DESKTOP_SMOKE_OK`n") { throw "PACKAGED_SMOKE_FAILED exit_code=$($process.ExitCode) stdout_bytes=$outBytes stderr_bytes=$errBytes marker_exact=$($result -eq "PACKAGED_DESKTOP_SMOKE_OK`n")" }
    } finally {
        if ($process) {
            Stop-VerifiedRunProcesses $process.Id $Exe '' '' $baselineProcessIds
            $remaining = @(Get-VerifiedRunProcess $process.Id $Exe '' '' $baselineProcessIds)
            if ($remaining) { throw 'SMOKE_PROCESS_STILL_RUNNING' }
        }
        if (Test-Path -LiteralPath $stdout) { Remove-Item -LiteralPath $stdout -Force }
        if (Test-Path -LiteralPath $stderr) { Remove-Item -LiteralPath $stderr -Force }
    }
}

function Test-DirectoryAbsentOrEmpty([string]$Path) {
    try {
        if (-not (Test-Path -LiteralPath $Path)) { return $true }
        return -not (Get-ChildItem -LiteralPath $Path -Force -ErrorAction Stop | Select-Object -First 1)
    } catch [System.IO.DirectoryNotFoundException] { return $true
    } catch [System.Management.Automation.ItemNotFoundException] { return $true
    } catch { return $false }
}

function Invoke-BoundedInstaller([string]$Exe, [string[]]$Arguments, [string]$Phase, [string]$LogPath, [string]$InstallRoot, [scriptblock]$CompletionProbe) {
    $baselineProcessIds = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $Exe } | ForEach-Object { [int]$_.ProcessId })
    $process = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru
    try {
        $deadline = (Get-Date).AddSeconds(300)
        while ((Get-Date) -lt $deadline) {
            if (& $CompletionProbe) { return }
            Start-Sleep -Milliseconds 250
        }
        $tail = if (Test-Path -LiteralPath $LogPath) { (Get-Content -LiteralPath $LogPath -Tail 20) -join "`n" } else { '(installer log unavailable)' }
        if ($Phase -eq 'INSTALL') { throw "INSTALL_TIMEOUT installer_log_tail=$tail" }
        throw "UNINSTALL_TIMEOUT installer_log_tail=$tail"
    } finally {
        Stop-VerifiedRunProcesses $process.Id $Exe $InstallRoot $LogPath $baselineProcessIds
        $remaining = @(Get-VerifiedRunProcess $process.Id $Exe $InstallRoot $LogPath $baselineProcessIds)
        if ($remaining) { throw "INSTALLER_PROCESS_STILL_RUNNING phase=$Phase" }
    }
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
    Invoke-BoundedInstaller $InstallerPath @('/VERYSILENT', '/SUPPRESSMSGBOXES', "/DIR=$installRoot", "/LOG=$installLog") 'INSTALL' $installLog $installRoot { (Test-Path -LiteralPath $installedExe -PathType Leaf) -and (Test-Path -LiteralPath (Join-Path $installRoot 'unins000.exe') -PathType Leaf) -and (Test-InnoLog $installLog 'Installation process succeeded.') }
    Invoke-ExactSmoke $installedExe
    $uninstaller = Join-Path $installRoot 'unins000.exe'
    Invoke-BoundedInstaller $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', "/LOG=$uninstallLog") 'UNINSTALL' $uninstallLog $installRoot { (Test-DirectoryAbsentOrEmpty $installRoot) -and (Test-InnoLog $uninstallLog 'Uninstallation process succeeded.') }
    $running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $installedExe -and $_.ProcessId -ne $PID }
    if ($running) { throw 'PROCESS_STILL_RUNNING' }
    if (-not (Test-DirectoryAbsentOrEmpty $installRoot)) { throw 'INSTALL_DIRECTORY_NOT_REMOVED' }
    $verified = $true
} finally {
    if ($verified -and (Test-Path -LiteralPath $installRoot)) { Remove-Item -LiteralPath $installRoot -Force }
    if ($verified -and (Test-Path -LiteralPath $installLog)) { Remove-Item -LiteralPath $installLog -Force }
    if ($verified -and (Test-Path -LiteralPath $uninstallLog)) { Remove-Item -LiteralPath $uninstallLog -Force }
}
Write-Output "INSTALLER_SHA256 $((Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash)"

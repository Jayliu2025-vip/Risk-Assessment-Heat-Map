[CmdletBinding()]
param(
    [string]$PythonExe,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($PythonExe)) { $PythonExe = Join-Path $RepoRoot '.venv-desktop\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "PYTHON_NOT_FOUND $PythonExe" }
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path

function Assert-AllowedBuildPath([string]$Candidate) {
    $resolved = [System.IO.Path]::GetFullPath($Candidate)
    $allowed = @(
        [System.IO.Path]::GetFullPath((Join-Path $RepoRoot 'build\risk_heatmap_desktop')),
        [System.IO.Path]::GetFullPath((Join-Path $RepoRoot 'dist\RiskAssessmentHeatMap')),
        [System.IO.Path]::GetFullPath((Join-Path $RepoRoot 'installer-output')),
        [System.IO.Path]::GetFullPath((Join-Path $RepoRoot 'build\licenses'))
    )
    if ($allowed -notcontains $resolved) { throw "UNSAFE_BUILD_PATH $resolved" }
    return $resolved
}

$BuildPath = Assert-AllowedBuildPath (Join-Path $RepoRoot 'build\risk_heatmap_desktop')
$DistPath = Assert-AllowedBuildPath (Join-Path $RepoRoot 'dist\RiskAssessmentHeatMap')
$InstallerPath = Assert-AllowedBuildPath (Join-Path $RepoRoot 'installer-output')
$LicensePath = Assert-AllowedBuildPath (Join-Path $RepoRoot 'build\licenses')
foreach ($path in @($BuildPath, $DistPath, $InstallerPath, $LicensePath)) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}

& $PythonExe -c "import platform, importlib.metadata as m; assert platform.python_version() == '3.13.14' and platform.architecture()[0] == '64bit', 'PYTHON_3_13_X64_REQUIRED exact=3.13.14'; assert m.version('PyInstaller') == '6.22.2'; import rapidocr, pypdfium2, onnxruntime, webview, keyring"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $PythonExe -m pip check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$RapidOcrExe = Join-Path (Split-Path -Parent $PythonExe) 'rapidocr.exe'
if (-not (Test-Path -LiteralPath $RapidOcrExe -PathType Leaf)) { Write-Error 'RAPIDOCR_ENVIRONMENT_CHECK_FAILED'; exit 2 }
& $RapidOcrExe check
if ($LASTEXITCODE -ne 0) { Write-Error 'RAPIDOCR_ENVIRONMENT_CHECK_FAILED'; exit $LASTEXITCODE }
if (-not $SkipTests) {
    & $PythonExe -m unittest discover -s (Join-Path $RepoRoot 'tests') -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Push-Location $RepoRoot
    try { npm exec playwright test } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $PythonExe (Join-Path $RepoRoot 'tools\export_third_party_licenses.py') --output $LicensePath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$PythonBase = (& $PythonExe -c "import sys; print(sys.base_prefix)").Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $PythonBase -PathType Container)) { throw 'PYTHON_BASE_NOT_FOUND' }
$OriginalPath = $env:PATH
$env:PATH = @(
    (Split-Path -Parent $PythonExe),
    $PythonBase,
    (Join-Path $PythonBase 'DLLs'),
    (Join-Path $env:SystemRoot 'System32'),
    $env:SystemRoot
) -join [System.IO.Path]::PathSeparator
try {
    & $PythonExe -m PyInstaller (Join-Path $RepoRoot 'packaging\risk_heatmap_desktop.spec') --workpath $BuildPath --distpath (Join-Path $RepoRoot 'dist') --noconfirm
    $PyInstallerExitCode = $LASTEXITCODE
} finally { $env:PATH = $OriginalPath }
if ($PyInstallerExitCode -ne 0) { exit $PyInstallerExitCode }
& $PythonExe (Join-Path $RepoRoot 'tools\export_third_party_licenses.py') --audit-analysis (Join-Path $BuildPath 'risk_heatmap_desktop\Analysis-00.toc') --dist-root $DistPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$OnedirExe = Join-Path $DistPath 'RiskAssessmentHeatMap.exe'
if (-not (Test-Path -LiteralPath $OnedirExe -PathType Leaf)) { throw "ONEDIR_NOT_BUILT $OnedirExe" }
Write-Output "ONEDIR_PATH $OnedirExe"
Write-Output "ONEDIR_SHA256 $((Get-FileHash -LiteralPath $OnedirExe -Algorithm SHA256).Hash)"
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue
if (-not $iscc) {
    $isccCandidates = @(
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    )
    $iscc = $isccCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
}
if (-not $iscc) { Write-Error 'INNO_SETUP_NOT_FOUND'; exit 2 }
& $iscc (Join-Path $RepoRoot 'packaging\RiskAssessmentHeatMap.iss')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$InstallerExe = Join-Path $InstallerPath 'RiskAssessmentHeatMap-Setup.exe'
Write-Output "INSTALLER_PATH $InstallerExe"
Write-Output "INSTALLER_SHA256 $((Get-FileHash -LiteralPath $InstallerExe -Algorithm SHA256).Hash)"

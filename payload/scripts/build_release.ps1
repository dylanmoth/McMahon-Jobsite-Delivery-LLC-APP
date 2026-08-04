param(
    [switch]$SkipTests,
    [switch]$RequireSigning,
    [string]$InnoSetupPath = "",
    [string]$CertificateThumbprint = $env:WINDOWS_CERTIFICATE_THUMBPRINT,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Create .venv with Python 3.12 or 3.13 and install .[dev] before building."
}

$Version = (& $Python -c "from mcmahon_dispatch.core.version import __version__; print(__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) {
    throw "Unable to read the application version."
}

Write-Host "Building McMahon Dispatch $Version" -ForegroundColor Cyan

if (-not $SkipTests) {
    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }

    & $Python -m ruff check src tests migrations
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed." }

    & $Python -m black --check src tests migrations
    if ($LASTEXITCODE -ne 0) { throw "Black formatting check failed." }
}

Remove-Item -Recurse -Force build\pyinstaller, dist, release -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force build, release | Out-Null

& $Python scripts\generate_version_info.py `
    --version $Version `
    --output build\version_info.txt
if ($LASTEXITCODE -ne 0) { throw "Version resource generation failed." }

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --workpath build\pyinstaller `
    build\McMahonDispatch.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

function Find-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $kits = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" `
        -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "\\x64\\signtool.exe$" } |
        Sort-Object FullName -Descending
    return ($kits | Select-Object -First 1).FullName
}

function Sign-File([string]$Path) {
    if (-not $CertificateThumbprint) {
        if ($RequireSigning) {
            throw "WINDOWS_CERTIFICATE_THUMBPRINT is required for a production-signed release."
        }
        Write-Warning "Code signing was skipped. Windows SmartScreen may warn users."
        return
    }
    $SignTool = Find-SignTool
    if (-not $SignTool) { throw "signtool.exe was not found. Install the Windows SDK." }
    & $SignTool sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $Path
    if ($LASTEXITCODE -ne 0) { throw "Code signing failed for $Path" }
}

$MainExe = Join-Path $Root "dist\McMahon Dispatch\McMahon Dispatch.exe"
Sign-File $MainExe

if (-not $InnoSetupPath) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $InnoSetupPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $InnoSetupPath -or -not (Test-Path $InnoSetupPath)) {
    throw "Inno Setup 6 was not found. Install it or pass -InnoSetupPath."
}

& $InnoSetupPath `
    "/DAppVersion=$Version" `
    "/DSourceRoot=$Root" `
    installer\McMahonDispatch.iss
if ($LASTEXITCODE -ne 0) { throw "Installer compilation failed." }

$Installer = Join-Path $Root "release\McMahonDispatch-Setup-$Version.exe"
Sign-File $Installer

$Portable = Join-Path $Root "release\McMahonDispatch-Portable-$Version.zip"
Compress-Archive -Path "dist\McMahon Dispatch\*" -DestinationPath $Portable -CompressionLevel Optimal

$InstallerHash = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
$PortableHash = (Get-FileHash $Portable -Algorithm SHA256).Hash.ToLowerInvariant()
"$InstallerHash  $(Split-Path $Installer -Leaf)" |
    Set-Content "$Installer.sha256" -Encoding ascii
@(
    "$InstallerHash  $(Split-Path $Installer -Leaf)"
    "$PortableHash  $(Split-Path $Portable -Leaf)"
) | Set-Content "release\SHA256SUMS.txt" -Encoding ascii

$Manifest = [ordered]@{
    product = "McMahon Dispatch"
    version = $Version
    published_at = (Get-Date).ToUniversalTime().ToString("o")
    minimum_windows_version = "10.0.17763"
    architecture = "x64"
    installer = [ordered]@{
        file = (Split-Path $Installer -Leaf)
        sha256 = $InstallerHash
        size_bytes = (Get-Item $Installer).Length
    }
    portable = [ordered]@{
        file = (Split-Path $Portable -Leaf)
        sha256 = $PortableHash
        size_bytes = (Get-Item $Portable).Length
    }
}
$Manifest | ConvertTo-Json -Depth 5 |
    Set-Content "release\release-manifest.json" -Encoding utf8

Write-Host ""
Write-Host "Release ready in $Root\release" -ForegroundColor Green
Get-ChildItem release | Format-Table Name, Length, LastWriteTime

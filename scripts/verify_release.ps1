param([string]$ReleaseDirectory = ".\release")
$ErrorActionPreference = "Stop"

$ManifestPath = Join-Path $ReleaseDirectory "release-manifest.json"
if (-not (Test-Path $ManifestPath)) { throw "release-manifest.json is missing." }
$Manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json

foreach ($entry in @($Manifest.installer, $Manifest.portable)) {
    $Path = Join-Path $ReleaseDirectory $entry.file
    if (-not (Test-Path $Path)) { throw "$($entry.file) is missing." }
    $Hash = (Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Hash -ne $entry.sha256) { throw "Checksum mismatch for $($entry.file)." }
}
Write-Host "Release files and checksums verified." -ForegroundColor Green

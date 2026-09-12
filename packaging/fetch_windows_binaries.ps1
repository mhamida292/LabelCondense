# Stage gswin64c.exe, its DLL, and poppler's tools into packaging\bin so
# PyInstaller can carry them. The Linux equivalent is collect_binaries.py.
#
# Versions are pinned deliberately: bumping them changes what ships to users,
# so it should be a reviewed change rather than silent drift.
$ErrorActionPreference = "Stop"
$out = Join-Path $PSScriptRoot "bin"
New-Item -ItemType Directory -Force -Path $out | Out-Null

$gsUrl  = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10051/gs10051w64.exe"
$popUrl = "https://github.com/oschwartz10612/poppler-windows/releases/download/v24.08.0-0/Release-24.08.0-0.zip"

Write-Host "Fetching Ghostscript..."
Invoke-WebRequest $gsUrl -OutFile "$env:TEMP\gs.exe"
Start-Process "$env:TEMP\gs.exe" -ArgumentList "/S","/D=$env:TEMP\gs" -Wait
Copy-Item "$env:TEMP\gs\bin\gswin64c.exe" $out
Copy-Item "$env:TEMP\gs\bin\gsdll64.dll"  $out

# Ghostscript needs its Resource/ tree at runtime to find fonts and colour
# profiles. The Linux build stages the same thing; see rthook_gs_env.py, which
# points GS_LIB at it inside the frozen bundle.
$gsRes = Join-Path $PSScriptRoot "gs-resources"
New-Item -ItemType Directory -Force -Path $gsRes | Out-Null
Copy-Item "$env:TEMP\gs\Resource"    $gsRes -Recurse -Force
Copy-Item "$env:TEMP\gs\lib"         $gsRes -Recurse -Force
Copy-Item "$env:TEMP\gs\iccprofiles" $gsRes -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Fetching Poppler..."
Invoke-WebRequest $popUrl -OutFile "$env:TEMP\poppler.zip"
Expand-Archive "$env:TEMP\poppler.zip" -DestinationPath "$env:TEMP\poppler" -Force
Copy-Item "$env:TEMP\poppler\poppler-24.08.0\Library\bin\*" $out -Recurse -Force

# A partial harvest produces a bundle that dies 90 seconds into a real run,
# so fail loudly here instead.
foreach ($required in @("gswin64c.exe", "gsdll64.dll", "pdftotext.exe", "pdfimages.exe")) {
    if (-not (Test-Path (Join-Path $out $required))) {
        throw "staging incomplete: $required is missing from $out"
    }
}

Get-ChildItem $out | Select-Object Name, Length
Write-Host "staged $((Get-ChildItem $out).Count) files into $out"

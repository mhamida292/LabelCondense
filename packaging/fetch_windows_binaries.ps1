# Stage gswin64c.exe, its DLL, and poppler's tools into packaging\bin so
# PyInstaller can carry them. The Linux equivalent is collect_binaries.py.
#
# Versions are pinned deliberately: bumping them changes what ships to users,
# so it should be a reviewed change rather than silent drift.
$ErrorActionPreference = "Stop"

# Windows PowerShell renders a progress bar for every Invoke-WebRequest chunk,
# which costs far more than the transfer itself -- it turns a 70 MB download
# into several minutes on a CI runner. Silencing it is the single biggest
# difference between this step taking seconds and appearing to hang.
$ProgressPreference = "SilentlyContinue"

$out = Join-Path $PSScriptRoot "bin"
New-Item -ItemType Directory -Force -Path $out | Out-Null

$gsUrl  = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10051/gs10051w64.exe"
$popUrl = "https://github.com/oschwartz10612/poppler-windows/releases/download/v24.08.0-0/Release-24.08.0-0.zip"

function Get-SevenZip {
    $cmd = Get-Command 7z -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @("$env:ProgramFiles\7-Zip\7z.exe",
                     "${env:ProgramFiles(x86)}\7-Zip\7z.exe")) {
        if (Test-Path $p) { return $p }
    }
    throw "7-Zip not found; needed to unpack the Ghostscript installer"
}

function Find-File($root, $name) {
    $hit = Get-ChildItem -Path $root -Filter $name -Recurse -File -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if (-not $hit) { throw "$name not found anywhere under $root" }
    return $hit.FullName
}

Write-Host "Fetching Ghostscript..."
$gsExe = Join-Path $env:TEMP "gs.exe"
Invoke-WebRequest $gsUrl -OutFile $gsExe -UseBasicParsing -TimeoutSec 300

# Unpack rather than install. The NSIS installer was previously launched with
# Start-Process -Wait, which can sit forever on a headless runner: nothing
# guarantees the silent installer exits rather than handing off to a child.
# 7-Zip reads the NSIS archive directly, so there is no installer to wait on,
# nothing written outside TEMP, and no elevation needed.
$gsDir = Join-Path $env:TEMP "gs"
Remove-Item $gsDir -Recurse -Force -ErrorAction SilentlyContinue
& (Get-SevenZip) x $gsExe "-o$gsDir" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw "7-Zip failed to unpack $gsExe (exit $LASTEXITCODE)" }

Copy-Item (Find-File $gsDir "gswin64c.exe") $out
Copy-Item (Find-File $gsDir "gsdll64.dll")  $out

# Ghostscript needs its Resource/ tree at runtime to find fonts and colour
# profiles. The Linux build stages the same thing; see rthook_gs_env.py, which
# points GS_LIB at it inside the frozen bundle.
#
# Anchor on Resource\Init\gs_init.ps and walk up three levels, exactly as
# collect_binaries.py does on Linux: the extracted layout is the installer's
# rather than an installed one, so the tree is not where a normal install
# would put it, and gs_init.ps is the only unambiguous landmark.
$gsRes = Join-Path $PSScriptRoot "gs-resources"
New-Item -ItemType Directory -Force -Path $gsRes | Out-Null
$initPs = Get-ChildItem -Path $gsDir -Filter "gs_init.ps" -Recurse -File -ErrorAction SilentlyContinue |
          Where-Object { $_.Directory.Name -eq "Init" -and $_.Directory.Parent.Name -eq "Resource" } |
          Select-Object -First 1
if (-not $initPs) { throw "no Resource\Init\gs_init.ps found under $gsDir" }
$gsRoot = $initPs.Directory.Parent.Parent.FullName     # ...\Resource\Init\ -> root

Copy-Item (Join-Path $gsRoot "Resource") $gsRes -Recurse -Force
Copy-Item (Join-Path $gsRoot "lib")      $gsRes -Recurse -Force
$icc = Join-Path $gsRoot "iccprofiles"
if (Test-Path $icc) { Copy-Item $icc $gsRes -Recurse -Force }

# GS_LIB in rthook_gs_env.py points at Resource\Init first; if that file is
# missing the bundle builds fine and then dies at the end of a real run with
# "Can't find initialization file gs_init.ps".
if (-not (Test-Path (Join-Path $gsRes "Resource\Init\gs_init.ps"))) {
    throw "staging incomplete: gs-resources\Resource\Init\gs_init.ps is missing"
}

Write-Host "Fetching Poppler..."
$popZip = Join-Path $env:TEMP "poppler.zip"
Invoke-WebRequest $popUrl -OutFile $popZip -UseBasicParsing -TimeoutSec 300
$popDir = Join-Path $env:TEMP "poppler"
Remove-Item $popDir -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $popZip -DestinationPath $popDir -Force

# Locate the bin/ directory by finding a tool in it, so a version bump in the
# archive's top-level folder name does not silently stage nothing.
$popBin = Split-Path (Find-File $popDir "pdftotext.exe") -Parent
Copy-Item (Join-Path $popBin "*") $out -Recurse -Force

# A partial harvest produces a bundle that dies 90 seconds into a real run,
# so fail loudly here instead.
foreach ($required in @("gswin64c.exe", "gsdll64.dll", "pdftotext.exe", "pdfimages.exe", "pdftoppm.exe")) {
    if (-not (Test-Path (Join-Path $out $required))) {
        throw "staging incomplete: $required is missing from $out"
    }
}

# Prove the staged executables actually start -- a DLL harvested without its
# dependencies still passes a Test-Path check, then fails on the user's
# machine. GS_LIB is set the way rthook_gs_env.py sets it inside the frozen
# bundle, so this exercises the staged resource tree too.
$env:GS_LIB = @(
    (Join-Path $gsRes "Resource\Init"),
    (Join-Path $gsRes "lib"),
    (Join-Path $gsRes "iccprofiles")
) -join ";"
& (Join-Path $out "gswin64c.exe") --version
if ($LASTEXITCODE -ne 0) { throw "staged gswin64c.exe does not run (exit $LASTEXITCODE)" }
& (Join-Path $out "pdftotext.exe") -v
if ($LASTEXITCODE -ne 0) { throw "staged pdftotext.exe does not run (exit $LASTEXITCODE)" }

Get-ChildItem $out | Select-Object Name, Length
Write-Host "staged $((Get-ChildItem $out).Count) files into $out"

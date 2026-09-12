"""Stage gs/pdftotext/pdfimages and their shared libraries into packaging/bin/
so PyInstaller can carry them. Run before building on Linux."""
import glob, pathlib, shutil, subprocess, sys

TOOLS = ["gs", "pdftotext", "pdfimages"]
OUT = pathlib.Path(__file__).parent / "bin"

# Ghostscript refuses to start without its init files (gs_init.ps) and
# Resource tree — normally found under /usr/share/ghostscript/<version>.
# ldd never reports these (they aren't shared libraries), but a frozen gs
# needs them staged too, or it fails at the very last step of a run with
# "Can't find initialization file gs_init.ps."
GS_RESOURCES = pathlib.Path(__file__).parent / "gs-resources"

def libs_of(binary):
    out = subprocess.run(["ldd", binary], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        parts = line.split()
        for p in parts:
            if p.startswith("/") and pathlib.Path(p).is_file():
                yield pathlib.Path(p)

def stage_gs_resources():
    """Copy gs's Resource/Init/lib tree (found via `gs --help`'s search path,
    typically /usr/share/ghostscript/<ver>) so a frozen gs can initialize
    without the host having Ghostscript installed."""
    candidates = sorted(glob.glob("/usr/share/ghostscript/*/Resource/Init/gs_init.ps"))
    if not candidates:
        sys.exit("missing /usr/share/ghostscript/*/Resource/Init/gs_init.ps — is ghostscript installed?")
    version_dir = pathlib.Path(candidates[-1]).parents[2]
    if GS_RESOURCES.exists():
        shutil.rmtree(GS_RESOURCES)
    shutil.copytree(version_dir / "Resource", GS_RESOURCES / "Resource")
    shutil.copytree(version_dir / "lib", GS_RESOURCES / "lib")
    icc = version_dir / "iccprofiles"
    if icc.is_dir():
        shutil.copytree(icc, GS_RESOURCES / "iccprofiles")

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for tool in TOOLS:
        path = shutil.which(tool)
        if not path:
            sys.exit(f"missing {tool} — install poppler-utils and ghostscript")
        shutil.copy2(path, OUT / tool)
        for lib in libs_of(path):
            target = OUT / lib.name
            if not target.exists():
                shutil.copy2(lib, target)
    stage_gs_resources()
    print(f"staged {len(list(OUT.iterdir()))} files into {OUT}")
    print(f"staged gs Resource/lib tree into {GS_RESOURCES}")

if __name__ == "__main__":
    main()

"""Stage gs/pdftotext/pdfimages and their shared libraries into packaging/bin/
so PyInstaller can carry them. Run before building on Linux or macOS
(Homebrew ghostscript + poppler)."""
import glob, os, pathlib, shutil, subprocess, sys

TOOLS = ["gs", "pdftotext", "pdfimages", "pdftoppm"]
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
    share = f"{BREW}/share" if sys.platform == "darwin" else "/usr/share"
    candidates = glob.glob(f"{share}/ghostscript/*/Resource/Init/gs_init.ps")
    if not candidates:
        sys.exit(f"missing {share}/ghostscript/*/Resource/Init/gs_init.ps — is ghostscript installed?")
    if len(candidates) > 1:
        # Picking by string sort would choose 9.55.0 over 10.06.0, since "9" > "1".
        # Rather than guess a version-comparison rule, refuse and let a human say.
        sys.exit("more than one Ghostscript install found; remove one or stage by hand:\n  "
                 + "\n  ".join(sorted(candidates)))
    version_dir = pathlib.Path(candidates[0]).parents[2]
    if GS_RESOURCES.exists():
        shutil.rmtree(GS_RESOURCES)
    shutil.copytree(version_dir / "Resource", GS_RESOURCES / "Resource")
    shutil.copytree(version_dir / "lib", GS_RESOURCES / "lib")
    icc = version_dir / "iccprofiles"
    if icc.is_dir():
        shutil.copytree(icc, GS_RESOURCES / "iccprofiles")

# ------------------------------------------------------------------- macOS
# Homebrew binaries load their libraries by absolute path (/opt/homebrew/...),
# so copying them is not enough: every reference is rewritten to
# @loader_path/<name>, all files sitting side by side in bin/, and each file is
# re-signed ad hoc (Apple Silicon refuses to run a modified, unsigned binary).
BREW = os.environ.get("HOMEBREW_PREFIX", "/opt/homebrew")
MAC_SYSTEM = ("/usr/lib/", "/System/")

def _otool(*args):
    return subprocess.run(["otool", *args], capture_output=True, text=True, check=True).stdout

def _rpaths(owner):
    lines = _otool("-l", str(owner)).splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "cmd LC_RPATH":
            path = lines[i + 2].split()[1]
            yield pathlib.Path(path.replace("@loader_path", str(owner.parent)))

def _mac_deps(owner):
    """(as-referenced, resolved file) for each non-system library `owner` loads."""
    own_id = _otool("-D", str(owner)).splitlines()[1:]   # empty for executables
    for line in _otool("-L", str(owner)).splitlines()[1:]:
        ref = line.strip().split(" (")[0]
        if ref.startswith(MAC_SYSTEM) or ref in own_id:
            continue
        if ref.startswith(("@loader_path/", "@executable_path/")):
            hits = [owner.parent / ref.split("/", 1)[1]]
        elif ref.startswith("@rpath/"):
            name = ref.split("/", 1)[1]
            hits = [d / name for d in _rpaths(owner)] + [pathlib.Path(BREW, "lib", name)]
        else:
            hits = [pathlib.Path(ref)]
        found = next((h.resolve() for h in hits if h.is_file()), None)
        if found is None:
            sys.exit(f"{owner}: cannot find {ref}")
        yield ref, found

def stage_mac():
    staged = {}                           # staged name -> original file
    todo = []
    for tool in TOOLS:
        path = shutil.which(tool)
        if not path:
            sys.exit(f"missing {tool} — brew install poppler ghostscript")
        staged[tool] = pathlib.Path(path).resolve()
        todo.append(staged[tool])
    while todo:                           # walk the dependency graph
        for ref, lib in _mac_deps(todo.pop()):
            name = pathlib.Path(ref).name
            if name not in staged:
                staged[name] = lib
                todo.append(lib)
    for name, src in staged.items():
        dst = OUT / name
        shutil.copy2(src, dst)
        dst.chmod(0o755)                  # Homebrew installs read-only
        cmd = ["install_name_tool"]
        if name.endswith(".dylib"):
            cmd += ["-id", f"@loader_path/{name}"]
        for ref, _ in _mac_deps(src):
            cmd += ["-change", ref, f"@loader_path/{pathlib.Path(ref).name}"]
        subprocess.run(cmd + [str(dst)], check=True, capture_output=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(dst)],
                       check=True, capture_output=True)
    for f in OUT.iterdir():               # nothing may still point into Homebrew
        for line in _otool("-L", str(f)).splitlines()[1:]:
            ref = line.strip().split(" (")[0]
            if not ref.startswith(MAC_SYSTEM + ("@loader_path/",)):
                sys.exit(f"{f.name} still loads {ref}")

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        stage_mac()
    else:
        stage_linux()
    stage_gs_resources()

    # A silent partial harvest — ldd yielding nothing usable — produces a
    # bundle that looks fine and dies 90 seconds into a real run. Three tools
    # alone is the signature of that; a real harvest runs to dozens of files.
    staged = list(OUT.iterdir())
    if len(staged) < len(TOOLS) + 10:
        sys.exit(f"staging looks incomplete: only {len(staged)} files in {OUT}. "
                 "Check that ldd reported shared libraries for each tool.")
    print(f"staged {len(staged)} files into {OUT}")
    print(f"staged gs Resource/lib tree into {GS_RESOURCES}")

def stage_linux():
    for tool in TOOLS:
        path = shutil.which(tool)
        if not path:
            sys.exit(f"missing {tool} — install poppler-utils and ghostscript")
        shutil.copy2(path, OUT / tool)
        for lib in libs_of(path):
            target = OUT / lib.name
            if not target.exists():
                shutil.copy2(lib, target)

if __name__ == "__main__":
    main()

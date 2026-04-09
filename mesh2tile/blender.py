import os
import sys
import shutil
import subprocess


def find_blender(config_blender_path=None):
    """Find the Blender executable.

    Precedence: config_blender_path > PATH > OS-specific fallback locations.
    Returns path string or None.
    """
    if config_blender_path and os.path.isfile(config_blender_path):
        return config_blender_path

    blender = shutil.which("blender")
    if blender:
        return blender

    if sys.platform == "win32":
        for base in [os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")]:
            blender_dir = os.path.join(base, "Blender Foundation")
            if os.path.isdir(blender_dir):
                versions = sorted(os.listdir(blender_dir), reverse=True)
                for ver in versions:
                    candidate = os.path.join(blender_dir, ver, "blender.exe")
                    if os.path.isfile(candidate):
                        return candidate
    elif sys.platform == "darwin":
        candidate = "/Applications/Blender.app/Contents/MacOS/Blender"
        if os.path.isfile(candidate):
            return candidate
    else:
        for candidate in ["/usr/bin/blender", "/snap/bin/blender"]:
            if os.path.isfile(candidate):
                return candidate

    return None


def check_dependencies(blender_exe):
    """Pre-check all required dependencies and report clear errors.
    Exits with code 1 if any dependency is missing."""
    errors = []

    # Blender
    if not blender_exe:
        errors.append(
            "Blender not found. Install Blender 4.4+ and either:\n"
            "  - Add it to your PATH, or\n"
            "  - Use --blender-path to specify the location, or\n"
            "  - Install to a standard location (e.g. C:\\Program Files\\Blender Foundation\\)"
        )
    else:
        try:
            result = subprocess.run(
                [blender_exe, "--version"],
                capture_output=True, text=True, timeout=15
            )
            version_line = result.stdout.strip().split("\n")[0] if result.stdout else "unknown"
            print(f"  Blender: {version_line} ({blender_exe})")
        except Exception as e:
            errors.append(f"Blender found at {blender_exe} but failed to run: {e}")

    # npx (Node.js)
    npx_path = shutil.which("npx")
    if not npx_path:
        for path in [r"C:\Program Files\nodejs\npx.cmd", r"C:\nvm4w\nodejs\npx.cmd"]:
            if os.path.exists(path):
                npx_path = path
                break
    if not npx_path:
        errors.append(
            "npx not found. Install Node.js (which includes npx) and add it to your PATH.\n"
            "  Node.js is required for tileset.json generation via 3d-tiles-tools."
        )
    else:
        print(f"  npx: {npx_path}")

    # numpy
    try:
        import numpy
        print(f"  numpy: {numpy.__version__}")
    except ImportError:
        errors.append(
            "numpy not found. Install it with:\n"
            "  pip install numpy   (or: pip install -r requirements.txt)"
        )

    if errors:
        print("\n[ERROR] Missing dependencies:\n")
        for i, err in enumerate(errors, 1):
            print(f"  {i}. {err}\n")
        sys.exit(1)

    print()

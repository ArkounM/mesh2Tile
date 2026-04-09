import subprocess
import os
import shutil


def _find_npx():
    """Find npx executable, checking common locations."""
    npx = shutil.which("npx")
    if npx:
        return npx
    for path in [
        r"C:\Program Files\nodejs\npx.cmd",
        r"C:\nvm4w\nodejs\npx.cmd",
    ]:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("npx not found. Install Node.js or set it in your PATH.")


NODE_PATH = _find_npx()


def generate_tileset_json(output_dir, longitude="0.0", latitude="0.0", height="0.0",
                          tiles_tools_version="0.5.3"):
    """Generate tileset.json in the output directory using 3d-tiles-tools."""
    print(f"Generating tileset.json in {output_dir}...")
    tool = f"3d-tiles-tools@{tiles_tools_version}"
    subprocess.run([
        NODE_PATH, tool, "createTilesetJson",
        "-i", output_dir,
        "-o", os.path.join(output_dir, "tileset.json"),
        "-f",
        "--cartographicPositionDegrees", longitude, latitude, height
    ], check=True)


def gzip_output(output_path, tiles_tools_version="0.5.3"):
    """Gzip tiles in the output directory."""
    print("Gzipping tiles...")
    tool = f"3d-tiles-tools@{tiles_tools_version}"
    subprocess.run([
        NODE_PATH, tool, "gzip",
        "-i", output_path,
        "-o", output_path,
        "-f",
    ], check=True)

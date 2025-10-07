import subprocess
import os

NODE_PATH = r"C:\Program Files\nodejs\npx.cmd"

def generate_tileset_json(output_dir, longitude="-75.703833", latitude="45.417139", height="77.572"):
    """
    Generate tileset.json in the output directory using 3d-tiles-tools.
    """
    print(f"Generating tileset.json in {output_dir}...")
    subprocess.run([
        NODE_PATH, "3d-tiles-tools", "createTilesetJson",
        "-i", output_dir,
        "-o", os.path.join(output_dir, "tileset.json"),
        "-f",
        "--cartographicPositionDegrees", longitude, latitude, height
    ], check=True)

def gzip_output(output_path):
    print("Gzipping tiles...")
    subprocess.run([
        r"C:\Program Files\nodejs\npx.cmd", "3d-tiles-tools", "gzip",
        "-i", output_path,
        "-o", output_path,
        "-f",
    ], check=True)
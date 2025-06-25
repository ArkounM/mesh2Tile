import os
import subprocess

NODE_PATH = r"C:\Program Files\nodejs\npx.cmd"  # Adjust if needed

def convert_obj_to_glb(input_dir, output_dir):
    """
    Convert all OBJ files in a directory to GLB using obj23dtiles.
    """
    print(f"Converting OBJs in {input_dir} to GLB...")
    os.makedirs(output_dir, exist_ok=True)

    for file_name in os.listdir(input_dir):
        if file_name.lower().endswith(".obj"):
            input_obj_path = os.path.join(input_dir, file_name)

            # Run obj23dtiles
            subprocess.run([
                NODE_PATH, "obj23dtiles",
                "-i", input_obj_path, "-b"
            ], check=True)

            # Move resulting GLB into output dir
            for file in os.listdir(os.path.dirname(input_obj_path)):
                if file.lower().endswith(".glb"):
                    src = os.path.join(os.path.dirname(input_obj_path), file)
                    dst = os.path.join(output_dir, file)
                    if os.path.abspath(src) != os.path.abspath(dst):
                        os.replace(src, dst)
                        print(f"Moved: {dst}")

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
    
import subprocess
import os

NODE_PATH = r"C:\Program Files\nodejs\npx.cmd"

def convert_obj_to_glb(input_dir, output_dir):
    print(f"Converting OBJs in {input_dir} to GLB...")
    os.makedirs(output_dir, exist_ok=True)

    for file_name in os.listdir(input_dir):
        if not file_name.lower().endswith(".obj"):
            continue
        

        input_obj_path = os.path.join(input_dir, file_name)

        try:
            subprocess.run([
                NODE_PATH, "obj23dtiles",
                "-i", input_obj_path, "-b"
            ], check=True)

            # Move resulting .glb to output
            for file in os.listdir(os.path.dirname(input_obj_path)):
                if file.lower().endswith(".glb"):
                    src = os.path.join(os.path.dirname(input_obj_path), file)
                    dst = os.path.join(output_dir, file)
                    if os.path.abspath(src) != os.path.abspath(dst):
                        os.replace(src, dst)
                        print(f"✅ Converted: {file}")

        except subprocess.CalledProcessError:
            print(f"❌ Failed to convert {file_name} — skipping (non-zero exit code)")
        except Exception as e:
            print(f"❌ Unexpected error converting {file_name}: {e}")

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
    
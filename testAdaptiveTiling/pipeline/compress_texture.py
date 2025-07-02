import argparse
import os
from PIL import Image

def parse_obj_for_mtl(obj_path):
    with open(obj_path, "r") as file:
        for line in file:
            if line.startswith("mtllib"):
                return os.path.join(os.path.dirname(obj_path), line.split()[1].strip())
    raise FileNotFoundError("No .mtl file found in the OBJ file.")

def parse_mtl_for_texture(mtl_path):
    with open(mtl_path, "r") as file:
        for line in file:
            if line.lower().startswith("map_kd"):
                texture_path = line.split(" ",1)[1].strip()
                # Handle relative texutre paths
                return os.path.join(os.path.dirname(mtl_path), texture_path)
    raise FileNotFoundError("No texture file (map_kd) found in the MTL file")

def generate_lods(texture_path, num_lods):
    base_name, ext = os. path.splitext(os.path.basename(texture_path))
    image = Image.open(texture_path)
    width, height = image.size

    for i in range(num_lods):
        scale = 2 ** (i + 1) 
        new_width = max(1, width // scale)
        new_height = max(1, height // scale)
        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        lod_filename = f"{base_name}_LOD{i}{ext}"
        lod_path = os.path.join(os.path.dirname(texture_path), lod_filename)
        resized.save(lod_path)
        print(f"Saved: {lod_path} ({new_width}x{new_height})")

def main():
    parser = argparse.ArgumentParser(description="Generate LOD textures from an OBJ file.")
    parser.add_argument("input", type=str, help="Path to the input OBJ file")
    parser.add_argument("-l", "--lods", type=int, default=3, help= "Number of LOD levels to generate (default:3)")
    parser.add_argument("-c", "--compress", type=int, default=0, help="Factor to compress textures (0 for no compression, 1 for low, 2 for medium, 3 for high)")

    args = parser.parse_args()
    obj_path = args.input
    num_lods = args.lods
    compress = args.compress

    mtl_path = parse_obj_for_mtl(obj_path)
    texture_path = parse_mtl_for_texture(mtl_path)
    generate_lods(texture_path, num_lods)

def run_texture_compression(obj_path, num_lods, output_folder, compress=0):
    mtl_path = parse_obj_for_mtl(obj_path)
    texture_path = parse_mtl_for_texture(mtl_path)

    output_texture_dir = os.path.join(output_folder, "temp", "texture")
    os.makedirs(output_texture_dir, exist_ok=True)

    base_name, ext = os.path.splitext(os.path.basename(texture_path))
    image = Image.open(texture_path)
    width, height = image.size

    for i in range(num_lods):
        scale = 2 ** (i + compress)
        new_width = max(1, width // scale)
        new_height = max(1, height // scale)
        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        lod_filename = f"{base_name}_LOD{i}{ext}"
        lod_path = os.path.join(output_texture_dir, lod_filename)
        resized.save(lod_path, format="PNG", optimize=True, compress_level=9)
        print(f"Saved: {lod_path} ({new_width}x{new_height})")



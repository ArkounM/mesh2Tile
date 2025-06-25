import argparse
import os
import sys
import shutil

from pipeline.compress_texture import run_texture_compression
from pipeline.generate_LODs import run_blender_lod_gen
from pipeline.assignTexture2LOD import update_mtl_texture_path
from pipeline.tileLOD import run_blender_script
from pipeline.obj2glb_pipeline import convert_obj_to_glb, generate_tileset_json, gzip_output
from pipeline.createTilesetJson import restructure_tileset


def main():
    # === Parse CLI arguments ===
    parser = argparse.ArgumentParser(description="Full mesh-to-tileset pipeline.")
    parser.add_argument("--input", "-i", required=True, help="Path to input OBJ file")
    parser.add_argument("--output", "-o", required=True, help="Path to output folder")
    parser.add_argument("--lods", "-l", type=int, default=3, help="Number of LODs to generate (default: 3)")
    parser.add_argument("--gzip", action="store_true", help="Enable gzip compression for output")
    parser.add_argument("--temp", action="store_true", help="Preserve the temp folder after processing")
    args = parser.parse_args()

    input = os.path.abspath(args.input)
    output = os.path.abspath(args.output)
    lods = args.lods

    # === Blender config ===
    blender_exe = "C:/Program Files/Blender Foundation/Blender 4.4/blender.exe"
    blender_script = "./pipeline/BlenderScripts/lodOBJ_simple.py"
    tiling_script = "./pipeline/BlenderScripts/tileOBJ.py"

    # === Step 1: Texture compression ===
    run_texture_compression(input, lods, output)

    # === Step 2: LOD mesh generation ===
    run_blender_lod_gen(blender_exe, blender_script, input, output, lods)

    # === Step 3: Update MTLs with new texture paths ===
    lod_dir = os.path.join(output, "temp", "lods")
    texture_dir = os.path.join(output, "temp", "texture")
    update_mtl_texture_path(lod_dir, texture_dir)

    # === Step 4: Tile each LOD OBJ ===
    tiles_base_dir = os.path.join(output, "temp", "tiles")
    os.makedirs(tiles_base_dir, exist_ok=True)

    for filename in os.listdir(lod_dir):
        if filename.lower().endswith(".obj"):
            lod_level = "LOD0" if "LOD0" in filename.upper() else \
                        "LOD1" if "LOD1" in filename.upper() else \
                        "LOD2" if "LOD2" in filename.upper() else "unknown"

            if lod_level == "unknown":
                print(f"Skipping {filename}: LOD level not detected.")
                continue

            input_path = os.path.join(lod_dir, filename)
            output_dir = os.path.join(tiles_base_dir, lod_level.lower())
            os.makedirs(output_dir, exist_ok=True)

            run_blender_script(
                input_path=input_path,
                output_dir=output_dir,
                blender_exe=blender_exe,
                script_path=tiling_script
            )

    # === Step 5: Convert tiles to GLB + Generate tilesets ===
    for lod in os.listdir(tiles_base_dir):
        lod_dir = os.path.join(tiles_base_dir, lod)
        if not os.path.isdir(lod_dir):
            continue
        convert_obj_to_glb(lod_dir, output)

    # === Step 6: Clean up temp directory unless --temp is used ===
    temp_dir = os.path.join(output, "temp")
    if not args.temp and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    # === Step 7: Generate and restructure tileset.json ===
    tileset_path = os.path.join(output, "tileset.json")
    generate_tileset_json(output)
    restructure_tileset(tileset_path, tileset_path)

    # === Step 8: Gzip the final output if --gzip is enabled ===
    if args.gzip:
        gzip_output(output)

    print("GLB conversion and tileset generation complete.")


if __name__ == "__main__":
    main()

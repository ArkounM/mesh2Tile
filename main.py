import argparse
import os
import sys
import shutil
import glob

from pipeline.flip_obj_axes import flip_obj_axes
from pipeline.compress_texture import run_texture_compression
from pipeline.generate_LODs import run_blender_lod_gen
from pipeline.assignTexture2LOD import update_mtl_texture_path
from pipeline.tileLOD import run_blender_script, run_blender_bake
from pipeline.obj2glb_pipeline import convert_obj_to_glb, generate_tileset_json, gzip_output
from pipeline.createTilesetJson import restructure_tileset


def find_obj_files(input_dir):
    """
    Recursively find all OBJ files in the input directory and its subdirectories.
    Returns a list of absolute paths to OBJ files.
    """
    obj_files = []
    for root, dirs, files in os.walk(input_dir):
        for file in files:
            if file.lower().endswith('.obj'):
                obj_files.append(os.path.join(root, file))
    return obj_files


def process_single_obj(input_file, output_base_dir, args, blender_config):
    """
    Process a single OBJ file through the entire pipeline.
    """
    print(f"\n{'='*60}")
    print(f"Processing: {input_file}")
    print(f"{'='*60}")
    
    # Get the base name of the input file (e.g., building_LOD400.obj → building_LOD400)
    input_basename = os.path.splitext(os.path.basename(input_file))[0]
    
    # Create output directory for this specific model
    model_output_dir = os.path.join(output_base_dir, input_basename)
    os.makedirs(model_output_dir, exist_ok=True)
    
    print(f"Output directory: {model_output_dir}")
    
    # Create a working copy of the input file in case we need to flip axes
    working_input = input_file
    if args.flip_x or args.flip_y or args.flip_z:
        print("  → Flipping OBJ axes...")
        # Create a temporary copy to modify
        temp_input = os.path.join(model_output_dir, f"temp_{input_basename}.obj")
        shutil.copy2(input_file, temp_input)
        
        flip_obj_axes(
            input_file=temp_input,
            output_file=None,  # Overwrite in-place
            flip_x=args.flip_x,
            flip_y=args.flip_y,
            flip_z=args.flip_z,
            flip_normals=args.flip_normals
        )
        working_input = temp_input
    
    try:
        # === Step 1: Texture compression ===
        print("  → Running texture compression...")
        run_texture_compression(working_input, args.lods, model_output_dir, args.compress)
        
        # === Step 2: LOD mesh generation ===
        print("  → Generating LOD meshes...")
        run_blender_lod_gen(
            blender_config['exe'], 
            blender_config['lod_script'], 
            working_input, 
            model_output_dir, 
            args.lods
        )
        
        # === Step 3: Update MTLs with new texture paths ===
        print("  → Updating MTL texture paths...")
        lod_dir = os.path.join(model_output_dir, "temp", "lods")
        texture_dir = os.path.join(model_output_dir, "temp", "texture")
        update_mtl_texture_path(lod_dir, texture_dir)
        
        # === Step 4: Tile each LOD OBJ ===
        print("  → Tiling LOD meshes...")
        tiles_base_dir = os.path.join(model_output_dir, "temp", "tiles")
        os.makedirs(tiles_base_dir, exist_ok=True)
        
        for filename in os.listdir(lod_dir):
            if filename.lower().endswith(".obj"):
                lod_level = "LOD0" if "LOD0" in filename.upper() else \
                            "LOD1" if "LOD1" in filename.upper() else \
                            "LOD2" if "LOD2" in filename.upper() else "unknown"
                
                if lod_level == "unknown":
                    print(f"    Skipping {filename}: LOD level not detected.")
                    continue
                
                input_path = os.path.join(lod_dir, filename)
                output_dir = os.path.join(tiles_base_dir, lod_level.lower())
                os.makedirs(output_dir, exist_ok=True)
                
                run_blender_script(
                    input_path=input_path,
                    output_dir=output_dir,
                    blender_exe=blender_config['exe'],
                    script_path=blender_config['tiling_script']
                )
        
        # === Step 4.5: Bake textures to tiled OBJs ===
        print("  → Baking textures...")
        for lod in os.listdir(tiles_base_dir):
            lod_dir_path = os.path.join(tiles_base_dir, lod)
            if not os.path.isdir(lod_dir_path):
                continue
            
            print(f"    Baking textures in: {lod_dir_path}")
            baked_output_dir = os.path.join(lod_dir_path, "baked")
            run_blender_bake(
                blender_exe=blender_config['exe'],
                script_path=blender_config['baking_script'],
                input_folder=lod_dir_path,
                output_folder=baked_output_dir
            )
        
        # === Step 5: Convert tiles to GLB + Generate tilesets ===
        print("  → Converting to GLB and generating tilesets...")
        for lod in os.listdir(tiles_base_dir):
            lod_dir_path = os.path.join(tiles_base_dir, lod, "baked")
            if not os.path.isdir(lod_dir_path):
                continue
            
            try:
                convert_obj_to_glb(lod_dir_path, model_output_dir)
            except Exception as e:
                print(f"    Skipping LOD folder '{lod}': {e}")
        
        # === Step 6: Clean up temp directory unless --temp is used ===
        temp_dir = os.path.join(model_output_dir, "temp")
        if not args.temp and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        
        # Clean up temporary input file if we created one
        if working_input != input_file and os.path.exists(working_input):
            os.remove(working_input)
        
        # === Step 7: Generate and restructure tileset.json ===
        print("  → Generating tileset.json...")
        tileset_path = os.path.join(model_output_dir, "tileset.json")
        generate_tileset_json(model_output_dir)
        restructure_tileset(tileset_path, tileset_path)
        
        # === Step 8: Gzip the final output if --gzip is enabled ===
        if args.gzip:
            print("  → Applying gzip compression...")
            gzip_output(model_output_dir)
        
        print(f"  ✓ Successfully processed: {input_basename}")
        
    except Exception as e:
        print(f"  ✗ Error processing {input_basename}: {str(e)}")
        return False
    
    return True


def main():
    # === Parse CLI arguments ===
    parser = argparse.ArgumentParser(description="Batch mesh-to-tileset pipeline for directory processing.")
    parser.add_argument("--input", "-i", required=True, help="Path to input directory containing OBJ files")
    parser.add_argument("--output", "-o", required=True, help="Path to output directory")
    parser.add_argument("--lods", "-l", type=int, default=3, help="Number of LODs to generate (default: 3)")
    parser.add_argument("--gzip", action="store_true", help="Enable gzip compression for output")
    parser.add_argument("--temp", action="store_true", help="Preserve the temp folder after processing")
    parser.add_argument("--flip-x", action="store_true", help="Flip X axis of input OBJ")
    parser.add_argument("--flip-y", action="store_true", help="Flip Y axis of input OBJ")
    parser.add_argument("--flip-z", action="store_true", help="Flip Z axis of input OBJ")
    parser.add_argument("--flip-normals", action="store_true", help="Flip normals as well")
    parser.add_argument("-c", "--compress", type=int, default=0, help="Texture compression level (Default 0: none, 1: low, 2: medium, 3: high)")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue processing other files if one fails")

    args = parser.parse_args()

    # Validate input directory
    input_dir = os.path.abspath(args.input)
    if not os.path.isdir(input_dir):
        print(f"Error: Input path '{args.input}' is not a valid directory.")
        sys.exit(1)
    
    # Create output directory
    output_dir = os.path.abspath(args.output)
    os.makedirs(output_dir, exist_ok=True)
    
    # === Blender config ===
    blender_config = {
        'exe': "C:/Program Files/Blender Foundation/Blender 4.4/blender.exe",
        'lod_script': "./BlenderScripts/lodOBJ.py",
        'tiling_script': "./BlenderScripts/tileOBJ.py",
        'baking_script': "./BlenderScripts/bakeTextures.py"
    }
    
    # Find all OBJ files in the input directory
    print(f"Searching for OBJ files in: {input_dir}")
    obj_files = find_obj_files(input_dir)
    
    if not obj_files:
        print("No OBJ files found in the input directory or its subdirectories.")
        sys.exit(1)
    
    print(f"Found {len(obj_files)} OBJ file(s) to process:")
    for obj_file in obj_files:
        print(f"  - {obj_file}")
    
    # Process each OBJ file
    successful_count = 0
    failed_count = 0
    
    for i, obj_file in enumerate(obj_files, 1):
        print(f"\nProcessing file {i}/{len(obj_files)}")
        
        success = process_single_obj(obj_file, output_dir, args, blender_config)
        
        if success:
            successful_count += 1
        else:
            failed_count += 1
            if not args.continue_on_error:
                print("Stopping due to error. Use --continue-on-error to process remaining files.")
                break
    
    # Summary
    print(f"\n{'='*60}")
    print("BATCH PROCESSING COMPLETE")
    print(f"{'='*60}")
    print(f"Successfully processed: {successful_count} file(s)")
    print(f"Failed to process: {failed_count} file(s)")
    print(f"Output directory: {output_dir}")
    
    if failed_count > 0 and not args.continue_on_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
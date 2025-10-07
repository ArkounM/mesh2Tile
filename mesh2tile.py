import argparse
import os
import sys
import shutil
import glob
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

# Fix Unicode encoding issues on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

from pipeline.triggerBlender import run_blender_script, run_blender_bake
from pipeline.node_processes import generate_tileset_json, gzip_output
from pipeline.blender_obj2glb import convert_obj_to_glb_blender
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


def bake_lod_folder(args):
    """Worker function for parallel baking of a single LOD folder"""
    lod, tiling_dir_path, blender_config = args
    baked_output_dir = os.path.join(tiling_dir_path, "baked")
    try:
        print(f"    Starting bake for LOD: {lod}")
        run_blender_bake(
            blender_exe=blender_config['exe'],
            script_path=blender_config['baking_script'],
            input_folder=tiling_dir_path,
            output_folder=baked_output_dir
        )
        return lod, True, None
    except Exception as e:
        return lod, False, str(e)


def convert_lod_to_glb(args):
    """Worker function for parallel GLB conversion of a single LOD folder"""
    lod, tiling_dir_path, model_output_dir, blender_config = args
    try:
        print(f"    Starting GLB conversion for LOD: {lod}")
        success = convert_obj_to_glb_blender(
            input_dir=tiling_dir_path,
            output_dir=model_output_dir,
            blender_exe=blender_config['exe'],
            script_path=blender_config['obj2glb_script']
        )
        return lod, success, None if success else "Blender conversion failed"
    except Exception as e:
        return lod, False, str(e)


def process_single_obj(input_file, output_base_dir, args, blender_config):
    """
    Process a single OBJ file through the entire pipeline with parallelization.
    """
    print(f"\n{'='*60}")
    print(f"Processing: {input_file}")
    print(f"{'='*60}")
    
    # Get the base name of the input file (e.g., building_LOD400.obj → building_LOD400)
    input_basename = os.path.splitext(os.path.basename(input_file))[0]
    
    # Create output directory for this specific model
    model_output_dir = os.path.join(output_base_dir, input_basename)
    
    # Check if output directory already exists
    if os.path.exists(model_output_dir):
        if args.force:
            print(f"  ⚠ Output directory exists, removing due to --force: {model_output_dir}")
            shutil.rmtree(model_output_dir)
        else:
            print(f"  ⊗ Output directory already exists, skipping: {model_output_dir}")
            return None  # Return None to indicate skipped (not success or failure)

    os.makedirs(model_output_dir, exist_ok=True)
    
    print(f"Output directory: {model_output_dir}")

    try:
        
        # === Step 1: Run adaptive Tiling on Mesh ===
        print("  → Generating tiles using octree format...")
        tiling_dir = os.path.join(model_output_dir, "temp", "tiles")
        run_blender_script(
            input_path=input_file,
            output_dir=tiling_dir,
            blender_exe=blender_config['exe'],
            script_path=blender_config['adaptive_tiling_script']
        )

        # === Step 2: Bake textures to tiled OBJs (PARALLELIZED) ===
        print("  → Baking textures (parallel processing)...")
        
        # Collect all LOD folders that need baking
        bake_tasks = []
        for lod in os.listdir(tiling_dir):
            tiling_dir_path = os.path.join(tiling_dir, lod)
            if not os.path.isdir(tiling_dir_path):
                continue
            bake_tasks.append((lod, tiling_dir_path, blender_config))
        
        if bake_tasks:
            # Determine optimal number of workers
            # Use fewer workers if GPU baking to avoid GPU memory issues
            # For CPU baking, can use more workers
            max_bake_workers = args.max_bake_workers if hasattr(args, 'max_bake_workers') else min(4, max(1, multiprocessing.cpu_count() // 2))
            
            print(f"    Launching {len(bake_tasks)} baking tasks with {max_bake_workers} workers")
            
            with ProcessPoolExecutor(max_workers=max_bake_workers) as executor:
                futures = {executor.submit(bake_lod_folder, task): task[0] for task in bake_tasks}
                
                for future in as_completed(futures):
                    lod = futures[future]
                    try:
                        result_lod, success, error = future.result()
                        if success:
                            print(f"    ✓ Baked LOD: {result_lod}")
                        else:
                            print(f"    ✗ Failed to bake LOD {result_lod}: {error}")
                    except Exception as e:
                        print(f"    ✗ Exception during baking LOD {lod}: {e}")
        else:
            print("    No LOD folders found for baking")
        
        # === Step 3: Convert tiles to GLB + Generate tilesets (PARALLELIZED) ===
        print("  → Converting to GLB and generating tilesets (parallel processing)...")
        
        # Collect all baked LOD folders for GLB conversion
        conversion_tasks = []
        for lod in os.listdir(tiling_dir):
            tiling_dir_path = os.path.join(tiling_dir, lod, "baked")
            if not os.path.isdir(tiling_dir_path):
                continue
            conversion_tasks.append((lod, tiling_dir_path, model_output_dir, blender_config))
        
        if conversion_tasks:
            # GLB conversion using Blender - can now safely use parallelism
            # No longer using obj23dtiles/npm which had cache contention issues
            max_conversion_workers = args.max_conversion_workers if hasattr(args, 'max_conversion_workers') else min(4, max(1, multiprocessing.cpu_count() // 2))

            print(f"    Launching {len(conversion_tasks)} conversion tasks with {max_conversion_workers} workers (Blender-based)")
            
            with ProcessPoolExecutor(max_workers=max_conversion_workers) as executor:
                futures = {executor.submit(convert_lod_to_glb, task): task[0] for task in conversion_tasks}
                
                for future in as_completed(futures):
                    lod = futures[future]
                    try:
                        result_lod, success, error = future.result()
                        if success:
                            print(f"    ✓ Converted LOD: {result_lod}")
                        else:
                            print(f"    ✗ Failed to convert LOD {result_lod}: {error}")
                    except Exception as e:
                        print(f"    ✗ Exception during conversion LOD {lod}: {e}")
        else:
            print("    No baked LOD folders found for conversion")
        
        # === Step 4: Clean up temp directory unless --temp is used ===
        temp_dir = os.path.join(model_output_dir, "temp")
        if not args.temp and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        
        # === Step 5: Generate and restructure tileset.json ===
        print("  → Generating tileset.json...")
        tileset_path = os.path.join(model_output_dir, "tileset.json")
        generate_tileset_json(model_output_dir,
                            longitude=args.longitude,
                            latitude=args.latitude,
                            height=args.height)
        restructure_tileset(tileset_path, tileset_path)
        
        # === Step 6: Gzip the final output if --gzip is enabled ===
        if args.gzip:
            print("  → Applying gzip compression...")
            gzip_output(model_output_dir)
        
        print(f"  ✓ Successfully processed: {input_basename}")
        
    except Exception as e:
        print(f"  ✗ Error processing {input_basename}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


def main():
    # === Parse CLI arguments ===
    parser = argparse.ArgumentParser(description="Batch mesh-to-tileset pipeline for directory processing with parallelization.")
    parser.add_argument("--input", "-i", required=True, help="Path to input directory containing OBJ files")
    parser.add_argument("--output", "-o", required=True, help="Path to output directory")
    parser.add_argument("--lods", "-l", type=int, default=3, help="Number of LODs to generate (default: 3)")
    parser.add_argument("--gzip", action="store_true", help="Enable gzip compression for output")
    parser.add_argument("--temp", action="store_true", help="Preserve the temp folder after processing")
    parser.add_argument("--force", action="store_true", help="Force overwrite if output directory already exists")
    parser.add_argument("-c", "--compress", type=int, default=0, help="Texture compression level (Default 0: none, 1: low, 2: medium, 3: high)")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue processing other files if one fails")
    
    # Parallelization options
    parser.add_argument("--max-bake-workers", type=int, default=None,
                       help="Maximum parallel Blender instances for baking (default: CPU cores / 2, max 4 for GPU)")
    parser.add_argument("--max-conversion-workers", type=int, default=None,
                       help="Maximum parallel workers for GLB conversion (default: CPU cores)")

    # Geolocation options
    parser.add_argument("--longitude", type=str, default="-75.703833",
                       help="Longitude in degrees (default: -75.703833)")
    parser.add_argument("--latitude", type=str, default="45.417139",
                       help="Latitude in degrees (default: 45.417139)")
    parser.add_argument("--height", type=str, default="77.572",
                       help="Height in meters (default: 77.572)")

    args = parser.parse_args()
    
    # Set default worker counts if not specified
    if args.max_bake_workers is None:
        # Conservative default: use half CPU cores, max 4 (good for GPU baking)
        args.max_bake_workers = min(4, max(1, multiprocessing.cpu_count() // 2))
    
    if args.max_conversion_workers is None:
        # GLB conversion using Blender can use moderate parallelism
        args.max_conversion_workers = min(4, max(1, multiprocessing.cpu_count() // 2))

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
        'exe': "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe",
        'lod_script': "./BlenderScripts/lodOBJ.py",
        'tiling_script': "./BlenderScripts/tileOBJ.py",
        'baking_script': "./BlenderScripts/bakeTextures.py",
        'adaptive_tiling_script': "./BlenderScripts/adaptiveTiling.py",
        'obj2glb_script': "./BlenderScripts/obj2glb.py"
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
    
    print(f"\nParallelization settings:")
    print(f"  Max baking workers: {args.max_bake_workers}")
    print(f"  Max conversion workers: {args.max_conversion_workers}")
    print(f"  Available CPU cores: {multiprocessing.cpu_count()}")
    
    # Process each OBJ file
    successful_count = 0
    failed_count = 0
    skipped_count = 0
    
    for i, obj_file in enumerate(obj_files, 1):
        print(f"\nProcessing file {i}/{len(obj_files)}")
        
        result = process_single_obj(obj_file, output_dir, args, blender_config)
        
        if result is True:
            successful_count += 1
        elif result is False:
            failed_count += 1
            if not args.continue_on_error:
                print("Stopping due to error. Use --continue-on-error to process remaining files.")
                break
        else:  # result is None (skipped)
            skipped_count += 1
    
    # Summary
    print(f"\n{'='*60}")
    print("BATCH PROCESSING COMPLETE")
    print(f"{'='*60}")
    print(f"Successfully processed: {successful_count} file(s)")
    print(f"Skipped (already exists): {skipped_count} file(s)")
    print(f"Failed to process: {failed_count} file(s)")
    print(f"Output directory: {output_dir}")
    
    if failed_count > 0 and not args.continue_on_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
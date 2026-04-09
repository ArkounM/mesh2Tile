import os
import sys
import multiprocessing

# Fix Unicode encoding issues on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

import argparse

from mesh2tile import __version__
from mesh2tile.config import load_config, save_config, get_script_path, write_config_for_blender
from mesh2tile.blender import find_blender, check_dependencies
from mesh2tile.core import find_obj_files, process_single_obj


def main():
    parser = argparse.ArgumentParser(
        description="OBJ to Cesium 3D Tiles converter with adaptive octree tiling."
    )
    parser.add_argument("--version", action="version", version=f"mesh2tile {__version__}")
    parser.add_argument("--input", "-i", required=True, help="Path to input directory containing OBJ files")
    parser.add_argument("--output", "-o", required=True, help="Path to output directory")
    parser.add_argument("--lods", "-l", type=int, default=None, help="Number of LOD levels to generate (default: 3)")
    parser.add_argument("--gzip", action="store_true", help="Enable gzip compression for output")
    parser.add_argument("--temp", action="store_true", help="Preserve the temp folder after processing")
    parser.add_argument("--force", action="store_true", help="Force overwrite if output directory already exists")
    parser.add_argument("-c", "--compress", type=int, default=0,
                        help="Texture compression level (Default 0: none, 1: low, 2: medium, 3: high)")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue processing other files if one fails")

    # Config
    parser.add_argument("--config", type=str, default=None, help="Path to JSON config file")
    parser.add_argument("--save-config", type=str, default=None, help="Save resolved config to JSON file and exit")

    # Blender
    parser.add_argument("--blender-path", type=str, default=None, help="Path to Blender executable (overrides auto-detection)")

    # Tuning
    parser.add_argument("--triangle-threshold", type=int, default=None, help="Triangles per tile (default: 20000)")
    parser.add_argument("--bake-samples", type=int, default=None, help="Cycles bake samples (default: 128)")
    parser.add_argument("--texture-max-size", type=int, default=None, help="Max bake texture dimension (default: 1024)")

    # Parallelization
    parser.add_argument("--max-bake-workers", type=int, default=None,
                        help="Maximum parallel Blender instances for baking (default: CPU/2, max 8)")
    parser.add_argument("--max-conversion-workers", type=int, default=None,
                        help="Maximum parallel workers for GLB conversion (default: CPU/2, max 8)")
    parser.add_argument("--batch-bake", action="store_true",
                        help="Batch baking mode (per LOD in single Blender session)")
    parser.add_argument("--parallel-tiling", action="store_true",
                        help="Enable parallel octree tiling (process first-level chunks in parallel)")
    parser.add_argument("--max-tiling-workers", type=int, default=None,
                        help="Maximum parallel workers for tiling (default: 4)")

    # Pre-splitting
    parser.add_argument("--presplit-threshold", type=int, default=None,
                        help="Face count threshold for pre-splitting (default: 20M, 0 to disable)")

    # Geolocation
    parser.add_argument("--longitude", type=str, default=None, help="Longitude in degrees (default: 0.0)")
    parser.add_argument("--latitude", type=str, default=None, help="Latitude in degrees (default: 0.0)")
    parser.add_argument("--height", type=str, default=None, help="Height in meters (default: 0.0)")

    args = parser.parse_args()

    # Build resolved config
    config = load_config(args)

    # Handle --save-config
    if args.save_config:
        save_config(config, args.save_config)
        print(f"Config saved to: {args.save_config}")
        return

    # Validate input
    input_dir = os.path.abspath(args.input)
    if not os.path.isdir(input_dir):
        print(f"Error: Input path '{args.input}' is not a valid directory.")
        sys.exit(1)

    output_dir = os.path.abspath(args.output)
    os.makedirs(output_dir, exist_ok=True)

    # Find Blender
    blender_exe = find_blender(config.get("blender_path"))
    print("Checking dependencies...")
    check_dependencies(blender_exe)

    # Build blender_config (runtime paths, not user-configurable)
    blender_config = {
        'exe': blender_exe,
        'baking_script': get_script_path("bakeTextures.py"),
        'single_tile_bake_script': get_script_path("bakeSingleTile.py"),
        'adaptive_tiling_script': get_script_path("adaptiveTiling.py"),
        'adaptive_tiling_worker_script': get_script_path("adaptiveTilingWorker.py"),
        'obj2glb_script': get_script_path("obj2glb.py"),
    }

    # Write config for Blender subprocesses
    config_path = write_config_for_blender(config, output_dir)

    # Find OBJ files
    print(f"Searching for OBJ files in: {input_dir}")
    obj_files = find_obj_files(input_dir)

    if not obj_files:
        print("No OBJ files found in the input directory or its subdirectories.")
        sys.exit(1)

    print(f"Found {len(obj_files)} OBJ file(s) to process:")
    for obj_file in obj_files:
        print(f"  - {obj_file}")

    print(f"\nParallelization settings:")
    print(f"  Max baking workers: {config['max_bake_workers']}")
    print(f"  Max conversion workers: {config['max_conversion_workers']}")
    if args.parallel_tiling:
        print(f"  Parallel tiling: ENABLED")
        print(f"  Max tiling workers: {config['max_tiling_workers']}")
    else:
        print(f"  Parallel tiling: DISABLED (use --parallel-tiling to enable)")
    print(f"  Available CPU cores: {multiprocessing.cpu_count()}")

    # Process
    successful_count = 0
    failed_count = 0
    skipped_count = 0

    for i, obj_file in enumerate(obj_files, 1):
        print(f"\nProcessing file {i}/{len(obj_files)}")
        result = process_single_obj(obj_file, output_dir, args, blender_config, config, config_path)
        if result is True:
            successful_count += 1
        elif result is False:
            failed_count += 1
            if not args.continue_on_error:
                print("Stopping due to error. Use --continue-on-error to process remaining files.")
                break
        else:
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

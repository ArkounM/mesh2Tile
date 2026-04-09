import os
import sys
import shutil
import glob
import multiprocessing
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from mesh2tile.pipeline.triggerBlender import run_blender_script, run_blender_bake
from mesh2tile.pipeline.node_processes import generate_tileset_json, gzip_output
from mesh2tile.pipeline.blender_obj2glb import convert_obj_to_glb_blender
from mesh2tile.pipeline.createTilesetJson import restructure_tileset
from mesh2tile.pipeline.obj_presplitter import presplit_if_needed, merge_tilesets, estimate_obj_triangles


def find_obj_files(input_dir):
    """Recursively find all OBJ files in input_dir. Returns list of absolute paths."""
    obj_files = []
    for root, dirs, files in os.walk(input_dir):
        for file in files:
            if file.lower().endswith('.obj'):
                obj_files.append(os.path.join(root, file))
    return obj_files


def bake_single_tile(args):
    """Worker function for parallel baking of a single tile file."""
    obj_file, output_dir, blender_config, tile_index, total_tiles, config_path = args
    try:
        cmd = [
            blender_config['exe'],
            "--background",
            "--python", blender_config['single_tile_bake_script'],
            "--",
            "--input", obj_file,
            "--output", output_dir,
            "--config", config_path
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        tile_name = os.path.splitext(os.path.basename(obj_file))[0]
        return tile_name, True, None, tile_index
    except subprocess.CalledProcessError as e:
        tile_name = os.path.basename(obj_file)
        return tile_name, False, f"Exit code {e.returncode}", tile_index
    except Exception as e:
        tile_name = os.path.basename(obj_file)
        return tile_name, False, str(e), tile_index


def bake_lod_batch(args):
    """Worker function for batch baking all tiles in a LOD folder at once."""
    lod, lod_folder, blender_config, config_path = args
    try:
        baked_output_dir = os.path.join(lod_folder, "baked")
        os.makedirs(baked_output_dir, exist_ok=True)
        print(f"    Starting batch baking for {lod}")
        cmd = [
            blender_config['exe'],
            "--background",
            "--python", blender_config['baking_script'],
            "--",
            "--input", lod_folder,
            "--output", lod_folder,
            "--config", config_path
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        tile_count = len(glob.glob(os.path.join(lod_folder, "*.obj")))
        return lod, True, None, tile_count
    except subprocess.CalledProcessError as e:
        return lod, False, f"Exit code {e.returncode}", 0
    except Exception as e:
        return lod, False, str(e), 0


def convert_lod_to_glb(args):
    """Worker function for parallel GLB conversion of a single LOD folder."""
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


def process_chunk_worker(task, blender_config, config_path):
    """Worker function for parallel processing of octree chunks."""
    chunk_file, output_dir, tile_level, ix, iy, iz, max_lod = task
    try:
        cmd = [
            blender_config['exe'],
            "--background",
            "--python", blender_config['adaptive_tiling_worker_script'],
            "--",
            chunk_file, output_dir,
            str(tile_level), str(ix), str(iy), str(iz), str(max_lod),
            "--config", config_path
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, f"Exit code {e.returncode}"
    except Exception as e:
        return False, str(e)


def _process_single_obj_core(input_file, model_output_dir, args, blender_config, config, config_path):
    """
    Core pipeline: Steps 1-6 (tiling, baking, GLB conversion, tileset generation).
    Returns True on success, False on failure.
    """
    pipeline_start_time = time.time()
    phase_times = {}

    try:
        # === Step 1: Adaptive Tiling ===
        print("  -> Generating tiles using octree format...")
        step1_start = time.time()
        tiling_dir = os.path.join(model_output_dir, "temp", "tiles")

        if args.parallel_tiling:
            print("    Parallel tiling enabled")
            print("    Step 1a: Performing initial octree split...")
            run_blender_script(
                input_path=input_file,
                output_dir=tiling_dir,
                blender_exe=blender_config['exe'],
                script_path=blender_config['adaptive_tiling_script'],
                extra_args=[str(config["max_tile_level"]), "--first-split-only", "--config", config_path]
            )

            chunks_dir = os.path.join(tiling_dir, "_parallel_chunks")
            chunk_files = glob.glob(os.path.join(chunks_dir, "*.obj"))

            if not chunk_files:
                print("    Warning: No chunks found. Falling back to sequential processing.")
                run_blender_script(
                    input_path=input_file,
                    output_dir=tiling_dir,
                    blender_exe=blender_config['exe'],
                    script_path=blender_config['adaptive_tiling_script'],
                    extra_args=[str(config["max_tile_level"]), "--config", config_path]
                )
            else:
                print(f"    Step 1b: Processing {len(chunk_files)} chunks in parallel with {config['max_tiling_workers']} workers...")
                worker_tasks = []
                for chunk_file in chunk_files:
                    chunk_name = os.path.splitext(os.path.basename(chunk_file))[0]
                    parts = chunk_name.split('_')
                    if len(parts) >= 4:
                        tile_level = int(parts[0])
                        ix, iy, iz = int(parts[1]), int(parts[2]), int(parts[3])
                        worker_tasks.append((chunk_file, tiling_dir, tile_level, ix, iy, iz, config["max_tile_level"]))

                completed_count = 0
                failed_chunks = []
                with ProcessPoolExecutor(max_workers=config["max_tiling_workers"]) as executor:
                    futures = {executor.submit(process_chunk_worker, task, blender_config, config_path): task for task in worker_tasks}
                    for future in as_completed(futures):
                        task = futures[future]
                        chunk_name = os.path.basename(task[0])
                        try:
                            success, error = future.result()
                            completed_count += 1
                            if success:
                                print(f"    [{completed_count}/{len(worker_tasks)}] Processed chunk: {chunk_name}")
                            else:
                                print(f"    [{completed_count}/{len(worker_tasks)}] Failed chunk {chunk_name}: {error}")
                                failed_chunks.append(chunk_name)
                        except Exception as e:
                            completed_count += 1
                            print(f"    [{completed_count}/{len(worker_tasks)}] Exception processing {chunk_name}: {e}")
                            failed_chunks.append(chunk_name)

                if failed_chunks:
                    print(f"    Warning: {len(failed_chunks)} chunks failed to process")
                else:
                    print(f"    All {len(worker_tasks)} chunks processed successfully")
                shutil.rmtree(chunks_dir)
                print(f"    Cleaned up temporary chunks directory")
        else:
            run_blender_script(
                input_path=input_file,
                output_dir=tiling_dir,
                blender_exe=blender_config['exe'],
                script_path=blender_config['adaptive_tiling_script'],
                extra_args=[str(config["max_tile_level"]), "--config", config_path]
            )

        phase_times['Step 1: Adaptive Tiling'] = time.time() - step1_start
        print(f"    Tiling completed in {phase_times['Step 1: Adaptive Tiling']:.2f}s")

        # === Step 2: Bake textures ===
        step2_start = time.time()
        if args.batch_bake:
            print("  -> Baking textures (batch mode - per LOD processing)...")
            batch_tasks = []
            for lod in sorted(os.listdir(tiling_dir)):
                lod_folder = os.path.join(tiling_dir, lod)
                if not os.path.isdir(lod_folder):
                    continue
                obj_files = glob.glob(os.path.join(lod_folder, "*.obj"))
                if obj_files:
                    batch_tasks.append((lod, lod_folder, blender_config, config_path))

            if batch_tasks:
                max_bake_workers = min(len(batch_tasks), config["max_bake_workers"])
                print(f"    Processing {len(batch_tasks)} LOD levels with {max_bake_workers} parallel Blender sessions")
                completed_lods = 0
                total_tiles_processed = 0
                failed_lods = []
                with ProcessPoolExecutor(max_workers=max_bake_workers) as executor:
                    futures = {executor.submit(bake_lod_batch, task): task for task in batch_tasks}
                    for future in as_completed(futures):
                        try:
                            lod, success, error, tile_count = future.result()
                            completed_lods += 1
                            if success:
                                total_tiles_processed += tile_count
                                print(f"    [{completed_lods}/{len(batch_tasks)}] Completed {lod}: {tile_count} tiles baked")
                            else:
                                print(f"    [{completed_lods}/{len(batch_tasks)}] Failed {lod}: {error}")
                                failed_lods.append(lod)
                        except Exception as e:
                            completed_lods += 1
                            print(f"    [{completed_lods}/{len(batch_tasks)}] Exception: {e}")
                if failed_lods:
                    print(f"    Warning: {len(failed_lods)} LOD levels failed to bake")
                else:
                    print(f"    All {len(batch_tasks)} LOD levels completed ({total_tiles_processed} total tiles)")
            else:
                print("    No tiles found for baking")
        else:
            print("  -> Baking textures (per-tile parallel processing)...")
            bake_tasks = []
            tile_index = 0
            for lod in sorted(os.listdir(tiling_dir)):
                lod_folder = os.path.join(tiling_dir, lod)
                if not os.path.isdir(lod_folder):
                    continue
                obj_files = glob.glob(os.path.join(lod_folder, "*.obj"))
                baked_output_dir = os.path.join(lod_folder, "baked")
                os.makedirs(baked_output_dir, exist_ok=True)
                for obj_file in obj_files:
                    bake_tasks.append((obj_file, baked_output_dir, blender_config, tile_index, len(obj_files), config_path))
                    tile_index += 1

            if bake_tasks:
                total_tiles = len(bake_tasks)
                print(f"    Baking {total_tiles} tiles across ALL LOD levels with {config['max_bake_workers']} workers")
                completed_count = 0
                failed_tiles = []
                with ProcessPoolExecutor(max_workers=config["max_bake_workers"]) as executor:
                    futures = {executor.submit(bake_single_tile, task): task for task in bake_tasks}
                    for future in as_completed(futures):
                        try:
                            tile_name, success, error, idx = future.result()
                            completed_count += 1
                            if success:
                                print(f"    [{completed_count}/{total_tiles}] Baked: {tile_name}")
                            else:
                                print(f"    [{completed_count}/{total_tiles}] Failed: {tile_name} - {error}")
                                failed_tiles.append(tile_name)
                        except Exception as e:
                            completed_count += 1
                            print(f"    [{completed_count}/{total_tiles}] Exception: {e}")
                if failed_tiles:
                    print(f"    Warning: {len(failed_tiles)} tiles failed to bake")
                else:
                    print(f"    All {total_tiles} tiles baked successfully")
            else:
                print("    No tiles found for baking")

        phase_times['Step 2: Texture Baking'] = time.time() - step2_start
        print(f"    Baking completed in {phase_times['Step 2: Texture Baking']:.2f}s")

        # === Step 3: Convert to GLB ===
        print("  -> Converting to GLB and generating tilesets (parallel processing)...")
        step3_start = time.time()
        conversion_tasks = []
        for lod in os.listdir(tiling_dir):
            tiling_dir_path = os.path.join(tiling_dir, lod, "baked")
            if not os.path.isdir(tiling_dir_path):
                continue
            conversion_tasks.append((lod, tiling_dir_path, model_output_dir, blender_config))

        if conversion_tasks:
            print(f"    Launching {len(conversion_tasks)} conversion tasks with {config['max_conversion_workers']} workers (Blender-based)")
            with ProcessPoolExecutor(max_workers=config["max_conversion_workers"]) as executor:
                futures = {executor.submit(convert_lod_to_glb, task): task[0] for task in conversion_tasks}
                for future in as_completed(futures):
                    lod = futures[future]
                    try:
                        result_lod, success, error = future.result()
                        if success:
                            print(f"    Converted LOD: {result_lod}")
                        else:
                            print(f"    Failed to convert LOD {result_lod}: {error}")
                    except Exception as e:
                        print(f"    Exception during conversion LOD {lod}: {e}")
        else:
            print("    No baked LOD folders found for conversion")

        phase_times['Step 3: GLB Conversion'] = time.time() - step3_start
        print(f"    Conversion completed in {phase_times['Step 3: GLB Conversion']:.2f}s")

        # === Step 4: Clean up temp ===
        temp_dir = os.path.join(model_output_dir, "temp")
        if not args.temp and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

        # === Step 5: Generate tileset.json ===
        print("  -> Generating tileset.json...")
        step5_start = time.time()
        tileset_path = os.path.join(model_output_dir, "tileset.json")
        generate_tileset_json(
            model_output_dir,
            longitude=config["longitude"],
            latitude=config["latitude"],
            height=config["height"],
            tiles_tools_version=config["tiles_tools_version"]
        )
        restructure_tileset(tileset_path, tileset_path)
        phase_times['Step 5: Tileset Generation'] = time.time() - step5_start

        # === Step 6: Gzip ===
        if args.gzip:
            print("  -> Applying gzip compression...")
            step6_start = time.time()
            gzip_output(model_output_dir, tiles_tools_version=config["tiles_tools_version"])
            phase_times['Step 6: Gzip Compression'] = time.time() - step6_start

        # Timing summary
        total_time = time.time() - pipeline_start_time
        print(f"\n  {'='*60}")
        print(f"  PERFORMANCE SUMMARY")
        print(f"  {'='*60}")
        for phase, duration in phase_times.items():
            percent = (duration / total_time * 100) if total_time > 0 else 0
            print(f"  {phase:.<40} {duration:>8.2f}s ({percent:>5.1f}%)")
        print(f"  {'-'*60}")
        print(f"  {'TOTAL PIPELINE TIME':.<40} {total_time:>8.2f}s")
        print(f"  {'='*60}")
        return True

    except Exception as e:
        print(f"  Error in core pipeline: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def process_single_obj(input_file, output_base_dir, args, blender_config, config, config_path):
    """Process a single OBJ file through the entire pipeline."""
    print(f"\n{'='*60}")
    print(f"Processing: {input_file}")
    print(f"{'='*60}")

    input_basename = os.path.splitext(os.path.basename(input_file))[0]
    model_output_dir = os.path.join(output_base_dir, input_basename)

    if os.path.exists(model_output_dir):
        if args.force:
            print(f"  Warning: Output directory exists, removing due to --force: {model_output_dir}")
            shutil.rmtree(model_output_dir)
        else:
            print(f"  Output directory already exists, skipping: {model_output_dir}")
            return None

    os.makedirs(model_output_dir, exist_ok=True)
    print(f"Output directory: {model_output_dir}")

    # Pre-split check
    presplit_threshold = config["presplit_threshold"]
    if presplit_threshold > 0:
        print(f"  Checking if pre-split is needed (threshold: {presplit_threshold:,} triangles)...")
        tri_count = estimate_obj_triangles(input_file)
        print(f"  Input has {tri_count:,} faces.")

        if tri_count > presplit_threshold:
            print(f"  Pre-splitting required ({tri_count:,} > {presplit_threshold:,})...")
            presplit_start = time.time()
            presplit_dir = os.path.join(model_output_dir, "temp", "presplit_chunks")
            os.makedirs(presplit_dir, exist_ok=True)
            chunk_paths = presplit_if_needed(input_file, presplit_dir, max_triangles=presplit_threshold)
            presplit_time = time.time() - presplit_start
            print(f"  Pre-split produced {len(chunk_paths)} chunk(s) in {presplit_time:.1f}s")

            if len(chunk_paths) <= 1:
                print(f"  Pre-split did not produce multiple chunks. Proceeding normally.")
            else:
                chunk_tileset_paths = []
                all_success = True

                for ci, chunk_path in enumerate(chunk_paths, 1):
                    chunk_basename = os.path.splitext(os.path.basename(chunk_path))[0]
                    chunk_output_dir = os.path.join(model_output_dir, f"chunk_{ci:03d}_{chunk_basename}")
                    os.makedirs(chunk_output_dir, exist_ok=True)
                    print(f"\n  --- Processing chunk {ci}/{len(chunk_paths)}: {chunk_basename} ---")
                    try:
                        result = _process_single_obj_core(
                            chunk_path, chunk_output_dir, args, blender_config, config, config_path
                        )
                        if result:
                            tileset_path = os.path.join(chunk_output_dir, "tileset.json")
                            if os.path.exists(tileset_path):
                                chunk_tileset_paths.append(tileset_path)
                            else:
                                print(f"  WARNING: tileset.json not found for chunk {ci}")
                                all_success = False
                        else:
                            all_success = False
                    except Exception as e:
                        print(f"  ERROR processing chunk {ci}: {e}")
                        import traceback
                        traceback.print_exc()
                        all_success = False

                if chunk_tileset_paths:
                    print(f"\n  Flattening chunk outputs into root directory...")
                    prefix_map = {}
                    for ci, chunk_path in enumerate(chunk_paths, 1):
                        chunk_basename_c = os.path.splitext(os.path.basename(chunk_path))[0]
                        chunk_output_dir = os.path.join(model_output_dir, f"chunk_{ci:03d}_{chunk_basename_c}")
                        prefix = f"c{ci:02d}_"
                        prefix_map[os.path.normpath(chunk_output_dir)] = prefix
                        glb_files = glob.glob(os.path.join(chunk_output_dir, "*.glb"))
                        for glb_file in glb_files:
                            new_name = prefix + os.path.basename(glb_file)
                            dest = os.path.join(model_output_dir, new_name)
                            shutil.move(glb_file, dest)
                        print(f"    Moved {len(glb_files)} GLBs from chunk {ci} with prefix '{prefix}'")

                if chunk_tileset_paths:
                    print(f"\n  Merging {len(chunk_tileset_paths)} chunk tilesets...")
                    merged_tileset = os.path.join(model_output_dir, "tileset.json")
                    merge_tilesets(chunk_tileset_paths, merged_tileset, prefix_map=prefix_map)

                if chunk_tileset_paths:
                    for ci, chunk_path in enumerate(chunk_paths, 1):
                        chunk_basename_c = os.path.splitext(os.path.basename(chunk_path))[0]
                        chunk_output_dir = os.path.join(model_output_dir, f"chunk_{ci:03d}_{chunk_basename_c}")
                        if os.path.exists(chunk_output_dir):
                            shutil.rmtree(chunk_output_dir)
                            print(f"    Cleaned up {os.path.basename(chunk_output_dir)}")

                if not args.temp and os.path.exists(presplit_dir):
                    shutil.rmtree(presplit_dir)

                if all_success and chunk_tileset_paths:
                    print(f"  Successfully processed (pre-split): {input_basename}")
                    return True
                else:
                    print(f"  Some chunks failed for: {input_basename}")
                    return False

    result = _process_single_obj_core(input_file, model_output_dir, args, blender_config, config, config_path)
    if result:
        print(f"  Successfully processed: {input_basename}")
    else:
        print(f"  Error processing: {input_basename}")
    return result

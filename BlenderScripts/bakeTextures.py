import bpy
import bmesh
import os
import glob
from mathutils import Vector
import subprocess
import os
import argparse
import json
import math

# ===========================================
# ADAPTIVE TEXTURE SIZING (PHASE 1)
# ===========================================

def clamp_to_power_of_2(value, min_size=32, max_size=1024):
    """
    Clamp value to nearest power of 2 within [min_size, max_size].
    Valid sizes: 32, 64, 128, 256, 512, 1024
    """
    value = max(min_size, min(max_size, value))

    # Find nearest power of 2
    power = int(math.log2(value))
    lower = 2 ** power
    upper = 2 ** (power + 1)

    # Choose closest
    if value - lower < upper - value:
        result = lower
    else:
        result = upper

    # Clamp again to ensure within bounds
    return max(min_size, min(max_size, result))

def calculate_budget_exhausted_level(source_texture_pixels, base_resolution):
    """
    Calculate at which tile level the texture detail budget is exhausted.

    Returns: level at which cumulative texture pixels >= source pixels
    """
    cumulative_pixels = 0
    level = 0

    while cumulative_pixels < source_texture_pixels and level < 10:
        tiles_at_level = 8 ** level if level > 0 else 1
        pixels_per_tile = base_resolution ** 2
        cumulative_pixels += tiles_at_level * pixels_per_tile

        if cumulative_pixels >= source_texture_pixels:
            return level
        level += 1

    return level

def get_adaptive_texture_size(tile_name, source_texture_pixels, total_estimated_tiles, base_resolution=1024):
    """
    Determine texture size based on:
    1. Original texture detail budget
    2. Current tile level
    3. Whether we've exhausted the original texture detail

    Strategy:
    - Keep textures at base_resolution (1024) until budget is exhausted
    - After budget exhaustion, reduce by ÷2.83 per level (Option B: √8 for octree)
    - Clamp between 32x32 and 1024x1024
    """
    # Extract tile level from name (e.g., "2_0_1_0" → level 2)
    parts = tile_name.split('_')
    tile_level = int(parts[0])

    # Level 0 always uses 1024x1024 (root tile)
    if tile_level == 0:
        return 1024

    # Calculate at which level the budget is exhausted
    budget_level = calculate_budget_exhausted_level(source_texture_pixels, base_resolution)

    print(f"  Tile {tile_name}: level={tile_level}, budget_exhausted_at={budget_level}")

    # If we haven't exhausted the budget, use base resolution
    if tile_level <= budget_level:
        print(f"    Using base resolution: {base_resolution}x{base_resolution}")
        return base_resolution

    # Budget exhausted - reduce texture size
    # Each octree level subdivides into 8 children
    # Texture area should be divided by 8, so linear resolution ÷ √8 ≈ 2.828
    levels_past_budget = tile_level - budget_level
    reduction_factor = 2.828 ** levels_past_budget
    reduced_resolution = base_resolution / reduction_factor

    # Clamp to valid range and power of 2
    final_resolution = clamp_to_power_of_2(reduced_resolution, min_size=32, max_size=1024)

    print(f"    Budget exhausted: {levels_past_budget} levels past")
    print(f"    Reduction factor: {reduction_factor:.2f}x")
    print(f"    Calculated: {reduced_resolution:.1f} → Clamped: {final_resolution}x{final_resolution}")

    return final_resolution

def load_texture_metadata(base_dir):
    """
    Load texture metadata JSON file created during adaptive tiling.
    Searches up the directory tree to find texture_metadata.json.
    Returns dict with metadata, or None if not found.
    """
    # Search in multiple locations (current dir and parent directories)
    # base_dir might be: .../temp/tiles/TileLevel_4
    # metadata is at:    .../temp/tiles/texture_metadata.json

    search_paths = [
        os.path.join(base_dir, "texture_metadata.json"),                    # .../TileLevel_4/
        os.path.join(os.path.dirname(base_dir), "texture_metadata.json"),   # .../tiles/
        os.path.join(os.path.dirname(os.path.dirname(base_dir)), "texture_metadata.json"),  # .../temp/
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(base_dir))), "texture_metadata.json"),  # .../ (parent of temp)
    ]

    for metadata_path in search_paths:
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    print(f"  ✓ Loaded texture metadata from: {metadata_path}")
                    return metadata
            except Exception as e:
                print(f"  Error loading metadata from {metadata_path}: {e}")

    print(f"  ⚠ Texture metadata not found in any search location")
    print(f"    Searched: {base_dir} and parent directories")
    print(f"  Using default 1024x1024 for all tiles")
    return None

# ===========================================
# ORIGINAL BAKING FUNCTIONS
# ===========================================

def clear_scene():
    """Clear all mesh objects from the scene"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False, confirm=False)

def setup_cycles_gpu():
    """Setup Cycles rendering with GPU compute"""
    print("Setting up Cycles GPU rendering...")
    
    # Set render engine to Cycles
    bpy.context.scene.render.engine = 'CYCLES'
    print(f"Render engine set to: {bpy.context.scene.render.engine}")
    
    # Get user preferences for Cycles
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons['cycles'].preferences
    
    # Refresh devices to detect available hardware
    cycles_prefs.refresh_devices()
    print("Available compute devices:")
    
    gpu_found = False
    for device in cycles_prefs.devices:
        print(f"  - {device.name} ({device.type}) - Use: {device.use}")
        if device.type in ['CUDA', 'OPENCL', 'OPTIX', 'HIP']:
            device.use = True
            gpu_found = True
            print(f"    Enabled GPU device: {device.name}")
    
    if not gpu_found:
        print("WARNING: No GPU devices found! Will use CPU.")
        bpy.context.scene.cycles.device = 'CPU'
        return False
    
    # Set device to GPU
    bpy.context.scene.cycles.device = 'GPU'
    print(f"Cycles device set to: {bpy.context.scene.cycles.device}")
    
    # Additional GPU optimization settings
    bpy.context.scene.cycles.use_persistent_data = True  # Keep data in GPU memory
    
    # Set tile size for GPU (larger tiles are better for GPU)
    # Note: In Blender 2.8+, this is handled automatically, but we can still set preferences
    if hasattr(bpy.context.scene.cycles, 'tile_size'):
        bpy.context.scene.cycles.tile_size = 512  # Larger tiles for GPU
    
    return True

def setup_bake_settings(texture_size=1024):
    """Configure bake settings optimized for speed with adaptive settings based on texture size"""
    print(f"Configuring bake settings for {texture_size}x{texture_size} texture...")

    # Basic bake settings
    bpy.context.scene.render.bake.use_pass_direct = False
    bpy.context.scene.render.bake.use_pass_indirect = False
    bpy.context.scene.render.bake.use_pass_color = True
    bpy.context.scene.render.bake.use_selected_to_active = True

    # ADAPTIVE CAGE EXTRUSION: Scale with texture resolution
    # Smaller textures need smaller extrusion to avoid baking artifacts
    if texture_size >= 1024:
        bpy.context.scene.render.bake.cage_extrusion = 0.1
    elif texture_size >= 512:
        bpy.context.scene.render.bake.cage_extrusion = 0.05
    elif texture_size >= 256:
        bpy.context.scene.render.bake.cage_extrusion = 0.025
    else:
        bpy.context.scene.render.bake.cage_extrusion = 0.01

    # ADAPTIVE UV MARGIN: Scale with texture resolution to prevent black bleeding
    # Larger margins fill background around islands with edge colors, preventing black artifacts
    if texture_size >= 1024:
        margin_pixels = 16  # 1.6% of texture
    elif texture_size >= 512:
        margin_pixels = 8   # 1.6% of texture
    elif texture_size >= 256:
        margin_pixels = 4   # 1.6% of texture
    elif texture_size >= 128:
        margin_pixels = 3   # 2.3% of texture
    else:
        margin_pixels = 2   # 6.25% for 32x32

    bpy.context.scene.render.bake.margin = margin_pixels
    bpy.context.scene.render.bake.margin_type = 'EXTEND'  # Extend colors from islands into background

    print(f"  Cage extrusion: {bpy.context.scene.render.bake.cage_extrusion}")
    print(f"  UV margin: {margin_pixels}px (extends island colors into background)")

    # Speed-optimized settings (reduced samples with denoising compensation)
    bpy.context.scene.cycles.samples = 128  # Reduced from 128 for 4x faster baking
    bpy.context.scene.cycles.use_denoising = True  # Enable to compensate for lower samples
    bpy.context.scene.cycles.denoiser = 'OPENIMAGEDENOISE'

    # Note: tile_x and tile_y were removed in Blender 2.8+
    # Modern Blender uses adaptive sampling and doesn't need manual tile settings

    print("Bake settings configured")

def verify_gpu_usage():
    """Verify that GPU is actually being used"""
    print("\n=== GPU Usage Verification ===")
    print(f"Render engine: {bpy.context.scene.render.engine}")
    print(f"Cycles device: {bpy.context.scene.cycles.device}")
    
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons['cycles'].preferences
    
    active_devices = [device for device in cycles_prefs.devices if device.use]
    print(f"Active devices: {len(active_devices)}")
    for device in active_devices:
        print(f"  - {device.name} ({device.type})")
    
    if not active_devices:
        print("WARNING: No active compute devices found!")
        return False
        
    gpu_active = any(device.type in ['CUDA', 'OPENCL', 'OPTIX', 'HIP'] for device in active_devices)
    if not gpu_active:
        print("WARNING: No GPU devices are active!")
        return False
        
    print("GPU setup appears correct")
    return True

def has_valid_uvs(obj):
    """Check if object has valid UV coordinates"""
    if obj.type != 'MESH':
        return False

    mesh = obj.data
    if not mesh.uv_layers or len(mesh.uv_layers) == 0:
        return False

    # Check if UV layer has actual coordinates (not all zeros)
    uv_layer = mesh.uv_layers.active
    if not uv_layer:
        return False

    # Sample a few UVs to see if they're non-zero
    has_non_zero = False
    for poly in mesh.polygons[:min(10, len(mesh.polygons))]:
        for loop_index in poly.loop_indices:
            uv = uv_layer.data[loop_index].uv
            if abs(uv.x) > 0.001 or abs(uv.y) > 0.001:
                has_non_zero = True
                break
        if has_non_zero:
            break

    return has_non_zero

def get_original_texture_size(obj):
    """Get the size of the original texture from the object's materials"""
    if not obj.data.materials:
        return 1024, 1024  # Default size
    
    material = obj.data.materials[0]
    if not material.use_nodes:
        return 1024, 1024
    
    # Look for Image Texture nodes
    for node in material.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image:
            return node.image.size[0], node.image.size[1]
    
    return 1024, 1024  # Default if no texture found

def create_baked_material(obj, texture_name, width, height):
    """Create a new material with an image texture for baking"""
    # Remove existing materials
    obj.data.materials.clear()
    
    # Create new material
    mat = bpy.data.materials.new(name=f"{texture_name}_mat")
    mat.use_nodes = True
    obj.data.materials.append(mat)
    
    # Clear existing nodes
    mat.node_tree.nodes.clear()
    
    # Add Principled BSDF
    principled = mat.node_tree.nodes.new(type='ShaderNodeBsdfPrincipled')
    principled.location = (0, 0)
    
    # Add Material Output
    output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
    output.location = (400, 0)
    
    # Add Image Texture node
    img_tex = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
    img_tex.location = (-400, 0)
    
    # Create new image
    img = bpy.data.images.new(name=texture_name, width=width, height=height)
    img_tex.image = img
    
    # Connect nodes
    mat.node_tree.links.new(img_tex.outputs['Color'], principled.inputs['Base Color'])
    mat.node_tree.links.new(principled.outputs['BSDF'], output.inputs['Surface'])
    
    # Select the image texture node (important for baking)
    img_tex.select = True
    mat.node_tree.nodes.active = img_tex
    
    return img

def process_obj_file(obj_path, output_dir, metadata=None):
    """Process a single OBJ file - optimized for batch processing with adaptive texture sizing"""
    print(f"\n=== Processing: {obj_path} ===")

    # Clear only objects, not scene settings (faster than full clear)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False, confirm=False)

    # Import OBJ
    bpy.ops.wm.obj_import(filepath=obj_path)

    # Get the imported object (should be the only selected object)
    imported_objects = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
    if not imported_objects:
        print(f"No mesh objects found in {obj_path}")
        return

    original_obj = imported_objects[0]
    original_name = original_obj.name

    print(f"Original object name: {original_name}")

    # Calculate adaptive texture size
    if metadata:
        texture_size = get_adaptive_texture_size(
            tile_name=original_name,
            source_texture_pixels=metadata['source_texture_pixels'],
            total_estimated_tiles=metadata['estimated_tiles'],
            base_resolution=metadata['base_texture_size']
        )
    else:
        # Fallback: use default 1024x1024
        print("  Using fallback texture size: 1024x1024")
        texture_size = 1024

    print(f"  Selected texture size: {texture_size}x{texture_size}")

    # Setup bake settings with adaptive parameters based on texture size
    setup_bake_settings(texture_size)

    # Calculate adaptive island margin based on texture size
    # Smaller textures need smaller margins to avoid wasting texture space
    if texture_size >= 1024:
        island_margin = 0.04  # 4% for 1024x1024
    elif texture_size >= 512:
        island_margin = 0.02  # 2% for 512x512
    elif texture_size >= 256:
        island_margin = 0.01  # 1% for 256x256
    else:
        island_margin = 0.005  # 0.5% for 128x128 and smaller

    print(f"  UV unwrap island margin: {island_margin} ({island_margin*100}% of texture space)")

    # Duplicate the object
    bpy.context.view_layer.objects.active = original_obj
    bpy.ops.object.duplicate()
    baked_obj = bpy.context.active_object
    baked_obj.name = f"{original_name}_baked"

    print(f"Baked object name: {baked_obj.name}")

    # Ensure we're in Object mode before entering Edit mode
    bpy.ops.object.mode_set(mode='OBJECT')

    # Make sure the baked object is selected and active
    bpy.context.view_layer.objects.active = baked_obj
    baked_obj.select_set(True)

    # Enter edit mode for UV unwrapping
    bpy.ops.object.mode_set(mode='EDIT')

    # Select all faces for UV unwrapping
    bpy.ops.mesh.select_all(action='SELECT')

    # Smart UV unwrap with adaptive island margin
    print(f"  Creating UV unwrap...")
    bpy.ops.uv.smart_project(
        angle_limit=1.15192,
        margin_method='SCALED',
        rotate_method='AXIS_ALIGNED_Y',
        island_margin=island_margin,  # Adaptive margin based on texture size
        area_weight=0.0,
        correct_aspect=True,
        scale_to_bounds=False
    )

    print("UV unwrapping completed")

    # Return to Object mode
    bpy.ops.object.mode_set(mode='OBJECT')

    # Create baked material with adaptive texture size
    texture_name = f"{original_name}_baked_mat"
    baked_image = create_baked_material(baked_obj, texture_name, texture_size, texture_size)
    
    # Select objects for baking (original first, then baked as active)
    bpy.ops.object.select_all(action='DESELECT')
    original_obj.select_set(True)
    baked_obj.select_set(True)
    bpy.context.view_layer.objects.active = baked_obj
    
    # Bake the texture
    print("Starting bake...")
    try:
        bpy.ops.object.bake(type='DIFFUSE')
        print("Bake completed successfully")
    except Exception as e:
        print(f"Bake failed: {e}")
        return
    
    # Save the baked image
    baked_dir = os.path.join(output_dir, "baked")
    os.makedirs(baked_dir, exist_ok=True)
    
    image_path = os.path.join(baked_dir, f"{texture_name}.png")
    baked_image.filepath_raw = image_path
    baked_image.file_format = 'PNG'
    baked_image.save()
    print(f"Saved baked texture: {image_path}")
    
    # Export the baked object as OBJ
    bpy.ops.object.select_all(action='DESELECT')
    baked_obj.select_set(True)
    bpy.context.view_layer.objects.active = baked_obj
    
    # Export path (remove _baked suffix from filename)
    export_name = original_name
    export_path = os.path.join(baked_dir, f"{export_name}.obj")
    
    bpy.ops.wm.obj_export(
        filepath=export_path,
        export_selected_objects=True,
        export_materials=True,
        path_mode='COPY'  # This will copy textures and create .mtl file
    )
    print(f"Exported baked object: {export_path}")

    # Clear unused data to prevent memory buildup during batch processing
    bpy.ops.outliner.orphans_purge(do_recursive=True)

def bake_textures_to_tiles(input_directory, output_directory):
    """Main function to process all OBJ files in the input directory with adaptive texture sizing"""
    if not os.path.exists(input_directory):
        print(f"Input directory does not exist: {input_directory}")
        return

    # Setup Cycles and GPU
    gpu_success = setup_cycles_gpu()
    # Note: setup_bake_settings() is now called per-tile in process_obj_file()
    # with adaptive parameters based on calculated texture size

    # Verify GPU setup
    if gpu_success:
        verify_gpu_usage()
    else:
        print("Proceeding with CPU rendering...")

    # Load texture metadata for adaptive sizing
    print("\n" + "=" * 60)
    print("LOADING TEXTURE METADATA FOR ADAPTIVE SIZING")
    print("=" * 60)
    metadata = load_texture_metadata(input_directory)

    if metadata:
        print(f"  Source texture: {metadata['source_texture_width']}x{metadata['source_texture_height']}")
        print(f"  Total pixels: {metadata['source_texture_pixels']:,}")
        print(f"  Estimated tiles: {metadata['estimated_tiles']}")
        print(f"  Base texture size: {metadata['base_texture_size']}x{metadata['base_texture_size']}")
    else:
        print("  No metadata found - using default 1024x1024 for all tiles")
    print("=" * 60 + "\n")

    # Find all OBJ files
    obj_pattern = os.path.join(input_directory, "*.obj")
    obj_files = glob.glob(obj_pattern)

    if not obj_files:
        print(f"No OBJ files found in {input_directory}")
        return

    print(f"Found {len(obj_files)} OBJ files to process")

    # Process each OBJ file
    for i, obj_file in enumerate(obj_files):
        print(f"\n{'='*60}")
        print(f"Processing {i+1}/{len(obj_files)}: {os.path.basename(obj_file)}")
        print(f"{'='*60}")
        try:
            process_obj_file(obj_file, input_directory, metadata)
        except Exception as e:
            print(f"Error processing {obj_file}: {e}")
            continue

    print("\n" + "=" * 60)
    print("BATCH PROCESSING COMPLETED!")
    print("=" * 60)

if __name__ == "__main__":
    import sys
    import argparse

    # Get arguments passed after '--' in Blender command
    try:
        separator_index = sys.argv.index("--")
        argv = sys.argv[separator_index + 1:]
        print(f"Arguments after '--': {argv}")
    except ValueError:
        print("No '--' separator found in arguments")
        argv = sys.argv[1:]
        print(f"Using all arguments: {argv}")

    if not argv:
        print("No arguments provided after '--' separator")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to folder with .obj tiles")
    parser.add_argument("--output", required=True, help="Path to output folder for baked assets")
    
    try:
        args = parser.parse_args(argv)
        print(f"Parsed input: {args.input}")
        print(f"Parsed output: {args.output}")
    except SystemExit as e:
        print(f"Failed to parse arguments: {argv}")
        raise e

    input_directory = args.input
    output_directory = args.output

    bake_textures_to_tiles(input_directory, output_directory)
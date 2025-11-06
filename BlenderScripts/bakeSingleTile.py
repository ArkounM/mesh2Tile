import bpy
import bmesh
import os
import sys
import argparse
import json
import math
from mathutils import Vector

# ===========================================
# PHASE 1: ADAPTIVE TEXTURE SIZING
# ===========================================

def detect_source_texture_resolution(obj):
    """
    Scan all materials on the object to find the largest texture.
    Returns (width, height, total_pixels) or (1024, 1024, 1048576) as default.
    """
    max_width = 0
    max_height = 0

    if not obj.data.materials:
        print("  No materials found - using default 1024x1024")
        return 1024, 1024, 1048576

    for mat in obj.data.materials:
        if not mat or not mat.use_nodes:
            continue

        # Search for image texture nodes
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                width, height = node.image.size
                if width * height > max_width * max_height:
                    max_width = width
                    max_height = height

    if max_width == 0 or max_height == 0:
        print("  No textures found in materials - using default 1024x1024")
        return 1024, 1024, 1048576

    total_pixels = max_width * max_height
    print(f"  Detected source texture: {max_width}x{max_height} ({total_pixels:,} pixels)")
    return max_width, max_height, total_pixels

def estimate_total_tiles(total_triangles, triangle_threshold):
    """
    Estimate the total number of tiles that will be generated based on mesh complexity.
    Uses octree subdivision logic: each level creates up to 8 children.

    Returns: (estimated_tiles, max_depth)
    """
    if total_triangles <= triangle_threshold:
        return 1, 0

    # Calculate how many levels of subdivision we'll need
    # Each subdivision decimates parent to threshold, then splits children
    current_triangles = total_triangles
    max_depth = 0
    estimated_tiles = 0

    # Level 0: root tile (always 1)
    estimated_tiles += 1

    # Simulate subdivision
    while current_triangles > triangle_threshold and max_depth < 10:  # Cap at 10 levels for safety
        max_depth += 1
        # Each subdivision creates up to 8 tiles at the next level
        # Assume average of 6 non-empty octants (realistic for complex meshes)
        tiles_at_level = min(8 ** max_depth, int(total_triangles / triangle_threshold))
        estimated_tiles += tiles_at_level
        current_triangles = current_triangles / 8  # Each octant gets ~1/8 of triangles

    print(f"  Estimated {estimated_tiles} total tiles across {max_depth} levels")
    return estimated_tiles, max_depth

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

def load_texture_metadata(output_dir):
    """
    Load texture metadata JSON file created during adaptive tiling.
    Searches up the directory tree to find texture_metadata.json.
    Returns dict with metadata, or None if not found.
    """
    # Search in multiple locations (current dir and parent directories)
    # output_dir might be: .../temp/tiles/TileLevel_4/baked
    # metadata is at:      .../temp/tiles/texture_metadata.json

    search_paths = [
        os.path.join(output_dir, "texture_metadata.json"),                    # .../baked/
        os.path.join(os.path.dirname(output_dir), "texture_metadata.json"),   # .../TileLevel_4/
        os.path.join(os.path.dirname(os.path.dirname(output_dir)), "texture_metadata.json"),  # .../tiles/
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(output_dir))), "texture_metadata.json"),  # .../temp/
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
    print(f"    Searched: {output_dir} and parent directories")
    print(f"  Using default values (1024x1024, single tile)")
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
    # Set render engine to Cycles
    bpy.context.scene.render.engine = 'CYCLES'

    # Get user preferences for Cycles
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons['cycles'].preferences

    # Refresh devices to detect available hardware
    cycles_prefs.refresh_devices()

    gpu_found = False
    for device in cycles_prefs.devices:
        if device.type in ['CUDA', 'OPENCL', 'OPTIX', 'HIP']:
            device.use = True
            gpu_found = True

    if not gpu_found:
        bpy.context.scene.cycles.device = 'CPU'
        return False

    # Set device to GPU
    bpy.context.scene.cycles.device = 'GPU'

    # GPU optimization settings
    bpy.context.scene.cycles.use_persistent_data = True

    return True

def setup_bake_settings(texture_size=1024):
    """Configure bake settings optimized for speed with adaptive settings based on texture size"""
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

    print(f"  Bake settings for {texture_size}x{texture_size}:")
    print(f"    Cage extrusion: {bpy.context.scene.render.bake.cage_extrusion}")
    print(f"    UV margin: {margin_pixels}px (extends island colors into background)")

    # Speed-optimized settings (reduced samples with denoising compensation)
    bpy.context.scene.cycles.samples = 32  # Reduced from 128 for 4x faster baking
    bpy.context.scene.cycles.use_denoising = True  # Enable to compensate for lower samples
    bpy.context.scene.cycles.denoiser = 'OPENIMAGEDENOISE'

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

def bake_single_tile(obj_path, output_dir):
    """Process a single OBJ file - optimized for parallel execution with adaptive texture sizing"""

    # Clear scene
    clear_scene()

    # Import OBJ
    bpy.ops.wm.obj_import(filepath=obj_path)

    # Get the imported object
    imported_objects = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
    if not imported_objects:
        print(f"ERROR: No mesh objects found in {obj_path}")
        return False

    original_obj = imported_objects[0]
    original_name = original_obj.name

    # Load texture metadata (if available)
    print(f"\n=== Processing tile: {original_name} ===")
    metadata = load_texture_metadata(output_dir)

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
    setup_cycles_gpu()
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

    # Ensure we're in Object mode
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

    # Return to Object mode
    bpy.ops.object.mode_set(mode='OBJECT')
    print(f"  ✓ UV unwrap completed")

    # Create baked material with adaptive texture size
    texture_name = f"{original_name}_baked_mat"
    baked_image = create_baked_material(baked_obj, texture_name, texture_size, texture_size)

    # Select objects for baking (original first, then baked as active)
    bpy.ops.object.select_all(action='DESELECT')
    original_obj.select_set(True)
    baked_obj.select_set(True)
    bpy.context.view_layer.objects.active = baked_obj

    # Bake the texture
    try:
        bpy.ops.object.bake(type='DIFFUSE')
    except Exception as e:
        print(f"ERROR: Bake failed: {e}")
        return False

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Save the baked image
    image_path = os.path.join(output_dir, f"{texture_name}.png")
    baked_image.filepath_raw = image_path
    baked_image.file_format = 'PNG'
    baked_image.save()

    # Export the baked object as OBJ
    bpy.ops.object.select_all(action='DESELECT')
    baked_obj.select_set(True)
    bpy.context.view_layer.objects.active = baked_obj

    # Export path (remove _baked suffix from filename)
    export_name = original_name
    export_path = os.path.join(output_dir, f"{export_name}.obj")

    bpy.ops.wm.obj_export(
        filepath=export_path,
        export_selected_objects=True,
        export_materials=True,
        path_mode='COPY'
    )

    return True

if __name__ == "__main__":
    import sys
    import argparse

    # Get arguments passed after '--' in Blender command
    try:
        separator_index = sys.argv.index("--")
        argv = sys.argv[separator_index + 1:]
    except ValueError:
        argv = sys.argv[1:]

    if not argv:
        print("ERROR: No arguments provided")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to single .obj file")
    parser.add_argument("--output", required=True, help="Path to output folder for baked asset")

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        print(f"ERROR: Failed to parse arguments: {argv}")
        sys.exit(1)

    # Process the single tile
    # Note: setup_cycles_gpu() and setup_bake_settings() are called inside bake_single_tile()
    # with adaptive parameters based on calculated texture size
    success = bake_single_tile(args.input, args.output)

    if not success:
        sys.exit(1)

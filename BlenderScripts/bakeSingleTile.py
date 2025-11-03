import bpy
import bmesh
import os
import sys
import argparse
from mathutils import Vector

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

def setup_bake_settings():
    """Configure bake settings optimized for speed"""
    # Basic bake settings
    bpy.context.scene.render.bake.use_pass_direct = False
    bpy.context.scene.render.bake.use_pass_indirect = False
    bpy.context.scene.render.bake.use_pass_color = True
    bpy.context.scene.render.bake.use_selected_to_active = True
    bpy.context.scene.render.bake.cage_extrusion = 0.1
    bpy.context.scene.render.bake.margin = 8  # Reduced from 32 for faster baking

    # Speed-optimized settings (reduced samples with denoising compensation)
    bpy.context.scene.cycles.samples = 32  # Reduced from 128 for 4x faster baking
    bpy.context.scene.cycles.use_denoising = True  # Enable to compensate for lower samples
    bpy.context.scene.cycles.denoiser = 'OPENIMAGEDENOISE'

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
    """Process a single OBJ file - optimized for parallel execution"""

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

    # Smart UV unwrap
    bpy.ops.uv.smart_project(
        angle_limit=1.15192,
        margin_method='SCALED',
        rotate_method='AXIS_ALIGNED_Y',
        island_margin=0.04,
        area_weight=0.0,
        correct_aspect=True,
        scale_to_bounds=False
    )

    # Return to Object mode
    bpy.ops.object.mode_set(mode='OBJECT')

    # Create baked material
    texture_name = f"{original_name}_baked_mat"
    baked_image = create_baked_material(baked_obj, texture_name, 1024, 1024)

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

    # Setup Cycles and GPU (silent mode)
    setup_cycles_gpu()
    setup_bake_settings()

    # Process the single tile
    success = bake_single_tile(args.input, args.output)

    if not success:
        sys.exit(1)

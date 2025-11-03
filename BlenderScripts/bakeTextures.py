import bpy
import bmesh
import os
import glob
from mathutils import Vector
import subprocess
import os
import argparse

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

def setup_bake_settings():
    """Configure bake settings optimized for speed"""
    print("Configuring bake settings...")

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

def process_obj_file(obj_path, output_dir):
    """Process a single OBJ file - optimized for batch processing"""
    print(f"Processing: {obj_path}")

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
    
    # Get original texture size
    tex_width, tex_height = get_original_texture_size(original_obj)
    print(f"Original texture size: {tex_width}x{tex_height}")
    
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
    
    # Smart UV unwrap the object with padding to prevent seams
    bpy.ops.uv.smart_project(
        angle_limit=1.15192, 
        margin_method='SCALED', 
        rotate_method='AXIS_ALIGNED_Y', 
        island_margin=0.04,  # Increased margin to prevent seams (2% of texture space)
        area_weight=0.0, 
        correct_aspect=True, 
        scale_to_bounds=False
    )
    
    print("UV unwrapping completed")
    
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
    """Main function to process all OBJ files in the input directory"""
    if not os.path.exists(input_directory):
        print(f"Input directory does not exist: {input_directory}")
        return
    
    # Setup Cycles and GPU
    gpu_success = setup_cycles_gpu()
    setup_bake_settings()
    
    # Verify GPU setup
    if gpu_success:
        verify_gpu_usage()
    else:
        print("Proceeding with CPU rendering...")
    
    # Find all OBJ files
    obj_pattern = os.path.join(input_directory, "*.obj")
    obj_files = glob.glob(obj_pattern)
    
    if not obj_files:
        print(f"No OBJ files found in {input_directory}")
        return
    
    print(f"Found {len(obj_files)} OBJ files to process")
    
    # Process each OBJ file
    for i, obj_file in enumerate(obj_files):
        print(f"\n=== Processing {i+1}/{len(obj_files)}: {os.path.basename(obj_file)} ===")
        try:
            process_obj_file(obj_file, input_directory)
        except Exception as e:
            print(f"Error processing {obj_file}: {e}")
            continue
    
    print("Batch processing completed!")

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
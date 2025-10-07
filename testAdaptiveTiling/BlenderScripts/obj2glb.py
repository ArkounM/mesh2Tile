"""
Blender script to convert OBJ files to GLB format
Usage: blender --background --python obj2glb.py -- <input_dir> <output_dir>
"""

import bpy
import os
import sys

def convert_obj_to_glb(input_dir, output_dir):
    """
    Convert all OBJ files in input_dir to GLB files in output_dir.
    Removes '_decimated' from filenames during conversion.
    """
    print(f"\n=== Starting OBJ to GLB Conversion ===")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")

    os.makedirs(output_dir, exist_ok=True)

    # Find all OBJ files
    obj_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.obj')]
    print(f"Found {len(obj_files)} OBJ files to convert")

    success_count = 0
    fail_count = 0

    for obj_file in obj_files:
        try:
            # Clear the scene
            bpy.ops.wm.read_factory_settings(use_empty=True)

            input_path = os.path.join(input_dir, obj_file)

            # Remove '_decimated' from filename
            output_filename = obj_file.replace('_decimated', '').replace('.obj', '.glb')
            output_path = os.path.join(output_dir, output_filename)

            print(f"  Converting: {obj_file} -> {output_filename}")

            # Import OBJ
            bpy.ops.wm.obj_import(filepath=input_path)

            # Export as GLB with embedded textures
            bpy.ops.export_scene.gltf(
                filepath=output_path,
                export_format='GLB',
                export_texcoords=True,
                export_normals=True,
                export_materials='EXPORT',
                export_image_format='AUTO',
                export_apply=False
            )

            print(f"    ✓ Success: {output_filename}")
            success_count += 1

        except Exception as e:
            print(f"    ✗ Failed to convert {obj_file}: {e}")
            fail_count += 1

    print(f"\n=== Conversion Complete ===")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Output: {output_dir}")

    return success_count, fail_count


if __name__ == "__main__":
    # Get command line arguments after '--'
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []

    if len(argv) < 2:
        print("Usage: blender --background --python obj2glb.py -- <input_dir> <output_dir>")
        sys.exit(1)

    input_dir = argv[0]
    output_dir = argv[1]

    if not os.path.exists(input_dir):
        print(f"Error: Input directory does not exist: {input_dir}")
        sys.exit(1)

    success, failed = convert_obj_to_glb(input_dir, output_dir)

    # Exit with error code if any conversions failed
    if failed > 0:
        sys.exit(1)

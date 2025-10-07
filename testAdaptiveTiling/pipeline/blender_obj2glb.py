"""
Blender-based OBJ to GLB conversion pipeline
Replaces the obj23dtiles npm-based conversion to avoid cache conflicts
"""

import subprocess
import os

def convert_obj_to_glb_blender(input_dir, output_dir, blender_exe, script_path):
    """
    Convert OBJ files to GLB using Blender.

    Args:
        input_dir: Directory containing OBJ files to convert
        output_dir: Directory where GLB files will be saved
        blender_exe: Path to Blender executable
        script_path: Path to obj2glb.py Blender script
    """
    print(f"Converting OBJs in {input_dir} to GLB using Blender...")

    if not os.path.exists(input_dir):
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    os.makedirs(output_dir, exist_ok=True)

    # Run Blender in background mode
    cmd = [
        blender_exe,
        "--background",
        "--python", script_path,
        "--",
        input_dir,
        output_dir
    ]

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )

        # Print Blender output
        if result.stdout:
            for line in result.stdout.split('\n'):
                if '✓' in line or '✗' in line or 'Converting:' in line or '===' in line:
                    print(f"  {line}")

        return True

    except subprocess.CalledProcessError as e:
        print(f"  ✗ Blender conversion failed with exit code {e.returncode}")
        if e.stderr:
            print(f"  Error output: {e.stderr}")
        return False
    except Exception as e:
        print(f"  ✗ Unexpected error during Blender conversion: {e}")
        return False

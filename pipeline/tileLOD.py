import subprocess
import os

def run_blender_script(input_path, output_dir, blender_exe="blender", script_path="split_chunks.py"):
    """
    Runs the Blender chunking script with given input and output paths.
    
    Parameters:
    - input_path: str - Path to the input OBJ file
    - output_dir: str - Path to the directory where chunks will be saved
    - blender_exe: str - Path to Blender executable (e.g., "C:/Program Files/Blender Foundation/Blender 4.0/blender.exe")
    - script_path: str - Path to the Blender Python script
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Blender script not found: {script_path}")
    
    command = [
        blender_exe,
        "--background",
        "--python", script_path,
        "--", input_path, output_dir
    ]

    print("Running Blender script...")
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        print("Blender script failed:")
        print(result.stderr)
    else:
        print("Blender script completed successfully.")
        print(result.stdout)

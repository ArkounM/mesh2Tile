import subprocess

def run_blender_lod_gen(blender_path, script_path, input, output, lods):
    cmd = [
        blender_path,
        "--background",
        "--python", script_path,
        "--",
        "--input", input,
        "--output", output,
        "--lods", str(lods)
    ]
    subprocess.run(cmd)

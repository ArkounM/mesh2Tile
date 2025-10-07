import os

def update_mtl_texture_path(obj_dir, texture_dir):
    """
    Update each .mtl file referenced by LOD .obj files to point to the corresponding LOD texture
    while preserving the texture's original prefix.
    """
    for filename in os.listdir(obj_dir):
        if filename.endswith(".obj"):
            obj_path = os.path.join(obj_dir, filename)

            with open(obj_path, "r") as obj_file:
                lines = obj_file.readlines()

            mtl_name = next((line.split()[1].strip() for line in lines if line.startswith("mtllib")), None)

            if not mtl_name:
                print(f"[Warning] No mtllib found in {filename}")
                continue

            mtl_path = os.path.join(obj_dir, mtl_name)
            if not os.path.exists(mtl_path):
                print(f"[Warning] MTL file not found: {mtl_path}")
                continue

            # Read the original map_Kd texture line to extract prefix
            original_texture_name = None
            with open(mtl_path, "r") as mtl_file:
                for line in mtl_file:
                    if line.lower().startswith("map_kd"):
                        original_texture_name = os.path.basename(line.split(" ", 1)[1].strip())
                        break

            if not original_texture_name:
                print(f"[Warning] No map_Kd found in {mtl_name}")
                continue

            # Determine which LOD this is
            lod_suffix = os.path.splitext(filename)[0].split("_")[-1]  # e.g., LOD0

            # Append the new LOD to the original texture name (before extension)
            base_name, ext = os.path.splitext(original_texture_name)
            new_texture_name = f"{base_name}_{lod_suffix}{ext}"

            texture_rel_path = os.path.join("..", "texture", new_texture_name)

            # Rewrite MTL
            with open(mtl_path, "r") as mtl_file:
                mtl_lines = mtl_file.readlines()

            updated_lines = []
            for line in mtl_lines:
                if line.lower().startswith("map_kd"):
                    updated_lines.append(f"map_Kd {texture_rel_path}\n")
                else:
                    updated_lines.append(line)

            with open(mtl_path, "w") as mtl_file:
                mtl_file.writelines(updated_lines)

            print(f"[✓] {mtl_name} now references texture: {new_texture_name}")

# CLI support (optional)
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--lod_dir", required=True)
    parser.add_argument("--texture_dir", required=True)
    args = parser.parse_args()
    update_mtl_texture_path(args.lod_dir, args.texture_dir)

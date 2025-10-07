import os
import glob

def update_mtl_texture_path_by_leaf(tiling_dir, texture_dir):
    """
    Update MTL files in octree tile structure to reference appropriate LOD textures.
    
    Args:
        tiling_dir: Path to the tiles directory containing TileLevel_* folders
        texture_dir: Path to the texture directory containing LOD textures
    
    Tile level to LOD mapping:
        - TileLevel_0 -> LOD3 (finest detail)
        - TileLevel_1 -> LOD2 (medium detail)  
        - TileLevel_2+ -> LOD0 (coarsest detail)
    """
    
    # Check if tiling directory exists
    if not os.path.exists(tiling_dir):
        print(f"[Error] Tiling directory not found: {tiling_dir}")
        return
    
    # Check if texture directory exists
    if not os.path.exists(texture_dir):
        print(f"[Error] Texture directory not found: {texture_dir}")
        return
    
    # Find all TileLevel_* directories
    tile_level_dirs = glob.glob(os.path.join(tiling_dir, "TileLevel_*"))
    
    if not tile_level_dirs:
        print(f"[Warning] No TileLevel_* directories found in {tiling_dir}")
        return
    
    print(f"Found {len(tile_level_dirs)} tile level directories")
    
    # Process each tile level directory
    for tile_level_dir in tile_level_dirs:
        # Extract tile level number from directory name
        dir_name = os.path.basename(tile_level_dir)
        try:
            tile_level = int(dir_name.split('_')[1])
        except (IndexError, ValueError):
            print(f"[Warning] Could not parse tile level from directory name: {dir_name}")
            continue
        
        # Determine which LOD to use based on tile level
        if tile_level == 0:
            lod_suffix = "LOD3"
        elif tile_level == 1:
            lod_suffix = "LOD2"
        else:  # tile_level >= 2
            lod_suffix = "LOD0"
        
        print(f"Processing {dir_name} -> using {lod_suffix} textures")
        
        # Process all OBJ files in this tile level directory
        obj_files = glob.glob(os.path.join(tile_level_dir, "*.obj"))
        
        if not obj_files:
            print(f"[Warning] No OBJ files found in {tile_level_dir}")
            continue
        
        processed_count = 0
        
        for obj_file in obj_files:
            success = process_single_obj_file(obj_file, texture_dir, lod_suffix)
            if success:
                processed_count += 1
        
        print(f"  ✓ Updated {processed_count}/{len(obj_files)} OBJ files in {dir_name}")


def process_single_obj_file(obj_path, texture_dir, lod_suffix):
    """
    Process a single OBJ file and update its corresponding MTL file.
    
    Args:
        obj_path: Path to the OBJ file
        texture_dir: Path to the texture directory
        lod_suffix: LOD suffix to use (e.g., "LOD0", "LOD2", "LOD3")
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Read OBJ file to find MTL reference
        with open(obj_path, "r") as obj_file:
            lines = obj_file.readlines()
        
        # Find the mtllib line
        mtl_name = None
        for line in lines:
            if line.strip().startswith("mtllib"):
                parts = line.strip().split()
                if len(parts) >= 2:
                    mtl_name = parts[1]
                    break
        
        if not mtl_name:
            print(f"[Warning] No mtllib found in {os.path.basename(obj_path)}")
            return False
        
        # Construct MTL file path
        mtl_path = os.path.join(os.path.dirname(obj_path), mtl_name)
        
        if not os.path.exists(mtl_path):
            print(f"[Warning] MTL file not found: {mtl_path}")
            return False
        
        # Read MTL file
        with open(mtl_path, "r") as mtl_file:
            mtl_lines = mtl_file.readlines()
        
        # Find and extract the original texture name from map_Kd
        original_texture_name = None
        for line in mtl_lines:
            stripped_line = line.strip()
            if stripped_line.lower().startswith("map_kd"):
                # Extract texture filename from the line
                parts = stripped_line.split(None, 1)  # Split on any whitespace, max 1 split
                if len(parts) >= 2:
                    texture_path = parts[1].strip()
                    original_texture_name = os.path.basename(texture_path)
                    break
        
        if not original_texture_name:
            print(f"[Warning] No map_Kd found in {os.path.basename(mtl_path)}")
            return False
        
        # Generate new texture name with LOD suffix
        base_name, ext = os.path.splitext(original_texture_name)
        # Remove any existing LOD suffix first (in case it's already there)
        if base_name.endswith(('_LOD0', '_LOD1', '_LOD2', '_LOD3')):
            base_name = '_'.join(base_name.split('_')[:-1])
        
        new_texture_name = f"{base_name}_{lod_suffix}{ext}"
        
        # Check if the new texture file exists
        new_texture_path = os.path.join(texture_dir, new_texture_name)
        if not os.path.exists(new_texture_path):
            print(f"[Warning] Target texture not found: {new_texture_path}")
            # Continue anyway, as the texture might be generated later
        
        # Create relative path from MTL location to texture
        mtl_dir = os.path.dirname(mtl_path)
        rel_texture_path = os.path.relpath(new_texture_path, mtl_dir)
        
        # Update MTL file
        updated_lines = []
        updated = False
        
        for line in mtl_lines:
            stripped_line = line.strip()
            if stripped_line.lower().startswith("map_kd"):
                # Replace the map_Kd line
                updated_lines.append(f"map_Kd {rel_texture_path}\n")
                updated = True
            else:
                updated_lines.append(line)
        
        if updated:
            # Write updated MTL file
            with open(mtl_path, "w") as mtl_file:
                mtl_file.writelines(updated_lines)
            
            return True
        else:
            print(f"[Warning] No map_Kd line found to update in {os.path.basename(mtl_path)}")
            return False
            
    except Exception as e:
        print(f"[Error] Failed to process {os.path.basename(obj_path)}: {str(e)}")
        return False


# CLI support for standalone testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Update MTL files in octree tile structure to reference appropriate LOD textures"
    )
    parser.add_argument("--tiling_dir", required=True, 
                       help="Path to the tiles directory containing TileLevel_* folders")
    parser.add_argument("--texture_dir", required=True,
                       help="Path to the texture directory containing LOD textures")
    
    args = parser.parse_args()
    
    update_mtl_texture_path_by_leaf(args.tiling_dir, args.texture_dir)
import bpy
import bmesh
import os
from mathutils import Vector
import argparse
import sys

class LODGenerator:
    def __init__(self, input_file, output_dir="", lod_levels=4):
        self.input_file = input_file
        self.output_dir = output_dir if output_dir else os.path.dirname(input_file)
        self.lod_levels = lod_levels
        self.base_name = os.path.splitext(os.path.basename(input_file))[0]
        
        # LOD reduction ratios (percentage of original geometry to keep)
        self.lod_ratios = [1.0, 0.5, 0.1, 0.1][:lod_levels]
        
    def clear_scene(self):
        """Clear all objects from the scene"""
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        
    def import_obj(self):
        """Import the OBJ file"""
        # Clear selection first
        bpy.ops.object.select_all(action='DESELECT')
        
        # Import OBJ - handle different Blender versions
        try:
            # Blender 4.0+
            bpy.ops.wm.obj_import(filepath=self.input_file)
        except AttributeError:
            try:
                # Blender 3.x
                bpy.ops.import_scene.obj(filepath=self.input_file)
            except AttributeError:
                # Fallback for older versions
                bpy.ops.import_scene.obj(filepath=self.input_file)
                
        # Return selected objects after import
        return list(bpy.context.view_layer.objects.selected)
        
    def decimate_mesh(self, obj, ratio):
        """Apply decimation modifier to reduce polygon count"""
        # Ensure we're in object mode
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # Add decimate modifier
        decimate = obj.modifiers.new(name="Decimate", type='DECIMATE')
        decimate.ratio = ratio
        decimate.use_collapse_triangulate = True
        
        # Apply the modifier
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier="Decimate")
        
    def optimize_materials(self, obj, lod_level):
        """Compress and optimize materials for LOD level"""
        if not obj.data.materials:
            return
            
        for mat_slot in obj.material_slots:
            if mat_slot.material:
                material = mat_slot.material
                
                # Create simplified material for higher LOD levels
                if lod_level > 0:
                    # Duplicate material for LOD
                    new_mat = material.copy()
                    new_mat.name = f"{material.name}_LOD{lod_level}"
                    
                    # Simplify material based on LOD level
                    if new_mat.use_nodes:
                        self.simplify_material_nodes_advanced(new_mat, lod_level)
                    
                    mat_slot.material = new_mat
                    
    def compress_material_textures(self, material, lod_level):
        """Compress texture sizes for LOD level"""
        nodes = material.node_tree_advanced.nodes
        
        # Calculate target resolution based on LOD level
        # LOD0: Original size, LOD1: 1/4 size, LOD2: 1/8 size, LOD3: 1/16 size
        resolution_divisors = [1, 2, 4, 8]
        divisor = resolution_divisors[min(lod_level, len(resolution_divisors) - 1)]
        
        # Process all texture nodes
        for node in nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                original_image = node.image
                
                # Skip if image is already processed for this LOD
                lod_suffix = f"_LOD{lod_level}"
                if lod_suffix in original_image.name:
                    continue
                
                # Calculate new dimensions
                original_width = original_image.size[0]
                original_height = original_image.size[1]
                
                new_width = max(64, original_width // divisor)  # Minimum 64px
                new_height = max(64, original_height // divisor)  # Minimum 64px
                
                # Only compress if the new size is different
                if new_width != original_width or new_height != original_height:
                    # Create compressed version
                    compressed_image = self.create_compressed_image(
                        original_image, 
                        new_width, 
                        new_height, 
                        lod_level
                    )
                    
                    if compressed_image:
                        node.image = compressed_image
                        print(f"  Compressed texture: {original_image.name} "
                              f"({original_width}x{original_height}) -> "
                              f"{compressed_image.name} ({new_width}x{new_height})")
                        
        # For higher LOD levels, also remove complex nodes
        if lod_level >= 2:
            self.simplify_material_nodes_advanced(material, lod_level)
            
    def create_compressed_image(self, original_image, new_width, new_height, lod_level):
        """Create a compressed version of an image"""
        try:
            # Create new image with compressed dimensions
            compressed_name = f"{original_image.name}_LOD{lod_level}"
            
            # Remove existing compressed image if it exists
            if compressed_name in bpy.data.images:
                bpy.data.images.remove(bpy.data.images[compressed_name])
            
            # Create new image
            compressed_image = bpy.data.images.new(
                name=compressed_name,
                width=new_width,
                height=new_height,
                alpha=original_image.channels == 4
            )
            
            # Copy and resize pixel data
            if original_image.pixels:
                # Get original pixels
                original_pixels = list(original_image.pixels)
                original_width = original_image.size[0]
                original_height = original_image.size[1]
                channels = original_image.channels
                
                # Create new pixel array
                new_pixels = []
                
                # Simple nearest-neighbor sampling for resizing
                for y in range(new_height):
                    for x in range(new_width):
                        # Map new coordinates to original coordinates
                        orig_x = int((x / new_width) * original_width)
                        orig_y = int((y / new_height) * original_height)
                        
                        # Clamp coordinates
                        orig_x = min(orig_x, original_width - 1)
                        orig_y = min(orig_y, original_height - 1)
                        
                        # Get pixel index in original image
                        orig_index = (orig_y * original_width + orig_x) * channels
                        
                        # Copy pixel data
                        for c in range(channels):
                            if orig_index + c < len(original_pixels):
                                new_pixels.append(original_pixels[orig_index + c])
                            else:
                                new_pixels.append(0.0)
                
                # Assign new pixels
                compressed_image.pixels = new_pixels
                
            # Copy image settings
            compressed_image.colorspace_settings.name = original_image.colorspace_settings.name
            compressed_image.alpha_mode = original_image.alpha_mode
            
            return compressed_image
            
        except Exception as e:
            print(f"  Warning: Failed to compress image {original_image.name}: {e}")
            return original_image
            
    def simplify_material_nodes_advanced(self, material, lod_level):
        """Remove complex material nodes for higher LOD levels"""
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        
        # For LOD2+, remove detail nodes
        if lod_level >= 2:
            nodes_to_remove = []
            for node in nodes:
                if node.type in ['NORMAL_MAP', 'DISPLACEMENT', 'BUMP']:
                    nodes_to_remove.append(node)
                    
            for node in nodes_to_remove:
                nodes.remove(node)
                
        # For LOD3+, keep only essential nodes
        if lod_level >= 3:
            nodes_to_keep = []
            for node in nodes:
                if node.type in ['BSDF_PRINCIPLED', 'OUTPUT_MATERIAL', 'TEX_IMAGE']:
                    nodes_to_keep.append(node)
                    
            nodes_to_remove = [node for node in nodes if node not in nodes_to_keep]
            for node in nodes_to_remove:
                nodes.remove(node)
                
    def create_lod_collection(self, lod_level):
        """Create a collection for LOD level"""
        collection_name = f"LOD_{lod_level}"
        if collection_name in bpy.data.collections:
            bpy.data.collections.remove(bpy.data.collections[collection_name])
            
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)
        return collection
        
    def export_lod(self, objects, lod_level):
        """Export LOD objects to file"""
        # Select only the LOD objects
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects:
            obj.select_set(True)
            
        # Export path
        export_path = os.path.join(self.output_dir, f"{self.base_name}_LOD{lod_level}.obj")

        # 🔧 Ensure directory exists
        os.makedirs(os.path.dirname(export_path), exist_ok=True)

        try:
            bpy.ops.wm.obj_export(
                filepath=export_path,
                export_selected_objects=True,
                export_materials=True,
                export_triangulated_mesh=True,
                path_mode='COPY'
            )
        except (AttributeError, TypeError):
            try:
                # Blender 3.x
                bpy.ops.export_scene.obj(
                    filepath=export_path,
                    use_selection=True,
                    use_materials=True,
                    use_triangles=True,
                    path_mode='COPY'  # Copy textures to export folder
                )
            except (AttributeError, TypeError):
                # Fallback for older versions or parameter issues
                bpy.ops.export_scene.obj(
                    filepath=export_path,
                    use_selection=True,
                    use_materials=True,
                    use_triangles=True
                )
        
    def save_compressed_textures(self, lod_level):
        """Save compressed textures to disk"""
        texture_dir = os.path.join(self.output_dir, f"textures_LOD{lod_level}")
        if not os.path.exists(texture_dir):
            os.makedirs(texture_dir)
            
        saved_textures = []
        for image in bpy.data.images:
            if f"_LOD{lod_level}" in image.name and image.has_data:
                try:
                    # Set file format for export
                    image.file_format = 'PNG'  # or 'JPEG' for smaller files
                    
                    # Save path
                    texture_path = os.path.join(texture_dir, f"{image.name}.png")
                    image.filepath_raw = texture_path
                    image.save()
                    saved_textures.append(texture_path)
                    print(f"  Saved compressed texture: {texture_path}")
                except Exception as e:
                    print(f"  Warning: Failed to save texture {image.name}: {e}")
                    
        return saved_textures
        
    def generate_lods(self):
        """Main function to generate all LOD levels"""
        print(f"Generating LODs for: {self.input_file}")
        
        # Clear scene
        self.clear_scene()
        
        # Import original model
        imported_objects = self.import_obj()
        if not imported_objects:
            print("Failed to import OBJ file")
            return
            
        original_objects = imported_objects.copy()
        
        # Generate each LOD level
        for lod_level, ratio in enumerate(self.lod_ratios):
            print(f"Creating LOD {lod_level} with ratio {ratio}")
            
            # Create collection for this LOD
            lod_collection = self.create_lod_collection(lod_level)
            
            # Work with copies of original objects for each LOD
            lod_objects = []
            
            for orig_obj in original_objects:
                if orig_obj.type == 'MESH':
                    # Create copy for this LOD
                    lod_obj = orig_obj.copy()
                    lod_obj.data = orig_obj.data.copy()
                    lod_obj.name = f"{orig_obj.name}_LOD{lod_level}"
                    
                    # Link to scene and collection
                    bpy.context.collection.objects.link(lod_obj)
                    lod_collection.objects.link(lod_obj)
                    lod_objects.append(lod_obj)
                    
                    # Apply decimation if not LOD 0
                    if lod_level > 0:
                        self.decimate_mesh(lod_obj, ratio)
                        
                    # Optimize materials
                    self.optimize_materials(lod_obj, lod_level)
                    
            # Save compressed textures for this LOD level
            if lod_level > 0:
                self.save_compressed_textures(lod_level)
                    
            # Export this LOD level
            if lod_objects:
                self.export_lod(lod_objects, lod_level)
                
        print("LOD generation complete!")
        
        # Print summary
        self.print_summary()
        
    def print_summary(self):
        """Print generation summary"""
        print("\n" + "="*50)
        print("LOD GENERATION SUMMARY")
        print("="*50)
        print(f"Input file: {self.input_file}")
        print(f"Output directory: {self.output_dir}")
        print(f"Generated {self.lod_levels} LOD levels:")
        
        for i, ratio in enumerate(self.lod_ratios):
            poly_percentage = int(ratio * 100)
            output_file = f"{self.base_name}_LOD{i}.obj"
            print(f"  LOD {i}: {poly_percentage}% polygons -> {output_file}")
            
        print("="*50)

# Usage example and main execution
def main():
    # Configuration - modify these paths as needed
    INPUT_OBJ_FILE = "C:/Users/AMerchant/Documents/Level_4/test2/P28_01_INT_401S_LOD400.obj"  # Change this path
    OUTPUT_DIRECTORY = "C:/Users/AMerchant/Documents/Level_4/test2_LODs_0/"       # Change this path (optional)
    LOD_LEVELS = 3  # Number of LOD levels to generate
    
    # Validate input file
    if not os.path.exists(INPUT_OBJ_FILE):
        print(f"Error: Input file not found: {INPUT_OBJ_FILE}")
        print("Please update the INPUT_OBJ_FILE path in the script")
        return
        
    # Create output directory if it doesn't exist
    if OUTPUT_DIRECTORY and not os.path.exists(OUTPUT_DIRECTORY):
        os.makedirs(OUTPUT_DIRECTORY)
        
    # Generate LODs
    generator = LODGenerator(INPUT_OBJ_FILE, OUTPUT_DIRECTORY, LOD_LEVELS)
    generator.generate_lods()

# Alternative function for direct execution with parameters
def generate_lods_from_file(input_file, output_dir="", lod_levels=3):
    """
    Generate LODs from an input OBJ file
    
    Args:
        input_file (str): Path to input OBJ file
        output_dir (str): Output directory (default: same as input file)
        lod_levels (int): Number of LOD levels to generate (default: 4)
    """
    output_dir = os.path.join(output_dir, "temp", "lods")
    os.makedirs(output_dir, exist_ok=True)

    generator = LODGenerator(input_file, output_dir, lod_levels)

    generator.generate_lods()

# Execute main function
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Generate LODs for an OBJ file")
    parser.add_argument("--input", required=True, help="Path to input OBJ file")
    parser.add_argument("--output", required=False, default="", help="Path to output directory")
    parser.add_argument("--lods", type=int, default=3, help="Number of LOD levels to generate")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    
    generate_lods_from_file(args.input, args.output, args.lods)

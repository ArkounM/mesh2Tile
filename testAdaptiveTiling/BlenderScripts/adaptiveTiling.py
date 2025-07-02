import bpy, bmesh
from mathutils import Vector
import os
import sys

# ===========================================
# CONFIGURATION - MODIFY THESE PATHS FOR TESTING
# ===========================================

# Test configuration - set these paths for your system
#TEST_OBJ_PATH = ""  # Change this to your test OBJ file
#TEST_OUTPUT_DIR = ""     # Change this to your output directory

# Parse CLI arguments passed after `--`
if "--" in sys.argv:
    argv = sys.argv[sys.argv.index("--") + 1:]
    if len(argv) >= 2:
        TEST_OBJ_PATH = argv[0]
        TEST_OUTPUT_DIR = argv[1]
    else:
        print("❌ Error: Expected 2 arguments after '--': input_path output_dir")
        sys.exit(1)
else:
    print("❌ Error: Missing '--' in arguments. Blender CLI should use '--' before script args.")
    sys.exit(1)

# Alternative: Use a blend file object instead of importing
USE_EXISTING_OBJECT = False  # Set to True to use selected object in scene
EXISTING_OBJECT_NAME = ""   # Leave empty to use active object, or specify name

# Script parameters
TRIANGLE_THRESHOLD = 10000
MAX_TILE_LEVEL = 3  # Reduced for testing to prevent too many objects

# Mesh cleanup parameters
MERGE_DISTANCE = 0.001  # Distance threshold for merging vertices

# ===========================================
# ADAPTIVE TILING FUNCTIONS (Enhanced)
# ===========================================

# Global counters for tracking
total_exported = 0
total_decimated = 0
def clear_scene(self):
    """Clear all objects from the scene"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    print("Scene cleared.")


def cleanup_mesh(obj):
    """Clean up mesh by merging vertices by distance and removing doubles"""
    print(f"  Cleaning up mesh for {obj.name}...")
    
    # Select the object and make it active
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    
    # Enter edit mode
    bpy.ops.object.mode_set(mode='EDIT')
    
    # Select all vertices
    bpy.ops.mesh.select_all(action='SELECT')
    
    # Merge vertices by distance
    original_verts = len(obj.data.vertices)
    bpy.ops.mesh.remove_doubles(threshold=MERGE_DISTANCE)
    
    # Update mesh
    bpy.ops.mesh.normals_make_consistent(inside=False)
    
    # Exit edit mode
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Update mesh data
    obj.data.update()
    
    new_verts = len(obj.data.vertices)
    merged_verts = original_verts - new_verts
    
    print(f"    Merged {merged_verts} vertices (was: {original_verts}, now: {new_verts})")
    print(".    Mesh cleanup complete.")

def get_bounds(obj, local=True):
    """Get the bounding box of an object"""
    if local:
        coords = obj.bound_box
    else:
        coords = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [p[0] for p in coords]; ys = [p[1] for p in coords]; zs = [p[2] for p in coords]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))

def get_triangle_count(obj):
    """Get the number of triangles in a mesh object"""
    if obj.type != 'MESH' or not obj.data:
        return 0
    
    # Ensure mesh is triangulated for accurate count
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    triangle_count = len(bm.faces)
    bm.free()
    return triangle_count

def duplicate_object(obj, new_name):
    """Create a duplicate of an object with a new name"""
    # Create new mesh data
    new_mesh = obj.data.copy()
    new_mesh.name = new_name + "_mesh"
    
    # Create new object
    new_obj = bpy.data.objects.new(new_name, new_mesh)
    bpy.context.collection.objects.link(new_obj)
    
    # Copy materials
    for mat in obj.data.materials:
        new_mesh.materials.append(mat)
    
    # Copy transform
    new_obj.location = obj.location.copy()
    new_obj.rotation_euler = obj.rotation_euler.copy()
    new_obj.scale = obj.scale.copy()
    
    return new_obj

def decimate_object(obj, target_triangles):
    """Decimate an object to target triangle count"""
    global total_decimated
    
    current_triangles = get_triangle_count(obj)
    if current_triangles <= target_triangles:
        print(f"  Object {obj.name} already has {current_triangles} triangles (≤ {target_triangles})")
        return obj
    
    print(f"  Decimating {obj.name} from {current_triangles} to {target_triangles} triangles")
    
    # Calculate decimation ratio
    ratio = target_triangles / current_triangles
    
    # Apply decimation modifier
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    
    # Add decimate modifier
    decimate_mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
    decimate_mod.ratio = ratio
    decimate_mod.use_collapse_triangulate = True
    
    # Apply modifier
    bpy.ops.object.modifier_apply(modifier="Decimate")
    
    final_triangles = get_triangle_count(obj)
    print(f"    Result: {final_triangles} triangles (ratio: {ratio:.3f})")
    total_decimated += 1
    
    return obj

def create_chunk_with_materials(bm, chunk_name, original_obj):
    """Create a new object from bmesh with preserved materials"""
    if len(bm.faces) == 0:
        return None
    
    me = bpy.data.meshes.new(chunk_name + "_mesh")
    bm.to_mesh(me)
    
    # Copy all materials from original
    for mat in original_obj.data.materials:
        me.materials.append(mat)
    
    # Restore material assignments if we have the material layer
    if "material_index" in bm.faces.layers.int:
        material_layer = bm.faces.layers.int["material_index"]
        bm.faces.ensure_lookup_table()

        for i, poly in enumerate(me.polygons):
            if i < len(bm.faces):
                stored_mat_index = bm.faces[i][material_layer]
                poly.material_index = min(stored_mat_index, len(me.materials) - 1)
    
    ob = bpy.data.objects.new(chunk_name, me)
    bpy.context.collection.objects.link(ob)
    return ob

def bisect_object_octree(obj, tile_level, ix, iy, iz):
    """
    Bisect an object into 8 octree chunks (2x2x2)
    Returns list of non-empty chunk objects
    """
    print(f"  Bisecting object {obj.name} into octree...")
    
    # Get bounds
    (xmin, xmax), (ymin, ymax), (zmin, zmax) = get_bounds(obj, True)
    
    print(f"    Bounds: X({xmin:.3f}, {xmax:.3f}), Y({ymin:.3f}, {ymax:.3f}), Z({zmin:.3f}, {zmax:.3f})")
    
    # Calculate midpoints
    x_mid = (xmin + xmax) / 2
    y_mid = (ymin + ymax) / 2
    z_mid = (zmin + zmax) / 2
    
    # Create bmesh from object
    bm_orig = bmesh.new()
    obj.data.update()
    bm_orig.from_mesh(obj.data)
    bm_orig.faces.ensure_lookup_table()
    bm_orig.verts.ensure_lookup_table()
    
    # Store material indices in custom layer
    if len(obj.data.materials) > 0:
        material_layer = bm_orig.faces.layers.int.new("material_index")
        for i, face in enumerate(bm_orig.faces):
            poly_index = i if i < len(obj.data.polygons) else 0
            face[material_layer] = obj.data.polygons[poly_index].material_index
    
    chunks = []
    
    # Create 8 octree chunks (2x2x2)
    for dx in range(2):
        for dy in range(2):
            for dz in range(2):
                bm = bm_orig.copy()
                
                # Calculate new indices
                new_ix = ix * 2 + dx
                new_iy = iy * 2 + dy
                new_iz = iz * 2 + dz
                
                chunk_name = f"{int(tile_level)}_{int(new_ix)}_{int(new_iy)}_{int(new_iz)}"
                
                print(f"    Processing chunk {chunk_name} (dx:{dx}, dy:{dy}, dz:{dz})")
                
                # Define chunk boundaries
                x_left = xmin if dx == 0 else x_mid
                x_right = x_mid if dx == 0 else xmax
                y_bottom = ymin if dy == 0 else y_mid
                y_top = y_mid if dy == 0 else ymax
                z_bottom = zmin if dz == 0 else z_mid
                z_top = z_mid if dz == 0 else zmax
                
                # Center points for bisection planes
                center_x = (x_left + x_right) / 2
                center_y = (y_bottom + y_top) / 2
                center_z = (z_bottom + z_top) / 2
                
                # Cut along X-axis
                if dx == 0:  # Keep left half
                    bmesh.ops.bisect_plane(
                        bm,
                        geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                        plane_co=Vector((x_mid, center_y, center_z)),
                        plane_no=Vector((1, 0, 0)),
                        clear_outer=True,
                        clear_inner=False
                    )
                else:  # Keep right half
                    bmesh.ops.bisect_plane(
                        bm,
                        geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                        plane_co=Vector((x_mid, center_y, center_z)),
                        plane_no=Vector((-1, 0, 0)),
                        clear_outer=True,
                        clear_inner=False
                    )
                
                # Cut along Y-axis
                if dy == 0:  # Keep bottom half
                    bmesh.ops.bisect_plane(
                        bm,
                        geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                        plane_co=Vector((center_x, y_mid, center_z)),
                        plane_no=Vector((0, 1, 0)),
                        clear_outer=True,
                        clear_inner=False
                    )
                else:  # Keep top half
                    bmesh.ops.bisect_plane(
                        bm,
                        geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                        plane_co=Vector((center_x, y_mid, center_z)),
                        plane_no=Vector((0, -1, 0)),
                        clear_outer=True,
                        clear_inner=False
                    )
                
                # Cut along Z-axis
                if dz == 0:  # Keep bottom half
                    bmesh.ops.bisect_plane(
                        bm,
                        geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                        plane_co=Vector((center_x, center_y, z_mid)),
                        plane_no=Vector((0, 0, 1)),
                        clear_outer=True,
                        clear_inner=False
                    )
                else:  # Keep top half
                    bmesh.ops.bisect_plane(
                        bm,
                        geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                        plane_co=Vector((center_x, center_y, z_mid)),
                        plane_no=Vector((0, 0, -1)),
                        clear_outer=True,
                        clear_inner=False
                    )
                
                # Create chunk object if it has geometry
                if len(bm.faces) > 0 and len(bm.verts) > 0:
                    chunk_obj = create_chunk_with_materials(bm, chunk_name, obj)
                    if chunk_obj:
                        chunks.append(chunk_obj)
                        print(f"      Created chunk {chunk_name}: {len(bm.faces)} faces")
                else:
                    print(f"      Chunk {chunk_name} is empty - skipping")
                
                bm.free()
    
    bm_orig.free()
    print(f"    Created {len(chunks)} non-empty chunks")
    return chunks

def get_tile_level_from_name(obj_name):
    """Extract tile level from object name"""
    parts = obj_name.split('_')
    if len(parts) >= 1 and parts[0].isdigit():
        return int(parts[0])
    return 0

def clean_object_name(obj_name):
    """Remove '_decimated' suffix from object name"""
    return obj_name.replace('_decimated', '')

def export_object_test(obj, output_dir):
    """Export an object to OBJ file organized by tile level"""
    global total_exported
    
    # Get tile level from object name
    tile_level = get_tile_level_from_name(obj.name)
    
    # Clean the object name (remove _decimated suffix)
    clean_name = clean_object_name(obj.name)
    
    print(f"  Exporting {obj.name} -> {clean_name} (Tile Level: {tile_level}):")
    print(f"    Vertices: {len(obj.data.vertices)}")
    print(f"    Faces: {len(obj.data.polygons)}")
    print(f"    Triangles: {get_triangle_count(obj)}")
    print(f"    Materials: {len(obj.data.materials)}")
    
    # Create tile level folder
    tile_folder = os.path.join(output_dir, f"TileLevel_{tile_level}")
    os.makedirs(tile_folder, exist_ok=True)
    
    # Select only this object
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    
    # Export with cleaned name
    output_file = os.path.join(tile_folder, f"{clean_name}.obj")
    bpy.ops.wm.obj_export(
        filepath=output_file,
        export_selected_objects=True,
        export_materials=True,
        export_uv=True,
        apply_modifiers=False,
        global_scale=1.0
    )
    print(f"    Exported: {output_file}")
    
    total_exported += 1

def process_object_adaptive(obj, tile_level=0, ix=0, iy=0, iz=0, max_level=MAX_TILE_LEVEL):
    """
    Recursively process an object with adaptive tiling
    """
    print(f"\n=== Processing object {obj.name} at tile level {tile_level} ===")
    
    triangle_count = get_triangle_count(obj)
    print(f"Triangle count: {triangle_count}")
    
    # Check if we need to tile this object
    if triangle_count <= TRIANGLE_THRESHOLD:
        print(f"Object has ≤ {TRIANGLE_THRESHOLD} triangles - exporting as is")
        export_object_test(obj, TEST_OUTPUT_DIR)
        return
    
    if tile_level >= max_level:
        print(f"Maximum tile level ({max_level}) reached - decimating and exporting")
        decimate_object(obj, TRIANGLE_THRESHOLD)
        export_object_test(obj, TEST_OUTPUT_DIR)
        return
    
    print(f"Object exceeds {TRIANGLE_THRESHOLD} triangles - tiling...")
    
    # Duplicate the object
    decimated_name = f"{tile_level}_{ix}_{iy}_{iz}_decimated"
    decimated_obj = duplicate_object(obj, decimated_name)
    
    # Decimate the duplicate
    decimate_object(decimated_obj, TRIANGLE_THRESHOLD)
    export_object_test(decimated_obj, TEST_OUTPUT_DIR)
    
    # For testing, we might want to keep the decimated object visible
    # Remove the decimated object from scene (we've exported it)
    # bpy.data.objects.remove(decimated_obj, do_unlink=True)
    
    # Bisect the original object into octree
    chunks = bisect_object_octree(obj, tile_level + 1, ix, iy, iz)
    
    # Remove the original object (it's been split)
    bpy.data.objects.remove(obj, do_unlink=True)
    
    # Recursively process each chunk
    for chunk in chunks:
        # Parse chunk name to get coordinates
        parts = chunk.name.split('_')
        if len(parts) >= 4:
            chunk_tile_level = int(parts[0])
            chunk_ix = int(parts[1])
            chunk_iy = int(parts[2])
            chunk_iz = int(parts[3])
            
            process_object_adaptive(chunk, chunk_tile_level, chunk_ix, chunk_iy, chunk_iz, max_level)

# ===========================================
# TEST SETUP AND EXECUTION
# ===========================================

def setup_test_object():
    """Setup test object - either import OBJ or use existing object"""
    
    if USE_EXISTING_OBJECT:
        # Use existing object from scene
        if EXISTING_OBJECT_NAME:
            # Use specified object
            if EXISTING_OBJECT_NAME in bpy.data.objects:
                obj = bpy.data.objects[EXISTING_OBJECT_NAME]
                print(f"Using existing object: {obj.name}")
            else:
                print(f"ERROR: Object '{EXISTING_OBJECT_NAME}' not found!")
                return None
        else:
            # Use active object
            obj = bpy.context.active_object
            if not obj:
                print("ERROR: No active object selected!")
                print("Please select an object in the 3D viewport or set EXISTING_OBJECT_NAME")
                return None
            print(f"Using active object: {obj.name}")
        
        if obj.type != 'MESH':
            print(f"ERROR: Selected object is not a mesh! Type: {obj.type}")
            return None
            
        # Duplicate the object so we don't modify the original
        original_name = obj.name
        obj = duplicate_object(obj, f"{original_name}_test_copy")
        print(f"Created test copy: {obj.name}")
        
    else:
        # Import OBJ file
        if not os.path.exists(TEST_OBJ_PATH):
            print(f"ERROR: Test OBJ file not found: {TEST_OBJ_PATH}")
            print("Please update TEST_OBJ_PATH or set USE_EXISTING_OBJECT = True")
            return None
        
        print(f"Importing OBJ from: {TEST_OBJ_PATH}")
        
        # Clear selection
        bpy.ops.object.select_all(action='DESELECT')
        
        try:
            bpy.ops.wm.obj_import(filepath=TEST_OBJ_PATH)
            obj = bpy.context.selected_objects[0] if bpy.context.selected_objects else None
            if not obj:
                print("ERROR: No object was imported!")
                return None
            print(f"Imported object: {obj.name}")
        except Exception as e:
            print(f"Import failed: {e}")
            return None
    
    return obj

def run_adaptive_tiling_test():
    """Main test function"""
    global total_exported, total_decimated
    clear_scene(None)  # Clear the scene before starting
    
    print("=" * 50)
    print("ADAPTIVE OCTREE TILING - BLENDER TEST")
    print("=" * 50)
    print(f"Triangle threshold: {TRIANGLE_THRESHOLD}")
    print(f"Max tile level: {MAX_TILE_LEVEL}")
    print(f"Merge distance: {MERGE_DISTANCE}")
    print(f"Use existing object: {USE_EXISTING_OBJECT}")
    if not USE_EXISTING_OBJECT:
        print(f"Test OBJ path: {TEST_OBJ_PATH}")
    print(f"Output directory: {TEST_OUTPUT_DIR}")
    print()
    
    # Reset counters
    total_exported = 0
    total_decimated = 0
    
    # Setup test object
    obj = setup_test_object()
    if not obj:
        return
    
    print(f"Test object: {obj.name}")
    print(f"Vertices: {len(obj.data.vertices)}")
    print(f"Polygons: {len(obj.data.polygons)}")
    print(f"Triangles: {get_triangle_count(obj)}")
    print(f"Materials: {len(obj.data.materials)}")
    
    # Apply transforms
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    print("Transforms applied.")
    
    # CLEANUP MESH - New addition
    print("\n" + "=" * 30)
    print("CLEANING UP MESH")
    print("=" * 30)
    cleanup_mesh(obj)
    
    # Start adaptive processing
    process_object_adaptive(obj, tile_level=0, ix=0, iy=0, iz=0)
    
    print("\n" + "=" * 50)
    print("ADAPTIVE TILING TEST COMPLETE")
    print("=" * 50)
    print(f"Total objects processed: {total_exported}")
    print(f"Total objects decimated: {total_decimated}")
    print(f"Check the 3D viewport to see the generated tiles")
    print(f"Objects in scene: {len([o for o in bpy.data.objects if o.type == 'MESH'])}")
    print(f"Output organized in folders by tile level in: {TEST_OUTPUT_DIR}")

# ===========================================
# RUN THE TEST
# ===========================================

# Execute the test
run_adaptive_tiling_test()
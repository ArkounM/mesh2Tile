import bpy, bmesh
from mathutils import Vector
import os
import sys


# Configuration
obj_path = "C:/Users/AMerchant/Documents/Level_4/test2/LODs/P28_01_INT_401S_LOD400_LOD0.obj"
output_dir = "C:/Users/AMerchant/Documents/Level_4/test3_Tiled_0/"

# Parse arguments passed after the "--" delimiter
argv = sys.argv
argv = argv[argv.index("--") + 1:] if "--" in argv else []

if len(argv) != 2:
    print("Usage: blender --background --python your_script.py -- <input_path> <output_dir>")
    sys.exit(1)

obj_path = argv[0]
output_dir = argv[1]

# Detect LOD from filename (assumes LOD0, LOD1, LOD2 in filename)
if "LOD0" in obj_path.upper():
    chunks = (4, 4, 2)
    lod_prefix = "2"  # LOD0 = "2-x-y-z"
elif "LOD1" in obj_path.upper():
    chunks = (2, 2, 1)
    lod_prefix = "1"  # LOD1 = "1-x-y-z"
elif "LOD2" in obj_path.upper():
    chunks = (1, 1, 1)
    lod_prefix = "0"  # LOD2 = "0-x-y-z"
else:
    print("ERROR: Cannot detect LOD level from filename.")
    sys.exit(1)

print(f"Using chunks: {chunks} with LOD prefix: {lod_prefix}")

# REMOVED: chunks = (2, 2, 2)  # This was overriding the detected chunks!

if not os.path.exists(output_dir):
    os.makedirs(output_dir, exist_ok=True)

# Define utility functions first
def get_bounds(o, local=True):
    if local:
        coords = o.bound_box
    else:
        coords = [o.matrix_world @ Vector(c) for c in o.bound_box]
    xs = [p[0] for p in coords]; ys = [p[1] for p in coords]; zs = [p[2] for p in coords]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))

# Function to create a new object from bmesh WITH material preservation
def new_object_from_bmesh(bm, name, original_obj):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    
    # Copy materials from original object
    for mat in original_obj.data.materials:
        me.materials.append(mat)
    
    # Copy material assignments for faces that still exist
    # Note: bmesh operations may have changed face indices, so we need to be careful
    if len(me.polygons) > 0 and len(original_obj.data.materials) > 0:
        # Try to preserve material assignments based on face centers
        # This is a fallback - for complex cases you might need more sophisticated mapping
        for poly in me.polygons:
            # Use the first material as default if we can't determine the original assignment
            poly.material_index = 0
    
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob

# Alternative: More sophisticated material preservation
def new_object_from_bmesh_advanced(bm, name, original_obj, face_material_map=None):
    """
    Create new object with more sophisticated material preservation
    face_material_map: dict mapping new face indices to original material indices
    """
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    
    # Copy materials from original object
    for mat in original_obj.data.materials:
        me.materials.append(mat)
    
    # Apply material assignments if we have the mapping
    if face_material_map and len(me.polygons) > 0:
        for i, poly in enumerate(me.polygons):
            if i in face_material_map:
                poly.material_index = face_material_map[i]
            else:
                poly.material_index = 0  # Default to first material
    
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob

# Clear scene.
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Import OBJ (adjust as needed).
print(f"Attempting to import OBJ from: {obj_path}")
print(f"File exists: {os.path.exists(obj_path)}")

try:
    bpy.ops.wm.obj_import(filepath=obj_path)
    print(f"Import successful. Selected objects: {len(bpy.context.selected_objects)}")
except Exception as e:
    print(f"Import failed with error: {e}")
    exit()

if len(bpy.context.selected_objects) == 0:
    print("ERROR: No objects were imported!")
    exit()

obj = bpy.context.selected_objects[0]
print(f"Imported object name: {obj.name}")
print(f"Object type: {obj.type}")

if obj.type != 'MESH':
    print(f"ERROR: Imported object is not a mesh! Type: {obj.type}")
    exit()

print(f"Mesh data exists: {obj.data is not None}")
print(f"Number of vertices: {len(obj.data.vertices)}")
print(f"Number of polygons: {len(obj.data.polygons)}")
print(f"Number of materials: {len(obj.data.materials)}")

# Print material information
if len(obj.data.materials) > 0:
    print("Materials found:")
    for i, mat in enumerate(obj.data.materials):
        print(f"  Material {i}: {mat.name if mat else 'None'}")
else:
    print("WARNING: No materials found on imported object!")

if len(obj.data.vertices) == 0:
    print("ERROR: Imported mesh has no vertices!")
    exit()

bpy.context.view_layer.objects.active = obj

# Store original material assignments before any operations
original_material_assignments = {}
for i, poly in enumerate(obj.data.polygons):
    original_material_assignments[i] = poly.material_index

print(f"Stored material assignments for {len(original_material_assignments)} faces")

# Print original bounds BEFORE applying transforms
print("\n=== BOUNDS BEFORE TRANSFORM ===")
(xmin_orig, xmax_orig), (ymin_orig, ymax_orig), (zmin_orig, zmax_orig) = get_bounds(obj, False)
print(f"World space bounds: X({xmin_orig:.3f}, {xmax_orig:.3f}), Y({ymin_orig:.3f}, {ymax_orig:.3f}), Z({zmin_orig:.3f}, {zmax_orig:.3f})")
(xmin_local, xmax_local), (ymin_local, ymax_local), (zmin_local, zmax_local) = get_bounds(obj, True)
print(f"Local space bounds: X({xmin_local:.3f}, {xmax_local:.3f}), Y({ymin_local:.3f}, {ymax_local:.3f}), Z({zmin_local:.3f}, {zmax_local:.3f})")

# Apply transformations to ensure we're working in local space consistently
print(f"Object location: {obj.location}")
print(f"Object rotation: {obj.rotation_euler}")
print(f"Object scale: {obj.scale}")

bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
print("Transforms applied.")

# Get bounds in local space after applying transforms
(xmin, xmax), (ymin, ymax), (zmin, zmax) = get_bounds(obj, True)

print(f"\n=== BOUNDS AFTER TRANSFORM ===")
print(f"Final bounds used for cutting: X({xmin:.3f}, {xmax:.3f}), Y({ymin:.3f}, {ymax:.3f}), Z({zmin:.3f}, {zmax:.3f})")

# Validate bounds make sense
x_size = xmax - xmin
y_size = ymax - ymin
z_size = zmax - zmin
print(f"Object dimensions: X={x_size:.3f}, Y={y_size:.3f}, Z={z_size:.3f}")

if x_size <= 0 or y_size <= 0 or z_size <= 0:
    print("ERROR: Object has zero or negative dimensions!")
    exit()

# Load original into BMesh with proper mesh update
bm_orig = bmesh.new()
obj.data.update()
bm_orig.from_mesh(obj.data)
bm_orig.faces.ensure_lookup_table()
bm_orig.verts.ensure_lookup_table()

# IMPORTANT: Store material indices in bmesh custom data layer
# This preserves material assignments through bmesh operations
if len(obj.data.materials) > 0:
    # Create a custom integer layer to store material indices
    material_layer = bm_orig.faces.layers.int.new("material_index")
    for i, face in enumerate(bm_orig.faces):
        # Store the original material index
        face[material_layer] = original_material_assignments.get(i, 0)
    print(f"Created material layer and stored indices for {len(bm_orig.faces)} faces")

print(f"\n=== BMESH DATA ===")
print(f"Original mesh has {len(bm_orig.verts)} vertices, {len(bm_orig.faces)} faces")

if len(bm_orig.faces) == 0:
    print("ERROR: BMesh has no faces after loading!")
    bm_orig.free()
    exit()

# Prepare split ranges
ranges = [
    [xmin + i*(xmax - xmin)/chunks[0] for i in range(chunks[0]+1)],
    [ymin + i*(ymax - ymin)/chunks[1] for i in range(chunks[1]+1)],
    [zmin + i*(zmax - zmin)/chunks[2] for i in range(chunks[2]+1)],
]

print(f"\n=== CUTTING RANGES ===")
print(f"X ranges ({chunks[0]+1} points): {[f'{x:.3f}' for x in ranges[0]]}")
print(f"Y ranges ({chunks[1]+1} points): {[f'{y:.3f}' for y in ranges[1]]}")
print(f"Z ranges ({chunks[2]+1} points): {[f'{z:.3f}' for z in ranges[2]]}")

count = 0
exported_count = 0

# Function to create object with preserved materials
def create_chunk_with_materials(bm, chunk_name, original_obj):
    me = bpy.data.meshes.new(chunk_name)
    bm.to_mesh(me)
    
    # Copy all materials from original
    for mat in original_obj.data.materials:
        me.materials.append(mat)
    
    # Restore material assignments if we have the material layer
    if "material_index" in bm.faces.layers.int:
        material_layer = bm.faces.layers.int["material_index"]

        # Ensure lookup table is updated before using face indices
        bm.faces.ensure_lookup_table()

        for i, poly in enumerate(me.polygons):
            if i < len(bm.faces):
                stored_mat_index = bm.faces[i][material_layer]
                poly.material_index = min(stored_mat_index, len(me.materials) - 1)
    
    ob = bpy.data.objects.new(chunk_name, me)
    bpy.context.collection.objects.link(ob)
    return ob

# Iterate each cell - now creating chunks with X, Y, and Z divisions
for ix in range(chunks[0]):
    for iy in range(chunks[1]):
        for iz in range(chunks[2]):
            bm = bm_orig.copy()
            
            print(f"\n=== Processing chunk {count} (X:{ix}, Y:{iy}, Z:{iz}) ===")
            print(f"Starting with {len(bm.faces)} faces")

            # Calculate chunk boundaries
            x_left = ranges[0][ix]
            x_right = ranges[0][ix + 1]
            y_bottom = ranges[1][iy]
            y_top = ranges[1][iy + 1]
            z_bottom = ranges[2][iz]
            z_top = ranges[2][iz + 1]
            
            print(f"  Chunk bounds: X({x_left:.3f} to {x_right:.3f}), Y({y_bottom:.3f} to {y_top:.3f}), Z({z_bottom:.3f} to {z_top:.3f})")
            
            # Center points for bisection planes
            center_x = (x_left + x_right) / 2
            center_y = (y_bottom + y_top) / 2
            center_z = (z_bottom + z_top) / 2

            # Cut along X-axis (keep only the current X slice)
            print(f"  Cutting X: keeping slice between {x_left:.3f} and {x_right:.3f}")
            
            # Remove everything to the left of x_left
            if ix > 0:  # Only cut if not the leftmost chunk
                bmesh.ops.bisect_plane(
                    bm,
                    geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                    plane_co=Vector((x_left, center_y, center_z)),
                    plane_no=Vector((-1, 0, 0)),  # Normal pointing left
                    clear_outer=True,  # Remove everything on the left side
                    clear_inner=False
                )
                print(f"    After left X cut: {len(bm.faces)} faces")

            # Remove everything to the right of x_right
            if ix < chunks[0] - 1:  # Only cut if not the rightmost chunk
                bmesh.ops.bisect_plane(
                    bm,
                    geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                    plane_co=Vector((x_right, center_y, center_z)),
                    plane_no=Vector((1, 0, 0)),  # Normal pointing right
                    clear_outer=True,  # Remove everything on the right side
                    clear_inner=False
                )
                print(f"    After right X cut: {len(bm.faces)} faces")

            # Cut along Y-axis (keep only the current Y slice)
            print(f"  Cutting Y: keeping slice between {y_bottom:.3f} and {y_top:.3f}")
            
            # Remove everything below y_bottom
            if iy > 0:  # Only cut if not the bottom chunk
                bmesh.ops.bisect_plane(
                    bm,
                    geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                    plane_co=Vector((center_x, y_bottom, center_z)),
                    plane_no=Vector((0, -1, 0)),  # Normal pointing down
                    clear_outer=True,  # Remove everything below
                    clear_inner=False
                )
                print(f"    After bottom Y cut: {len(bm.faces)} faces")

            # Remove everything above y_top
            if iy < chunks[1] - 1:  # Only cut if not the top chunk
                bmesh.ops.bisect_plane(
                    bm,
                    geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                    plane_co=Vector((center_x, y_top, center_z)),
                    plane_no=Vector((0, 1, 0)),  # Normal pointing up
                    clear_outer=True,  # Remove everything above
                    clear_inner=False
                )
                print(f"    After top Y cut: {len(bm.faces)} faces")

            # Cut along Z-axis (keep only the current Z slice)
            print(f"  Cutting Z: keeping slice between {z_bottom:.3f} and {z_top:.3f}")
            
            # Remove everything below z_bottom
            if iz > 0:  # Only cut if not the bottom chunk
                bmesh.ops.bisect_plane(
                    bm,
                    geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                    plane_co=Vector((center_x, center_y, z_bottom)),
                    plane_no=Vector((0, 0, -1)),  # Normal pointing down (negative Z)
                    clear_outer=True,  # Remove everything below
                    clear_inner=False
                )
                print(f"    After bottom Z cut: {len(bm.faces)} faces")

            # Remove everything above z_top
            if iz < chunks[2] - 1:  # Only cut if not the top chunk
                bmesh.ops.bisect_plane(
                    bm,
                    geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                    plane_co=Vector((center_x, center_y, z_top)),
                    plane_no=Vector((0, 0, 1)),  # Normal pointing up (positive Z)
                    clear_outer=True,  # Remove everything above
                    clear_inner=False
                )
                print(f"    After top Z cut: {len(bm.faces)} faces")

            print(f"  Final result: {len(bm.faces)} faces remaining")

            # Check if chunk has any geometry left
            if len(bm.faces) > 0 and len(bm.verts) > 0:
                print(f"  Chunk {count} has {len(bm.faces)} faces, {len(bm.verts)} vertices - EXPORTING")
                # Updated chunk naming with LOD prefix
                chunk_name = f"{lod_prefix}_{ix}_{iy}_{iz}"
                create_chunk_with_materials(bm, chunk_name, obj)
                exported_count += 1
            else:
                print(f"  Chunk {count} is empty - SKIPPING")
            
            bm.free()
            count += 1

print(f"Created {exported_count} non-empty chunks out of {count} total chunks")

# Remove original
bpy.data.objects.remove(obj, do_unlink=True)

# Export only the chunks that were created (non-empty ones)
export_count = 0
for ob in bpy.context.collection.objects:
    # Updated to match new naming pattern (LOD prefix + underscore + coordinates)
    if not (ob.name.startswith("quad_") or ob.name.startswith("0_") or ob.name.startswith("1_") or ob.name.startswith("2_")):
        continue

    print(f"\nExporting {ob.name}:")
    print(f"  Vertices: {len(ob.data.vertices)}")
    print(f"  Faces: {len(ob.data.polygons)}")
    print(f"  Materials: {len(ob.data.materials)}")
    
    # Print material usage
    if len(ob.data.materials) > 0:
        mat_usage = {}
        for poly in ob.data.polygons:
            mat_idx = poly.material_index
            mat_usage[mat_idx] = mat_usage.get(mat_idx, 0) + 1
        
        print("  Material usage:")
        for mat_idx, count in mat_usage.items():
            mat_name = ob.data.materials[mat_idx].name if mat_idx < len(ob.data.materials) and ob.data.materials[mat_idx] else "None"
            print(f"    Material {mat_idx} ({mat_name}): {count} faces")

    # Export with correct operator
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob

    output_file = os.path.join(output_dir, f"{ob.name}.obj")
    bpy.ops.wm.obj_export(
        filepath=output_file,
        export_selected_objects=True,
        export_materials=True,  # This should now work properly
        export_uv=True,
        apply_modifiers=False,
        global_scale=1.0
    )
    export_count += 1
    print(f"  Exported: {output_file}")

print(f"Successfully exported {export_count} chunk files with materials to {output_dir}")

# Clean up bmesh
bm_orig.free()
"""
Adaptive Tiling Worker Script
Processes a single chunk from the first-level octree split in parallel.

This script is called by mesh2tile.py to enable parallel processing of octree chunks.
Each worker processes one chunk independently, allowing for significant speedup.
"""

import bpy, bmesh
from mathutils import Vector
import os
import sys

# Import shared functions from adaptiveTiling
# Since we can't easily import from another script, we'll duplicate necessary functions
# This is not ideal but works for Blender's execution model

# ===========================================
# CONFIGURATION
# ===========================================

# Parse CLI arguments passed after `--`
if "--" in sys.argv:
    argv = sys.argv[sys.argv.index("--") + 1:]
    if len(argv) >= 6:
        CHUNK_OBJ_PATH = argv[0]      # Input chunk OBJ file
        OUTPUT_DIR = argv[1]            # Output directory for tiles
        TILE_LEVEL = int(argv[2])       # Starting tile level
        IX = int(argv[3])               # X index
        IY = int(argv[4])               # Y index
        IZ = int(argv[5])               # Z index
        MAX_TILE_LEVEL = int(argv[6]) if len(argv) >= 7 else 3
        TRIANGLE_THRESHOLD = int(argv[7]) if len(argv) >= 8 else 20000
        MERGE_DISTANCE = float(argv[8]) if len(argv) >= 9 else 0.001
    else:
        print("❌ Error: Expected at least 6 arguments")
        print("Usage: blender --python adaptiveTilingWorker.py -- chunk.obj output_dir level ix iy iz [max_lod] [threshold] [merge_dist]")
        sys.exit(1)
else:
    print("❌ Error: Missing '--' in arguments")
    sys.exit(1)

# Global counters
total_exported = 0
total_decimated = 0
triangle_count_cache = {}
created_directories = set()

print(f"\n{'='*60}")
print(f"ADAPTIVE TILING WORKER")
print(f"{'='*60}")
print(f"Chunk: {CHUNK_OBJ_PATH}")
print(f"Starting indices: level={TILE_LEVEL}, ix={IX}, iy={IY}, iz={IZ}")
print(f"Max LOD: {MAX_TILE_LEVEL}")
print(f"Triangle threshold: {TRIANGLE_THRESHOLD}")
print(f"{'='*60}\n")

# ===========================================
# COPY OF NECESSARY FUNCTIONS FROM adaptiveTiling.py
# ===========================================

def get_bounds(obj, local=True):
    """Get the bounding box of an object"""
    if local:
        coords = obj.bound_box
    else:
        coords = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [p[0] for p in coords]; ys = [p[1] for p in coords]; zs = [p[2] for p in coords]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))

def get_triangle_count(obj):
    """Get the number of triangles in a mesh object (with caching)"""
    global triangle_count_cache

    if obj.type != 'MESH' or not obj.data:
        return 0

    cache_key = (obj.name, len(obj.data.vertices), len(obj.data.polygons))
    if cache_key in triangle_count_cache:
        return triangle_count_cache[cache_key]

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    triangle_count = len(bm.faces)
    bm.free()

    triangle_count_cache[cache_key] = triangle_count
    return triangle_count

def duplicate_object(obj, new_name):
    """Create a duplicate of an object with a new name"""
    new_mesh = obj.data.copy()
    new_mesh.name = new_name + "_mesh"

    new_obj = bpy.data.objects.new(new_name, new_mesh)
    bpy.context.collection.objects.link(new_obj)

    for mat in obj.data.materials:
        new_mesh.materials.append(mat)

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

    ratio = target_triangles / current_triangles

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    decimate_mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
    decimate_mod.ratio = ratio
    decimate_mod.use_collapse_triangulate = True

    bpy.ops.object.modifier_apply(modifier="Decimate")

    final_triangles = get_triangle_count(obj)
    print(f"    Result: {final_triangles} triangles (ratio: {ratio:.3f})")
    total_decimated += 1

    return obj

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
    global total_exported, created_directories

    tile_level = get_tile_level_from_name(obj.name)
    clean_name = clean_object_name(obj.name)

    print(f"  Exporting {obj.name} -> {clean_name} (Tile Level: {tile_level}):")
    print(f"    Vertices: {len(obj.data.vertices)}")
    print(f"    Faces: {len(obj.data.polygons)}")
    print(f"    Triangles: {get_triangle_count(obj)}")
    print(f"    Materials: {len(obj.data.materials)}")

    tile_folder = os.path.join(output_dir, f"TileLevel_{tile_level}")
    if tile_folder not in created_directories:
        os.makedirs(tile_folder, exist_ok=True)
        created_directories.add(tile_folder)

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

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

def bisect_object_octree(obj, tile_level, ix, iy, iz):
    """
    Bisect an object into 8 octree chunks using optimized spatial partitioning
    (Phase 2 optimized version with UV preservation)
    """
    print(f"  Bisecting object {obj.name} into octree (optimized spatial partitioning)...")

    (xmin, xmax), (ymin, ymax), (zmin, zmax) = get_bounds(obj, True)
    print(f"    Bounds: X({xmin:.3f}, {xmax:.3f}), Y({ymin:.3f}, {ymax:.3f}), Z({zmin:.3f}, {zmax:.3f})")

    x_mid = (xmin + xmax) / 2
    y_mid = (ymin + ymax) / 2
    z_mid = (zmin + zmax) / 2

    bm_orig = bmesh.new()
    obj.data.update()
    bm_orig.from_mesh(obj.data)
    bm_orig.faces.ensure_lookup_table()
    bm_orig.verts.ensure_lookup_table()

    face_materials = []
    if len(obj.data.materials) > 0:
        for i, face in enumerate(bm_orig.faces):
            poly_index = i if i < len(obj.data.polygons) else 0
            mat_idx = obj.data.polygons[poly_index].material_index
            face_materials.append(mat_idx)
    else:
        face_materials = [0] * len(bm_orig.faces)

    octant_faces = {(dx, dy, dz): [] for dx in range(2) for dy in range(2) for dz in range(2)}

    for face_idx, face in enumerate(bm_orig.faces):
        centroid = face.calc_center_median()
        dx = 0 if centroid.x < x_mid else 1
        dy = 0 if centroid.y < y_mid else 1
        dz = 0 if centroid.z < z_mid else 1
        octant_faces[(dx, dy, dz)].append((face_idx, face_materials[face_idx]))

    chunks = []

    for dx in range(2):
        for dy in range(2):
            for dz in range(2):
                face_list = octant_faces[(dx, dy, dz)]

                if not face_list:
                    new_ix = ix * 2 + dx
                    new_iy = iy * 2 + dy
                    new_iz = iz * 2 + dz
                    chunk_name = f"{int(tile_level)}_{int(new_ix)}_{int(new_iy)}_{int(new_iz)}"
                    print(f"    Processing chunk {chunk_name} (dx:{dx}, dy:{dy}, dz:{dz})")
                    print(f"      Chunk {chunk_name} is empty - skipping")
                    continue

                new_ix = ix * 2 + dx
                new_iy = iy * 2 + dy
                new_iz = iz * 2 + dz
                chunk_name = f"{int(tile_level)}_{int(new_ix)}_{int(new_iy)}_{int(new_iz)}"
                print(f"    Processing chunk {chunk_name} (dx:{dx}, dy:{dy}, dz:{dz})")

                bm_chunk = bmesh.new()

                # UV layer preservation
                uv_layer_orig = bm_orig.loops.layers.uv.active
                if uv_layer_orig:
                    uv_layer_chunk = bm_chunk.loops.layers.uv.new(uv_layer_orig.name)

                vert_map = {}
                created_faces_materials = []

                for face_idx, mat_idx in face_list:
                    orig_face = bm_orig.faces[face_idx]

                    new_verts = []
                    for vert in orig_face.verts:
                        if vert.index not in vert_map:
                            new_vert = bm_chunk.verts.new(vert.co)
                            vert_map[vert.index] = new_vert
                        new_verts.append(vert_map[vert.index])

                    try:
                        new_face = bm_chunk.faces.new(new_verts)

                        # Copy UV coordinates
                        if uv_layer_orig and uv_layer_chunk:
                            for i, loop in enumerate(new_face.loops):
                                orig_loop = orig_face.loops[i]
                                loop[uv_layer_chunk].uv = orig_loop[uv_layer_orig].uv

                        created_faces_materials.append(mat_idx)

                    except ValueError:
                        pass

                bm_chunk.verts.ensure_lookup_table()
                bm_chunk.faces.ensure_lookup_table()

                if len(bm_chunk.faces) > 0 and len(bm_chunk.verts) > 0:
                    me = bpy.data.meshes.new(chunk_name + "_mesh")
                    bm_chunk.to_mesh(me)

                    for mat in obj.data.materials:
                        me.materials.append(mat)

                    for face_idx, mat_idx in enumerate(created_faces_materials):
                        if face_idx < len(me.polygons):
                            me.polygons[face_idx].material_index = mat_idx

                    chunk_obj = bpy.data.objects.new(chunk_name, me)
                    bpy.context.collection.objects.link(chunk_obj)

                    chunks.append(chunk_obj)
                    print(f"      Created chunk {chunk_name}: {len(bm_chunk.faces)} faces")
                else:
                    print(f"      Chunk {chunk_name} is empty - skipping")

                bm_chunk.free()

    bm_orig.free()
    print(f"    Created {len(chunks)} non-empty chunks")
    return chunks

def process_object_adaptive(obj, tile_level=0, ix=0, iy=0, iz=0, max_level=3):
    """Recursively process an object with adaptive tiling"""
    print(f"\n=== Processing object {obj.name} at tile level {tile_level} ===")

    triangle_count = get_triangle_count(obj)
    print(f"Triangle count: {triangle_count}")

    if triangle_count <= TRIANGLE_THRESHOLD:
        print(f"Object has ≤ {TRIANGLE_THRESHOLD} triangles - exporting as is")
        export_object_test(obj, OUTPUT_DIR)
        return

    if tile_level >= max_level:
        print(f"Maximum tile level ({max_level}) reached - decimating and exporting")
        decimate_object(obj, TRIANGLE_THRESHOLD)
        export_object_test(obj, OUTPUT_DIR)
        return

    print(f"Object exceeds {TRIANGLE_THRESHOLD} triangles - tiling...")

    decimated_name = f"{tile_level}_{ix}_{iy}_{iz}_decimated"
    decimated_obj = duplicate_object(obj, decimated_name)

    decimate_object(decimated_obj, TRIANGLE_THRESHOLD)
    export_object_test(decimated_obj, OUTPUT_DIR)

    chunks = bisect_object_octree(obj, tile_level + 1, ix, iy, iz)

    bpy.data.objects.remove(obj, do_unlink=True)

    for chunk in chunks:
        parts = chunk.name.split('_')
        if len(parts) >= 4:
            chunk_tile_level = int(parts[0])
            chunk_ix = int(parts[1])
            chunk_iy = int(parts[2])
            chunk_iz = int(parts[3])

            process_object_adaptive(chunk, chunk_tile_level, chunk_ix, chunk_iy, chunk_iz, max_level)

# ===========================================
# MAIN WORKER EXECUTION
# ===========================================

def run_worker():
    """Main worker function"""
    global total_exported, total_decimated

    # Clear scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    # Import the chunk OBJ
    print(f"Importing chunk: {CHUNK_OBJ_PATH}")
    bpy.ops.wm.obj_import(filepath=CHUNK_OBJ_PATH)

    imported_objects = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
    if not imported_objects:
        print(f"ERROR: No mesh found in {CHUNK_OBJ_PATH}")
        sys.exit(1)

    obj = imported_objects[0]
    print(f"Loaded object: {obj.name}")
    print(f"Vertices: {len(obj.data.vertices)}")
    print(f"Polygons: {len(obj.data.polygons)}")
    print(f"Triangles: {get_triangle_count(obj)}")

    # Apply transforms
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Process this chunk recursively
    process_object_adaptive(obj, TILE_LEVEL, IX, IY, IZ, MAX_TILE_LEVEL)

    print(f"\n{'='*60}")
    print(f"WORKER COMPLETE")
    print(f"{'='*60}")
    print(f"Total objects exported: {total_exported}")
    print(f"Total objects decimated: {total_decimated}")
    print(f"{'='*60}\n")

# Execute worker
if __name__ == "__main__":
    run_worker()

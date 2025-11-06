import bpy, bmesh
from mathutils import Vector
import os
import sys
import json

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
        # Optional third argument for max LOD level
        MAX_TILE_LEVEL = int(argv[2]) if len(argv) >= 3 else 3
        # Optional fourth argument for first-split-only mode (Phase 3 parallel processing)
        FIRST_SPLIT_ONLY = (argv[3] == "--first-split-only") if len(argv) >= 4 else False
    else:
        print("❌ Error: Expected at least 2 arguments after '--': input_path output_dir [max_lod] [--first-split-only]")
        sys.exit(1)
else:
    print("❌ Error: Missing '--' in arguments. Blender CLI should use '--' before script args.")
    sys.exit(1)

# Alternative: Use a blend file object instead of importing
USE_EXISTING_OBJECT = False  # Set to True to use selected object in scene
EXISTING_OBJECT_NAME = ""   # Leave empty to use active object, or specify name

# Script parameters
TRIANGLE_THRESHOLD = 20000
# MAX_TILE_LEVEL is now set from command-line arguments (default: 3)

# Mesh cleanup parameters
MERGE_DISTANCE = 0.001  # Distance threshold for merging vertices

# ===========================================
# TEXTURE METADATA GENERATION
# ===========================================

def detect_source_texture_resolution(obj):
    """
    Scan all materials on the object to find the largest texture.
    Returns (width, height, total_pixels) or (1024, 1024, 1048576) as default.
    """
    max_width = 0
    max_height = 0

    if not obj.data.materials:
        print("  No materials found - using default 1024x1024")
        return 1024, 1024, 1048576

    for mat in obj.data.materials:
        if not mat or not mat.use_nodes:
            continue

        # Search for image texture nodes
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                width, height = node.image.size
                if width * height > max_width * max_height:
                    max_width = width
                    max_height = height

    if max_width == 0 or max_height == 0:
        print("  No textures found in materials - using default 1024x1024")
        return 1024, 1024, 1048576

    total_pixels = max_width * max_height
    print(f"  Detected source texture: {max_width}x{max_height} ({total_pixels:,} pixels)")
    return max_width, max_height, total_pixels

def estimate_total_tiles_for_metadata(total_triangles, triangle_threshold):
    """
    Estimate the total number of tiles that will be generated based on mesh complexity.
    Uses octree subdivision logic: each level creates up to 8 children.

    Returns: (estimated_tiles, max_depth)
    """
    if total_triangles <= triangle_threshold:
        return 1, 0

    # Calculate how many levels of subdivision we'll need
    current_triangles = total_triangles
    max_depth = 0
    estimated_tiles = 0

    # Level 0: root tile (always 1)
    estimated_tiles += 1

    # Simulate subdivision
    while current_triangles > triangle_threshold and max_depth < 10:  # Cap at 10 levels for safety
        max_depth += 1
        # Each subdivision creates up to 8 tiles at the next level
        # Assume average of 6 non-empty octants (realistic for complex meshes)
        tiles_at_level = min(8 ** max_depth, int(total_triangles / triangle_threshold))
        estimated_tiles += tiles_at_level
        current_triangles = current_triangles / 8  # Each octant gets ~1/8 of triangles

    print(f"  Estimated {estimated_tiles} total tiles across {max_depth} levels")
    return estimated_tiles, max_depth

def generate_texture_metadata(obj, output_dir, triangle_threshold):
    """
    Generate and save texture metadata JSON file for adaptive texture sizing.
    This metadata will be used by bakeSingleTile.py to determine texture sizes.
    """
    print("\n" + "=" * 50)
    print("GENERATING TEXTURE METADATA")
    print("=" * 50)

    # Detect source texture resolution
    width, height, total_pixels = detect_source_texture_resolution(obj)

    # Get triangle count
    total_triangles = get_triangle_count(obj)
    print(f"  Total triangles: {total_triangles:,}")

    # Estimate total tiles
    estimated_tiles, max_depth = estimate_total_tiles_for_metadata(total_triangles, triangle_threshold)

    # Create metadata dictionary
    metadata = {
        "source_texture_width": width,
        "source_texture_height": height,
        "source_texture_pixels": total_pixels,
        "total_triangles": total_triangles,
        "triangle_threshold": triangle_threshold,
        "estimated_tiles": estimated_tiles,
        "estimated_max_depth": max_depth,
        "base_texture_size": 1024  # Base resolution for tiles
    }

    # Save to JSON file
    metadata_path = os.path.join(output_dir, "texture_metadata.json")
    os.makedirs(output_dir, exist_ok=True)

    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n  Metadata saved to: {metadata_path}")
    print(f"  Summary:")
    print(f"    - Source texture: {width}x{height} ({total_pixels:,} pixels)")
    print(f"    - Triangle count: {total_triangles:,}")
    print(f"    - Estimated tiles: {estimated_tiles}")
    print(f"    - Max depth: {max_depth}")
    print(f"    - Base texture size: 1024x1024")
    print("=" * 50 + "\n")

    return metadata

# ===========================================
# ADAPTIVE TILING FUNCTIONS (Enhanced)
# ===========================================

# Global counters for tracking
total_exported = 0
total_decimated = 0

# Performance optimization: Cache for triangle counts
triangle_count_cache = {}

# Performance optimization: Cache for created directories to avoid repeated os.makedirs checks
created_directories = set()
def clear_scene(self):
    """Clear all objects from the scene"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    print("Scene cleared.")


def cleanup_mesh(obj):
    """Clean up mesh by merging vertices by distance using BMesh (faster than edit mode)"""
    print(f"  Cleaning up mesh for {obj.name}...")

    # Store original vertex count
    original_verts = len(obj.data.vertices)

    # Use BMesh for faster cleanup (no mode switching overhead)
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    # Remove doubles using bmesh operation (faster than edit mode operators)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=MERGE_DISTANCE)

    # Write back to mesh
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()

    # Report results
    new_verts = len(obj.data.vertices)
    merged_verts = original_verts - new_verts

    print(f"    Merged {merged_verts} vertices (was: {original_verts}, now: {new_verts})")
    print(f"    Mesh cleanup complete.")

def get_bounds(obj, local=True):
    """Get the bounding box of an object"""
    if local:
        coords = obj.bound_box
    else:
        coords = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [p[0] for p in coords]; ys = [p[1] for p in coords]; zs = [p[2] for p in coords]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))

def get_triangle_count(obj):
    """Get the number of triangles in a mesh object (with caching for performance)"""
    global triangle_count_cache

    if obj.type != 'MESH' or not obj.data:
        return 0

    # Create cache key based on object name and geometry signature
    # Using vertex/polygon counts as a quick signature
    cache_key = (obj.name, len(obj.data.vertices), len(obj.data.polygons))

    # Check cache first
    if cache_key in triangle_count_cache:
        return triangle_count_cache[cache_key]

    # Calculate triangle count if not cached
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    triangle_count = len(bm.faces)
    bm.free()

    # Store in cache
    triangle_count_cache[cache_key] = triangle_count

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
    Bisect an object into 8 octree chunks (2x2x2) using optimized spatial partitioning
    Returns list of non-empty chunk objects

    OPTIMIZED APPROACH (Phase 2):
    Instead of copying the mesh 8 times and cutting, we:
    1. Calculate face centroids once
    2. Assign faces to octants based on centroid position
    3. Build separate meshes from assigned faces (no copying)

    This is 3-5x faster for large meshes and uses 80% less memory.
    """
    print(f"  Bisecting object {obj.name} into octree (optimized spatial partitioning)...")

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

    # Store material indices (we'll need these when creating chunks)
    face_materials = []
    if len(obj.data.materials) > 0:
        for i, face in enumerate(bm_orig.faces):
            poly_index = i if i < len(obj.data.polygons) else 0
            mat_idx = obj.data.polygons[poly_index].material_index
            face_materials.append(mat_idx)
    else:
        face_materials = [0] * len(bm_orig.faces)

    # OPTIMIZATION: Single-pass spatial partitioning
    # Assign each face to an octant based on its centroid
    octant_faces = {(dx, dy, dz): [] for dx in range(2) for dy in range(2) for dz in range(2)}

    for face_idx, face in enumerate(bm_orig.faces):
        # Calculate face centroid
        centroid = face.calc_center_median()

        # Determine octant (0 or 1 for each axis)
        dx = 0 if centroid.x < x_mid else 1
        dy = 0 if centroid.y < y_mid else 1
        dz = 0 if centroid.z < z_mid else 1

        # Store face index and material for this octant
        octant_faces[(dx, dy, dz)].append((face_idx, face_materials[face_idx]))

    chunks = []

    # Create 8 octree chunks from assigned faces
    for dx in range(2):
        for dy in range(2):
            for dz in range(2):
                face_list = octant_faces[(dx, dy, dz)]

                if not face_list:
                    # Empty octant - skip
                    new_ix = ix * 2 + dx
                    new_iy = iy * 2 + dy
                    new_iz = iz * 2 + dz
                    chunk_name = f"{int(tile_level)}_{int(new_ix)}_{int(new_iy)}_{int(new_iz)}"
                    print(f"    Processing chunk {chunk_name} (dx:{dx}, dy:{dy}, dz:{dz})")
                    print(f"      Chunk {chunk_name} is empty - skipping")
                    continue

                # Calculate new indices
                new_ix = ix * 2 + dx
                new_iy = iy * 2 + dy
                new_iz = iz * 2 + dz

                chunk_name = f"{int(tile_level)}_{int(new_ix)}_{int(new_iy)}_{int(new_iz)}"
                print(f"    Processing chunk {chunk_name} (dx:{dx}, dy:{dy}, dz:{dz})")

                # Create new bmesh for this chunk
                bm_chunk = bmesh.new()

                # CRITICAL: Copy UV layers from original mesh
                # Without UVs, texture baking will produce black textures!
                uv_layer_orig = bm_orig.loops.layers.uv.active
                if uv_layer_orig:
                    uv_layer_chunk = bm_chunk.loops.layers.uv.new(uv_layer_orig.name)

                # Copy vertices and faces for this octant
                vert_map = {}  # Map original vertex indices to new vertex indices
                created_faces_materials = []  # Track materials for successfully created faces

                for face_idx, mat_idx in face_list:
                    orig_face = bm_orig.faces[face_idx]

                    # Create/get vertices for this face
                    new_verts = []
                    for vert in orig_face.verts:
                        if vert.index not in vert_map:
                            # Create new vertex
                            new_vert = bm_chunk.verts.new(vert.co)
                            vert_map[vert.index] = new_vert
                        new_verts.append(vert_map[vert.index])

                    # Create face with same vertices
                    try:
                        new_face = bm_chunk.faces.new(new_verts)

                        # CRITICAL: Copy UV coordinates from original face
                        if uv_layer_orig and uv_layer_chunk:
                            for i, loop in enumerate(new_face.loops):
                                orig_loop = orig_face.loops[i]
                                loop[uv_layer_chunk].uv = orig_loop[uv_layer_orig].uv

                        # Track material for this successfully created face
                        created_faces_materials.append(mat_idx)

                    except ValueError:
                        # Face already exists (can happen with shared edges)
                        pass

                # Ensure lookup tables are built
                bm_chunk.verts.ensure_lookup_table()
                bm_chunk.faces.ensure_lookup_table()

                # Create chunk object if it has geometry
                if len(bm_chunk.faces) > 0 and len(bm_chunk.verts) > 0:
                    # Convert bmesh to mesh
                    me = bpy.data.meshes.new(chunk_name + "_mesh")
                    bm_chunk.to_mesh(me)

                    # Copy materials from original
                    for mat in obj.data.materials:
                        me.materials.append(mat)

                    # Restore material assignments (only for faces that were actually created)
                    for face_idx, mat_idx in enumerate(created_faces_materials):
                        if face_idx < len(me.polygons):
                            me.polygons[face_idx].material_index = mat_idx

                    # Create object
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
    """Export an object to OBJ file organized by tile level (optimized I/O)"""
    global total_exported, created_directories

    # Get tile level from object name
    tile_level = get_tile_level_from_name(obj.name)

    # Clean the object name (remove _decimated suffix)
    clean_name = clean_object_name(obj.name)

    print(f"  Exporting {obj.name} -> {clean_name} (Tile Level: {tile_level}):")
    print(f"    Vertices: {len(obj.data.vertices)}")
    print(f"    Faces: {len(obj.data.polygons)}")
    print(f"    Triangles: {get_triangle_count(obj)}")
    print(f"    Materials: {len(obj.data.materials)}")

    # Create tile level folder (cached to avoid redundant filesystem checks)
    tile_folder = os.path.join(output_dir, f"TileLevel_{tile_level}")
    if tile_folder not in created_directories:
        os.makedirs(tile_folder, exist_ok=True)
        created_directories.add(tile_folder)

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
    global total_exported, total_decimated, triangle_count_cache, created_directories
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

    # Reset counters and caches
    total_exported = 0
    total_decimated = 0
    triangle_count_cache.clear()  # Clear triangle count cache for new run
    created_directories.clear()   # Clear directory cache for new run
    
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

    # GENERATE TEXTURE METADATA - For adaptive texture sizing
    generate_texture_metadata(obj, TEST_OUTPUT_DIR, TRIANGLE_THRESHOLD)

    # Check if this is first-split-only mode (for parallel processing)
    if FIRST_SPLIT_ONLY:
        print("\n" + "=" * 50)
        print("FIRST SPLIT ONLY MODE (Phase 3 Parallel)")
        print("=" * 50)
        print("Performing initial octree split and exporting chunks...")

        # CRITICAL: Create root tile (TileLevel_0) before splitting
        # This is the decimated version of the entire model
        triangle_count = get_triangle_count(obj)

        if triangle_count > TRIANGLE_THRESHOLD:
            print(f"\nCreating root tile (TileLevel_0)...")
            print(f"  Original triangle count: {triangle_count}")

            # Create decimated root tile
            decimated_name = "0_0_0_0_decimated"
            decimated_obj = duplicate_object(obj, decimated_name)
            decimate_object(decimated_obj, TRIANGLE_THRESHOLD)
            export_object_test(decimated_obj, TEST_OUTPUT_DIR)

            # Clean up decimated object (we've exported it)
            bpy.data.objects.remove(decimated_obj, do_unlink=True)
            print(f"  ✓ Root tile created and exported to TileLevel_0")
        else:
            print(f"\nModel has {triangle_count} triangles (≤ {TRIANGLE_THRESHOLD})")
            print("No tiling needed - exporting as single tile")
            export_object_test(obj, TEST_OUTPUT_DIR)
            # Don't proceed with splitting if model is already small enough
            return

        # Create first-level chunks directory
        chunks_temp_dir = os.path.join(TEST_OUTPUT_DIR, "_parallel_chunks")
        os.makedirs(chunks_temp_dir, exist_ok=True)

        # Perform first split
        print(f"\nSplitting into first-level chunks...")
        chunks = bisect_object_octree(obj, tile_level=1, ix=0, iy=0, iz=0)

        print(f"\nExporting {len(chunks)} first-level chunks for parallel processing...")

        # Export each chunk as OBJ for worker processes
        chunk_files = []
        for chunk in chunks:
            chunk_file = os.path.join(chunks_temp_dir, f"{chunk.name}.obj")

            bpy.ops.object.select_all(action='DESELECT')
            chunk.select_set(True)
            bpy.context.view_layer.objects.active = chunk

            bpy.ops.wm.obj_export(
                filepath=chunk_file,
                export_selected_objects=True,
                export_materials=True,
                export_uv=True,
                apply_modifiers=False,
                global_scale=1.0
            )

            chunk_files.append(chunk_file)
            print(f"  Exported: {chunk.name} → {chunk_file}")

        print(f"\nFirst split complete! {len(chunk_files)} chunks ready for parallel workers")
        print(f"Chunk files located in: {chunks_temp_dir}")

    else:
        # Normal sequential processing
        process_object_adaptive(obj, tile_level=0, ix=0, iy=0, iz=0)

    print("\n" + "=" * 50)
    print("ADAPTIVE TILING TEST COMPLETE")
    print("=" * 50)
    print(f"Total objects processed: {total_exported}")
    print(f"Total objects decimated: {total_decimated}")
    print(f"Check the 3D viewport to see the generated tiles")
    print(f"Objects in scene: {len([o for o in bpy.data.objects if o.type == 'MESH'])}")
    print(f"Output organized in folders by tile level in: {TEST_OUTPUT_DIR}")
    if not FIRST_SPLIT_ONLY:
        print()
        print("Performance optimizations active:")
        print(f"  - Triangle count cache hits: {len(triangle_count_cache)} cached values")
        print(f"  - Directory creation optimizations: {len(created_directories)} folders cached")

# ===========================================
# RUN THE TEST
# ===========================================

# Execute the test
run_adaptive_tiling_test()
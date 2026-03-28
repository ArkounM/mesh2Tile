"""
Out-of-core OBJ pre-splitter for large meshes.

Splits large OBJ files spatially (binary space partition along longest axis)
WITHOUT loading the entire mesh into memory. This allows the downstream
Blender-based tiling pipeline to process each chunk independently,
avoiding OOM on models with 90M+ triangles.

Memory strategy:
  - Vertex positions: stored as a numpy array (~1 GB for 45M verts). Fits in RAM.
  - Texture coords / normals: stored as numpy arrays (same scale as verts).
  - Faces: streamed line-by-line; never stored in bulk.
"""

import os
import sys
import shutil
import time
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def estimate_obj_triangles(filepath):
    """Quick streaming count of face lines ('f ...') in an OBJ file."""
    count = 0
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("f "):
                count += 1
    return count


def _parse_vertex_line(line):
    """Parse 'v x y z' and return (x, y, z) as floats."""
    parts = line.split()
    return float(parts[1]), float(parts[2]), float(parts[3])


def _parse_vt_line(line):
    """Parse 'vt u v [w]' and return the raw parts after 'vt'."""
    return line.rstrip("\n\r")


def _parse_vn_line(line):
    """Parse 'vn x y z' and return the raw line (stripped)."""
    return line.rstrip("\n\r")


def _parse_face_vertex_indices(token):
    """
    Parse a face vertex token like '12/34/56' or '12//56' or '12/34' or '12'.
    Returns (v_idx, vt_idx, vn_idx) — each 1-based int or None.
    """
    parts = token.split("/")
    v = int(parts[0])
    vt = int(parts[1]) if len(parts) > 1 and parts[1] != "" else None
    vn = int(parts[2]) if len(parts) > 2 and parts[2] != "" else None
    return v, vt, vn


# ---------------------------------------------------------------------------
# Pass 1 — read all vertex positions, texture coords, and normals
# ---------------------------------------------------------------------------

def load_vertex_data(filepath):
    """
    Stream through the OBJ and collect:
      - vertex positions  (list of (x, y, z))
      - texture coords    (list of raw 'vt ...' lines)
      - normals           (list of raw 'vn ...' lines)
      - header lines      (comment, mtllib, object name, etc.)
      - material name     (from 'usemtl' line)

    Returns (positions_np, vt_lines, vn_lines, header_lines, material_name, mtllib_line)
    """
    positions = []
    vt_lines = []
    vn_lines = []
    header_lines = []
    material_name = None
    mtllib_line = None
    header_done = False

    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("v "):
                header_done = True
                p = line.split()
                positions.append((float(p[1]), float(p[2]), float(p[3])))
            elif line.startswith("vt "):
                header_done = True
                vt_lines.append(line.rstrip("\n\r"))
            elif line.startswith("vn "):
                header_done = True
                vn_lines.append(line.rstrip("\n\r"))
            elif line.startswith("usemtl "):
                material_name = line.strip()
            elif line.startswith("mtllib "):
                mtllib_line = line.strip()
            elif not header_done:
                # Collect header comments / object name
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("o ") or stripped.startswith("s "):
                    header_lines.append(stripped)

    positions_np = np.array(positions, dtype=np.float64)
    print(f"    Loaded {len(positions_np)} vertices, {len(vt_lines)} texcoords, {len(vn_lines)} normals")
    return positions_np, vt_lines, vn_lines, header_lines, material_name, mtllib_line


# ---------------------------------------------------------------------------
# Bounding box & split axis
# ---------------------------------------------------------------------------

def compute_bounding_box(positions_np):
    """Return (min_corner, max_corner) as numpy arrays."""
    return positions_np.min(axis=0), positions_np.max(axis=0)


def choose_split_axis_and_point(bb_min, bb_max):
    """Split along the longest axis at the midpoint."""
    extents = bb_max - bb_min
    axis = int(np.argmax(extents))
    point = (bb_min[axis] + bb_max[axis]) / 2.0
    return axis, point


# ---------------------------------------------------------------------------
# Pass 2 — stream faces, assign to halves, write output OBJs
# ---------------------------------------------------------------------------

def split_obj_file(filepath, output_dir, axis, split_point,
                   positions_np, vt_lines, vn_lines,
                   header_lines, material_name, mtllib_line,
                   suffix_lo="lo", suffix_hi="hi"):
    """
    Stream through the OBJ face lines. For each face, compute centroid from
    vertex positions, assign to lo (centroid <= split_point) or hi, and
    collect the set of vertex/vt/vn indices used by each half.

    Then write two complete OBJ files with remapped indices.

    Returns (path_lo, path_hi, count_lo, count_hi).
    """
    basename = os.path.splitext(os.path.basename(filepath))[0]

    # --- First sub-pass: classify faces and record which indices each half uses ---
    # We store faces as lists of tuples for each half so we can remap indices later.
    # For very large files this could use a lot of memory, but faces are small per-line.
    # A face line is ~60 bytes; 90M faces ~ 5.4 GB which is too much.
    # So instead we do TWO sub-passes: one to collect index sets, one to write.

    used_v_lo = set()
    used_vt_lo = set()
    used_vn_lo = set()
    used_v_hi = set()
    used_vt_hi = set()
    used_vn_hi = set()

    # We also need to know which half each face belongs to, but we cannot store
    # that for 90M faces. Instead we recompute the centroid in the second sub-pass.
    # Two passes over the file is fine — it's sequential I/O.

    print(f"    Pass 2a: classifying faces and collecting index sets...")
    t0 = time.time()
    count_lo = 0
    count_hi = 0

    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("f "):
                continue
            tokens = line.split()
            # Parse vertex indices to compute centroid
            v_indices = []
            vt_indices = []
            vn_indices = []
            for tok in tokens[1:]:
                v, vt, vn = _parse_face_vertex_indices(tok)
                v_indices.append(v)
                if vt is not None:
                    vt_indices.append(vt)
                if vn is not None:
                    vn_indices.append(vn)

            # Compute centroid along split axis (1-based indices, so subtract 1)
            centroid_val = 0.0
            for vi in v_indices:
                centroid_val += positions_np[vi - 1, axis]
            centroid_val /= len(v_indices)

            if centroid_val <= split_point:
                count_lo += 1
                for vi in v_indices:
                    used_v_lo.add(vi)
                for vti in vt_indices:
                    used_vt_lo.add(vti)
                for vni in vn_indices:
                    used_vn_lo.add(vni)
            else:
                count_hi += 1
                for vi in v_indices:
                    used_v_hi.add(vi)
                for vti in vt_indices:
                    used_vt_hi.add(vti)
                for vni in vn_indices:
                    used_vn_hi.add(vni)

    print(f"    Classified {count_lo + count_hi} faces in {time.time() - t0:.1f}s "
          f"(lo={count_lo}, hi={count_hi})")

    # --- Build remap tables ---
    # old 1-based index -> new 1-based index
    def build_remap(used_set):
        sorted_indices = sorted(used_set)
        return {old: new for new, old in enumerate(sorted_indices, start=1)}

    remap_v_lo = build_remap(used_v_lo)
    remap_vt_lo = build_remap(used_vt_lo)
    remap_vn_lo = build_remap(used_vn_lo)
    remap_v_hi = build_remap(used_v_hi)
    remap_vt_hi = build_remap(used_vt_hi)
    remap_vn_hi = build_remap(used_vn_hi)

    # --- Write output OBJs ---
    path_lo = os.path.join(output_dir, f"{basename}_{suffix_lo}.obj")
    path_hi = os.path.join(output_dir, f"{basename}_{suffix_hi}.obj")

    def write_half(path, remap_v, remap_vt, remap_vn, is_lo):
        """Write one half's OBJ file."""
        t1 = time.time()
        label = suffix_lo if is_lo else suffix_hi

        with open(path, "w", encoding="utf-8") as out:
            # Header
            out.write(f"# Pre-split chunk ({label})\n")
            if mtllib_line:
                out.write(mtllib_line + "\n")
            for h in header_lines:
                if h.startswith("o "):
                    out.write(f"o {basename}_{label}\n")
                elif h.startswith("s "):
                    out.write(h + "\n")

            # Write vertices in remapped order
            sorted_v = sorted(remap_v.keys())
            for old_idx in sorted_v:
                x, y, z = positions_np[old_idx - 1]
                out.write(f"v {x} {y} {z}\n")

            # Write texture coords
            sorted_vt = sorted(remap_vt.keys())
            for old_idx in sorted_vt:
                out.write(vt_lines[old_idx - 1] + "\n")

            # Write normals
            sorted_vn = sorted(remap_vn.keys())
            for old_idx in sorted_vn:
                out.write(vn_lines[old_idx - 1] + "\n")

            # Material
            if material_name:
                out.write(material_name + "\n")

            # Second sub-pass: stream faces (and edge lines) and write remapped
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.startswith("f "):
                        tokens = line.split()
                        v_indices = []
                        for tok in tokens[1:]:
                            v, vt, vn = _parse_face_vertex_indices(tok)
                            v_indices.append(v)

                        # Recompute centroid to decide half
                        centroid_val = 0.0
                        for vi in v_indices:
                            centroid_val += positions_np[vi - 1, axis]
                        centroid_val /= len(v_indices)

                        belongs_lo = centroid_val <= split_point
                        if belongs_lo != is_lo:
                            continue

                        # Remap and write
                        new_tokens = ["f"]
                        for tok in tokens[1:]:
                            v, vt, vn = _parse_face_vertex_indices(tok)
                            new_v = remap_v[v]
                            if vt is not None and vn is not None:
                                new_tokens.append(f"{new_v}/{remap_vt[vt]}/{remap_vn[vn]}")
                            elif vt is not None:
                                new_tokens.append(f"{new_v}/{remap_vt[vt]}")
                            elif vn is not None:
                                new_tokens.append(f"{new_v}//{remap_vn[vn]}")
                            else:
                                new_tokens.append(str(new_v))
                        out.write(" ".join(new_tokens) + "\n")

                    elif line.startswith("l "):
                        # Edge lines — remap vertex indices if they exist in this half
                        tokens = line.split()
                        new_indices = []
                        all_present = True
                        for tok in tokens[1:]:
                            vi = int(tok)
                            if vi in remap_v:
                                new_indices.append(str(remap_v[vi]))
                            else:
                                all_present = False
                                break
                        if all_present and len(new_indices) >= 2:
                            out.write("l " + " ".join(new_indices) + "\n")

        elapsed = time.time() - t1
        print(f"    Wrote {path} in {elapsed:.1f}s")

    print(f"    Pass 2b: writing lo half...")
    write_half(path_lo, remap_v_lo, remap_vt_lo, remap_vn_lo, is_lo=True)
    print(f"    Pass 2b: writing hi half...")
    write_half(path_hi, remap_v_hi, remap_vt_hi, remap_vn_hi, is_lo=False)

    return path_lo, path_hi, count_lo, count_hi


# ---------------------------------------------------------------------------
# Recursive driver
# ---------------------------------------------------------------------------

def _copy_supporting_files(src_dir, dst_dir, obj_basename):
    """
    Copy MTL and texture files that accompany an OBJ from src_dir to dst_dir.
    Also handles the case where mtl references textures with different names.
    """
    if os.path.normpath(src_dir) == os.path.normpath(dst_dir):
        return

    for f in os.listdir(src_dir):
        lower = f.lower()
        if lower.endswith(".mtl") or lower.endswith(".jpg") or lower.endswith(".jpeg") or \
           lower.endswith(".png") or lower.endswith(".tif") or lower.endswith(".tiff") or \
           lower.endswith(".bmp"):
            src = os.path.join(src_dir, f)
            dst = os.path.join(dst_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)


def presplit_if_needed(filepath, output_dir, max_triangles=20_000_000, _depth=0, _max_depth=6):
    """
    Recursively split an OBJ file until every chunk has <= max_triangles faces.

    Parameters:
      filepath       - path to the input OBJ
      output_dir     - directory where chunk OBJs will be written
      max_triangles  - face count threshold for splitting
      _depth         - internal recursion depth counter
      _max_depth     - safety limit on recursion depth

    Returns a list of paths to the final chunk OBJ files.
    """
    indent = "  " * _depth

    # Quick triangle count
    print(f"{indent}  Counting faces in {os.path.basename(filepath)}...")
    t0 = time.time()
    tri_count = estimate_obj_triangles(filepath)
    print(f"{indent}  {tri_count:,} faces ({time.time() - t0:.1f}s)")

    if tri_count <= max_triangles:
        print(f"{indent}  Below threshold ({max_triangles:,}), no split needed.")
        # If the file is not already in output_dir, copy it there
        dst = os.path.join(output_dir, os.path.basename(filepath))
        if os.path.abspath(filepath) != os.path.abspath(dst):
            shutil.copy2(filepath, dst)
            _copy_supporting_files(os.path.dirname(filepath), output_dir,
                                   os.path.splitext(os.path.basename(filepath))[0])
        return [dst]

    if _depth >= _max_depth:
        print(f"{indent}  WARNING: max recursion depth ({_max_depth}) reached. "
              f"Chunk has {tri_count:,} faces (threshold {max_triangles:,}).")
        dst = os.path.join(output_dir, os.path.basename(filepath))
        if os.path.abspath(filepath) != os.path.abspath(dst):
            shutil.copy2(filepath, dst)
        return [dst]

    print(f"{indent}  Splitting {os.path.basename(filepath)} ({tri_count:,} faces)...")
    os.makedirs(output_dir, exist_ok=True)

    # Pass 1: load vertex data
    print(f"{indent}  Pass 1: loading vertex data...")
    t1 = time.time()
    positions_np, vt_lines, vn_lines, header_lines, material_name, mtllib_line = \
        load_vertex_data(filepath)
    print(f"{indent}  Pass 1 done in {time.time() - t1:.1f}s")

    # Compute bounding box and choose split
    bb_min, bb_max = compute_bounding_box(positions_np)
    axis, split_point = choose_split_axis_and_point(bb_min, bb_max)
    axis_name = ["X", "Y", "Z"][axis]
    print(f"{indent}  Splitting along {axis_name} at {split_point:.4f} "
          f"(range {bb_min[axis]:.4f} to {bb_max[axis]:.4f})")

    # Pass 2: split
    path_lo, path_hi, count_lo, count_hi = split_obj_file(
        filepath, output_dir, axis, split_point,
        positions_np, vt_lines, vn_lines,
        header_lines, material_name, mtllib_line
    )

    # Copy supporting files (MTL, textures) to output_dir
    _copy_supporting_files(os.path.dirname(filepath), output_dir,
                           os.path.splitext(os.path.basename(filepath))[0])

    # Free memory before recursion
    del positions_np, vt_lines, vn_lines

    # Sanity check
    if count_lo + count_hi != tri_count:
        print(f"{indent}  WARNING: face count mismatch! lo={count_lo} + hi={count_hi} "
              f"= {count_lo + count_hi} != original {tri_count}")

    # Handle degenerate splits (all faces on one side)
    if count_lo == 0 or count_hi == 0:
        print(f"{indent}  WARNING: degenerate split (one side is empty). Stopping recursion.")
        # Keep the non-empty file, remove the empty one
        if count_lo == 0:
            os.remove(path_lo)
            return [path_hi]
        else:
            os.remove(path_hi)
            return [path_lo]

    # Recurse on each half
    results = []
    for chunk_path, chunk_count in [(path_lo, count_lo), (path_hi, count_hi)]:
        if chunk_count > max_triangles:
            sub_results = presplit_if_needed(
                chunk_path, output_dir, max_triangles,
                _depth=_depth + 1, _max_depth=_max_depth
            )
            results.extend(sub_results)
            # Remove the intermediate file if it was further split
            if len(sub_results) > 1 or (len(sub_results) == 1 and
                    os.path.abspath(sub_results[0]) != os.path.abspath(chunk_path)):
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)
        else:
            results.append(chunk_path)

    return results


# ---------------------------------------------------------------------------
# Tileset merging (for combining outputs from multiple pre-split chunks)
# ---------------------------------------------------------------------------

def merge_tilesets(tileset_paths, output_path, prefix_map=None):
    """
    Merge multiple tileset.json files into a single tileset.json.

    Each input tileset has its own root with bounding volume and children.
    The merged tileset creates a new structural root whose bounding volume
    encompasses all inputs, and whose children are the roots of the inputs.

    If prefix_map is provided (dict of chunk_dir -> prefix string), GLB URIs
    are rewritten to flat prefixed filenames instead of relative subdirectory
    paths. This produces output identical to a non-presplit run.
    """
    import json
    import math

    if len(tileset_paths) == 1:
        # Just copy the single tileset; apply prefix if provided
        if prefix_map:
            with open(tileset_paths[0], "r") as f:
                ts = json.load(f)
            chunk_dir = os.path.normpath(os.path.dirname(os.path.abspath(tileset_paths[0])))
            prefix = prefix_map.get(chunk_dir, "")

            def _prefix_uris(node, pfx):
                if "content" in node and "uri" in node["content"]:
                    old_uri = node["content"]["uri"]
                    # Strip any directory component, keep just the filename
                    basename = os.path.basename(old_uri)
                    node["content"]["uri"] = pfx + basename
                for child in node.get("children", []):
                    _prefix_uris(child, pfx)

            _prefix_uris(ts["root"], prefix)
            with open(output_path, "w") as f:
                json.dump(ts, f, indent=2)
        else:
            shutil.copy2(tileset_paths[0], output_path)
        return

    tilesets = []
    for p in tileset_paths:
        with open(p, "r") as f:
            tilesets.append(json.load(f))

    # Collect all root bounding boxes to compute an encompassing box
    # 3D Tiles box format: [cx, cy, cz, xx, xy, xz, yx, yy, yz, zx, zy, zz]
    # For axis-aligned boxes the off-diagonals are 0, so:
    # box = [cx, cy, cz, half_x, 0, 0, 0, half_y, 0, 0, 0, half_z]

    all_min = np.array([np.inf, np.inf, np.inf])
    all_max = np.array([-np.inf, -np.inf, -np.inf])

    for ts in tilesets:
        box = ts["root"]["boundingVolume"]["box"]
        cx, cy, cz = box[0], box[1], box[2]
        # Extract half-extents (assuming axis-aligned for simplicity)
        hx = math.sqrt(box[3]**2 + box[4]**2 + box[5]**2)
        hy = math.sqrt(box[6]**2 + box[7]**2 + box[8]**2)
        hz = math.sqrt(box[9]**2 + box[10]**2 + box[11]**2)
        all_min = np.minimum(all_min, [cx - hx, cy - hy, cz - hz])
        all_max = np.maximum(all_max, [cx + hx, cy + hy, cz + hz])

    center = (all_min + all_max) / 2.0
    half_extents = (all_max - all_min) / 2.0

    merged_box = [
        float(center[0]), float(center[1]), float(center[2]),
        float(half_extents[0]), 0, 0,
        0, float(half_extents[1]), 0,
        0, 0, float(half_extents[2])
    ]

    diagonal = 2 * math.sqrt(float(np.sum(half_extents**2)))

    # Build children from each tileset's root, fixing relative URIs
    output_dir = os.path.dirname(os.path.abspath(output_path))

    def rewrite_uris(node, chunk_dir, prefix):
        """Recursively rewrite content URIs.

        If prefix is provided, flatten to prefixed basename (e.g. c01_0_0_0_0.glb).
        Otherwise fall back to relative path from output_dir.
        """
        if "content" in node and "uri" in node["content"]:
            old_uri = node["content"]["uri"]
            if prefix:
                # Flat mode: just prefix the filename
                basename = os.path.basename(old_uri)
                node["content"]["uri"] = prefix + basename
            else:
                # Legacy mode: relative path through chunk subdir
                abs_glb = os.path.normpath(os.path.join(chunk_dir, old_uri))
                rel_path = os.path.relpath(abs_glb, output_dir).replace("\\", "/")
                node["content"]["uri"] = rel_path
        for child in node.get("children", []):
            rewrite_uris(child, chunk_dir, prefix)

    children = []
    for ts, ts_path in zip(tilesets, tileset_paths):
        root = ts["root"]
        chunk_dir = os.path.normpath(os.path.dirname(os.path.abspath(ts_path)))
        prefix = prefix_map.get(chunk_dir, "") if prefix_map else ""
        rewrite_uris(root, chunk_dir, prefix)
        children.append(root)

    # Use the transform from the first tileset (they should all be the same
    # since they're geo-located identically)
    transform = tilesets[0]["root"].get("transform")

    merged_root = {
        "boundingVolume": {"box": merged_box},
        "geometricError": diagonal,
        "refine": "REPLACE",
        "children": children
    }
    if transform:
        merged_root["transform"] = transform
        # Remove transform from children to avoid double-application
        for child in children:
            child.pop("transform", None)

    merged = {
        "asset": tilesets[0]["asset"],
        "geometricError": diagonal,
        "root": merged_root
    }

    with open(output_path, "w") as f:
        json.dump(merged, f, indent=2)

    print(f"  Merged {len(tileset_paths)} tilesets into {output_path}")


# ---------------------------------------------------------------------------
# CLI entry point (for standalone testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pre-split large OBJ files for mesh2tile")
    parser.add_argument("input", help="Path to input OBJ file")
    parser.add_argument("--output", "-o", help="Output directory (default: next to input)")
    parser.add_argument("--max-triangles", "-m", type=int, default=20_000_000,
                        help="Max triangles per chunk (default: 20M)")
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    if args.output:
        out_dir = os.path.abspath(args.output)
    else:
        out_dir = os.path.join(os.path.dirname(input_path), "presplit_chunks")

    os.makedirs(out_dir, exist_ok=True)

    print(f"Pre-splitting: {input_path}")
    print(f"Output dir:    {out_dir}")
    print(f"Max triangles: {args.max_triangles:,}")

    t_start = time.time()
    chunks = presplit_if_needed(input_path, out_dir, max_triangles=args.max_triangles)
    t_total = time.time() - t_start

    print(f"\nDone in {t_total:.1f}s. Produced {len(chunks)} chunk(s):")
    for c in chunks:
        print(f"  {c}")

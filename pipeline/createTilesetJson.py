import json
import argparse
import os
import re
from collections import defaultdict
import math

def parse_tile_id(uri):
    """Supports both dash and underscore naming: 2-1-1-1.glb or 2_1_1_1.glb"""
    match = re.match(r"(\d+)[-_](\d+)[-_](\d+)[-_](\d+)\.glb", uri)
    return tuple(map(int, match.groups())) if match else None

def group_tiles_by_level(children):
    levels = defaultdict(dict)
    for tile in children:
        info = parse_tile_id(tile["content"]["uri"])
        if info:
            levels[info[0]][(info[1], info[2], info[3])] = {
                "info": info,
                "tile": tile
            }
    return levels

def calculate_bounding_box_diagonal(box):
    hx = math.sqrt(box[3]**2 + box[4]**2 + box[5]**2)
    hy = math.sqrt(box[6]**2 + box[7]**2 + box[8]**2)
    hz = math.sqrt(box[9]**2 + box[10]**2 + box[11]**2)
    return 2 * math.sqrt(hx**2 + hy**2 + hz**2)

def calculate_geometric_error_from_box(bounding_box):
    """Calculate geometric error from a tile's bounding box using spatial extent.
    Uses max_half_extent / 8.0 (Entwine 2.1 formula), proportional to actual tile
    size so LOD transitions adapt to the dataset's spatial scale."""
    hx = math.sqrt(bounding_box[3]**2 + bounding_box[4]**2 + bounding_box[5]**2)
    hy = math.sqrt(bounding_box[6]**2 + bounding_box[7]**2 + bounding_box[8]**2)
    hz = math.sqrt(bounding_box[9]**2 + bounding_box[10]**2 + bounding_box[11]**2)
    max_half_extent = max(hx, hy, hz)
    return max_half_extent / 8.0


# NOTE: get_geometric_error() with hardcoded values was removed.
# All geometric errors are now calculated from tile bounding volumes
# using calculate_geometric_error_from_box().

def build_hierarchy(current_level, parent_coords, tiles_by_level):
    next_level = current_level + 1
    children = []
    for coords, data in tiles_by_level.get(next_level, {}).items():
        cx, cy, cz = coords
        px, py, pz = parent_coords
        if cx // 2 == px and cy // 2 == py and cz // 2 == pz:
            child = data["tile"].copy()
            child["geometricError"] = calculate_geometric_error_from_box(
                child["boundingVolume"]["box"]
            )
            child["children"] = build_hierarchy(next_level, coords, tiles_by_level)
            children.append(child)
    return children

def restructure_tileset(input_path, output_path):
    with open(input_path, "r") as f:
        flat_tileset = json.load(f)

    children = flat_tileset["root"].get("children", [])
    tiles_by_level = group_tiles_by_level(children)

    # Handle single-tile case (chunk too small to subdivide)
    if not tiles_by_level or 0 not in tiles_by_level or len(tiles_by_level[0]) == 0:
        # No parseable tile levels — this is a single-tile or non-standard tileset.
        # If there's exactly one child, use it as the root content tile.
        if len(children) == 1:
            child = children[0]
            box = child["boundingVolume"]["box"]
            geo_error = calculate_geometric_error_from_box(box) * 16.0
            root_tile = {
                "boundingVolume": child["boundingVolume"],
                "geometricError": geo_error,
                "refine": "REPLACE",
                "content": child.get("content"),
            }
            if "transform" in flat_tileset["root"]:
                root_tile["transform"] = flat_tileset["root"]["transform"]
            final_tileset = {
                "asset": flat_tileset["asset"],
                "geometricError": geo_error,
                "root": root_tile
            }
            with open(output_path, "w") as f:
                json.dump(final_tileset, f, indent=2)
            print(f"Restructured tileset (single tile) written to: {output_path}")
            return
        else:
            # Multiple children but none parseable — just write as-is
            with open(output_path, "w") as f:
                json.dump(flat_tileset, f, indent=2)
            print(f"Tileset written as-is (no parseable levels) to: {output_path}")
            return

    # Root tile setup
    root_info, root_tile_data = list(tiles_by_level[0].values())[0]["info"], list(tiles_by_level[0].values())[0]["tile"]
    root_box = root_tile_data["boundingVolume"]["box"]

    # Spatial-based geometric error (matching pointcloud2Tiles approach)
    lod0_geometric_error = calculate_geometric_error_from_box(root_box)
    ROOT_ERROR_MULTIPLIER = 16.0  # Inflates root error for distant visibility
    root_geometric_error = lod0_geometric_error * ROOT_ERROR_MULTIPLIER

    # Create a new LOD0 tile from root's original content
    lod0_tile = {
        "boundingVolume": root_tile_data["boundingVolume"],
        "geometricError": lod0_geometric_error,
        "content": {"uri": root_tile_data["content"]["uri"]},
        "children": build_hierarchy(0, root_info[1:], tiles_by_level)
    }

    # Root node becomes structural only (no content)
    root_tile = {
        "boundingVolume": root_tile_data["boundingVolume"],
        "geometricError": root_geometric_error,
        "refine": "REPLACE",
        "children": [lod0_tile]
    }

    if "transform" in flat_tileset["root"]:
        root_tile["transform"] = flat_tileset["root"]["transform"]

    final_tileset = {
        "asset": flat_tileset["asset"],
        "geometricError": root_geometric_error,
        "root": root_tile
    }

    with open(output_path, "w") as f:
        json.dump(final_tileset, f, indent=2)

    print(f"Restructured tileset written to: {output_path}")




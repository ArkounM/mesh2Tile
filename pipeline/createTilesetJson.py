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

def get_geometric_error(level):
    if level == 0:
        return None  # root calculated separately
    elif level == 1:
        return 0.1
    elif level == 2:
        return 0.05
    elif level == 3:
        return 0.005
    else:
        return 0.005 / (2 ** (level - 3))

def build_hierarchy(current_level, parent_coords, tiles_by_level):
    next_level = current_level + 1
    children = []
    for coords, data in tiles_by_level.get(next_level, {}).items():
        cx, cy, cz = coords
        px, py, pz = parent_coords
        if cx // 2 == px and cy // 2 == py and cz // 2 == pz:
            child = data["tile"].copy()
            level = data["info"][0]
            child["geometricError"] = get_geometric_error(level)
            child["children"] = build_hierarchy(level, coords, tiles_by_level)
            children.append(child)
    return children

def restructure_tileset(input_path, output_path):
    with open(input_path, "r") as f:
        flat_tileset = json.load(f)

    tiles_by_level = group_tiles_by_level(flat_tileset["root"]["children"])

    # Root tile setup
    root_info, root_tile_data = list(tiles_by_level[0].values())[0]["info"], list(tiles_by_level[0].values())[0]["tile"]
    root_box = root_tile_data["boundingVolume"]["box"]
    root_geometric_error = calculate_bounding_box_diagonal(root_box)

    # Create a new LOD0 tile from root's original content
    lod0_tile = {
        "boundingVolume": root_tile_data["boundingVolume"],
        "geometricError": 1.0,  # Fixed LOD0 error
        "content": {"uri": root_tile_data["content"]["uri"]},
        "children": build_hierarchy(0, root_info[1:], tiles_by_level)
    }

    # Root node becomes structural only (no content)
    root_tile = {
        "boundingVolume": root_tile_data["boundingVolume"],
        "geometricError": root_geometric_error,
        "refine": "REPLACE",  # REPLACE is more appropriate for this
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




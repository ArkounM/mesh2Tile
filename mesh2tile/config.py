import json
import os
import copy
import multiprocessing


DEFAULTS = {
    # Blender
    "blender_path": None,              # None = auto-detect

    # Tiling
    "triangle_threshold": 20000,
    "max_tile_level": 3,
    "merge_distance": 0.001,

    # Texturing
    "texture_max_size": 1024,
    "texture_min_size": 32,
    "bake_samples": 128,
    "bake_tile_size": 512,

    # Pipeline
    "max_bake_workers": None,          # None = auto (CPU/2, max 8)
    "max_conversion_workers": None,    # None = auto
    "max_tiling_workers": 4,
    "presplit_threshold": 20000000,

    # Geolocation
    "longitude": "0.0",
    "latitude": "0.0",
    "height": "0.0",

    # Dependencies
    "tiles_tools_version": "0.5.3",
}


def get_script_path(script_name):
    """Resolve a BlenderScript path relative to the package directory."""
    return os.path.join(os.path.dirname(__file__), "BlenderScripts", script_name)


def load_config(cli_args):
    """
    Build resolved config from defaults, optional JSON config file, and CLI args.

    Precedence (lowest to highest):
    1. DEFAULTS
    2. JSON config file (--config)
    3. CLI arguments (non-None values only)
    """
    config = copy.deepcopy(DEFAULTS)

    # Layer 2: config file
    config_path = getattr(cli_args, "config", None)
    if config_path:
        with open(config_path) as f:
            file_config = json.load(f)
        for key, value in file_config.items():
            if key in config and value is not None:
                config[key] = value

    # Layer 3: CLI args override (only non-None values)
    cli_mapping = {
        "blender_path": "blender_path",
        "triangle_threshold": "triangle_threshold",
        "bake_samples": "bake_samples",
        "texture_max_size": "texture_max_size",
        "lods": "max_tile_level",
        "max_bake_workers": "max_bake_workers",
        "max_conversion_workers": "max_conversion_workers",
        "max_tiling_workers": "max_tiling_workers",
        "presplit_threshold": "presplit_threshold",
        "longitude": "longitude",
        "latitude": "latitude",
        "height": "height",
    }
    for cli_attr, config_key in cli_mapping.items():
        value = getattr(cli_args, cli_attr, None)
        if value is not None:
            config[config_key] = value

    # Resolve auto values
    cpu_count = multiprocessing.cpu_count()
    if config["max_bake_workers"] is None:
        config["max_bake_workers"] = min(8, max(1, cpu_count // 2))
    if config["max_conversion_workers"] is None:
        config["max_conversion_workers"] = min(8, max(1, cpu_count // 2))

    return config


def save_config(config, path):
    """Write current resolved config to a JSON file."""
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def write_config_for_blender(config, output_dir):
    """Write config JSON to temp dir so Blender subprocesses can read it.
    Returns the path to the written config file."""
    temp_dir = os.path.join(output_dir, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    config_path = os.path.join(temp_dir, "mesh2tile.config.json")
    save_config(config, config_path)
    return config_path

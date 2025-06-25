# mesh2Tile
A repo for converting OBJ files into Cesium-compatible 3D tiles for use in Unreal. This script uses Blender and Python to automate the conversion process.

## Overview
This pipeline automates the process of converting a single OBJ mesh into a set of 3D tiles compatible with Cesium, suitable for streaming in Unreal Engine. The workflow is managed by `main.py` and includes the following steps:

1. **Texture Compression**: Compresses textures associated with the input OBJ file for efficient use in the pipeline.
2. **LOD Generation**: Uses Blender to generate multiple Levels of Detail (LODs) for the mesh.
3. **MTL Update**: Updates material files (MTL) to reference the new compressed textures.
4. **Tiling**: Splits each LOD mesh into spatial tiles using Blender scripts.
5. **GLB Conversion**: Converts each OBJ tile into the GLB format.
6. **Tileset Generation**: Generates and restructures a `tileset.json` for Cesium compatibility.
7. **Optional Gzip Compression**: Optionally compresses the output for efficient delivery.
8. **Cleanup**: Optionally removes temporary files after processing.

## Usage
Run the pipeline from the command line:

```
python main.py --input <path_to_input.obj> --output <output_folder> [--lods N] [--gzip] [--temp]
```

- `--input` / `-i`: Path to the input OBJ file (required)
- `--output` / `-o`: Path to the output folder (required)
- `--lods` / `-l`: Number of LODs to generate (default: 3)
- `--gzip`: Enable gzip compression for the output (optional)
- `--temp`: Preserve the temp folder after processing (optional)

## Requirements
- venv is recommended (conda or equivalent)
- Python 3.11+
- Blender 4.4 (update the path in `main.py` if needed)
- pip install Pillow

## Notes
- The pipeline uses Blender scripts for mesh processing and tiling. Ensure Blender is installed and the path in `main.py` is correct for your system.
- Output is structured for Cesium 3D Tiles and can be used in Unreal Engine with Cesium integration.

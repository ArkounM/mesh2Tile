# mesh2tile v2.0

High-performance OBJ to Cesium 3D Tiles converter with adaptive octree tiling and parallel processing.

## Overview

This pipeline automates the conversion of OBJ meshes into optimized 3D Tiles compatible with Cesium for streaming in Unreal Engine. The v2.0 rewrite features intelligent adaptive tiling, parallel processing, and native Blender-based GLB export.

### Key Features

- **Adaptive Octree Tiling**: Intelligent spatial partitioning based on geometry density
- **Parallel Processing**: Multi-worker texture baking and GLB conversion
- **Blender-Native Export**: Reliable GLB generation with embedded textures and Draco compression
- **Automatic Texture Baking**: Per-tile UV unwrapping and texture generation
- **Mesh Optimization**: Non-manifold edge removal and aggressive decimation
- **Batch Processing**: Process entire directories of OBJ files
- **93% File Size Reduction**: Optimized output compared to legacy pipeline

## Pipeline Workflow

```
Input OBJ(s)
    ↓
Adaptive Octree Tiling (4 LOD levels, 20k triangles/tile)
    ↓
Parallel Texture Baking (4 workers)
    ↓
Parallel Blender GLB Export (4 workers)
    ↓
Cesium Tileset JSON Generation
    ↓
Optional Gzip Compression
    ↓
3D Tiles Output
```

## Quick Start

### Basic Usage

```bash
python mesh2tile.py --input path/to/input.obj --output path/to/output --gzip
```

### Batch Processing Directory

```bash
python mesh2tile.py --input path/to/obj/directory --output path/to/output --gzip --continue-on-error
```

### Preserve Intermediate Files

```bash
python mesh2tile.py --input input.obj --output output/ --temp
```

## Command-Line Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--input` | `-i` | Input OBJ file or directory (required) | - |
| `--output` | `-o` | Output directory (required) | - |
| `--lods` | `-l` | Number of LOD levels to generate | 3 |
| `--gzip` | - | Enable gzip compression | False |
| `--temp` | - | Preserve temp folder after processing | False |
| `--force` | - | Force overwrite existing output directory | False |
| `--compress` | `-c` | Texture compression level (0-3) | 0 |
| `--continue-on-error` | - | Continue processing on file failure | False |
| `--max-bake-workers` | - | Parallel baking workers | CPU/2 (max 4) |
| `--max-conversion-workers` | - | Parallel conversion workers | CPU/2 (max 4) |
| `--longitude` | - | Longitude in degrees for tileset positioning | -75.703833 |
| `--latitude` | - | Latitude in degrees for tileset positioning | 45.417139 |
| `--height` | - | Height in meters for tileset positioning | 77.572 |

## Output Structure

```
output_directory/
├── model_name/
│   ├── tileset.json          # Cesium tileset manifest
│   ├── 0_0_0_0.glb          # Root tile (LOD 0)
│   ├── 1_*.glb              # LOD 1 tiles (8 tiles)
│   ├── 2_*.glb              # LOD 2 tiles (64 tiles)
│   ├── 3_*.glb              # LOD 3 tiles (variable)
│   └── temp/                # Intermediate files (if --temp used)
│       ├── tiles/           # OBJ tiles by LOD
│       │   ├── TileLevel_0/
│       │   ├── TileLevel_1/
│       │   ├── TileLevel_2/
│       │   └── TileLevel_3/
│       └── texture/         # Original textures
```

## Requirements

### Software Dependencies
- **Python**: 3.8+ (3.11+ recommended)
- **Blender**: 4.4+ (update path in `mesh2tile.py` line 267 if needed)
- **Node.js**: Required for tileset.json generation and gzip compression
- **npm**: Required for 3d-tiles-tools package

### Python Packages
```bash
pip install Pillow
```

### Node.js Packages
The pipeline uses the `3d-tiles-tools` npm package for tileset.json generation and optional gzip compression:
```bash
# No installation needed - npx will automatically download when first used
# The pipeline calls: npx 3d-tiles-tools createTilesetJson
# And optionally: npx 3d-tiles-tools gzip
```

### System Requirements
- **RAM**: 16GB+ recommended for large meshes
- **CPU**: Multi-core processor (parallel processing scales with cores)
- **GPU**: Optional (can improve Blender baking performance)

## Configuration

### Blender Path
Update the Blender executable path in `mesh2tile.py` (line 267):

```python
blender_config = {
    'exe': "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe",
    # ... other config
}
```

### Parallelization Tuning
- **Baking Workers**: Default is CPU cores / 2, max 4 (good for GPU baking)
- **Conversion Workers**: Default is CPU cores / 2, max 4 (Blender instances)
- Adjust with `--max-bake-workers` and `--max-conversion-workers` flags

### Tiling Parameters
Edit `BlenderScripts/adaptiveTiling.py` to adjust:
- `TRIANGLE_THRESHOLD = 20000` - Triangles per tile
- `MAX_TILE_LEVEL = 3` - Maximum octree depth
- `MERGE_DISTANCE = 0.001` - Non-manifold edge merge distance

## Performance

### Benchmark Results (5.7M triangle mesh)
- **Output Size**: 1.1 GB (462 GLB files)
- **Processing Time**: ~1.5 hours
- **LOD Levels**: 4 (0-3)
- **Tiles Generated**: 462
- **File Reduction**: 93% compared to legacy pipeline

### Optimization Tips
1. Use `--gzip` for web delivery (additional 50-70% size reduction)
2. Adjust `TRIANGLE_THRESHOLD` based on target platform performance
3. Use `--continue-on-error` for batch processing large datasets
4. Monitor GPU memory if using GPU baking (reduce `--max-bake-workers` if needed)

## Architecture

### Core Components

**Main Pipeline** (`mesh2tile.py`)
- Entry point and orchestration
- Batch processing and error handling
- Parallel worker management

**Pipeline Modules** (`pipeline/`)
- `triggerBlender.py` - Blender script execution wrapper
- `blender_obj2glb.py` - Blender-based GLB conversion
- `flip_obj_axes.py` - Axis transformation utilities
- `createTilesetJson.py` - Cesium tileset manifest restructuring
- `node_processes.py` - Node.js 3d-tiles-tools integration (tileset.json generation and gzip)

**Blender Scripts** (`BlenderScripts/`)
- `adaptiveTiling.py` - Adaptive octree spatial tiling
- `bakeTextures.py` - Per-tile texture baking
- `obj2glb.py` - Native Blender GLB export

## Migration from v1.x

### Breaking Changes
- Entry point: `main.py` → `mesh2tile.py`
- Node.js/npm no longer required
- Old pipeline archived in `_archive/`

### What Changed
- **Tiling**: Fixed grid → Adaptive octree
- **GLB Export**: obj23dtiles (npm) → Blender native
- **Processing**: Serial → Parallel (4 workers)
- **Mesh Cleanup**: Added non-manifold edge removal
- **File Sizes**: 93% reduction via better decimation and texture optimization

See [CHANGELOG.md](CHANGELOG.md) for detailed changes.

## Troubleshooting

### Common Issues

**"Blender not found"**
- Update Blender path in `mesh2tile.py` line 267

**"Out of memory during baking"**
- Reduce `--max-bake-workers` to 1 or 2
- Process smaller batches

**"GLB files are empty/corrupt"**
- Check Blender version is 4.5+
- Verify OBJ has valid UVs and textures

**"Process hangs during conversion"**
- Reduce `--max-conversion-workers`
- Check system resources (CPU/RAM)

**"testAdaptiveTiling directory still present"**
- Background processes may be using it
- Safe to delete manually after processes complete

## License

See [LICENSE](LICENSE) for details.

## Credits

- Adaptive tiling algorithm: Octree-based spatial partitioning
- GLB export: Blender Python API with Draco compression
- Parallel processing: Python ProcessPoolExecutor
- Previous versions: See `_archive/` for legacy implementation

## Support

For issues, feature requests, or contributions, please open an issue on the project repository.

---

**Version**: 2.0.0
**Last Updated**: 2025-10-07
**Python**: 3.8+
**Blender**: 4.5+

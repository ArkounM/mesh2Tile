# Changelog

All notable changes to the mesh2tile project will be documented in this file.

## [2.1.0] - 2025-11-03

### Performance Optimizations (Phases 1-2)

Implemented algorithm-level performance optimizations including triangle count caching, BMesh-based cleanup, spatial partitioning octree bisection, and UV-preserving mesh operations, achieving a 31% reduction in processing time (105s → 75s) for typical architectural models. Evaluated but excluded parallel tiling optimization (Phase 3) as startup overhead cancels benefits for models under 1M triangles, making it beneficial only for large photogrammetry datasets.

### Changed
- **Optimized**: Triangle count calculations now cached to eliminate redundant bmesh operations
- **Optimized**: Mesh cleanup uses direct BMesh API instead of edit mode operators (50-70% faster)
- **Optimized**: Directory creation cached to reduce filesystem overhead during export
- **Optimized**: Octree bisection uses spatial partitioning instead of iterative mesh copying (3-5x faster, 80% less memory)
- **Fixed**: UV coordinates now properly preserved during octree subdivision (prevents black textures)
- **Added**: Optional `--parallel-tiling` flag for models >1M triangles (disabled by default)

### Performance
- **Step 1 (Adaptive Tiling)**: 34s → 23s (32% faster)
- **Overall Pipeline**: 105s → 75s (29% faster)
- **Memory Usage**: 80% reduction during octree subdivision
- **UV Preservation**: Zero visual quality loss with optimized algorithm

---

## [2.0.0] - 2025-10-07

### Major Refactor - Adaptive Tiling Pipeline

This release represents a complete rewrite of the mesh-to-3D-tiles pipeline with significant performance and reliability improvements.

### Added
- **Adaptive Octree Tiling**: New intelligent spatial partitioning that creates LOD hierarchy based on geometry density
- **Blender-based GLB Conversion**: Native Blender export replacing problematic obj23dtiles npm dependency
- **Parallel Processing**: Multi-worker support for texture baking (4 workers) and GLB conversion (4 workers)
- **Texture Baking**: Automatic texture baking for each tile with UV unwrapping
- **New Blender Scripts**:
  - `adaptiveTiling.py` - Octree-based spatial tiling with adaptive LOD generation
  - `obj2glb.py` - Native Blender OBJ to GLB conversion with embedded textures
- **New Pipeline Modules**:
  - `blender_obj2glb.py` - Python wrapper for Blender GLB conversion
  - `triggerBlender.py` - Unified Blender script execution interface

### Changed
- **BREAKING**: Main entry point renamed from `main.py` to `mesh2tile.py`
- **BREAKING**: Removed obj23dtiles dependency (replaced with Blender native export)
- **BREAKING**: New directory structure - testAdaptiveTiling promoted to root
- **Improved**: Mesh cleanup now removes non-manifold edges before decimation
- **Improved**: Parallel execution eliminates npm cache conflicts
- **Improved**: Windows Unicode encoding fixes for console output
- **Improved**: Better error handling with per-LOD conversion tracking

### Removed
- obj23dtiles npm-based conversion (unreliable, npm cache conflicts)
- Old LOD generation workflow (lodOBJ.py, generate_LODs.py)
- Old tiling workflow (tileOBJ.py, tileLOD.py)
- Legacy assignTexture2LOD.py module

### Fixed
- **Critical**: 100% failure rate in OBJ to GLB conversion (npm cache issues)
- Non-manifold edges causing holes in decimated meshes
- Unicode encoding errors on Windows console
- Texture path resolution in tiled meshes
- Race conditions in parallel npm cache access

### Performance
- **File Size Reduction**: Test outputs reduced from 560 MB to 40 MB (93% reduction)
- **Texture Optimization**: Alpha-masked textures reduce tile sizes from 17 MB to 1 MB each
- **Processing Speed**: Parallel baking and conversion significantly faster than serial processing

### Migration Guide

#### For Users of Old Pipeline:
1. Update entry point: `python main.py` → `python mesh2tile.py`
2. Old pipeline scripts archived in `_archive/` directory
3. No changes to command-line arguments
4. Node.js/npm still required for tileset.json generation and gzip (3d-tiles-tools)

#### Key Differences:
- **Old**: Sequential LOD generation → tiling → conversion
- **New**: Adaptive octree tiling → parallel baking → parallel conversion
- **Old**: npm-based obj23dtiles for GLB conversion
- **New**: Native Blender GLB export with Draco compression

### Architecture
```
Old Pipeline (v1.x):
Input OBJ → Generate LODs → Tile each LOD → Bake textures → obj23dtiles → 3D Tiles

New Pipeline (v2.0):
Input OBJ → Adaptive Octree Tiling → Parallel Texture Baking → Parallel Blender GLB Export → 3D Tiles
```

### Technical Details
- Blender 4.5+ required
- Python 3.8+ required
- Node.js/npm required for tileset.json generation and gzip (3d-tiles-tools)
- Removed obj23dtiles npm dependency (replaced with Blender native)
- Parallel processing: 4 workers for baking, 4 workers for conversion
- Octree max depth: 3 levels (configurable)
- Triangle threshold: 20,000 per tile (configurable)

### Credits
- Adaptive tiling algorithm based on octree spatial partitioning
- Blender Python API for native GLB export
- Process-based parallelization for improved throughput

---

## [1.x.x] - Legacy (Archived)

Old pipeline implementation archived in `_archive/` directory.
See `_archive/README_old.md` for legacy documentation.

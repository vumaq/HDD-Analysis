# Hidden & Dangerous I3D Tools

This repository provides utilities for working with **Illusion Softworks I3D model files** (as used in *Hidden & Dangerous* and *Hidden & Dangerous: Deluxe*).  

The I3D format is derived from the **Autodesk 3D Studio `.3ds` format**, but extends it with additional chunk types  
(e.g. `0x4200 FACE_MAP_CHANNEL` for multi-UV support). These scripts are designed for **modders, researchers, and developers** who want to inspect, extract, and convert I3D assets into modern formats.

---

## Roadmap

- ✅ Static model parsing  
- ✅ Decoding of `0x4200 FACE_MAP_CHANNEL` (extra UVs)  
- ✅ Proof-of-concept: **I3D → OBJ conversion**  
- ❌ Animation/keyframe decoding  
- ❌ Blender .i3d importer that respects I3D-specific chunks  
- ❌ Blender .i3d exporter

---

## Tools

### 1. I3D / 3DS Analyzer

📄 [Documentation](documentation/i3d_analyzer.md)  
⚙️ [Download Script](tools/i3d_analyzer.py)

A registry-driven parser that inspects the full binary chunk structure of `.i3d` files.  

**Usage:**
```bash
python i3d_analyzer.py file.i3d
```

---

### 2. I3D → OBJ Converter

📄 [Documentation](documentation/i3d_to_obj.md)  
⚙️ [Download Script](tools/i3d_to_obj.py)

Converts `.i3d` models into **Wavefront OBJ + MTL** files for use in Blender, MeshLab, Microsoft 3D Viewer, etc.  

**Usage:**
```bash
# Basic conversion
python i3d_to_obj.py domek.i3d

# With custom axis mapping
python i3d_to_obj.py domek.i3d --transform "(x, -z, y)"

# Bake object transforms into vertices
python i3d_to_obj.py domek.i3d --bake
```

Produces:
- `domek.obj`  
- `domek.mtl`  
in the same directory as the source `.i3d`.  
Textures should be placed alongside the `.i3d` file.

---

## I3D-Specific Notes

- **Extra UV maps (`0x4200 FACE_MAP_CHANNEL`)**: Unique to I3D, allows multiple UV channels per mesh.  
- **Axis differences**: I3D uses Z-up, while OBJ uses Y-up. Default transform corrects this.  
- **Animations**: Keyframe chunks (`0xB000`) are parsed by the analyzer but **not exported** by the OBJ converter.  

---

## Limitations

- Only tested against *Hidden & Dangerous* I3D files.  
- Static models supported; animated I3D and map files are only partially covered.  
- Additional UV channels beyond the first are not exported to OBJ.  
- Materials assume `.png` texture files; missing textures result in untextured meshes.  

---

## License

MIT License — free to use, modify, and share.

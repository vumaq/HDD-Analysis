# I3D → OBJ Converter

📂 [Download Script](../tools/i3d_to_obj.py)

## Overview
The `i3d_to_obj.py` script converts **Illusion Softworks I3D models** into the widely supported **Wavefront OBJ** format.  
It is designed to preserve meshes, UVs, and materials so assets can be opened in Blender, MeshLab, Microsoft 3D Viewer, and other tools.

---

## Features
- **Mesh export** – vertices and faces written as OBJ geometry  
- **UV mapping** – parses `0x4200 FACE_MAP_CHANNEL` to correctly apply per-face UVs  
- **Materials** – generates an `.mtl` file referencing texture files (assumed to be alongside the `.i3d`)  
- **Axis transform correction** – applies `(x, -y, -z)` by default to convert I3D’s Z-up system to OBJ’s Y-up  
- **Custom transforms** – optional `--transform "(exprX, exprY, exprZ)"` syntax for manual axis remapping  
- **Bake option** – `--bake` collapses object transforms into vertex coordinates  

---

## Usage
### Basic Conversion
```bash
python i3d_to_obj.py domek.i3d
```
Produces `domek.obj` + `domek.mtl` in the same directory. Textures (`.png`) should be next to the `.i3d`.

### With Custom Transform
```bash
python i3d_to_obj.py domek.i3d --transform "(x, -z, y)"
```
Applies a custom axis remap.

### With Bake
```bash
python i3d_to_obj.py domek.i3d --bake
```
Applies baked object matrices so meshes appear in in-game positions.

---

## Limitations
- Only the **first UV channel** is exported  
- Materials assume `.png` textures with matching filenames  

- Animations and keyframes (`0xB000` chunks) are not exported

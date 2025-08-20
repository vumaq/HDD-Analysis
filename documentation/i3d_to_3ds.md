# I3D → 3DS Converter

📂 [Download Script](../tools/i3d_to_3ds.py)

## Overview
The `i3d_to_3ds.py` script converts **Illusion Softworks I3D model files** into the **Autodesk 3DS format**.  

It preserves meshes, UVs, materials, and keyframer data so assets can be imported into **3ds Max**, **Blender**, or other 3DS-capable tools.

---

## Features
- **Mesh export** – converts all `0x4000 OBJECT` blocks into 3DS mesh chunks  
- **UV mapping** – reads `0x4200 FACE_MAP_CHANNEL` and outputs standard 3DS UVs  
- **Materials** – converts I3D material chunks into 3DS `MAT_*`, linking textures by filename  
- **Animation support** – preserves keyframer data (`0xB000` chunks)  
- **Transform options** –  
  - Default: keeps `0x4160 OBJECT_TRANS_MATRIX` for **3ds Max compatibility**  
  - `--bake-xform`: multiplies transforms into vertices and omits the matrix (safer for Blender and other tools that double-apply transforms)  

---

## Usage
### Basic Conversion
```bash
python i3d_to_3ds.py domek.i3d -o domek.3ds
```
Outputs `domek.3ds` in the same directory. Textures should be present alongside the `.i3d` or in the working directory.

### With Transform Baking
```bash
python i3d_to_3ds.py die_0.i3d -o die_0_baked.3ds --bake-xform
```
Applies all object transforms directly to vertex positions, omitting transform matrices.

### With Specific UV Channel
```bash
python i3d_to_3ds.py die_0.i3d -o die_0.3ds --channel 2
```
Exports UVs from FACE_MAP_CHANNEL index 2 instead of channel 1.

---

## Limitations
- Expects textures to be available on disk, matching the filenames in the I3D  
- Only single mesh hierarchy is supported (lights/cameras skipped)  
- Keyframe data is preserved but not interpreted  
- 3DS format limit: 65,535 vertices per mesh  

# OBJ → I3D Converter

📂 [Download Script](../tools/obj_to_i3d.py)

## Overview
The `obj_to_i3d.py` script converts standard **Wavefront OBJ models** (with optional MTL files) into the **Illusion Softworks I3D format**.  
It is designed to recreate meshes, UVs, materials, and smoothing groups in the original I3D structure, making round-tripping between formats possible.

---

## Features
- **Mesh import** – reads OBJ vertices, faces, and triangulates polygons  
- **UV mapping** – exports texture coordinates into the I3D-specific `0x4200 FACE_MAP_CHANNEL` chunk when UVs are present  
- **Materials** – parses `.mtl` files, preserves diffuse color and texture assignments (`map_Kd`)  
- **Smoothing groups** – OBJ `s` flags are written into `0x4150 OBJECT_SMOOTH` subchunks  
- **Axis correction** – applies `(x, -y, -z)` to convert OBJ’s Y-up system into I3D’s Z-up  
- **Keyframer support (optional)** – `--kf` flag embeds minimal `0xB000` keyframe data for scene compatibility  
- **UV flip control** – `--no-flip-v` disables the default `v = 1 - v` correction  

---

## Usage
### Basic Conversion
```bash
python obj_to_i3d.py cube.obj
```
Produces `cube.i3d` alongside the original OBJ.

### Custom Object Name
```bash
python obj_to_i3d.py cube.obj --name "MyObject"
```
Overrides the default object name.

### With Keyframer
```bash
python obj_to_i3d.py cube.obj --kf
```
Includes a minimal keyframer block (`0xB000`) for baseline animation support.

### Without V-Flip
```bash
python obj_to_i3d.py cube.obj --no-flip-v
```
Preserves the OBJ’s native V coordinate orientation.

---

## Limitations
- Only supports **triangulated faces** (non-tri polygons are auto-fanned into triangles)  
- **Per-mesh limits** apply: ≤ 65,535 vertices and faces (3DS/I3D spec)  
- Does not include scaling, transform matrices, or edit-config chunks (`0x3D3E`)  
- Only exports a single mesh object per file  

---

# I3D → 3DS Converter

📂 [Download Script](../tools/i3d_to_3ds.py)

## Overview
The `i3d_to_3ds.py` script converts **Illusion Softworks I3D models** into the classic **Autodesk 3DS** format.  

It is designed for compatibility with **3D Studio Max** and similar tools, expanding I3D’s extended UV format (`0x4200 FACE_MAP_CHANNEL`) into standard `0x4140 OBJECT_UV` arrays required by 3DS.  

---

## Features
- **Mesh export** – vertices and faces written as proper 3DS `POINT_ARRAY` + `OBJECT_FACES`  
- **UV mapping** – always expands seams from I3D `0x4200 FACE_MAP_CHANNEL` so `len(POINT_ARRAY) == len(OBJECT_UV)` as expected by 3DS  
- **Material support** – exports `MATERIAL` blocks with diffuse color and texture maps (`MAT_MAP_FILEPATH`)  
- **Transform handling** – preserves `OBJECT_TRANS_MATRIX` (0x4160), with option to bake into vertex positions  
- **Smoothing groups** – retains `OBJECT_SMOOTH` masks when present  
- **Keyframer data** – copies `0xB000 KFDATA` blobs directly for animation compatibility  

---

## Usage
### Basic Conversion
```bash
python i3d_to_3ds.py domek.i3d
```
Produces `domek.3ds` in the same directory.

### With Output Path
```bash
python i3d_to_3ds.py domek.i3d -o models/domek_fixed.3ds
```
Writes the converted model to a custom location.

### Bake Transforms
```bash
python i3d_to_3ds.py domek.i3d --bake-xform
```
Applies `OBJECT_TRANS_MATRIX` directly into vertex coordinates, removing transform blocks for compatibility.

---

## Limitations
- Only **one UV channel** is written (expanded from channel 1, or first available)  
- Materials assume external texture files are available on disk  
- Animation (`KFDATA`) is preserved but not interpreted  
- Does **not** re-emit Illusion’s `0x4200` chunks (they are converted)  

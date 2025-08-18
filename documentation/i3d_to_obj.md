# I3D → OBJ Conversion Script

## Purpose

The `i3d_to_obj.py` script is a dedicated converter for **Illusion Softworks I3D model files** (used in *Hidden & Dangerous* and derivatives) into the widely-supported **Wavefront OBJ** format.

The goal is to preserve meshes, UVs, and textures so the models can be viewed, edited, or re-imported in modern tools such as Blender, Microsoft 3D Viewer, or MeshLab.

---

## Features

- **Mesh export**  
  Extracts vertices and faces from I3D geometry chunks and outputs them as OBJ meshes.

- **UV mapping**  
  Correctly reads `0x4200 FACE_MAP_CHANNEL` chunks and applies UV coordinates per face. This ensures textures appear correctly in OBJ consumers.

- **Material/texture linking**  
  Generates a `.mtl` file alongside the OBJ, with each material referencing the corresponding texture (assumed to be in the same directory as the original I3D).  
  Example:  
  ```mtl
  newmtl $DOMEK_DVERE
  map_Kd E_DS2.png
  ```

- **Transform support**  
  By default, vertices are exported with a transform that corrects axis orientation:  
  ```
  (x, -y, -z)
  ```
  This aligns I3D’s Z-up system with OBJ’s Y-up expectations, so models appear upright without extra manipulation.

- **Optional custom transforms**  
  You may override the default with:  
  ```bash
  python i3d_to_obj.py domek.i3d --transform "(-x, z, -y)"
  ```
  This string is parsed as `(newX, newY, newZ)` where each term can be `x`, `y`, `z` with optional `-` sign.

- **Bake option**  
  `--bake` can be enabled to collapse object-space transforms into the exported vertex data. Without `--bake`, the raw mesh is exported as-is.

- **Verbose logging**  
  The script always reports progress and applied transforms to the console so modders can track what happened.

---

## Usage

### Basic Conversion

```bash
python i3d_to_obj.py domek.i3d
```

- Produces `domek.obj` and `domek.mtl` in the same directory.  
- Texture `.png` files should be next to the `.i3d`.

### With Custom Transform

```bash
python i3d_to_obj.py domek.i3d --transform "(x, -z, y)"
```

Rotates the model differently by re-mapping axes manually.

### Baking Transforms

```bash
python i3d_to_obj.py domek.i3d --bake
```

Applies baked object matrices so meshes appear in their in-game position.

---

## Default Transform

By default, the script applies:

```
(x, -y, -z)
```

This was chosen because:

- Raw I3D coordinates are Z-up, while OBJ is usually Y-up.
- Without correction, models appear sideways or upside down.
- Testing across viewers (Blender, Microsoft 3D Viewer) showed this mapping yields the expected upright orientation.

---

## Limitations

- **Multiple UV channels**: Only the first UV channel is exported. Additional UV maps exist in I3D but are not included in OBJ.  
- **Materials**: The script assumes textures are `.png` files with names matching those referenced in the I3D. If not found, the OBJ loads without textures.  
- **Animations**: Keyframe and transform data (`0xB000` chunks) are not exported. Only static meshes are supported.
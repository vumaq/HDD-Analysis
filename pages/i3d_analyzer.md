# Hidden & Dangerous I3D Analyzer Documentation

## Overview
This tool is a **dedicated analyzer for Hidden & Dangerous `.i3d` model files**, which are derived from the classic **Autodesk 3D Studio `.3ds` format** but extended in several ways.  
It inspects the binary chunk structure, extracts meaningful values, and produces both:

- **Markdown reports** for human inspection.  
- **JSON trees** for downstream processing (e.g. conversion to OBJ/MTL).  

Unlike generic 3DS parsers, this analyzer focuses on the **Illusion Softworks I3D dialect**, as used in *Hidden & Dangerous* and *Hidden & Dangerous: Deluxe*.  

---

## Goals
- Reverse-engineer the **I3D variant** of the 3DS format.  
- Provide clear **visual reports** of the structure and values.  
- Support modders and researchers by enabling export to **intermediate JSON**.  

⚠️ **Important**: So far this has only been tested on **static I3D models**, not animations or map files.

---

## Outputs
For each `.i3d` file, the analyzer generates multiple reports:

- **`summary.md`** – quick statistics (chunk counts, unknown IDs, anomalies).  
- **`chunk_tree.md`** – indented outline of the chunk hierarchy.  
- **`chunks_by_id.md`** – all occurrences grouped by chunk type.  
- **`unknown_ids.md`** – IDs found in I3D but not yet mapped.  
- **`unused_known_ids.md`** – known IDs not encountered in this file.  
- **`anomalies.md`** – warnings about bad lengths or truncated payloads.  
- **`report.json`** – structured tree with parsed values.  
- **`viewports.md`** – captures viewport/display chunk info.

---

## JSON Structure
The JSON output was designed for clarity and compactness:

- Each chunk is represented with only what matters:
  ```json
  {
    "id_hex": "0xA000",
    "name": "MAT_NAME",
    "lines": ["Material Name: $DOMEK OKNO"]
  }
  ```

- `children` are only included if present.  
- `lines` contain semantic values (like colors, UVs, face indices).  
- Empty arrays are omitted entirely.  

This makes the output easier to read, and cleaner for re-use in exporters.

---

## Nuances of Hidden & Dangerous I3D

### Materials (`0xAFFF`)
- Fully parsed including **ambient**, **diffuse**, **specular**, **shininess**, **transparency**, and **Phong shading** flags.  
- Textures (`MAT_TEXTUREMAP`) list **file paths**, **tiling flags**, and **blur values**.  

### Object Material Groups (`0x4130`)
- Correctly expanded into:
  - Material name.  
  - Number of faces.  
  - Explicit face indices.  
- Fixes the problem where earlier analyzers just repeated empty `OBJECT_MATERIAL` stubs.

### Smoothing (`0x4150`)
- Face-by-face smoothing groups are extracted.  
- Output shows one smoothing ID per face, useful for checking shading fidelity.

### Extra UV Maps (`0x4200 FACE_MAP_CHANNEL`)
- Specific to I3D.  
- Allows **multiple UV channels per mesh**, unlike vanilla 3DS (which only supports one).  
- This feature was introduced for Hidden & Dangerous to support multi-texturing (detail maps, lightmaps, etc.).  

### Keyframe Data (`0xB000 KFDATA`)
- Structural parsing works (e.g. `KFHDR`, `KFCURTIME_RANGE`).  
- Animation controller semantics are not yet fully decoded.  
- Only static model testing has been done so far.

### Viewports / Display (`0x7000` series)
- Blocks such as `0x7001`, `0x7011`, `0x7012`, `0x7020` store **viewport/editor display settings**.  
- Extracted values include:  
  - **View type** (Perspective, Top, Left, Camera, etc.)  
  - **Zoom factor**  
  - **Pan offsets** (X/Y)  
  - **Viewport rectangle** coordinates (left, top, right, bottom)  
  - **Reference object name** (if any)  
- These were originally written by 3D Studio’s viewport/editor system.  
- While not directly used by the Hidden & Dangerous engine, they provide **valuable context** for modders trying to reconstruct how the model was viewed or aligned during authoring.

---

## Known Limitations
- Only tested against **Hidden & Dangerous I3D model files**.  
- **Map files** and **animated I3Ds** have not been validated.  
- Registry of chunk IDs is still incomplete (unknown IDs appear in `unknown_ids.md`).  
- Some float values are noisy (extra decimals).  

---

## Future Work
- Add robust **animation/keyframe parsing**.  
- Build a **converter from I3D JSON → OBJ/MTL**, copying referenced textures into place.  
- Test on **map files** for performance and scaling.  
- Expand the registry with all known **Hidden & Dangerous chunk IDs**.  
- Document quirks of the format (e.g. why some chunks overlap with standard 3DS, while others are I3D-only).

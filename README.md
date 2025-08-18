# Hidden & Dangerous I3D Analyzer Documentation

[Download i3d_analyzier.py](tools/i3d_analyzer.py)

## Overview
This tool is a **dedicated analyzer for Hidden & Dangerous `.i3d` model files**, which are derived from the classic **Autodesk 3D Studio `.3ds` format** but extended in several ways.  
It inspects the binary chunk structure, extracts meaningful values, and produces both:

The I3D format is derived from the classic **Autodesk 3D Studio `.3ds` format**, but includes several extensions specific to Illusion Softworks, such as **extra UV map channels** [Understanding 4200](documentation/understanding_4200.md).    

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

### Extra UV Maps (`0x4200 FACE_MAP_CHANNEL`)
- Specific to I3D.  
- Allows **multiple UV channels per mesh**, unlike vanilla 3DS (which only supports one).  
- This feature was introduced for Hidden & Dangerous to support multi-texturing (detail maps, lightmaps, etc.).

[Understanding 4200](../documentation/understanding_4200.md)

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

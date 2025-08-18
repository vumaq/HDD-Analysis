# I3D / 3DS Analyzer

📂 [Download Script](../tools/i3d_analyzer.py)

## Overview
The `i3d_analyzer.py` tool inspects **Hidden & Dangerous `.i3d` model files**, a variant of the **Autodesk 3D Studio `.3ds` format** with extensions specific to Illusion Softworks.  
It parses the binary chunk structure, extracts meaningful values, and generates structured reports.  

Unlike generic 3DS parsers, this analyzer is tailored to the **I3D dialect** used in *Hidden & Dangerous* and *Hidden & Dangerous Deluxe*.

---

## Goals
- Reverse-engineer the I3D format  
- Provide clear, visual reports of structure and values  
- Support modders and researchers working with legacy Illusion Softworks assets  

⚠️ Tested primarily on static I3D models. Animation and map files are only partially covered.

---

## Outputs
For each `.i3d` file, the analyzer generates:

- **`<file>.dump.txt`** – human-readable text dump  
- **`report.json`** – nested JSON representation  
- **`summary.md`** – high-level stats  
- **`chunk_tree.md`** – flat chunk tree (offsets/sizes)  
- **`chunks_by_cid.md`** – chunks grouped by ID  
- **`unknown_ids.md`** – unknown chunk IDs encountered  
- **`unused_known_ids.md`** – known IDs not used in this file  
- **`anomalies.md`** – anomalies like truncations or invalid sizes  
- **`viewports.md`** – parsed viewport/display blocks (optional)  

---

## JSON Design
The JSON report is designed to be minimal but reusable:

```json
{
  "id_hex": "0xA000",
  "name": "MAT_NAME",
  "lines": ["Material Name: $DOMEK OKNO"]
}
```

- `lines` contain semantic values (e.g. colors, UVs, face indices)  
- `children` included only if present  
- Empty arrays are omitted  

This structure makes the output easy to read and suitable for converters.

---

## I3D-Specific Notes
### Extra UV Maps (`0x4200 FACE_MAP_CHANNEL`)
- Unique to I3D  
- Supports multiple UV channels per mesh (vanilla 3DS only supports one)  
- Used in *Hidden & Dangerous* for multi-texturing, detail maps, and lightmaps  

---

## Limitations
- Tested against *Hidden & Dangerous* I3D models only  
- Animated I3D and map files not fully supported  
- Chunk ID registry incomplete (see `unknown_ids.md`)  
- Some float values may display extra decimals  

---

## Roadmap
- ✅ Static model parsing  
- ✅ Decoding of `0x4200 FACE_MAP_CHANNEL`  
- ❌ Animation and keyframe decoding  
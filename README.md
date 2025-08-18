# Hidden & Dangerous I3D File Format (analysis)

## Overview
This repository contains tools and documentation for analyzing and working with the **I3D model format** used in *Hidden & Dangerous* and *Hidden & Dangerous Deluxe*.  

The I3D format is derived from the classic **Autodesk 3D Studio `.3ds` format**, but includes several extensions specific to Illusion Softworks, such as **extra UV map channels** [Understanding 4200](documentation/understanding_4200.md).    

Our goal is to provide **modders and researchers** with reference tools that make it easier to explore, document, and eventually build tools.

---

## Features
- **I3D Analyzer**  
  - Reads binary `.i3d` files.  
  - Produces both **Markdown reports** and **JSON trees** for inspection.  
  - Extracts materials, UVs, smoothing groups, and structural hierarchy.  

- **Outputs**  
  - `summary.md` – quick statistics and metadata.  
  - `chunk_tree.md` – indented hierarchy of all chunks.  
  - `chunks_by_id.md` – grouped by chunk type.  
  - `unknown_ids.md` – unmapped IDs.  
  - `unused_known_ids.md` – registered IDs not found in this file.  
  - `anomalies.md` – suspicious chunk lengths, bad data.  
  - `viewports.md` – extracted viewport / display settings.  
  - `dump.txt` – raw tree dump for cross-checking.  
  - `report.json` – structured machine-readable output.  

- **Format Nuances Covered**  
  - Multi-UV support via `0x4200 FACE_MAP_CHANNEL`.  

---

## Status
⚠️ Currently only **static I3D models** have been tested.  
Map files and animated models have not yet been validated.  

The tool is still evolving, expect **unknown IDs** and **partial feature coverage**.

---

## Roadmap
- ✅ Static model parsing  
- 🔄 Animation and keyframe decoding  
- 🔄 Converter: I3D JSON → OBJ/MTL (+ texture extraction)  

---

## Audience
This repository is primarily aimed at:
- **Modders** working with *Hidden & Dangerous* assets.  
- **Researchers** studying legacy Illusion Softworks formats.  
- **Developers** who want to build converters or importers.  

---

## License
MIT License — feel free to use, adapt, and contribute.
 

# Hidden & Dangerous Modding Tools

## Overview
This repository provides a set of **reference tools for modders** working with *Hidden & Dangerous* and *Hidden & Dangerous: Deluxe*.  
The goal is to **unpack, analyze, and document** the game’s data formats to make modding easier and more transparent.

Currently, the focus is on the **`.i3d` model format**, but the project will expand to cover other asset types such as **maps, textures, and animations**.

---

## Features
- **I3D Analyzer**
  - Parses Hidden & Dangerous `.i3d` model files (derived from Autodesk 3DS).
  - Produces **Markdown reports** for human-readable inspection.
  - Exports **JSON trees** for automated conversion (e.g. `.obj/.mtl` workflows).

- **Reports Generated**
  - `summary.md` – quick statistics on chunks and anomalies.
  - `chunk_tree.md` – indented outline of the file structure.
  - `chunks_by_id.md` – grouped chunk occurrences.
  - `unknown_ids.md` – unmapped IDs.
  - `unused_known_ids.md` – unused but known IDs.
  - `anomalies.md` – warnings for odd/truncated data.
  - `dump.txt` – raw annotated chunk dump.
  - `viewports.md` – viewport/display configuration.
  - `report.json` – clean, hierarchical JSON representation.

---

## Example

```bash
python i3d_analyzer.py domek.i3d
```

Produces JSON and Markdown outputs for that file.

---

## Limitations
- Tested only on **static I3D models** so far.
- Map files and animated I3Ds have not yet been validated.
- Registry of chunk IDs is incomplete – expect unknowns.
- JSON float precision can be verbose.

---

## Roadmap
- Expand chunk registry with full Hidden & Dangerous structures.
- Improve **animation/keyframe parsing**.
- Add **I3D → OBJ/MTL converter**, including automatic texture copying.
- Extend tooling to:
  - Map files.
  - Animation data.
  - Other game resource formats.

---

## Audience
These tools are meant as **reference utilities** for:
- Modders who want to extract or edit assets.
- Researchers documenting the I3D format.
- Developers writing converters or import/export plugins.

---

## License
This project is released under the **MIT License**. Contributions are welcome!

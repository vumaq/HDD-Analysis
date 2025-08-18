# The I3D 0x4200 Chunk

## Purpose

The `FACE_MAP_CHANNEL` chunk (`0x4200`) is a custom extension introduced by Illusion Softworks for their I3D format, derived from the classic 3D Studio (`.3ds`) structure.  

Its role is to provide **per-mesh support for multiple UV mapping channels**, something the original 3DS format did not allow. Each occurrence of this chunk defines a complete UV set, identified by its own channel index.

Community research has confirmed its use. For example, one exporter note states:  
> “We create a chunk called FACE_MAP_CHANNEL. Hex value is 0x4200. Code: … // export mapping channels for (int i=1; i…).”  
([hidden-and-dangerous.net](https://hidden-and-dangerous.net/board/viewtopic.php?t=43851))

---

## Comparison with Standard 3DS UV Mapping (0x4140)

In a standard 3DS file, UVs are stored in the `MAPPINGCOORDS` chunk (`0x4140`). As documented by [Paul Bourke](http://paulbourke.net/dataformats/3ds/), this format simply lists a count of vertices followed by a corresponding series of `(U, V)` pairs.  

The I3D approach in `0x4200` differs in several important ways:

- **Multiple channels per mesh** Whereas `0x4140` is limited to a single UV layer, `0x4200` may appear multiple times within the same mesh, one for each UV channel. Each chunk begins with an integer channel index to distinguish which UV set it represents (e.g., channel 1 for the base layer, channel 2 for a secondary set, etc.).
- **Independent UV vertices** Unlike the 3DS scheme, which assumes UVs map 1:1 with mesh vertices, `0x4200` defines its own list of UV coordinates. This decoupling avoids duplicating geometry when a single vertex needs different UV positions across faces.
- **Per-face UV indices** Each chunk also carries a face-UV index array. This mirrors the standard `FACE_ARRAY` (`0x4120`), but for texture coordinates. Every face entry contains three indices, referencing the UV list rather than the geometry vertices.

Because of this system, most I3D meshes contain **no `0x4140` data at all**. Instead, their primary UV set is stored under `0x4200` (usually with channel index = 1).

---

## Binary Layout

After the usual 6-byte chunk header (`id=0x4200`, `length`), the chunk data is laid out as follows:

| Offset (bytes) | Type            | Meaning |
| -------------- | --------------- | ------- |
| 0x00           | int32           | Channel index (identifies the UV set) |
| 0x04           | uint16          | Number of UV vertices (N) |
| 0x06           | float × 2 × N   | List of N `(U, V)` coordinate pairs |
| ...            | uint16          | Number of faces (M) – should equal mesh face count |
| ...            | uint16 × 3 × M  | UV face indices (3 per face, referencing the UV list) |

**Example:**  
- `01 00 00 00` → channel index = 1  
- `0A 00` → 10 UV vertices, followed by 10 × `(U, V)` pairs (80 bytes)  
- `20 00` → 32 faces, followed by 32 × 3 indices (per face corner)

---

## Why It Exists

The introduction of `FACE_MAP_CHANNEL` was a practical requirement for *Hidden & Dangerous*.  
Illusion Softworks needed a way to support more than one UV channel and to decouple texture mapping from geometry. By doing so, they enabled techniques like multiple textures, detail maps, or lightmaps that the single-UV `0x4140` scheme could not accommodate ([hidden-and-dangerous.net](https://hidden-and-dangerous.net/board/viewtopic.php?t=43851)).

---

## Import and Tooling Notes

- **Blender Import** Blender’s stock 3DS importer does not support this extension, so I3D models often lose their UV mapping on import.  
- **3ds Max I3D plugin** The original plugin for Max 3.0/3.1 includes support for this chunk ([hidden-and-dangerous.net](https://hidden-and-dangerous.net/board/viewtopic.php?p=15301#p15301)).  
- **Custom tooling** Scripts and analyzers that specifically handle `0x4200` are required for faithful conversion.

---

## Summary

The I3D `0x4200` `FACE_MAP_CHANNEL` chunk is a structural upgrade over the classic 3DS `0x4140`.  
It introduces independent, channel-indexed UV sets with explicit face mappings, allowing multiple texture coordinate layers per mesh. Correct handling of this chunk is essential for accurate import, export, and editing of I3D models.


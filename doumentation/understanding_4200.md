# Understanding the I3D 0x4200 Chunk

## Purpose of the 0x4200 FACE_MAP_CHANNEL Chunk

The `FACE_MAP_CHANNEL` chunk (ID 0x4200) in I3D files is a custom extension to the classic 3D Studio (.3ds) format used by Illusion Softworks (e.g., *Hidden & Dangerous*). It was introduced to store additional UV mapping data and support multiple UV sets per mesh. A modding forum explains: *“Here from exporter, we create a chunk called FACE_MAP_CHANNEL. Hex value is 0x4200. Code: … //export mapping channels for(int i=1; i….”* ([hidden-and-dangerous.net](https://hidden-and-dangerous.net/board/viewtopic.php?t=43851)).

## Differences from Standard 3DS UV Mapping (Chunk 0x4140)

In a standard 3DS file, UV coordinates reside in the `MAPPINGCOORDS` chunk (0x4140). Paul Bourke’s 3DS file format documentation outlines that this chunk stores a vertex count followed by that many (U, V) float pairs ([Paul Bourke](http://paulbourke.net/dataformats/3ds/)).  

The 0x4200 chunk differs significantly:

- **Multiple Channels per Mesh**: Unlike 0x4140 (one-and-done), the 0x4200 chunk can appear multiple times in a mesh, each instance carrying a different UV map. Each chunk begins with an integer channel index to identify which UV layer it represents (e.g. 1 for the base UV set, 2 for a second UV set, etc.). This means a single mesh can have UV1, UV2, etc., each stored in its own 0x4200 chunk.
- **Independent UV Vertices**: The 0x4200 chunk stores its own list of UV coordinates and does not assume a 1:1 correspondence with the mesh’s vertex list. In the original 3DS scheme, texture coordinates are essentially parallel to the vertex list (and if a vertex needed two different UV positions on different faces, the old format often duplicated that vertex). In contrast, the I3D format decouples them: each UV map has its own UV vertex list and faces refer to those UV vertices by index.
- **Face Mapping Indices**: Along with UV coordinates, each 0x4200 chunk contains a face-UV index list. This is analogous to the regular face index list (`FACE_ARRAY` 0x4120), but for UVs. Each face of the mesh has three indices referencing the UV coordinate list (one index per triangle corner).

#### No 0x4140 in I3D

Because I3D uses the new chunk, you’ll often not find a 0x4140 chunk at all in those files. The primary UV map is stored as a 0x4200 chunk (usually with channel index 1) instead.

### Byte-Level Structure of the 0x4200 Chunk

Each `FACE_MAP_CHANNEL` chunk follows a specific binary layout (after the standard 6-byte 3DS chunk header consisting of the ID 0x4200 and length). In byte-level terms, the content of the chunk is organized as follows:

| Offset (bytes) | Data Type  | Description |
| -------------- | ---------- | ----------- |
| 0x0            | int32      | UV channel index (identifies which UV set this is) |
| 0x4            | uint16     | Number of UV vertices (N) in this channel |
| 0x6            | float × 2 × N | List of N UV coordinate pairs (each entry = 2 floats: U and V) |
| ...            |            | ... |
| ...            | uint16     | Number of faces (M) – should match the mesh’s face count |
| ...            | uint16 × 3 × M | UV face index list: M entries, each 3 indices (one per face corner) |

For example:  
- Bytes `01 00 00 00` → `channel index = 1`  
- Bytes `0A 00` → `N = 10` UV vertices, followed by 10 × (U, V) floats (80 bytes)  
- Next `uint16 M = 32` → 32 faces, followed by 32 × 3 × 2 bytes of UV indices.

## Why 0x4200 Was Introduced: Hidden & Dangerous

Illusion Softworks introduced FACE_MAP_CHANNEL in *Hidden & Dangerous* to overcome the single-UV limitation of 3DS. The chunk allows UV coordinates stored “with [an] ID, x position, y position” per map, instead of being tied per face ([hidden-and-dangerous.net](https://hidden-and-dangerous.net/board/viewtopic.php?t=43851)).

## Blender Import Issues

Most modern importers—including Blender's default 3DS importer—don’t recognize 0x4200. One user noted issues preserving UV maps when importing I3D files into Blender ([hidden-and-dangerous.net](https://hidden-and-dangerous.net/board/viewtopic.php?t=43851)).

## Workarounds and Tools

- **Use the original 3ds Max I3D plugin:** Supports 0x4200 (for Max 3.0/3.1) ([hidden-and-dangerous.net](https://hidden-and-dangerous.net/board/viewtopic.php?p=15301#p15301)).  
- **Custom scripts/tools:** Parse 0x4200 chunks manually using the structure described above.

## Conclusion

The I3D 0x4200 `FACE_MAP_CHANNEL` chunk enables multi-UV support in *Hidden & Dangerous* model files by embedding separate UV coordinate lists and per-face indices per channel. Understanding its structure is essential for accurate importing, exporting, or editing of these files.

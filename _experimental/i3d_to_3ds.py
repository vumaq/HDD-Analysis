#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
I3D → 3DS Converter (focus on moving UVs 0x4200 → 0x4140)
---------------------------------------------------------
- Reads Illusion-style I3D (3DS-flavored) files.
- Writes a classic .3DS that stores UVs in 0x4140 (MAPPINGCOORDS).
- If the source has 0x4200 FACE_MAP_CHANNEL (UVs + per-face vt indices),
  this script reconstructs a standard 3DS vertex/UV layout. When a vertex
  is referenced with *different* UVs by different faces, we "unweld"
  (duplicate) the vertex so that each vertex has one canonical UV, as
  required by 3DS 0x4140.

What’s preserved:
- Vertices, faces, per-material face groups (0x4130), smoothing masks (0x4150)
- Materials (name + tex map name via 0xA200→0xA300, plus tiling/blur if present)
- Object name
- Optional OBJECT_TRANS_MATRIX (0x4160)

Assumptions:
- Standard chunk tree: PRIMARY→OBJECTINFO→(MATERIAL*)→OBJECT(s)→OBJECT_MESH→…
- Multi-object is supported; each OBJECT’s first/only mesh is converted.
- If no 0x4200 is found, any 0x4140 already present is passed through.

Usage:
    python i3d_to_3ds.py input.i3d [-o output.3ds] [--channel 1]

Note:
- If your I3D contains multiple 0x4200 channels, use --channel to choose which
  to convert (default 1). If the chosen channel is absent, we fall back to any
  available channel, else pass through existing 0x4140 if present.
"""

import sys
import struct
import argparse
from io import BytesIO
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from collections import defaultdict

# --------- Chunk IDs (3DS / I3D flavored) ------------------------------------
PRIMARY                 = 0x4D4D
M3D_VERSION             = 0x0002
OBJECTINFO              = 0x3D3D
EDIT_CONFIG             = 0x3D3E

MATERIAL                = 0xAFFF
MAT_NAME                = 0xA000
MAT_TEXMAP              = 0xA200
MAT_TEX_NAME            = 0xA300
MAT_MAP_TILING          = 0xA351
MAT_MAP_TEXBLUR         = 0xA353
MAT_AMBIENT             = 0xA010
MAT_DIFFUSE             = 0xA020
MAT_SPECULAR            = 0xA030
MAT_SHININESS           = 0xA040
MAT_SHIN2PCT            = 0xA041
MAT_TRANSPARENCY        = 0xA050
MAT_XPFALL              = 0xA052
MAT_REFBLUR             = 0xA053
MAT_SELF_ILPCT          = 0xA084
MAT_TRANS_FALLOFF_IN    = 0xA08A
MAT_SOFTEN              = 0xA08C
MAT_WIRESIZE            = 0xA087
MAT_SHADING             = 0xA100

OBJECT                  = 0x4000
OBJECT_MESH             = 0x4100
POINT_ARRAY             = 0x4110
OBJECT_FACES            = 0x4120
OBJECT_MATERIAL         = 0x4130
OBJECT_UV_PRIMARY       = 0x4140
OBJECT_SMOOTH           = 0x4150
OBJECT_TRANS_MATRIX     = 0x4160
FACE_MAP_CHANNEL        = 0x4200

PERCENT_I               = 0x0030

# --------- I/O helpers --------------------------------------------------------
def read_chunk(f):
    hdr = f.read(6)
    if len(hdr) < 6:
        return None
    cid, length = struct.unpack("<HI", hdr)
    return cid, length, f.tell() + (length - 6)

def read_u16(f): return struct.unpack("<H", f.read(2))[0]
def read_u32(f): return struct.unpack("<I", f.read(4))[0]
def read_f32(f): return struct.unpack("<f", f.read(4))[0]

def read_cstr(f) -> str:
    out = bytearray()
    while True:
        b = f.read(1)
        if not b or b == b"\x00":
            break
        out.extend(b)
    return out.decode("ascii", errors="replace")

def write_chunk(cid: int, payload: bytes) -> bytes:
    return struct.pack("<HI", cid, 6 + len(payload)) + payload

class ChunkBuilder:
    def __init__(self, cid: int):
        self.cid = cid
        self.buf = BytesIO()
    def add(self, payload: bytes):
        self.buf.write(payload)
    def add_chunk(self, cid: int, payload: bytes):
        self.buf.write(write_chunk(cid, payload))
    def finalize(self) -> bytes:
        body = self.buf.getvalue()
        return write_chunk(self.cid, body)

def write_cstr(s: str) -> bytes:
    return (s or "").encode("ascii", errors="replace") + b"\x00"

# --------- Data models --------------------------------------------------------
class Mesh:
    def __init__(self):
        self.name: str = "Object"
        self.vertices: List[Tuple[float,float,float]] = []
        self.faces: List[Tuple[int,int,int]] = []
        self.face_flags: List[int] = []
        self.mat_faces: Dict[str, List[int]] = defaultdict(list)
        self.smooth_masks: List[int] = []
        self.trans_matrix: Optional[bytes] = None  # raw 0x4160 payload
        # UVs: either from 0x4140 (simple list aligned to vertices)
        # or from 0x4200 (uv list + per-face vt indices)
        self.uvs_4140: List[Tuple[float,float]] = []
        # For 4200:
        self.fmc_channels: Dict[int, Dict[str, object]] = {}  # channel -> {"uvs": [(u,v)], "uv_tris": [(i,j,k)]}

class Doc:
    def __init__(self):
        self.materials: Dict[str, Dict[str, Optional[str]]] = {}  # name -> {map_Kd, tiling, tex_blur}
        self.objects: List[Mesh] = []
        self.mesh_version: Optional[int] = None

# --------- Parser (I3D) -------------------------------------------------------
def parse_i3d(path: str) -> Doc:
    doc = Doc()
    with open(path, "rb") as f:
        while True:
            ch = read_chunk(f)
            if not ch: break
            cid, _ln, e1 = ch
            if cid == PRIMARY:
                _parse_primary(f, e1, doc)
            f.seek(e1)
    return doc

def _parse_primary(f, endpos, doc: Doc):
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _ln, e2 = ch
        if cid == OBJECTINFO:
            _parse_objectinfo(f, e2, doc)
        elif cid == M3D_VERSION:
            _ = f.read(4)  # not used for writing back
        f.seek(e2)

def _parse_objectinfo(f, endpos, doc: Doc):
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _ln, e2 = ch
        if cid == EDIT_CONFIG and (e2 - f.tell()) >= 4:
            doc.mesh_version = read_u32(f)
        elif cid == MATERIAL:
            _parse_material(f, e2, doc)
        elif cid == OBJECT:
            mesh = Mesh()
            mesh.name = read_cstr(f) or mesh.name
            _parse_object(f, e2, mesh)
            doc.objects.append(mesh)
        f.seek(e2)

def _parse_material(f, endpos, doc: Doc):
    name = None
    tex = None
    tiling = None
    blur = None
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _ln, e2 = ch
        if cid == MAT_NAME:
            name = read_cstr(f)
        elif cid == MAT_TEXMAP:
            # Nested texture info
            while f.tell() < e2:
                ch2 = read_chunk(f)
                if not ch2: break
                cid2, _l2, e3 = ch2
                if cid2 == PERCENT_I:
                    _ = read_u16(f)  # map amount
                elif cid2 == MAT_TEX_NAME:
                    tex = read_cstr(f)
                elif cid2 == MAT_MAP_TILING and (e3 - f.tell()) >= 2:
                    tiling = read_u16(f)
                elif cid2 == MAT_MAP_TEXBLUR and (e3 - f.tell()) >= 4:
                    blur = read_f32(f)
                f.seek(e3)
        f.seek(e2)
    if name:
        doc.materials[name] = {
            "map_Kd": Path(tex).name if tex else None,
            "tiling": tiling,
            "tex_blur": blur
        }

def _parse_object(f, endpos, mesh: Mesh):
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _ln, e2 = ch
        if cid == OBJECT_MESH:
            _parse_mesh(f, e2, mesh)
        f.seek(e2)

def _parse_mesh(f, endpos, mesh: Mesh):
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _ln, e2 = ch
        if cid == POINT_ARRAY:
            n = read_u16(f)
            mesh.vertices = [struct.unpack("<3f", f.read(12)) for _ in range(n)]
        elif cid == OBJECT_FACES:
            _parse_faces_block(f, e2, mesh)
        elif cid == OBJECT_UV_PRIMARY:
            n = read_u16(f)
            mesh.uvs_4140 = [struct.unpack("<2f", f.read(8)) for _ in range(n)]
        elif cid == OBJECT_SMOOTH:
            cnt = max(0, (e2 - f.tell()) // 4)
            mesh.smooth_masks = [struct.unpack("<I", f.read(4))[0] for _ in range(cnt)]
        elif cid == OBJECT_TRANS_MATRIX:
            mesh.trans_matrix = f.read(e2 - f.tell())
        elif cid == FACE_MAP_CHANNEL:
            _parse_face_map_channel(f, e2, mesh)
        f.seek(e2)

def _parse_faces_block(f, endpos, mesh: Mesh):
    face_count = read_u16(f)
    faces = []
    flags = []
    for _ in range(face_count):
        a,b,c = struct.unpack("<3H", f.read(6))
        fl = read_u16(f)
        faces.append((a,b,c))
        flags.append(fl)
    mesh.faces = faces
    mesh.face_flags = flags
    # material groups nested
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _ln, e2 = ch
        if cid == OBJECT_MATERIAL:
            mname = read_cstr(f)
            n = read_u16(f)
            idxs = [read_u16(f) for _ in range(n)]
            mesh.mat_faces[mname].extend(idxs)
        f.seek(e2)

def _parse_face_map_channel(f, endpos, mesh: Mesh):
    # layout: u32 channel, u16 uv_count, (u,v)*, u16 face_count, (iu,iv,iw)*
    ch_idx = read_u32(f)
    uv_count = read_u16(f)
    uvs = [struct.unpack("<2f", f.read(8)) for _ in range(uv_count)]
    tri_count = read_u16(f)
    uv_tris = [struct.unpack("<3H", f.read(6)) for _ in range(tri_count)]
    mesh.fmc_channels[ch_idx] = {"uvs": uvs, "uv_tris": uv_tris}

# --------- Geometry utilities -------------------------------------------------
def rebuild_vertex_layout_for_3ds(vertices: List[Tuple[float,float,float]],
                                  faces: List[Tuple[int,int,int]],
                                  uv_from_fmc: List[Tuple[float,float]],
                                  uv_tris: List[Tuple[int,int,int]]):
    """
    Convert (per-face UV indices) → (per-vertex UV array).
    3DS requires 0x4140: count == len(vertices) and UV[i] is the texcoord
    for vertex i. When a vertex is used with multiple UVs across faces,
    we must duplicate that vertex and update faces accordingly.

    Returns:
      new_vertices, new_faces, new_uvs4140
    """
    # Build mapping (vertex_index, uv) -> new_vertex_index
    new_vertices: List[Tuple[float,float,float]] = []
    new_uvs: List[Tuple[float,float]] = []
    remap: Dict[Tuple[int,Tuple[float,float]], int] = {}

    def put(v_idx: int, uv: Tuple[float,float]) -> int:
        key = (v_idx, (round(uv[0], 8), round(uv[1], 8)))  # stabilize float keys
        if key in remap:
            return remap[key]
        new_index = len(new_vertices)
        new_vertices.append(vertices[v_idx])
        new_uvs.append(uv)
        remap[key] = new_index
        return new_index

    # Remap faces
    new_faces: List[Tuple[int,int,int]] = []
    for (a,b,c), (ua,ub,uc) in zip(faces, uv_tris):
        ia = put(a, uv_from_fmc[ua])
        ib = put(b, uv_from_fmc[ub])
        ic = put(c, uv_from_fmc[uc])
        new_faces.append((ia, ib, ic))

    return new_vertices, new_faces, new_uvs

# --------- Writer (3DS classic layout) ----------------------------------------
def emit_point_array(verts: List[Tuple[float,float,float]]) -> bytes:
    out = BytesIO()
    out.write(struct.pack("<H", len(verts)))
    for x,y,z in verts:
        out.write(struct.pack("<3f", float(x), float(y), float(z)))
    return out.getvalue()

def emit_faces_block(faces: List[Tuple[int,int,int]], flags: List[int],
                     mat_faces: Dict[str, List[int]]) -> bytes:
    out = BytesIO()
    out.write(struct.pack("<H", len(faces)))
    for (a,b,c), fl in zip(faces, flags if flags else [0]*len(faces)):
        out.write(struct.pack("<3H", a,b,c))
        out.write(struct.pack("<H", fl))
    # Add material groups
    for mname, idxs in mat_faces.items():
        sub = BytesIO()
        sub.write(write_cstr(mname))
        sub.write(struct.pack("<H", len(idxs)))
        for i in idxs:
            sub.write(struct.pack("<H", i))
        out.write(write_chunk(OBJECT_MATERIAL, sub.getvalue()))
    return out.getvalue()

def emit_uv_chunk_4140(uvs: List[Tuple[float,float]]) -> bytes:
    out = BytesIO()
    out.write(struct.pack("<H", len(uvs)))
    for u,v in uvs:
        out.write(struct.pack("<2f", float(u), float(v)))
    return out.getvalue()

def emit_smoothing_block(smooth_masks: List[int]) -> bytes:
    out = BytesIO()
    for m in smooth_masks:
        out.write(struct.pack("<I", int(m)))
    return out.getvalue()

def emit_material_block(name: str, meta: Dict[str, Optional[str]]) -> bytes:
    cb = ChunkBuilder(MATERIAL)
    cb.add_chunk(MAT_NAME, write_cstr(name))
    if meta.get("map_Kd") is not None:
        a200 = ChunkBuilder(MAT_TEXMAP)
        a200.add_chunk(PERCENT_I, struct.pack("<H", 100))  # amount 100%
        a200.add_chunk(MAT_TEX_NAME, write_cstr(meta["map_Kd"]))
        if meta.get("tiling") is not None:
            a200.add_chunk(MAT_MAP_TILING, struct.pack("<H", meta["tiling"]))
        if meta.get("tex_blur") is not None:
            a200.add_chunk(MAT_MAP_TEXBLUR, struct.pack("<f", float(meta["tex_blur"])))
        cb.add(a200.finalize())
    return cb.finalize()

def compose_3ds(doc: Doc, *, prefer_channel: int = 1) -> bytes:
    # OBJECTINFO subtree
    info_cb = ChunkBuilder(OBJECTINFO)
    # Preserve an EDIT_CONFIG equivalent? Classic 3DS doesn't require it, but harmless to include if present.
    if doc.mesh_version is not None:
        info_cb.add_chunk(EDIT_CONFIG, struct.pack("<I", int(doc.mesh_version)))
    # Materials
    for name, meta in doc.materials.items():
        info_cb.add(emit_material_block(name, meta))

    # Objects
    for mesh in doc.objects:
        # Decide UV source: prefer requested 4200 channel, else any 4200, else pass-through 4140
        uvs_4140: List[Tuple[float,float]] = []
        verts = mesh.vertices[:]
        faces = mesh.faces[:]
        flags = mesh.face_flags[:]

        fmc = None
        if prefer_channel in mesh.fmc_channels:
            fmc = mesh.fmc_channels[prefer_channel]
        elif mesh.fmc_channels:
            # pick any available (lowest channel)
            ch = sorted(mesh.fmc_channels.keys())[0]
            fmc = mesh.fmc_channels[ch]

        if fmc:
            # Need to ensure per-vertex UV layout; may require vertex splitting
            verts2, faces2, uvs2 = rebuild_vertex_layout_for_3ds(verts, faces, fmc["uvs"], fmc["uv_tris"])
            # When vertices are duplicated, flags must match new faces length
            if len(faces2) != len(flags):
                # If flags exist, replicate by re-indexing faces one-to-one order
                # (faces order preserved by rebuild)
                if flags:
                    if len(flags) == len(faces):
                        flags = flags[:]  # keep same count; one-to-one mapping preserved
                    else:
                        flags = [0]*len(faces2)
            verts = verts2
            faces = faces2
            uvs_4140 = uvs2
        elif mesh.uvs_4140:
            # Already suitable
            uvs_4140 = mesh.uvs_4140
            # 3DS expects len(uvs) == len(verts); if mismatch, fallback to rebuild style
            if len(uvs_4140) != len(verts):
                verts2, faces2, uvs2 = rebuild_vertex_layout_for_3ds(
                    verts, faces, uvs_4140, [(a,b,c) for (a,b,c) in faces]
                )
                verts, faces, uvs_4140 = verts2, faces2, uvs2

        # OBJECT_MESH subtree
        mesh_cb = ChunkBuilder(OBJECT_MESH)
        mesh_cb.add_chunk(POINT_ARRAY, emit_point_array(verts))
        if mesh.trans_matrix:
            mesh_cb.add_chunk(OBJECT_TRANS_MATRIX, mesh.trans_matrix)
        mesh_cb.add_chunk(OBJECT_FACES, emit_faces_block(faces, flags, mesh.mat_faces))
        if mesh.smooth_masks:
            mesh_cb.add_chunk(OBJECT_SMOOTH, emit_smoothing_block(mesh.smooth_masks))
        if uvs_4140:
            mesh_cb.add_chunk(OBJECT_UV_PRIMARY, emit_uv_chunk_4140(uvs_4140))

        # OBJECT: name + mesh
        obj_payload = BytesIO()
        obj_payload.write(write_cstr(mesh.name))
        obj_payload.write(mesh_cb.finalize())
        info_cb.add(write_chunk(OBJECT, obj_payload.getvalue()))

    # PRIMARY root
    root_cb = ChunkBuilder(PRIMARY)
    # put a conventional version; 3 is seen in many I3D samples
    root_cb.add_chunk(M3D_VERSION, struct.pack("<I", 3))
    root_cb.add(info_cb.finalize())
    return root_cb.finalize()

# --------- CLI ----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Convert I3D → classic 3DS (move 0x4200 UVs into 0x4140).")
    ap.add_argument("input", help="Path to input .i3d")
    ap.add_argument("-o", "--output", help="Path to output .3ds (default: alongside source)")
    ap.add_argument("--channel", type=int, default=1, help="Preferred FACE_MAP_CHANNEL index (default: 1)")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"ERROR: not found: {src}")
        sys.exit(2)
    out_path = Path(args.output) if args.output else src.with_suffix(".3ds")

    print(f"[I3D] Loading: {src}")
    doc = parse_i3d(str(src))
    print(f"[INFO] Objects: {len(doc.objects)}, Materials: {len(doc.materials)}, MeshVersion: {doc.mesh_version}")
    for i, m in enumerate(doc.objects):
        has4200 = ", ".join(str(ch) for ch in sorted(m.fmc_channels.keys())) if m.fmc_channels else "none"
        print(f"  - Mesh[{i}] '{m.name}': verts={len(m.vertices)}, faces={len(m.faces)}, 0x4200 channels={has4200}, 0x4140={len(m.uvs_4140)}")

    blob = compose_3ds(doc, prefer_channel=args.channel)
    with open(out_path, "wb") as f:
        f.write(blob)
    print(f"[OK] Wrote 3DS: {out_path} ({len(blob)} bytes)")

if __name__ == "__main__":
    main()

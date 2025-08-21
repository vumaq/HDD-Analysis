#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
i3d_to_3ds.py — I3D → 3DS with correct UVs for 3ds Max
-----------------------------------------------------
- Parses I3D (3DS-derived) including Illusion's FACE_MAP_CHANNEL (0x4200).
- ALWAYS expands vertices at UV seams so standard 3DS expects:
    len(POINT_ARRAY) == len(OBJECT_UV) and 0x4140 exists.
- Emits OBJECT_UV (0x4140) before OBJECT_FACES (0x4120).
- Does NOT emit 0x4200 in the .3ds output.

Usage:
    python i3d_to_3ds.py input.i3d -o output.3ds [--bake-xform]

Notes:
- Materials: emits MAT_TEXMAP/A300 when available and links faces via 0x4130.
- COLOR chunks conform to spec (MAT_DIFFUSE contains COLOR_24).
"""

import sys
import struct
import argparse
from pathlib import Path
from typing import List, Tuple, Dict, Optional

# ---------- Chunk IDs ----------
PRIMARY                 = 0x4D4D
M3D_VERSION             = 0x0002

OBJECTINFO              = 0x3D3D

MATERIAL                = 0xAFFF
MAT_NAME                = 0xA000
MAT_TEXMAP              = 0xA200
MAT_MAP_FILEPATH        = 0xA300
MAT_DIFFUSE             = 0xA020
COLOR_24                = 0x0011

OBJECT                  = 0x4000
OBJECT_MESH             = 0x4100
POINT_ARRAY             = 0x4110
OBJECT_FACES            = 0x4120
OBJECT_MATERIAL         = 0x4130
OBJECT_UV               = 0x4140
OBJECT_SMOOTH           = 0x4150
OBJECT_TRANS_MATRIX     = 0x4160

# Illusion extension in I3D
FACE_MAP_CHANNEL        = 0x4200  # input only

KFDATA                  = 0xB000

# ---------- Helpers ----------
def read_chunk(f):
    hdr = f.read(6)
    if len(hdr) < 6:
        return None
    cid, ln = struct.unpack("<HI", hdr)
    return cid, ln

def read_cstr(f) -> str:
    bs = bytearray()
    while True:
        b = f.read(1)
        if not b or b == b"\x00":
            break
        bs += b
    try:
        return bs.decode("ascii", errors="replace")
    except Exception:
        return bs.decode("latin1", errors="replace")

def maybe_nested(f, region_end) -> bool:
    pos = f.tell()
    if region_end - pos < 6:
        return False
    peek = f.read(6); f.seek(pos)
    if len(peek) < 6:
        return False
    _cid, ln = struct.unpack("<HI", peek)
    return ln >= 6 and pos + ln <= region_end

# ---------- Data ----------
class Mesh:
    def __init__(self, name: str):
        self.name = name
        self.vertices: List[Tuple[float,float,float]] = []
        self.faces: List[Tuple[int,int,int]] = []
        self.face_flags: List[int] = []
        self.smooth_masks: List[int] = []
        self.trans_matrix: Optional[bytes] = None
        self.uv_primary: List[Tuple[float,float]] = []  # 0x4140 if present
        # FMC: channel -> {'uvs': [(u,v)...], 'uvfaces': [(ua,ub,uc)...]}
        self.fmc_channels: Dict[int, Dict[str, list]] = {}
        # material assignment: name -> list of face indices
        self.mat_faces: Dict[str, List[int]] = {}

class Doc:
    def __init__(self):
        self.materials: Dict[str, Dict[str, Optional[str]]] = {}
        self.meshes: List[Mesh] = []
        self.kfdata_blobs: List[bytes] = []

# ---------- Parse I3D ----------
def parse_i3d(path: Path) -> Doc:
    doc = Doc()
    with path.open("rb") as f:
        cid_ln = read_chunk(f)
        if not cid_ln or cid_ln[0] != PRIMARY:
            raise ValueError("Not a 3DS/I3D file (missing PRIMARY).")
        prim_end = f.tell() - 6 + cid_ln[1]
        while f.tell() < prim_end:
            at = f.tell()
            ch = read_chunk(f)
            if not ch: break
            cid, ln = ch
            cend = at + ln
            if cid == M3D_VERSION:
                _ver = struct.unpack("<I", f.read(4))[0]
            elif cid == OBJECTINFO:
                parse_objectinfo(f, cend, doc)
            elif cid == KFDATA:
                f.seek(at); blob = f.read(ln); doc.kfdata_blobs.append(blob); f.seek(cend)
            else:
                f.seek(cend)
    return doc

def parse_objectinfo(f, endpos: int, doc: Doc):
    while f.tell() < endpos:
        at = f.tell()
        ch = read_chunk(f)
        if not ch: break
        cid, ln = ch
        cend = at + ln
        if cid == MATERIAL:
            parse_material(f, cend, doc)
        elif cid == OBJECT:
            name = read_cstr(f)
            mesh = Mesh(name or "Object")
            parse_object(f, cend, mesh)
            doc.meshes.append(mesh)
        else:
            f.seek(cend)

def parse_material(f, endpos: int, doc: Doc):
    name = None
    filepath = None
    while f.tell() < endpos:
        at = f.tell()
        ch = read_chunk(f)
        if not ch: break
        cid, ln = ch
        cend = at + ln
        if cid == MAT_NAME:
            name = read_cstr(f)
        elif cid == MAT_TEXMAP:
            while f.tell() < cend:
                sat = f.tell()
                sub = read_chunk(f)
                if not sub: break
                scid, sln = sub
                send = sat + sln
                if scid == MAT_MAP_FILEPATH:
                    filepath = read_cstr(f)
                f.seek(send)
        else:
            f.seek(cend)
    if name:
        doc.materials[name] = {"filepath": filepath}

def parse_object(f, endpos: int, mesh: Mesh):
    while f.tell() < endpos:
        at = f.tell()
        ch = read_chunk(f)
        if not ch: break
        cid, ln = ch
        cend = at + ln
        if cid == OBJECT_MESH:
            parse_object_mesh(f, cend, mesh)
        else:
            f.seek(cend)

def parse_object_mesh(f, endpos: int, mesh: Mesh):
    while f.tell() < endpos:
        at = f.tell()
        ch = read_chunk(f)
        if not ch: break
        cid, ln = ch
        cend = at + ln
        if cid == POINT_ARRAY:
            n = struct.unpack("<H", f.read(2))[0]
            mesh.vertices = [struct.unpack("<fff", f.read(12)) for _ in range(n)]
        elif cid == OBJECT_FACES:
            n = struct.unpack("<H", f.read(2))[0]
            mesh.faces = []
            mesh.face_flags = []
            for _ in range(n):
                a,b,c,flag = struct.unpack("<HHHH", f.read(8))
                mesh.faces.append((a,b,c))
                mesh.face_flags.append(flag)
            while f.tell() < cend:
                sat = f.tell()
                sub = read_chunk(f)
                if not sub: break
                scid, sln = sub
                send = sat + sln
                if scid == OBJECT_SMOOTH:
                    cnt = len(mesh.faces)
                    mesh.smooth_masks = list(struct.unpack("<" + "I"*cnt, f.read(4*cnt)))
                elif scid == OBJECT_MATERIAL:
                    mname = read_cstr(f)
                    cnt = struct.unpack("<H", f.read(2))[0]
                    idxs = list(struct.unpack("<" + "H"*cnt, f.read(2*cnt)))
                    mesh.mat_faces.setdefault(mname, []).extend(idxs)
                else:
                    f.seek(send)
        elif cid == OBJECT_UV:
            n = struct.unpack("<H", f.read(2))[0]
            mesh.uv_primary = [struct.unpack("<ff", f.read(8)) for _ in range(n)]
        elif cid == OBJECT_TRANS_MATRIX:
            mesh.trans_matrix = f.read(48)
        elif cid == FACE_MAP_CHANNEL:
            parse_fmc(f, cend, mesh)
        else:
            f.seek(cend)

def parse_fmc(f, endpos: int, mesh: Mesh):
    """
    Layout (per spec):
        int32  channel
        uint16 uv_count
        (float u, float v) * uv_count
        uint16 face_count
        (uint16 ua, uint16 ub, uint16 uc) * face_count
    """
    try:
        channel = struct.unpack("<i", f.read(4))[0]
        uv_count = struct.unpack("<H", f.read(2))[0]
        uvs = [struct.unpack("<ff", f.read(8)) for _ in range(uv_count)]
        face_count = struct.unpack("<H", f.read(2))[0]
        uvfaces = [struct.unpack("<HHH", f.read(6)) for _ in range(face_count)]
        mesh.fmc_channels[channel] = {"uvs": uvs, "uvfaces": uvfaces}
    except Exception:
        pass
    f.seek(endpos)

# ---------- Math ----------
def apply_matrix_to_vertices(vertices: List[Tuple[float,float,float]], m: bytes) -> List[Tuple[float,float,float]]:
    vals = list(struct.unpack("<12f", m))
    M = [vals[0:4], vals[4:8], vals[8:12]]
    out = []
    for x,y,z in vertices:
        X = M[0][0]*x + M[0][1]*y + M[0][2]*z + M[0][3]
        Y = M[1][0]*x + M[1][1]*y + M[1][2]*z + M[1][3]
        Z = M[2][0]*x + M[2][1]*y + M[2][2]*z + M[2][3]
        out.append((X,Y,Z))
    return out

# ---------- Rebuild (ALWAYS expand at UV seams) ----------
def expand_vertices_with_fmc(mesh: Mesh) -> Tuple[List[Tuple[float,float,float]], List[Tuple[float,float]], List[Tuple[int,int,int]]]:
    """
    Build vertex+uv arrays so len(verts_out) == len(uvs_out) and faces index verts_out.
    Prefers FMC channel 1 if present; otherwise any channel; otherwise falls back to existing 0x4140.
    """
    # Choose FMC channel (prefer 1)
    channel = None
    if mesh.fmc_channels:
        channel = 1 if 1 in mesh.fmc_channels else sorted(mesh.fmc_channels.keys())[0]

    if channel is not None:
        data = mesh.fmc_channels[channel]
        uvs = data["uvs"]
        uvfaces = data["uvfaces"]
        if len(uvfaces) != len(mesh.faces):
            # malformed: fall back
            return mesh.vertices, (mesh.uv_primary or []), mesh.faces

        key2idx: Dict[Tuple[int,int], int] = {}
        new_vtx: List[Tuple[float,float,float]] = []
        new_uvs: List[Tuple[float,float]] = []
        new_faces: List[Tuple[int,int,int]] = []

        def ensure_idx(pos_idx: int, uv_idx: int) -> int:
            k = (pos_idx, uv_idx)
            idx = key2idx.get(k)
            if idx is not None:
                return idx
            vx, vy, vz = mesh.vertices[pos_idx] if 0 <= pos_idx < len(mesh.vertices) else (0.0,0.0,0.0)
            u, v = uvs[uv_idx] if 0 <= uv_idx < len(uvs) else (0.0, 0.0)
            idx = len(new_vtx)
            new_vtx.append((vx,vy,vz))
            new_uvs.append((u,v))
            key2idx[k] = idx
            return idx

        for fi, (a,b,c) in enumerate(mesh.faces):
            ua, ub, uc = uvfaces[fi]
            A = ensure_idx(a, ua)
            B = ensure_idx(b, ub)
            C = ensure_idx(c, uc)
            new_faces.append((A,B,C))

        return new_vtx, new_uvs, new_faces

    # No FMC: if primary UVs match vertices, use them; else warn/fallback
    if mesh.uv_primary and len(mesh.uv_primary) == len(mesh.vertices):
        return mesh.vertices, mesh.uv_primary, mesh.faces

    # Fallback: no valid UV source
    return mesh.vertices, [], mesh.faces

# ---------- Emit ----------
class ChunkBuilder:
    def __init__(self, cid: int):
        self.cid = cid
        self.parts: List[bytes] = []
    def add(self, raw: bytes):
        self.parts.append(raw)
    def add_chunk(self, cid: int, payload: bytes):
        ln = 6 + len(payload)
        self.parts.append(struct.pack("<HI", cid, ln) + payload)
    def finalize(self) -> bytes:
        payload = b"".join(self.parts)
        return struct.pack("<HI", self.cid, 6 + len(payload)) + payload

def emit_cstr(s: str) -> bytes:
    return s.encode("ascii", errors="replace") + b"\x00"

def emit_material(name: str, meta: Dict[str, Optional[str]]) -> bytes:
    cb = ChunkBuilder(MATERIAL)
    cb.add_chunk(MAT_NAME, emit_cstr(name))
    # MAT_DIFFUSE with nested COLOR_24
    body = bytes((180,180,180))
    color_chunk = struct.pack("<HI", COLOR_24, 6 + len(body)) + body
    cb.add(struct.pack("<HI", MAT_DIFFUSE, 6 + len(color_chunk)) + color_chunk)
    fp = meta.get("filepath") if meta else None
    if fp:
        tm = ChunkBuilder(MAT_TEXMAP)
        tm.add_chunk(MAT_MAP_FILEPATH, emit_cstr(fp))
        cb.add(tm.finalize())
    return cb.finalize()

def emit_point_array(verts: List[Tuple[float,float,float]]) -> bytes:
    out = [struct.pack("<H", len(verts))]
    for x,y,z in verts:
        out.append(struct.pack("<fff", x, y, z))
    return b"".join(out)

def emit_object_faces(faces: List[Tuple[int,int,int]], face_flags: Optional[List[int]], smooth_masks: Optional[List[int]], mat_faces: Dict[str, List[int]]) -> bytes:
    cb = ChunkBuilder(OBJECT_FACES)
    out = [struct.pack("<H", len(faces))]
    flags = face_flags if face_flags and len(face_flags) == len(faces) else [0]*len(faces)
    for (a,b,c), fl in zip(faces, flags):
        out.append(struct.pack("<HHHH", a, b, c, fl))
    body = b"".join(out)

    if smooth_masks and len(smooth_masks) == len(faces):
        scb = ChunkBuilder(OBJECT_SMOOTH)
        scb.add(struct.pack("<" + "I"*len(faces), *smooth_masks))
        body += scb.finalize()

    for mname, idxs in (mat_faces or {}).items():
        if not idxs: continue
        mcb = ChunkBuilder(OBJECT_MATERIAL)
        mcb.add(emit_cstr(mname))
        mcb.add(struct.pack("<H", len(idxs)))
        mcb.add(struct.pack("<" + "H"*len(idxs), *idxs))
        body += mcb.finalize()

    cb.add(body)
    return cb.finalize()

def emit_object_uv(uvs: List[Tuple[float,float]], expected_count: int) -> bytes:
    assert len(uvs) == expected_count, f"UV count {len(uvs)} must match vertex count {expected_count}"
    out = [struct.pack("<H", len(uvs))]
    for u,v in uvs:
        out.append(struct.pack("<ff", float(u), float(v)))
    return b"".join(out)

def emit_object(mesh: Mesh, bake_xform: bool = False) -> bytes:
    name = mesh.name or "Object"
    cb = ChunkBuilder(OBJECT)
    cb.add(emit_cstr(name))

    # ALWAYS expand using FMC when available
    verts, uvs, faces = expand_vertices_with_fmc(mesh)

    if bake_xform and mesh.trans_matrix:
        verts = apply_matrix_to_vertices(verts, mesh.trans_matrix)

    mb = ChunkBuilder(OBJECT_MESH)
    # Emit in compatible order: POINT_ARRAY -> OBJECT_UV -> OBJECT_FACES -> MATRIX
    mb.add_chunk(POINT_ARRAY, emit_point_array(verts))
    if uvs:
        mb.add_chunk(OBJECT_UV, emit_object_uv(uvs, expected_count=len(verts)))
    else:
        # still emit empty? safer to omit if none
        pass
    mb.add(emit_object_faces(faces, mesh.face_flags, mesh.smooth_masks, mesh.mat_faces))
    if (not bake_xform) and mesh.trans_matrix:
        mb.add_chunk(OBJECT_TRANS_MATRIX, mesh.trans_matrix)

    cb.add(mb.finalize())
    return cb.finalize()

def compose_3ds(doc: Doc, bake_xform: bool = False) -> bytes:
    root = ChunkBuilder(PRIMARY)
    root.add_chunk(M3D_VERSION, struct.pack("<I", 3))

    edit = ChunkBuilder(OBJECTINFO)

    # Materials
    for mname, meta in doc.materials.items():
        edit.add(emit_material(mname, meta))

    # Ensure materials referenced exist
    for mesh in doc.meshes:
        for mname in mesh.mat_faces.keys():
            if mname and mname not in doc.materials:
                doc.materials[mname] = {"filepath": None}
                edit.add(emit_material(mname, {"filepath": None}))

    # Objects
    for mesh in doc.meshes:
        edit.add(emit_object(mesh, bake_xform=bake_xform))

    root.add(edit.finalize())

    for blob in doc.kfdata_blobs:
        root.add(blob)

    return root.finalize()

# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser(description="I3D → 3DS converter with correct 0x4140 UVs (vertex-expanded from 0x4200).")
    ap.add_argument("i3d_file", help="Path to input .i3d")
    ap.add_argument("-o", "--output", help="Path to output .3ds (default: alongside input)")
    ap.add_argument("--bake-xform", action="store_true", help="Bake OBJECT_TRANS_MATRIX (0x4160) into vertices")
    args = ap.parse_args()

    in_path = Path(args.i3d_file)
    if not in_path.exists() or in_path.suffix.lower() != ".i3d":
        print(f"[ERR] Not a valid .i3d: {in_path}")
        sys.exit(2)

    out_path = Path(args.output) if args.output else in_path.with_suffix(".3ds")

    print(f"[I3D] Loading: {in_path}")
    doc = parse_i3d(in_path)
    print(f"[I3D] Meshes: {len(doc.meshes)} | Materials: {len(doc.materials)} | KFDATA: {len(doc.kfdata_blobs)}")

    blob = compose_3ds(doc, bake_xform=args.bake_xform)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(blob)
    print(f"[OK ] Wrote: {out_path.resolve()} ({len(blob)} bytes)")

if __name__ == "__main__":
    main()

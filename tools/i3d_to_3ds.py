#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
I3D -> 3DS converter with:
- FACE_MAP_CHANNEL (0x4200) -> 0x4140 UVs (per-mesh channel selection, --channel N with fallback)
- OBJECT_TRANS_MATRIX (0x4160) preserved or baked into vertex positions (--bake-xform)
- KFDATA (0xB000) animation/keyframer subtree passed through verbatim under PRIMARY
- Materials and MAT_TEXMAP filepath (0xA300) preserved

Usage:
  python i3d_to_3ds.py input.i3d -o output.3ds [--channel 1] [--bake-xform]

Notes:
- Focuses on meshes/materials/keyframer for H&D-style I3D (3DS-derived).
- Defensive parsing; skips unknowns but preserves KFDATA raw.
"""

import os
import sys
import struct
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# -----------------------------
# I3D/3DS Chunk IDs (subset)
# -----------------------------
PRIMARY                 = 0x4D4D
M3D_VERSION             = 0x0002
OBJECTINFO              = 0x3D3D
EDIT_CONFIG             = 0x3D3E

# Materials
MATERIAL                = 0xAFFF
MAT_NAME                = 0xA000
MAT_AMBIENT             = 0xA010
MAT_DIFFUSE             = 0xA020
MAT_SPECULAR            = 0xA030
MAT_SHININESS           = 0xA040
MAT_SHIN2PCT            = 0xA041
MAT_TRANSPARENCY        = 0xA050
MAT_XPFALL              = 0xA052
MAT_REFBLUR             = 0xA053
MAT_SELF_ILPCT          = 0xA084
MAT_WIRESIZE            = 0xA087
MAT_SHADING             = 0xA100
MAT_TEXMAP              = 0xA200
MAT_MAP_FILEPATH        = 0xA300
MAT_MAP_TILING          = 0xA351
MAT_MAP_TEXBLUR         = 0xA353

# Objects / Mesh
OBJECT                  = 0x4000
OBJECT_MESH             = 0x4100
POINT_ARRAY             = 0x4110
VERTEX_OPTIONS          = 0x4111
OBJECT_FACES            = 0x4120
OBJECT_MATERIAL         = 0x4130
OBJECT_UV_PRIMARY       = 0x4140
OBJECT_SMOOTH           = 0x4150
OBJECT_TRANS_MATRIX     = 0x4160
OBJECT_TRI_VISIBLE      = 0x4165
MESH_TEXTURE_INFO       = 0x4170
MESH_COLOR              = 0x4190
FACE_MAP_CHANNEL        = 0x4200

# Lights/Cameras (ignored here)
OBJECT_LIGHT            = 0x4600
OBJECT_CAMERA           = 0x4700

# Keyframer
KFDATA                  = 0xB000
KFHDR                   = 0xB00A
KFCURTIME_RANGE         = 0xB008
KFCURTIME               = 0xB009
OBJECT_NODE_TAG         = 0xB002
CAMERA_NODE_TAG         = 0xB003
TARGET_NODE_TAG         = 0xB004
LIGHT_NODE_TAG          = 0xB005
L_TARGET_NODE_TAG       = 0xB006
SPOTLIGHT_NODE_TAG      = 0xB007
NODE_HDR                = 0xB010
INSTANCE_NAME           = 0xB011
PIVOT                   = 0xB013
BOUNDBOX                = 0xB014
POS_TRACK_TAG           = 0xB020
ROT_TRACK_TAG           = 0xB021
SCL_TRACK_TAG           = 0xB022
NODE_ID                 = 0xB030

# Helper/color/percent
PERCENT_I               = 0x0030
PERCENT_F               = 0x0031
COLOR_FLOAT             = 0x0010
COLOR_24                = 0x0011
LIN_COLOR_24F           = 0x0013

# -----------------------------
# Binary helpers
# -----------------------------
def read_chunk(f):
    """Read chunk header; returns (cid, length, endpos) or None."""
    hdr = f.read(6)
    if len(hdr) < 6:
        return None
    cid, ln = struct.unpack("<HI", hdr)
    return cid, ln, f.tell() - 6 + ln

def read_cstr(f) -> str:
    bs = bytearray()
    while True:
        b = f.read(1)
        if not b or b == b'\x00':
            break
        bs += b
    try:
        return bs.decode("ascii", errors="replace")
    except Exception:
        return bs.decode("latin1", errors="replace")

def read_color_block(f, endpos) -> Optional[Tuple[int,int,int]]:
    pos0 = f.tell()
    inner = read_chunk(f)
    if not inner:
        f.seek(endpos)
        return None
    icid, iln, iend = inner
    if iend > endpos:
        f.seek(endpos)
        return None
    if icid == COLOR_24 and iln >= 9:
        rgb = f.read(3)
        f.seek(iend)
        return tuple(int(b) for b in rgb)
    elif icid in (COLOR_FLOAT, LIN_COLOR_24F) and iln >= 18:
        r, g, b = struct.unpack("<fff", f.read(12))
        f.seek(iend)
        clamp = lambda x: int(max(0, min(255, round(x*255))))
        return (clamp(r), clamp(g), clamp(b))
    f.seek(iend)
    return None

def read_pct_block(f, endpos) -> Optional[float]:
    pos = f.tell()
    inner = read_chunk(f)
    if not inner:
        return None
    icid, iln, iend = inner
    if iend > endpos:
        return None
    if icid == PERCENT_I and iln >= 8:
        (v,) = struct.unpack("<H", f.read(2))
        f.seek(iend)
        return float(v)
    if icid == PERCENT_F and iln >= 10:
        (v,) = struct.unpack("<f", f.read(4))
        f.seek(iend)
        return v * 100.0
    f.seek(iend)
    return None

def maybe_nested(f, region_end) -> bool:
    pos = f.tell()
    if region_end - pos < 6:
        return False
    peek = f.read(6); f.seek(pos)
    if len(peek) < 6:
        return False
    _cid, ln = struct.unpack("<HI", peek)
    return ln >= 6 and pos + ln <= region_end

def read_whole_chunk_at_current(f, endpos) -> bytes:
    """Return header+payload bytes for the current chunk (assumes header already read)."""
    start = f.tell() - 6
    f.seek(start)
    return f.read(endpos - start)

# -----------------------------
# Data model
# -----------------------------
class Mesh:
    def __init__(self, name: str):
        self.name = name
        self.vertices: List[Tuple[float,float,float]] = []
        self.faces: List[Tuple[int,int,int]] = []     # indices
        self.face_flags: List[int] = []               # u16
        self.smooth_masks: List[int] = []             # u32 per face
        self.trans_matrix: Optional[bytes] = None     # raw 48 bytes (12 floats)
        self.mat_faces: Dict[str, List[int]] = {}     # material name => list of face indices
        self.uv_primary: List[Tuple[float,float]] = []  # from 0x4140 if present
        self.fmc_channels: Dict[int, Dict[str, object]] = {}  # channel -> {'uvs':[(u,v)], 'uvfaces':[(a,b,c)]}

class Doc:
    def __init__(self):
        self.materials: Dict[str, Dict[str, Optional[str]]] = {}  # name -> meta dict
        self.objects: List[Mesh] = []
        self.mesh_version: Optional[int] = None
        self.kfdata_blobs: List[bytes] = []  # raw KFDATA chunks

# -----------------------------
# I3D parsing (OBJECTINFO + KFDATA)
# -----------------------------
def parse_i3d(path: Path) -> Doc:
    doc = Doc()
    with path.open("rb") as f:
        size = path.stat().st_size
        def walk_region(endpos):
            while f.tell() < endpos:
                ch = read_chunk(f)
                if not ch:
                    break
                cid, ln, cend = ch
                if cid == OBJECTINFO:
                    parse_objectinfo(f, cend, doc)
                elif cid == EDIT_CONFIG and ln >= 10:
                    # Mesh Version
                    (v,) = struct.unpack("<I", f.read(4))
                    doc.mesh_version = int(v)
                elif cid == M3D_VERSION and ln >= 10:
                    _ = f.read(4)  # ignore
                elif cid == KFDATA:
                    # Pass-through copy of keyframer subtree
                    blob = read_whole_chunk_at_current(f, cend)
                    doc.kfdata_blobs.append(blob)
                else:
                    if maybe_nested(f, cend):
                        walk_region(cend)
                    else:
                        pass
                f.seek(cend)
        walk_region(size)
    return doc

def parse_objectinfo(f, endpos, doc: Doc):
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch:
            break
        cid, ln, cend = ch
        if cid == MATERIAL:
            parse_material(f, cend, doc)
        elif cid == OBJECT:
            parse_object(f, cend, doc)
        else:
            if maybe_nested(f, cend):
                parse_objectinfo(f, cend, doc)
        f.seek(cend)

def parse_material(f, endpos, doc: Doc):
    mat_name = None
    meta: Dict[str, Optional[str]] = {
        "filepath": None, "tiling": None, "texblur": None,
        "ambient": None, "diffuse": None, "specular": None,
        "shininess": None, "shine_strength": None, "transparency": None,
    }
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch:
            break
        cid, ln, cend = ch
        if cid == MAT_NAME:
            mat_name = read_cstr(f)
        elif cid in (MAT_AMBIENT, MAT_DIFFUSE, MAT_SPECULAR):
            rgb = read_color_block(f, cend)
            key = {MAT_AMBIENT:"ambient", MAT_DIFFUSE:"diffuse", MAT_SPECULAR:"specular"}[cid]
            if rgb:
                meta[key] = "#{:02X}{:02X}{:02X}".format(*rgb)
        elif cid in (MAT_SHININESS, MAT_SHIN2PCT, MAT_TRANSPARENCY, MAT_XPFALL, MAT_REFBLUR, MAT_SELF_ILPCT):
            pct = read_pct_block(f, cend)
            key = {
                MAT_SHININESS:"shininess",
                MAT_SHIN2PCT:"shine_strength",
                MAT_TRANSPARENCY:"transparency",
                MAT_XPFALL:"transp_falloff",
                MAT_REFBLUR:"ref_blur",
                MAT_SELF_ILPCT:"self_illum",
            }[cid]
            if pct is not None:
                meta[key] = f"{pct:.3f}"
        elif cid == MAT_TEXMAP:
            # dive
            while f.tell() < cend:
                sch = read_chunk(f)
                if not sch:
                    break
                scid, sln, send = sch
                if scid == MAT_MAP_FILEPATH:
                    meta["filepath"] = read_cstr(f)
                elif scid == MAT_MAP_TILING and sln >= 8:
                    (til,) = struct.unpack("<H", f.read(2))
                    meta["tiling"] = f"0x{til:04X}"
                elif scid == MAT_MAP_TEXBLUR and sln >= 10:
                    (blur,) = struct.unpack("<f", f.read(4))
                    meta["texblur"] = f"{blur:.6g}"
                f.seek(send)
        else:
            if maybe_nested(f, cend):
                # ignore subtrees we don't need
                pass
        f.seek(cend)
    if mat_name:
        doc.materials[mat_name] = meta

def parse_object(f, endpos, doc: Doc):
    name = read_cstr(f)
    mesh = Mesh(name or "Object")
    # parse mesh subtree
    if f.tell() < endpos:
        parse_object_mesh(f, endpos, mesh)
    doc.objects.append(mesh)

def parse_object_mesh(f, endpos, mesh: Mesh):
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch:
            break
        cid, ln, cend = ch

        if cid == OBJECT_MESH:
            # nested content
            parse_object_mesh(f, cend, mesh)

        elif cid == POINT_ARRAY and ln >= 8:
            (vcount,) = struct.unpack("<H", f.read(2))
            verts = []
            have = max(0, cend - f.tell())
            read_cnt = min(vcount, have // 12)
            for _ in range(read_cnt):
                x, y, z = struct.unpack("<fff", f.read(12))
                verts.append((x, y, z))
            mesh.vertices.extend(verts)

        elif cid == OBJECT_FACES and ln >= 8:
            (num_faces,) = struct.unpack("<H", f.read(2))
            faces, flags = [], []
            have = max(0, cend - f.tell())
            read_cnt = min(num_faces, have // 8)
            for _ in range(read_cnt):
                a,b,c,fl = struct.unpack("<HHHH", f.read(8))
                faces.append((a,b,c))
                flags.append(fl)
            mesh.faces.extend(faces)
            mesh.face_flags.extend(flags)
            # subchunks: materials / smoothing may follow
            while f.tell() < cend:
                sch = read_chunk(f)
                if not sch:
                    break
                scid, sln, send = sch
                if scid == OBJECT_MATERIAL:
                    mname = read_cstr(f)
                    cnt = 0
                    if f.tell() + 2 <= send:
                        (cnt,) = struct.unpack("<H", f.read(2))
                    idxs = []
                    have2 = max(0, send - f.tell())
                    read2 = min(cnt, have2 // 2)
                    for _ in range(read2):
                        (fi,) = struct.unpack("<H", f.read(2))
                        idxs.append(fi)
                    mesh.mat_faces.setdefault(mname, []).extend(idxs)
                elif scid == OBJECT_SMOOTH and sln > 6:
                    # u32 per face
                    n = max(0, (send - f.tell()) // 4)
                    for _ in range(n):
                        (mask,) = struct.unpack("<I", f.read(4))
                        mesh.smooth_masks.append(mask)
                f.seek(send)

        elif cid == OBJECT_UV_PRIMARY and ln >= 8:
            (uvcount,) = struct.unpack("<H", f.read(2))
            have = max(0, cend - f.tell())
            read_cnt = min(uvcount, have // 8)
            for _ in range(read_cnt):
                u, v = struct.unpack("<ff", f.read(8))
                mesh.uv_primary.append((u, v))

        elif cid == OBJECT_TRANS_MATRIX and ln >= (6+48):
            mesh.trans_matrix = f.read(48)

        elif cid == FACE_MAP_CHANNEL and ln >= 12:
            # read channel index, uv count, uvs, face count, uv faces (a,b,c)
            if f.tell() + 6 <= cend:
                channel, uvcount = struct.unpack("<I H", f.read(6))
            else:
                f.seek(cend); continue
            # uvs
            uvs = []
            need = uvcount * 8
            if f.tell() + need <= cend:
                for _ in range(uvcount):
                    u, v = struct.unpack("<ff", f.read(8))
                    uvs.append((u, v))
            else:
                f.seek(cend); continue
            # face mapping indices
            if f.tell() + 2 <= cend:
                (fcnt,) = struct.unpack("<H", f.read(2))
            else:
                fcnt = 0
            uvfaces = []
            need2 = fcnt * 6
            if f.tell() + need2 <= cend:
                for _ in range(fcnt):
                    a,b,c = struct.unpack("<HHH", f.read(6))
                    uvfaces.append((a,b,c))
            # store
            mesh.fmc_channels[channel] = {"uvs": uvs, "uvfaces": uvfaces}

        else:
            # swallow unknown or container
            pass

        f.seek(cend)

# -----------------------------
# 3DS emit helpers
# -----------------------------
class ChunkBuilder:
    def __init__(self, cid: int):
        self.cid = cid
        self.parts: List[bytes] = []

    def add(self, blob: bytes):
        self.parts.append(blob)

    def add_chunk(self, cid: int, payload: bytes):
        self.parts.append(struct.pack("<HI", cid, 6 + len(payload)) + payload)

    def finalize(self) -> bytes:
        payload = b"".join(self.parts)
        return struct.pack("<HI", self.cid, 6 + len(payload)) + payload

def emit_cstr(s: str) -> bytes:
    return s.encode("ascii", errors="replace") + b"\x00"

def emit_material_block(name: str, meta: Dict[str, Optional[str]]) -> bytes:
    cb = ChunkBuilder(MATERIAL)
    cb.add_chunk(MAT_NAME, emit_cstr(name))
    # Minimal essentials; extend as needed
    if meta.get("filepath"):
        t = ChunkBuilder(MAT_TEXMAP)
        t.add_chunk(MAT_MAP_FILEPATH, emit_cstr(meta["filepath"]))
        cb.add(t.finalize())
    return cb.finalize()

def emit_point_array(verts: List[Tuple[float,float,float]]) -> bytes:
    out = [struct.pack("<H", len(verts))]
    for x,y,z in verts:
        out.append(struct.pack("<fff", x, y, z))
    return b"".join(out)

def emit_faces_block(faces: List[Tuple[int,int,int]], flags: List[int], mat_faces: Dict[str, List[int]]) -> bytes:
    cb = ChunkBuilder(OBJECT_FACES)
    n = len(faces)
    out = [struct.pack("<H", n)]
    for i,(a,b,c) in enumerate(faces):
        fl = flags[i] if i < len(flags) else 0
        out.append(struct.pack("<HHHH", a, b, c, fl))
    cb.add(b"".join(out))
    # material groups
    for mname, idxs in mat_faces.items():
        sub = [emit_cstr(mname), struct.pack("<H", len(idxs))]
        for fi in idxs:
            sub.append(struct.pack("<H", int(fi)))
        cb.add_chunk(OBJECT_MATERIAL, b"".join(sub))
    return cb.finalize()

def emit_smoothing_block(masks: List[int]) -> bytes:
    out = [struct.pack("<I", int(m)) for m in masks]
    return b"".join(out)

def emit_uv_chunk_4140(uvs: List[Tuple[float,float]]) -> bytes:
    out = [struct.pack("<H", len(uvs))]
    for u,v in uvs:
        out.append(struct.pack("<ff", float(u), float(v)))
    return b"".join(out)

# -----------------------------
# Xform baking
# -----------------------------
def apply_xform_to_vertices(verts: List[Tuple[float,float,float]], raw_4160: Optional[bytes]) -> List[Tuple[float,float,float]]:
    if not raw_4160 or len(raw_4160) < 48:
        return verts
    r00,r01,r02,tx, r10,r11,r12,ty, r20,r21,r22,tz = struct.unpack("<12f", raw_4160)
    out = []
    for x,y,z in verts:
        nx = r00*x + r01*y + r02*z + tx
        ny = r10*x + r11*y + r12*z + ty
        nz = r20*x + r21*y + r22*z + tz
        out.append((nx,ny,nz))
    return out

# -----------------------------
# UV selection from 4200
# -----------------------------
def build_uvs_from_fmc(mesh: Mesh, prefer_channel: int) -> List[Tuple[float,float]]:
    """
    Convert FACE_MAP_CHANNEL channel into a flat vertex-ordered UV list for 0x4140.
    Strategy: if there are as many UVs as vertices and uvfaces use vertex indices,
    pass uvs directly; otherwise fallback to primary or empty.
    """
    fmc = None
    ch_used = None
    if prefer_channel in mesh.fmc_channels:
        fmc = mesh.fmc_channels[prefer_channel]
        ch_used = prefer_channel
    elif mesh.fmc_channels:
        ch_used = sorted(mesh.fmc_channels.keys())[0]
        fmc = mesh.fmc_channels[ch_used]

    if fmc:
        # Heuristic: If uv count matches vertex count, we can emit directly.
        uvs = fmc["uvs"]  # list[(u,v)]
        if len(uvs) == len(mesh.vertices):
            # Good case: 1:1 mapping
            # print(f"    using FACE_MAP_CHANNEL={ch_used} (1:1)")
            return list(uvs)
        # Else try to build per-vertex average from uvfaces indexing (a,b,c) -> uv indices.
        uvfaces: List[Tuple[int,int,int]] = fmc.get("uvfaces") or []
        if uvfaces and len(uvs) > 0 and len(mesh.faces) == len(uvfaces):
            # Compute per-vertex UV by averaging contributions
            accum = [(0.0,0.0,0) for _ in range(len(mesh.vertices))]
            for (viA,viB,viC), (uiA,uiB,uiC) in zip(mesh.faces, uvfaces):
                for vi, ui in ((viA,uiA),(viB,uiB),(viC,uiC)):
                    if 0 <= ui < len(uvs) and 0 <= vi < len(accum):
                        u,v = uvs[ui]
                        su,sv,c = accum[vi]
                        accum[vi] = (su+u, sv+v, c+1)
            flat = []
            for su,sv,c in accum:
                if c > 0:
                    flat.append((su/c, sv/c))
                else:
                    flat.append((0.0, 0.0))
            # print(f"    using FACE_MAP_CHANNEL={ch_used} (averaged)")
            return flat

    # Fallback to existing 0x4140 primary if present
    if mesh.uv_primary:
        # print("    using OBJECT_UV_PRIMARY")
        return list(mesh.uv_primary)

    # No UVs found
    return []

# -----------------------------
# Compose 3DS
# -----------------------------
def compose_3ds(doc: Doc, *, prefer_channel: int = 1, bake_xform: bool = False) -> bytes:
    info_cb = ChunkBuilder(OBJECTINFO)
    if doc.mesh_version is not None:
        info_cb.add_chunk(EDIT_CONFIG, struct.pack("<I", int(doc.mesh_version)))

    # Materials
    for name, meta in doc.materials.items():
        info_cb.add(emit_material_block(name, meta))

    # Objects
    for mesh in doc.objects:
        obj_cb = ChunkBuilder(OBJECT)
        obj_cb.add(emit_cstr(mesh.name))

        # Build mesh block
        verts = mesh.vertices[:]
        if bake_xform and mesh.trans_matrix:
            verts = apply_xform_to_vertices(verts, mesh.trans_matrix)
            keep_4160 = False
        else:
            keep_4160 = bool(mesh.trans_matrix)

        uv_4140 = build_uvs_from_fmc(mesh, prefer_channel)
        mcb = ChunkBuilder(OBJECT_MESH)
        # 4110
        mcb.add_chunk(POINT_ARRAY, emit_point_array(verts))
        # 4160 (optional)
        if keep_4160:
            mcb.add_chunk(OBJECT_TRANS_MATRIX, mesh.trans_matrix)
        # 4120 (+ 4130 groups)
        mcb.add(emit_faces_block(mesh.faces, mesh.face_flags, mesh.mat_faces))
        # 4150 smoothing (optional)
        if mesh.smooth_masks:
            mcb.add_chunk(OBJECT_SMOOTH, emit_smoothing_block(mesh.smooth_masks))
        # 4140 UVs
        if uv_4140:
            mcb.add_chunk(OBJECT_UV_PRIMARY, emit_uv_chunk_4140(uv_4140))

        obj_cb.add(mcb.finalize())
        info_cb.add(obj_cb.finalize())

    # Root
    root = ChunkBuilder(PRIMARY)
    root.add_chunk(M3D_VERSION, struct.pack("<I", 3))
    root.add(info_cb.finalize())

    # Append raw KFDATA blobs (sibling of OBJECTINFO under PRIMARY)
    for blob in doc.kfdata_blobs:
        root.add(blob)

    return root.finalize()

# -----------------------------
# CLI
# -----------------------------
def main():
    ap = argparse.ArgumentParser(description="Convert I3D -> 3DS (materials, transforms, UVs, animations).")
    ap.add_argument("input", help="Path to input .i3d")
    ap.add_argument("-o", "--output", required=True, help="Output .3ds file")
    ap.add_argument("--channel", type=int, default=1, help="Preferred FACE_MAP_CHANNEL index (default: 1)")
    ap.add_argument("--bake-xform", action="store_true", help="Bake OBJECT_TRANS_MATRIX into vertices (omit 0x4160)")
    args = ap.parse_args()

    i3d_path = Path(args.input)
    if not i3d_path.exists() or i3d_path.suffix.lower() != ".i3d":
        print(f"[ERR] Not a valid .i3d file: {i3d_path}")
        sys.exit(2)

    print(f"[I3D] Reading: {i3d_path}")
    doc = parse_i3d(i3d_path)

    print(f"[I3D] Materials: {len(doc.materials)} | Meshes: {len(doc.objects)} | KFDATA blocks: {len(doc.kfdata_blobs)}")
    blob = compose_3ds(doc, prefer_channel=args.channel, bake_xform=args.bake_xform)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(blob)
    print(f"[OK ] Wrote: {out_path.resolve()}  ({len(blob)} bytes)")
    if args.bake_xform:
        print("[INFO] Transforms baked; 0x4160 omitted on meshes that had it.")

if __name__ == "__main__":
    main()

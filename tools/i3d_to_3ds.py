#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
i3d_to_3ds.py — I3D → 3DS (minimal, deterministic, no flags)
------------------------------------------------------------
- Converts I3D (Illusion/Hidden & Dangerous) back to classic .3DS.
- Properly handles Illusion FACE_MAP_CHANNEL (0x4200) → standard OBJECT_UV (0x4140):
    * Expands vertices at UV seams so len(POINT_ARRAY) == len(OBJECT_UV).
    * Emits 0x4140; never writes 0x4200 to the .3ds output.
- PRESERVES animation (KFDATA 0xB000) byte-for-byte.
- Keeps empty objects; does NOT fabricate meshes for lights/cameras/dummies.
- Strips vendor/unknown subchunks (e.g., 0x2426, 0x948D, 0xA220, 0xA230).
- Robust parsing: clamps any subchunk length to its parent to avoid runaway seeks.
- Deterministic canonical emission order: Materials → Objects → Animation.

Usage:
  python i3d_to_3ds.py scene-game-ready.i3d
  # Writes scene-game-ready.3ds next to input
"""

from __future__ import annotations
import sys
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---- 3DS Chunk IDs ----
PRIMARY                 = 0x4D4D
M3D_VERSION             = 0x0002
OBJECTINFO              = 0x3D3D

MATERIAL                = 0xAFFF
MAT_NAME                = 0xA000
MAT_TEXMAP              = 0xA200
MAT_MAP_FILEPATH        = 0xA300

OBJECT                  = 0x4000
OBJECT_MESH             = 0x4100
POINT_ARRAY             = 0x4110
OBJECT_FACES            = 0x4120
OBJECT_MATERIAL         = 0x4130
OBJECT_UV               = 0x4140
OBJECT_SMOOTH           = 0x4150
OBJECT_TRANS_MATRIX     = 0x4160
OBJECT_LIGHT            = 0x4600   # input only, do not fabricate meshes
OBJECT_CAMERA           = 0x4700   # input only

# Illusion extension in I3D (input only)
FACE_MAP_CHANNEL        = 0x4200

KFDATA                  = 0xB000

# Known vendor/unknown chunks to strip anywhere inside editable areas:
VENDOR_STRIP_IDS = {0x2426, 0x948D, 0x9F59, 0xA220, 0xA230, 0xB023, 0xB024, 0xB025, 0xB027, 0xB028}

# ---------- Low-level I/O ----------
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
        return bs.decode("latin-1", errors="replace")

def emit_cstr(s: str) -> bytes:
    return s.encode("ascii", errors="replace") + b"\x00"

def clamp_end(at: int, ln: int, parent_end: int) -> int:
    """Clamp a child's computed end to its parent's end to avoid runaway seeks."""
    cend = at + ln
    return cend if cend <= parent_end else parent_end

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

# ---------- Data containers ----------
class Mesh:
    def __init__(self, name: str):
        self.name = name
        # input-type flags
        self.had_mesh: bool = False
        self.had_light: bool = False
        self.had_camera: bool = False

        # mesh data
        self.verts: List[Tuple[float,float,float]] = []
        self.face_flags: List[int] = []
        self.faces: List[Tuple[int,int,int]] = []
        self.smooth_masks: List[int] = []
        self.trans_matrix: Optional[bytes] = None
        self.uv_primary: List[Tuple[float,float]] = []  # from 0x4140 if present
        # FMC: channel -> {'uvs': [(u,v)...], 'uvfaces': [(ua,ub,uc)...]}
        self.fmc_channels: Dict[int, Dict[str, list]] = {}
        # material assignment: name -> list of face indices
        self.mat_faces: Dict[str, List[int]] = {}

class Doc:
    def __init__(self):
        self.materials: Dict[str, Dict[str, Optional[str]]] = {}
        self.meshes: List[Mesh] = []
        self.kfdata_blobs: List[bytes] = []  # preserved as-is

# ---------- Parse I3D ----------
def parse_i3d(path: Path) -> Doc:
    doc = Doc()
    with path.open("rb") as f:
        ch = read_chunk(f)
        if not ch:
            raise RuntimeError("Empty file")
        cid, ln = ch
        if cid != PRIMARY:
            raise RuntimeError("Not a 3DS/I3D PRIMARY file")
        file_end = ln  # absolute end for PRIMARY
        while f.tell() < file_end:
            at = f.tell()
            ch = read_chunk(f)
            if not ch:
                break
            cid, ln = ch
            cend = clamp_end(at, ln, file_end)
            if cid == M3D_VERSION:
                # Some I3D files report 200 here; ignore
                if f.tell() + 4 <= cend:
                    _ = struct.unpack("<I", f.read(4))[0]
                f.seek(cend)
            elif cid == OBJECTINFO:
                parse_objectinfo(f, cend, doc)
            elif cid == KFDATA:
                # Byte-exact copy-through of animation
                f.seek(at)
                doc.kfdata_blobs.append(f.read(cend - at))
            else:
                # swallow vendor/unknown roots safely
                f.seek(cend)
    return doc

def parse_objectinfo(f, endpos: int, doc: Doc):
    while f.tell() < endpos:
        at = f.tell()
        ch = read_chunk(f)
        if not ch:
            break
        cid, ln = ch
        cend = clamp_end(at, ln, endpos)
        if cid == MATERIAL:
            parse_material(f, cend, doc)
        elif cid == OBJECT:
            parse_object(f, cend, doc)
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
        cend = clamp_end(at, ln, endpos)
        if cid == MAT_NAME:
            name = read_cstr(f)
        elif cid == MAT_TEXMAP:
            while f.tell() < cend:
                sat = f.tell()
                sub = read_chunk(f)
                if not sub: break
                scid, sln = sub
                send = clamp_end(sat, sln, cend)
                if scid == MAT_MAP_FILEPATH:
                    filepath = read_cstr(f)
                else:
                    f.seek(send)
        else:
            f.seek(cend)
    if name:
        doc.materials[name] = {"filepath": filepath}

def parse_object(f, endpos: int, doc: Doc):
    name = read_cstr(f)
    mesh = Mesh(name or "Object")
    while f.tell() < endpos:
        at = f.tell()
        ch = read_chunk(f)
        if not ch: break
        cid, ln = ch
        cend = clamp_end(at, ln, endpos)
        if cid == OBJECT_MESH:
            mesh.had_mesh = True
            parse_object_mesh(f, cend, mesh)
        elif cid == OBJECT_LIGHT:
            mesh.had_light = True
            strip_vendor_children(f, cend)
        elif cid == OBJECT_CAMERA:
            mesh.had_camera = True
            strip_vendor_children(f, cend)
        else:
            f.seek(cend)
    doc.meshes.append(mesh)

def strip_vendor_children(f, endpos: int):
    """Skip over a LIGHT/CAMERA block, stripping known vendor children if present."""
    while f.tell() < endpos:
        at = f.tell()
        ch = read_chunk(f)
        if not ch: break
        _scid, sln = ch
        send = clamp_end(at, sln, endpos)
        f.seek(send)

def parse_object_mesh(f, endpos: int, mesh: Mesh):
    while f.tell() < endpos:
        at = f.tell()
        ch = read_chunk(f)
        if not ch: break
        cid, ln = ch
        cend = clamp_end(at, ln, endpos)

        if cid == POINT_ARRAY:
            if f.tell() + 2 <= cend:
                n = struct.unpack("<H", f.read(2))[0]
                verts = []
                for _ in range(n):
                    if f.tell() + 12 <= cend:
                        verts.append(struct.unpack("<fff", f.read(12)))
                    else:
                        break
                mesh.verts = verts
            f.seek(cend)

        elif cid == OBJECT_UV:
            if f.tell() + 2 <= cend:
                n = struct.unpack("<H", f.read(2))[0]
                uvs = []
                for _ in range(n):
                    if f.tell() + 8 <= cend:
                        uvs.append(struct.unpack("<ff", f.read(8)))
                    else:
                        break
                mesh.uv_primary = uvs
            f.seek(cend)

        elif cid == OBJECT_FACES:
            cnt = 0
            faces = []
            flags = []
            if f.tell() + 2 <= cend:
                cnt = struct.unpack("<H", f.read(2))[0]
                for _ in range(cnt):
                    if f.tell() + 8 <= cend:
                        a,b,c,fl = struct.unpack("<HHHH", f.read(8))
                        faces.append((a,b,c))
                        flags.append(fl)
                    else:
                        break
            mesh.faces = faces
            mesh.face_flags = flags
            # subchunks (material links, smoothing)
            while f.tell() < cend:
                sat = f.tell()
                sub = read_chunk(f)
                if not sub: break
                scid, sln = sub
                send = clamp_end(sat, sln, cend)
                if scid == OBJECT_MATERIAL:
                    mname = read_cstr(f)
                    idxs = []
                    if f.tell() + 2 <= send:
                        cnt = struct.unpack("<H", f.read(2))[0]
                        for _ in range(cnt):
                            if f.tell() + 2 <= send:
                                idxs.append(struct.unpack("<H", f.read(2))[0])
                            else:
                                break
                    mesh.mat_faces.setdefault(mname, []).extend(idxs)
                elif scid == OBJECT_SMOOTH:
                    # optional; align to face count
                    masks = []
                    while f.tell() + 4 <= send and len(masks) < len(faces):
                        masks.append(struct.unpack("<I", f.read(4))[0])
                    mesh.smooth_masks = masks
                else:
                    f.seek(send)
            f.seek(cend)

        elif cid == OBJECT_TRANS_MATRIX:
            # 3x4 matrix (48 bytes), row-major
            size = min(48, max(0, cend - f.tell()))
            mesh.trans_matrix = f.read(size).ljust(48, b"\x00")
            f.seek(cend)

        elif cid == FACE_MAP_CHANNEL:
            # Flat layout: <I chan><H uvCount><uvs...><optional H faceCount><HHH * faceCount | remainder/6>
            payload_len = max(0, cend - f.tell())
            payload = f.read(payload_len)
            uvs = []
            uvfaces = []
            chan = 1
            off = 0
            if len(payload) >= 6:
                chan = struct.unpack_from("<I", payload, off)[0]; off += 4
                uv_count = struct.unpack_from("<H", payload, off)[0]; off += 2
                # UV list
                needed = uv_count * 8
                if len(payload) >= off + needed:
                    for i in range(uv_count):
                        uvs.append(struct.unpack_from("<ff", payload, off + i*8))
                    off += needed
                    # Faces part (optional)
                    rem = len(payload) - off
                    if rem >= 2:
                        possible_count = struct.unpack_from("<H", payload, off)[0]
                        rem2 = rem - 2
                        if rem2 >= 0 and rem2 % 6 == 0 and (possible_count*6 == rem2):
                            off += 2
                            for i in range(possible_count):
                                uvfaces.append(struct.unpack_from("<HHH", payload, off + i*6))
                        else:
                            tri_count = rem // 6
                            for i in range(tri_count):
                                uvfaces.append(struct.unpack_from("<HHH", payload, off + i*6))
            if uvs:
                mesh.fmc_channels[chan] = {"uvs": uvs, "uvfaces": uvfaces}
            # No seek needed; we consumed to cend via payload

        else:
            # swallow unknown/vendor subchunks inside mesh safely
            f.seek(cend)

# ---------- FMC → expanded vertices ----------
def expand_vertices_with_fmc(mesh: Mesh):
    """
    Return verts, uvs, faces where each (v,uv) pair is a unique vertex so that
    len(POINT_ARRAY) == len(OBJECT_UV). If no FMC is present, fall back to
    primary 0x4140 UVs as-is (padding/truncation to match vertex count).
    """
    if mesh.fmc_channels:
        chan = 1 if 1 in mesh.fmc_channels else next(iter(mesh.fmc_channels.keys()))
        uvs = mesh.fmc_channels[chan].get("uvs", [])
        uvfaces = mesh.fmc_channels[chan].get("uvfaces", [])
        # If no uvfaces provided, attempt a simple mapping fallback
        if not uvfaces and mesh.faces and uvs:
            uvfaces = []
            for (a,b,c) in mesh.faces:
                uvfaces.append((a % len(uvs), b % len(uvs), c % len(uvs)))
        new_verts: List[Tuple[float,float,float]] = []
        new_uvs:   List[Tuple[float,float]] = []
        new_faces: List[Tuple[int,int,int]] = []
        remap: Dict[Tuple[int,int], int] = {}
        for (a,b,c), (ua,ub,uc) in zip(mesh.faces, uvfaces):
            tri_new = []
            for v_idx, uv_idx in ((a,ua),(b,ub),(c,uc)):
                key = (v_idx, uv_idx)
                if key not in remap:
                    remap[key] = len(new_verts)
                    v = mesh.verts[v_idx] if v_idx < len(mesh.verts) else (0.0,0.0,0.0)
                    uv = uvs[uv_idx] if uv_idx < len(uvs) else (0.0,0.0)
                    new_verts.append(v)
                    new_uvs.append(uv)
                tri_new.append(remap[key])
            new_faces.append(tuple(tri_new))
        if new_verts and len(new_verts) == len(new_uvs):
            return new_verts, new_uvs, new_faces

    # Fallback to primary 0x4140: ensure counts match vertices
    verts = mesh.verts
    uvs = list(mesh.uv_primary)
    if verts:
        if not uvs:
            uvs = [(0.0, 0.0)] * len(verts)
        elif len(uvs) < len(verts):
            uvs += [uvs[-1]] * (len(verts) - len(uvs))
        elif len(uvs) > len(verts):
            uvs = uvs[:len(verts)]
    return verts, uvs, mesh.faces

# ---------- Emit 3DS ----------
def emit_material(name: str, meta: Dict[str, Optional[str]]) -> bytes:
    cb = ChunkBuilder(MATERIAL)
    cb.add_chunk(MAT_NAME, emit_cstr(name))
    fp = meta.get("filepath") if meta else None
    if fp:
        m = ChunkBuilder(MAT_TEXMAP)
        m.add_chunk(MAT_MAP_FILEPATH, emit_cstr(fp))
        cb.add(m.finalize())
    return cb.finalize()

def emit_point_array(verts: List[Tuple[float,float,float]]) -> bytes:
    out = [struct.pack("<H", len(verts))]
    out += [struct.pack("<fff", *v) for v in verts]
    return b"".join(out)

def emit_object_faces_with_subs(faces: List[Tuple[int,int,int]], mat_faces: Dict[str, List[int]]):
    # Build OBJECT_FACES with embedded subchunks (OBJECT_MATERIAL etc.)
    base = [struct.pack("<H", len(faces))]
    for (a,b,c) in faces:
        base.append(struct.pack("<HHHH", a,b,c, 0))  # flags -> 0
    faces_payload = b"".join(base)

    faces_cb = ChunkBuilder(OBJECT_FACES)
    faces_cb.add(faces_payload)

    # Embed each OBJECT_MATERIAL as a subchunk inside OBJECT_FACES
    for mname, idxs in mat_faces.items():
        if not idxs:
            continue
        mb = [emit_cstr(mname), struct.pack("<H", len(idxs))]
        mb += [struct.pack("<H", i) for i in idxs]
        faces_cb.add_chunk(OBJECT_MATERIAL, b"".join(mb))

    return faces_cb.finalize()

def emit_object_uv(uvs: List[Tuple[float,float]], expected_count: Optional[int]=None) -> bytes:
    if expected_count is not None:
        if len(uvs) != expected_count:
            # pad or truncate to match expected (safer for finicky readers)
            if len(uvs) < expected_count and uvs:
                last = uvs[-1]
                uvs = uvs + [last] * (expected_count - len(uvs))
            else:
                uvs = uvs[:expected_count]
    out = [struct.pack("<H", len(uvs))]
    out += [struct.pack("<ff", *uv) for uv in uvs]
    return b"".join(out)

def emit_object(mesh: Mesh) -> bytes:
    name = mesh.name or "Object"
    cb = ChunkBuilder(OBJECT)
    cb.add(emit_cstr(name))

    # If the parsed object did NOT have a mesh, do not fabricate one.
    if not mesh.had_mesh:
        # This covers lights, cameras, and helper/dummy empties.
        # We emit just the OBJECT name, with no OBJECT_MESH subchunk.
        return cb.finalize()

    # Proper mesh emission:
    verts, uvs, faces = expand_vertices_with_fmc(mesh)

    mcb = ChunkBuilder(OBJECT_MESH)
    # Canonical subchunk order: 4110 → 4140 → 4120 → 4150 → 4160
    mcb.add_chunk(POINT_ARRAY, emit_point_array(verts))
    mcb.add_chunk(OBJECT_UV, emit_object_uv(uvs, expected_count=len(verts)))
    mcb.add(emit_object_faces_with_subs(faces, mesh.mat_faces))
    if mesh.smooth_masks:
        mcb.add_chunk(OBJECT_SMOOTH, b"".join(struct.pack("<I", m) for m in mesh.smooth_masks))
    if mesh.trans_matrix:
        mcb.add_chunk(OBJECT_TRANS_MATRIX, mesh.trans_matrix)

    cb.add(mcb.finalize())
    return cb.finalize()

def compose_3ds(doc: Doc) -> bytes:
    root = ChunkBuilder(PRIMARY)
    root.add_chunk(M3D_VERSION, struct.pack("<I", 3))  # always version 3

    edit = ChunkBuilder(OBJECTINFO)

    # Materials — preserve discovery order from I3D
    for mname, meta in doc.materials.items():
        edit.add(emit_material(mname, meta))

    # Ensure materials referenced exist
    for mesh in doc.meshes:
        for mname in mesh.mat_faces.keys():
            if mname and mname not in doc.materials:
                doc.materials[mname] = {"filepath": None}
                edit.add(emit_material(mname, {"filepath": None}))

    # Objects — preserve discovery order; do not fabricate meshes for non-mesh objects
    for mesh in doc.meshes:
        edit.add(emit_object(mesh))

    root.add(edit.finalize())

    # Animation (KFDATA) — byte-exact keep, after EDIT chunk
    for blob in doc.kfdata_blobs:
        root.add(blob)

    return root.finalize()

# ---------- CLI ----------
def main():
    if len(sys.argv) < 2:
        print("Usage: python i3d_to_3ds.py <input.i3d>")
        sys.exit(1)

    in_path = Path(sys.argv[1])
    if not in_path.exists() or in_path.suffix.lower() != ".i3d":
        print(f"[ERR] Not a valid .i3d: {in_path}")
        sys.exit(2)

    print(f"[I3D] Loading: {in_path}")
    doc = parse_i3d(in_path)
    print(f"[I3D] Meshes: {len(doc.meshes)} | Materials: {len(doc.materials)} | KFDATA: {len(doc.kfdata_blobs)}")

    blob = compose_3ds(doc)
    out_path = in_path.with_suffix(".3ds")
    out_path.write_bytes(blob)
    print(f"[OK ] Wrote: {out_path.resolve()} ({len(blob)} bytes)")

if __name__ == "__main__":
    main()

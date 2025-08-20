#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Surgical 3DS → I3D UV patcher
-----------------------------
Rewrites a .3ds so that the mesh UVs move from OBJECT_UV (0x4140) into
FACE_MAP_CHANNEL (0x4200) with a specified channel index, keeping all
other chunks byte-for-byte identical where possible.

Strategy
- Parse the chunk tree enough to locate: OBJECTINFO → OBJECT → OBJECT_MESH
- Extract raw bytes for:
  - POINT_ARRAY (0x4110)
  - OBJECT_FACES (0x4120) [we need face count]
  - OBJECT_UV (0x4140)    [we need uvs]
  - OBJECT_SMOOTH (0x4150), OBJECT_MATERIAL (0x4130), etc. (preserved)
- Build a new OBJECT_MESH:
  - copy existing subchunks (except 0x4140)
  - append 0x4200 constructed as:
      [u32 channel][u16 uv_count][uvs...][u16 face_count][(u16,u16,u16)*faces]
    mapping face vertex indices to UV indices directly (common in 3DS where
    vertex splits align UVs to geometry indices).
- Wrap the new OBJECT_MESH inside a new OBJECT (name preserved) and then
  a new OBJECTINFO with original siblings (EDIT_CONFIG, MATERIALs, etc.),
  and finally PRIMARY. MATERIAL blocks are preserved byte-for-byte.

Usage:
  python patch_3ds_uv_to_i3d.py input.3ds [-o out.i3d] [--channel 1]

Notes:
- Assumes a single OBJECT block containing a single OBJECT_MESH.
- If multiple objects exist, the first OBJECT_MESH is patched.
- Original file is not modified; a new .i3d file is written.
"""

import sys
import struct
import argparse
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple, List

# Chunk IDs
PRIMARY                 = 0x4D4D
M3D_VERSION             = 0x0002
OBJECTINFO              = 0x3D3D
EDIT_CONFIG             = 0x3D3E
MATERIAL                = 0xAFFF
OBJECT                  = 0x4000
OBJECT_MESH             = 0x4100
POINT_ARRAY             = 0x4110
OBJECT_FACES            = 0x4120
OBJECT_MATERIAL         = 0x4130
OBJECT_UV_PRIMARY       = 0x4140
OBJECT_SMOOTH           = 0x4150
OBJECT_TRANS_MATRIX     = 0x4160
FACE_MAP_CHANNEL        = 0x4200

def read_chunk_header(buf: bytes, off: int) -> Optional[Tuple[int,int]]:
    if off + 6 > len(buf):
        return None
    cid, length = struct.unpack_from("<HI", buf, off)
    return cid, length

def write_chunk(cid: int, payload: bytes) -> bytes:
    return struct.pack("<HI", cid, 6 + len(payload)) + payload

def find_children(buf: bytes, start: int, end: int) -> List[Tuple[int,int,int,int]]:
    """
    Returns list of (cid, start, length, body_start)
    """
    res = []
    p = start
    while p + 6 <= end:
        cid, ln = struct.unpack_from("<HI", buf, p)
        if ln < 6 or p + ln > end:
            break
        res.append((cid, p, ln, p + 6))
        p += ln
    return res

def read_cstr(buf: bytes, off: int) -> Tuple[str, int]:
    p = off
    out = bytearray()
    while p < len(buf) and buf[p] != 0:
        out.append(buf[p])
        p += 1
    if p < len(buf) and buf[p] == 0:
        p += 1
    return out.decode("ascii", errors="replace"), p

def parse_faces(buf: bytes, body_start: int, body_end: int):
    # face block layout: u16 n, then n*(H,H,H,H flags), then nested subchunks
    p = body_start
    n = struct.unpack_from("<H", buf, p)[0]
    p += 2
    faces = []
    flags = []
    for _ in range(n):
        a,b,c,fl = struct.unpack_from("<3HH", buf, p)
        faces.append((a,b,c))
        flags.append(fl)
        p += 8
    # ignore nested subchunks for counting; they remain as raw bytes
    return n, faces, flags

def parse_uvs(buf: bytes, body_start: int, body_end: int):
    p = body_start
    n = struct.unpack_from("<H", buf, p)[0]
    p += 2
    uvs = []
    for _ in range(n):
        u,v = struct.unpack_from("<2f", buf, p)
        uvs.append((u,v))
        p += 8
    return n, uvs

def build_face_map_channel_payload(channel: int, uvs: List[Tuple[float,float]], faces: List[Tuple[int,int,int]]) -> bytes:
    out = BytesIO()
    out.write(struct.pack("<I", int(channel)))
    out.write(struct.pack("<H", len(uvs)))
    for u,v in uvs:
        out.write(struct.pack("<2f", float(u), float(v)))
    out.write(struct.pack("<H", len(faces)))
    for a,b,c in faces:
        out.write(struct.pack("<3H", a, b, c))
    return out.getvalue()

def patch_file(src_path: Path, dst_path: Path, channel: int = 1):
    data = bytearray(src_path.read_bytes())

    # Parse top-level: PRIMARY
    cid0, ln0 = read_chunk_header(data, 0)
    if cid0 != PRIMARY:
        raise RuntimeError("Not a 3DS/I3D-like file (missing PRIMARY at start).")
    end0 = ln0

    # Walk PRIMARY children to find OBJECTINFO
    children0 = find_children(data, 6, end0)
    objinfo_span = None
    for cid, start, ln, body in children0:
        if cid == OBJECTINFO:
            objinfo_span = (start, ln, body, start + ln)
            break
    if not objinfo_span:
        raise RuntimeError("OBJECTINFO (0x3D3D) not found.")
    oi_start, oi_len, oi_body, oi_end = objinfo_span

    # Gather OBJECTINFO children; keep raw bytes for everything except OBJECT
    oi_kids = find_children(data, oi_body, oi_end)
    object_span = None
    # We'll also keep other children (e.g., EDIT_CONFIG, MATERIALS) raw
    preserved_chunks = []
    for cid, start, ln, body in oi_kids:
        if cid == OBJECT and object_span is None:
            object_span = (start, ln, body, start + ln)
        else:
            preserved_chunks.append(data[start:start+ln])
    if not object_span:
        raise RuntimeError("OBJECT (0x4000) not found under OBJECTINFO.")

    # Parse OBJECT: read name (cstr), then one OBJECT_MESH child we will patch
    o_start, o_len, o_body, o_end = object_span
    name, after_name = read_cstr(data, o_body)
    obj_children = find_children(data, after_name, o_end)

    mesh_span = None
    preserved_obj_children = []
    for cid, start, ln, body in obj_children:
        if cid == OBJECT_MESH and mesh_span is None:
            mesh_span = (start, ln, body, start + ln)
        else:
            preserved_obj_children.append(data[start:start+ln])
    if not mesh_span:
        raise RuntimeError("OBJECT_MESH (0x4100) not found under OBJECT.")

    # Parse OBJECT_MESH children; collect raw subchunks and locate faces/uvs
    m_start, m_len, m_body, m_end = mesh_span
    mesh_kids = find_children(data, m_body, m_end)

    # We will keep all subchunks raw except: drop 0x4140, and we need to know
    # faces (0x4120) content and uvs (0x4140) content to construct 0x4200.
    mesh_preserve = []
    faces = None
    faces_cnt = 0
    uvs = None
    point_array_chunk = None
    trans_matrix_chunk = None
    other_chunks = []
    for cid, start, ln, body in mesh_kids:
        raw = data[start:start+ln]
        if cid == POINT_ARRAY:
            point_array_chunk = raw
        elif cid == OBJECT_TRANS_MATRIX:
            trans_matrix_chunk = raw
        elif cid == OBJECT_FACES:
            faces_block = raw
            n, ftri, _flags = parse_faces(data, body, start+ln)
            faces_cnt = n
            faces = ftri
            other_chunks.append(faces_block)
        elif cid == OBJECT_UV_PRIMARY:
            # skip adding 0x4140; parse UVs for 0x4200
            n, uvs_list = parse_uvs(data, body, start+ln)
            uvs = uvs_list
        else:
            other_chunks.append(raw)

    if faces is None:
        raise RuntimeError("OBJECT_FACES (0x4120) not found in mesh.")
    if uvs is None:
        raise RuntimeError("OBJECT_UV (0x4140) not found in mesh; nothing to convert.")

    # Recompose preserved subchunks with enforced order: 4110, 4160 (if any), then the rest
    ordered_chunks = []
    if point_array_chunk is None:
        raise RuntimeError("POINT_ARRAY (0x4110) not found in mesh.")
    ordered_chunks.append(point_array_chunk)
    if trans_matrix_chunk is not None:
        ordered_chunks.append(trans_matrix_chunk)
    # Keep the rest in their original relative order as collected in other_chunks
    ordered_chunks.extend(other_chunks)

    # Build FACE_MAP_CHANNEL (0x4200)
    fmc_payload = build_face_map_channel_payload(channel, uvs, faces)
    fmc_chunk = write_chunk(FACE_MAP_CHANNEL, fmc_payload)

    # Compose new OBJECT_MESH: [ordered preserved subchunks except 0x4140] + [0x4200]
    new_mesh_body = b''.join(ordered_chunks) + fmc_chunk
    new_mesh = write_chunk(OBJECT_MESH, new_mesh_body)

    # Rebuild OBJECT: name (same) + new OBJECT_MESH + preserved siblings
    obj_body = name.encode('ascii', errors='replace') + b'\x00' + new_mesh + b''.join(preserved_obj_children)
    new_object = write_chunk(OBJECT, obj_body)

    # Rebuild OBJECTINFO: preserved (materials, edit_config, etc.) + new OBJECT
    new_oi_body = b''.join(preserved_chunks) + new_object
    new_oi = write_chunk(OBJECTINFO, new_oi_body)

    # Rebuild PRIMARY: keep all siblings (before/after OBJECTINFO) raw
    # Identify PRIMARY children again to collect siblings
    primary_kids = find_children(data, 6, end0)
    preserved_primary = []
    for cid, start, ln, body in primary_kids:
        if start == oi_start and ln == oi_len:
            # replaced by new_oi
            preserved_primary.append(new_oi)
        else:
            preserved_primary.append(bytes(data[start:start+ln]))
    new_primary_body = b''.join(preserved_primary)
    new_primary = write_chunk(PRIMARY, new_primary_body)

    dst_path.write_bytes(new_primary)

def main():
    ap = argparse.ArgumentParser(description="Patch 3DS UVs (0x4140) into I3D FACE_MAP_CHANNEL (0x4200).")
    ap.add_argument("input", help="Path to input .3ds")
    ap.add_argument("-o", "--output", help="Path to output .i3d (default: alongside)")
    ap.add_argument("--channel", type=int, default=1, help="FACE_MAP_CHANNEL index (default: 1)")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"ERROR: not found: {src}")
        sys.exit(2)
    dst = Path(args.output) if args.output else src.with_suffix(".i3d")

    print(f"[PATCH] Reading: {src}")
    patch_file(src, dst, channel=args.channel)
    print(f"[OK] Wrote: {dst}")

if __name__ == "__main__":
    main()

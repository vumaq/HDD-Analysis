#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-mesh 3DS → I3D UV patcher (numeric order, safe 4200 build)
-----------------------------------------------------------------
For EVERY OBJECT_MESH in a .3ds file:
- Remove OBJECT_UV (0x4140) *only if safe to convert*
- Create FACE_MAP_CHANNEL (0x4200) using the 0x4140 UV list and per-face vt indices
- Reorder ALL OBJECT_MESH subchunks by ascending numeric chunk ID (hex), incl. 0x4200
- Preserve everything else byte-for-byte (materials, edit_config, etc.)
- Recalculate only the necessary parent chunk sizes (OBJECT_MESH, OBJECT, OBJECTINFO, PRIMARY)

Safety:
- If UV count < max vertex index referenced by faces (i.e., invalid indices),
  the mesh is left unmodified (keeps original 0x4140) to avoid corrupt 0x4200.

Usage:
  python patch_3ds_uv_to_i3d_numeric.py input.3ds [-o out.i3d] [--channel 1]
"""

import sys
import struct
import argparse
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple, List

# --- Chunk IDs (3DS / I3D flavored) ---
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


# --- Basic helpers ---
def read_chunk_header(buf: bytes, off: int) -> Optional[Tuple[int, int]]:
    if off + 6 > len(buf):
        return None
    cid, ln = struct.unpack_from("<HI", buf, off)
    return cid, ln

def write_chunk(cid: int, payload: bytes) -> bytes:
    return struct.pack("<HI", cid, 6 + len(payload)) + payload

def find_children(buf: bytes, start: int, end: int) -> List[Tuple[int, int, int, int]]:
    """
    Enumerate immediate child chunks within [start, end).
    Returns list of (cid, chunk_start, chunk_len, body_start).
    """
    out = []
    p = start
    while p + 6 <= end:
        cid, ln = struct.unpack_from("<HI", buf, p)
        if ln < 6 or p + ln > end:
            break
        out.append((cid, p, ln, p + 6))
        p += ln
    return out

def read_cstr(buf: bytes, off: int) -> Tuple[str, int]:
    p = off
    out = bytearray()
    while p < len(buf) and buf[p] != 0:
        out.append(buf[p]); p += 1
    if p < len(buf) and buf[p] == 0:
        p += 1
    return out.decode("ascii", errors="replace"), p


# --- Parsers for the data we need ---
def parse_faces(buf: bytes, body_start: int, body_end: int):
    """
    OBJECT_FACES (0x4120):
      u16 face_count
      face_count * (u16 a, u16 b, u16 c, u16 flags)
      [nested subchunks we leave as raw]
    """
    p = body_start
    n = struct.unpack_from("<H", buf, p)[0]; p += 2
    faces, flags = [], []
    for _ in range(n):
        a, b, c, fl = struct.unpack_from("<3HH", buf, p)
        faces.append((a, b, c))
        flags.append(fl)
        p += 8
    return n, faces, flags

def parse_uvs(buf: bytes, body_start: int, body_end: int):
    """
    OBJECT_UV (0x4140):
      u16 uv_count
      uv_count * (float u, float v)
    """
    p = body_start
    n = struct.unpack_from("<H", buf, p)[0]; p += 2
    uvs = []
    for _ in range(n):
        u, v = struct.unpack_from("<2f", buf, p)
        uvs.append((u, v)); p += 8
    return n, uvs


# --- Build 0x4200 FACE_MAP_CHANNEL ---
def build_face_map_channel_payload(channel: int,
                                   uvs: List[Tuple[float, float]],
                                   faces: List[Tuple[int, int, int]]) -> bytes:
    """
    0x4200 layout:
      u32 channel
      u16 uv_count
      uv_count * (float u, float v)
      u16 face_count
      face_count * (u16 iu, u16 iv, u16 iw)  # UV indices per triangle
    Strategy: map triangle (a,b,c) vertex indices directly to UV indices.
    """
    out = BytesIO()
    out.write(struct.pack("<I", int(channel)))
    out.write(struct.pack("<H", len(uvs)))
    for u, v in uvs:
        out.write(struct.pack("<2f", float(u), float(v)))
    out.write(struct.pack("<H", len(faces)))
    for a, b, c in faces:
        out.write(struct.pack("<3H", a, b, c))
    return out.getvalue()

def chunk_id_of(raw: bytes) -> int:
    return struct.unpack_from("<H", raw, 0)[0]


# --- Patchers ---
def patch_object_mesh_numeric(mesh_raw: bytes, channel: int) -> bytes:
    """
    Returns rebuilt OBJECT_MESH with:
      - 0x4140 removed (only if safe to convert)
      - 0x4200 added
      - ALL subchunks sorted by numeric chunk ID (ascending)
    If no 0x4140 is present (no UVs) or conversion is unsafe, returns the original mesh blob unchanged.
    """
    cid, ln = read_chunk_header(mesh_raw, 0)
    assert cid == OBJECT_MESH and ln == len(mesh_raw), "Invalid OBJECT_MESH blob."
    kids = find_children(mesh_raw, 6, len(mesh_raw))

    point_present = False
    faces = None
    uvs = None
    preserved = []  # raw chunks to keep; we will omit 0x4140 only if conversion is safe

    # First pass: collect data and keep all chunks *except* 0x4140 (conditionally)
    # We'll decide to drop or keep 0x4140 after validating safety.
    raw_4140_chunks = []  # keep track of any 4140s we might need to preserve
    for kcid, start, clen, body in kids:
        raw = mesh_raw[start:start+clen]
        if kcid == POINT_ARRAY:
            point_present = True
            preserved.append(raw)
        elif kcid == OBJECT_FACES:
            _, faces_list, _ = parse_faces(mesh_raw, body, start+clen)
            faces = faces_list
            preserved.append(raw)
        elif kcid == OBJECT_UV_PRIMARY:
            _, uv_list = parse_uvs(mesh_raw, body, start+clen)
            uvs = uv_list
            raw_4140_chunks.append(raw)  # only keep if conversion turns out unsafe
        else:
            preserved.append(raw)

    # If there were no UVs, nothing to convert; return original mesh blob unchanged
    if uvs is None or faces is None or not point_present:
        return mesh_raw

    # --- SAFETY: ensure UV list can index all face vertices ---
    max_vi = 0
    for a, b, c in faces:
        if a > max_vi: max_vi = a
        if b > max_vi: max_vi = b
        if c > max_vi: max_vi = c
    if max_vi >= len(uvs):
        # Can't build a valid 0x4200; keep original 0x4140 for this mesh
        # Put back any raw 0x4140 chunks we held aside
        preserved.extend(raw_4140_chunks)
        # Preserve original subchunk order by reusing original blob
        return mesh_raw

    # Build 0x4200 and add it to the set (drop 0x4140)
    fmc_chunk = write_chunk(FACE_MAP_CHANNEL, build_face_map_channel_payload(channel, uvs, faces))
    preserved.append(fmc_chunk)

    # Numeric sort ALL subchunks now present (4140 removed, 4200 added)
    preserved.sort(key=chunk_id_of)

    # Rebuild OBJECT_MESH with sorted subchunks
    new_body = b"".join(preserved)
    return write_chunk(OBJECT_MESH, new_body)


def patch_object_numeric(obj_raw: bytes, channel: int) -> bytes:
    """
    Rebuild an OBJECT (0x4000) by rewriting EVERY OBJECT_MESH child with numeric ordering.
    Name and other children preserved byte-for-byte.
    """
    cid, ln = read_chunk_header(obj_raw, 0)
    assert cid == OBJECT and ln == len(obj_raw), "Invalid OBJECT blob."
    name, after_name = read_cstr(obj_raw, 6)
    kids = find_children(obj_raw, after_name, len(obj_raw))

    rebuilt = []
    touched = False
    for kcid, start, clen, body in kids:
        raw = obj_raw[start:start+clen]
        if kcid == OBJECT_MESH:
            new_mesh = patch_object_mesh_numeric(raw, channel)
            rebuilt.append(new_mesh)
            if new_mesh != raw:
                touched = True
        else:
            rebuilt.append(raw)

    if not touched:
        return obj_raw

    body = name.encode("ascii", errors="replace") + b"\x00" + b"".join(rebuilt)
    return write_chunk(OBJECT, body)


def patch_file_numeric(src_path: Path, dst_path: Path, channel: int = 1):
    data = bytearray(src_path.read_bytes())

    # PRIMARY
    ch0 = read_chunk_header(data, 0)
    if not ch0 or ch0[0] != PRIMARY:
        raise RuntimeError("Not a 3DS/I3D-like file (PRIMARY missing).")
    _, ln0 = ch0
    prim_children = find_children(data, 6, ln0)

    # Locate OBJECTINFO
    oi_idx = None
    for i, (cid, start, ln, body) in enumerate(prim_children):
        if cid == OBJECTINFO:
            oi_idx = i
            oi_start, oi_len, oi_body, oi_end = start, ln, body, start + ln
            break
    if oi_idx is None:
        raise RuntimeError("OBJECTINFO (0x3D3D) not found.")

    # Rebuild every OBJECT under OBJECTINFO
    oi_children = find_children(data, oi_body, oi_end)
    rebuilt_oi_children = []
    touched = False

    for kcid, start, ln, body in oi_children:
        raw = bytes(data[start:start+ln])
        if kcid == OBJECT:
            new_obj = patch_object_numeric(raw, channel)
            rebuilt_oi_children.append(new_obj)
            if new_obj != raw:
                touched = True
        else:
            rebuilt_oi_children.append(raw)

    if not touched:
        # Nothing changed; write original to dst
        dst_path.write_bytes(bytes(data))
        return

    # Rewrap into OBJECTINFO
    new_oi = write_chunk(OBJECTINFO, b"".join(rebuilt_oi_children))

    # Replace old OBJECTINFO in PRIMARY (preserving other primary children)
    rebuilt_prim_children = []
    for i, (cid, start, ln, body) in enumerate(prim_children):
        if i == oi_idx:
            rebuilt_prim_children.append(new_oi)
        else:
            rebuilt_prim_children.append(bytes(data[start:start+ln]))

    new_primary = write_chunk(PRIMARY, b"".join(rebuilt_prim_children))
    dst_path.write_bytes(new_primary)


def main():
    ap = argparse.ArgumentParser(description="Patch ALL OBJECT_MESH UVs (0x4140) into I3D FACE_MAP_CHANNEL (0x4200) with numeric subchunk ordering (safe mode).")
    ap.add_argument("input", help="Path to input .3ds")
    ap.add_argument("-o", "--output", help="Path to output .i3d (default: alongside source)")
    ap.add_argument("--channel", type=int, default=1, help="FACE_MAP_CHANNEL index to write (default: 1)")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"ERROR: not found: {src}")
        sys.exit(2)
    dst = Path(args.output) if args.output else src.with_suffix(".i3d")

    print(f"[PATCH] Reading: {src}")
    patch_file_numeric(src, dst, channel=args.channel)
    print(f"[OK] Wrote: {dst}")

if __name__ == "__main__":
    main()

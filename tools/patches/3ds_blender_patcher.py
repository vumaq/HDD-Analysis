#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3DS Blender Patcher
-------------------
Fix the classic "exploded / scattered parts" problem when importing .3ds into Blender by:
  - Baking OBJECT_TRANS_MATRIX (0x4160) into POINT_ARRAY (0x4110) vertices
  - Removing 0x4160 afterwards so Blender can't double-apply it

Optional:
  - --strip           : remove 0x4160 without baking (debug only)
  - --add-smoothing   : if a mesh has no OBJECT_SMOOTH (0x4150), add a simple one (group=1 for every face)

Scope:
  - Only touches .3ds files
  - Preserves all non-targeted chunks byte-for-byte
  - Recomputes parent sizes for OBJECT_MESH, OBJECT, OBJECTINFO, and PRIMARY

Usage:
  python 3ds_blender_patcher.py model.3ds -o model_fixed.3ds --bake
"""

from __future__ import annotations
import sys
import struct
import argparse
from pathlib import Path
from typing import List, Tuple, Optional

# ---------------------------
# Chunk IDs
# ---------------------------
PRIMARY             = 0x4D4D
M3D_VERSION         = 0x0002
OBJECTINFO          = 0x3D3D
MATERIAL            = 0xAFFF
OBJECT              = 0x4000
OBJECT_MESH         = 0x4100
POINT_ARRAY         = 0x4110
OBJECT_FACES        = 0x4120
OBJECT_MATERIAL     = 0x4130
OBJECT_UV_PRIMARY   = 0x4140
OBJECT_SMOOTH       = 0x4150
OBJECT_TRANS_MATRIX = 0x4160
KFDATA              = 0xB000

# ---------------------------
# Binary helpers
# ---------------------------
def read_chunk_header(buf: bytes, off: int) -> Optional[Tuple[int, int]]:
    """Return (cid, length) for chunk at off, or None if not enough bytes."""
    if off + 6 > len(buf):
        return None
    return struct.unpack_from("<HI", buf, off)

def write_chunk(cid: int, payload: bytes) -> bytes:
    return struct.pack("<HI", cid, 6 + len(payload)) + payload

def find_children(buf: bytes, start: int, end: int) -> List[Tuple[int, int, int, int]]:
    """
    Enumerate immediate child chunks within [start, end).
    Returns list of tuples: (cid, chunk_start, chunk_len, body_start)
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
    bs = bytearray()
    while p < len(buf) and buf[p] != 0:
        bs.append(buf[p])
        p += 1
    if p < len(buf) and buf[p] == 0:
        p += 1
    return bs.decode("ascii", errors="replace"), p

# ---------------------------
# Parsers we need
# ---------------------------
def parse_points_chunk(raw_chunk: bytes) -> List[Tuple[float,float,float]]:
    """raw_chunk must be a full 0x4110 chunk (header+payload)."""
    cid, ln = read_chunk_header(raw_chunk, 0)
    assert cid == POINT_ARRAY and ln == len(raw_chunk)
    p = 6
    (count,) = struct.unpack_from("<H", raw_chunk, p); p += 2
    verts = []
    for _ in range(count):
        x, y, z = struct.unpack_from("<fff", raw_chunk, p); p += 12
        verts.append((x, y, z))
    return verts

def build_points_chunk_from(verts: List[Tuple[float,float,float]]) -> bytes:
    payload = bytearray()
    payload.extend(struct.pack("<H", len(verts)))
    for x, y, z in verts:
        payload.extend(struct.pack("<fff", float(x), float(y), float(z)))
    return write_chunk(POINT_ARRAY, bytes(payload))

def parse_faces_header_count(raw_chunk: bytes) -> int:
    """Return face count from a full 0x4120 chunk. If malformed, return 0."""
    cid, ln = read_chunk_header(raw_chunk, 0)
    if cid != OBJECT_FACES or ln != len(raw_chunk) or ln < 8:
        return 0
    (count,) = struct.unpack_from("<H", raw_chunk, 6)
    return int(count)

def parse_matrix_payload(payload_48: bytes) -> Optional[Tuple[float,...]]:
    """Return 12 floats (r00 r01 r02 tx r10 r11 r12 ty r20 r21 r22 tz) or None."""
    if payload_48 is None or len(payload_48) < 48:
        return None
    return struct.unpack("<12f", payload_48)

def apply_matrix_to_vertices(verts: List[Tuple[float,float,float]], m12: Tuple[float,...]) -> List[Tuple[float,float,float]]:
    r00,r01,r02,tx, r10,r11,r12,ty, r20,r21,r22,tz = m12
    out = []
    for x,y,z in verts:
        nx = r00*x + r01*y + r02*z + tx
        ny = r10*x + r11*y + r12*z + ty
        nz = r20*x + r21*y + r22*z + tz
        out.append((nx, ny, nz))
    return out

def build_smoothing_chunk(face_count: int, group_value: int = 1) -> bytes:
    """
    OBJECT_SMOOTH payload is N * u32 masks, one per face.
    Using group_value=1 puts all faces into group #1 (simple, Blender-friendly).
    """
    payload = bytearray()
    for _ in range(face_count):
        payload.extend(struct.pack("<I", int(group_value)))
    return write_chunk(OBJECT_SMOOTH, bytes(payload))

# ---------------------------
# Mesh patcher
# ---------------------------
def patch_object_mesh(mesh_raw: bytes, *, bake: bool, strip: bool, add_smoothing: bool) -> bytes:
    """
    Operate on a full OBJECT_MESH (0x4100) blob.
    - If bake: parse 0x4110 points and 0x4160 matrix, apply matrix to points, replace 0x4110, drop 0x4160.
    - If strip (and not bake): drop 0x4160.
    - If add_smoothing and no 0x4150 exists: add a simple smoothing block using face count.
    Otherwise preserve children verbatim and order as close as possible.
    Returns patched OBJECT_MESH (or original if nothing changed).
    """
    cid, ln = read_chunk_header(mesh_raw, 0)
    assert cid == OBJECT_MESH and ln == len(mesh_raw), "Invalid OBJECT_MESH blob."
    kids = find_children(mesh_raw, 6, len(mesh_raw))

    # Gather info
    raw_points = None       # full 0x4110 chunk (bytes)
    raw_matrix_payload = None  # 48-byte payload
    had_smoothing = False
    face_count = 0

    for kcid, start, clen, body in kids:
        if kcid == POINT_ARRAY:
            raw_points = mesh_raw[start:start+clen]
        elif kcid == OBJECT_TRANS_MATRIX:
            raw_matrix_payload = mesh_raw[body:start+clen]
        elif kcid == OBJECT_SMOOTH:
            had_smoothing = True
        elif kcid == OBJECT_FACES:
            face_count = parse_faces_header_count(mesh_raw[start:start+clen])

    # Rebuild children
    out_children: List[bytes] = []
    changed = False

    for kcid, start, clen, body in kids:
        raw = mesh_raw[start:start+clen]

        if kcid == POINT_ARRAY and bake and raw_points is not None and raw_matrix_payload is not None:
            # bake transform into vertices
            verts = parse_points_chunk(raw_points)
            m12 = parse_matrix_payload(raw_matrix_payload)
            if m12 is not None and verts:
                baked = apply_matrix_to_vertices(verts, m12)
                out_children.append(build_points_chunk_from(baked))
                changed = True
            else:
                out_children.append(raw)  # fallback keep original
        elif kcid == OBJECT_TRANS_MATRIX and (bake or strip):
            # drop it
            changed = True
            continue
        else:
            out_children.append(raw)

    # Add smoothing if requested and not present
    if add_smoothing and not had_smoothing and face_count > 0:
        out_children.append(build_smoothing_chunk(face_count, group_value=1))
        changed = True

    if not changed:
        return mesh_raw

    # Rewrap as OBJECT_MESH
    new_body = b"".join(out_children)
    return write_chunk(OBJECT_MESH, new_body)

# ---------------------------
# OBJECT patcher
# ---------------------------
def patch_object(obj_raw: bytes, *, bake: bool, strip: bool, add_smoothing: bool) -> bytes:
    cid, ln = read_chunk_header(obj_raw, 0)
    assert cid == OBJECT and ln == len(obj_raw), "Invalid OBJECT blob."

    name, after_name = read_cstr(obj_raw, 6)
    kids = find_children(obj_raw, after_name, len(obj_raw))

    out_children: List[bytes] = []
    touched = False
    for kcid, start, clen, body in kids:
        raw = obj_raw[start:start+clen]
        if kcid == OBJECT_MESH:
            patched = patch_object_mesh(raw, bake=bake, strip=strip, add_smoothing=add_smoothing)
            out_children.append(patched)
            if patched != raw:
                touched = True
        else:
            out_children.append(raw)

    if not touched:
        return obj_raw

    body = name.encode("ascii", errors="replace") + b"\x00" + b"".join(out_children)
    return write_chunk(OBJECT, body)

# ---------------------------
# OBJECTINFO patcher
# ---------------------------
def patch_objectinfo(oi_raw: bytes, *, bake: bool, strip: bool, add_smoothing: bool) -> bytes:
    cid, ln = read_chunk_header(oi_raw, 0)
    assert cid == OBJECTINFO and ln == len(oi_raw)

    kids = find_children(oi_raw, 6, len(oi_raw))
    out_children: List[bytes] = []
    touched = False
    for kcid, start, clen, body in kids:
        raw = oi_raw[start:start+clen]
        if kcid == OBJECT:
            patched = patch_object(raw, bake=bake, strip=strip, add_smoothing=add_smoothing)
            out_children.append(patched)
            if patched != raw:
                touched = True
        else:
            out_children.append(raw)

    if not touched:
        return oi_raw
    return write_chunk(OBJECTINFO, b"".join(out_children))

# ---------------------------
# File patcher (PRIMARY)
# ---------------------------
def patch_file(src: Path, dst: Path, *, bake: bool, strip: bool, add_smoothing: bool) -> None:
    data = src.read_bytes()
    ch0 = read_chunk_header(data, 0)
    if not ch0 or ch0[0] != PRIMARY:
        raise RuntimeError("Not a .3ds file (PRIMARY 0x4D4D missing).")
    _, ln0 = ch0
    prim_kids = find_children(data, 6, ln0)

    out_kids: List[bytes] = []
    touched = False

    for cid, start, clen, body in prim_kids:
        raw = data[start:start+clen]
        if cid == OBJECTINFO:
            patched = patch_objectinfo(raw, bake=bake, strip=strip, add_smoothing=add_smoothing)
            out_kids.append(patched)
            if patched != raw:
                touched = True
        else:
            out_kids.append(raw)

    if not touched:
        # Nothing changed: write original bytes
        dst.write_bytes(data)
        return

    dst.write_bytes(write_chunk(PRIMARY, b"".join(out_kids)))

# ---------------------------
# CLI
# ---------------------------
def main():
    ap = argparse.ArgumentParser(description="Bake or strip 3DS object transforms to prevent Blender 'exploding' imports.")
    ap.add_argument("input", help="Path to input .3ds")
    ap.add_argument("-o", "--output", help="Path to output .3ds (default: alongside source, suffix _blender)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bake", action="store_true", help="Bake 0x4160 matrices into vertices and remove 0x4160 (recommended)")
    g.add_argument("--strip", action="store_true", help="Remove 0x4160 matrices without baking (debug only)")
    ap.add_argument("--add-smoothing", action="store_true", help="If no 0x4150 present, add a simple smoothing block (group=1)")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists() or src.suffix.lower() != ".3ds":
        print(f"[ERR] Not a valid .3ds file: {src}")
        sys.exit(2)

    out = Path(args.output) if args.output else src.with_name(src.stem + "_blender.3ds")

    try:
        patch_file(src, out, bake=args.bake, strip=args.strip, add_smoothing=args.add_smoothing)
    except Exception as ex:
        print(f"[ERR] Patch failed: {ex}")
        sys.exit(3)

    mode = "BAKE" if args.bake else "STRIP"
    print(f"[OK] Wrote: {out}  (mode={mode}{', +smoothing' if args.add_smoothing else ''})")

if __name__ == "__main__":
    main()

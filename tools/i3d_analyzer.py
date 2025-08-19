#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
I3D/3DS Analyzer — single file (registry-based)

Outputs (written to a directory named after the source file without extension):
  1) <file>.dump.txt            — Human-readable text dump (structural + values)
  2) report.json                — Nested JSON with minimal keys per node:
                                  - id_hex, name
                                  - lines: only if value lines exist
                                  - children: only if non-empty
  3) summary.md                 — High-level stats
  4) chunk_tree.md              — Flat tree of chunks with offsets/sizes
  5) chunks_by_cid.md           — Chunks grouped by ID
  6) unknown_ids.md             — Unknown chunk IDs encountered
  7) unused_known_ids.md        — Known IDs (registry) not used in this file
  8) anomalies.md               — Parse anomalies (invalid sizes, truncations)
  9) viewports.md               — Parsed viewport/display blocks (optional table)

Design:
- Structural/header lines go to the text dump only (via dump_line).
- “Value” lines (actual data like vertices, faces, materials, UVs, KF keys, etc.)
  are emitted to the dump AND collected for JSON (via value_line).
- Value lines are attached to the chunk index currently being handled.

Usage:
  python i3d_analyzer.py file.i3d

Notes:
- Built and tested on static I3D/3DS-like chunks. Animation/maps have limited coverage.
- I3D is derived from 3DS, but some vendor or viewport/display blocks may be quirky.
"""

import os
import sys
import struct
import json
from collections import defaultdict
from pathlib import Path

# -----------------------------
# I/O helpers
# -----------------------------
def read_chunk(f):
    hdr = f.read(6)
    if len(hdr) < 6:
        return None
    return struct.unpack("<HI", hdr)

def read_cstr_from_bytes(buf, start, limit):
    end = start
    while end < limit and buf[end] != 0:
        end += 1
    if end >= limit:
        return None, start
    try:
        s = bytes(buf[start:end]).decode("ascii", errors="replace")
    except Exception:
        s = bytes(buf[start:end]).decode("latin1", errors="replace")
    return s, end + 1

def read_cstr(f):
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

# -----------------------------
# Formatting helpers (shorten noisy floats)
# -----------------------------
def fmtf(x):
    """Nice float formatter: trims noise while keeping detail."""
    if x is None:
        return "0"
    if abs(x) < 1e-7:
        return "0"
    s = f"{x:.6g}"
    if s.endswith("."):
        s = s[:-1]
    return s

def fmt3(a, b, c):
    return f"({fmtf(a)}, {fmtf(b)}, {fmtf(c)})"

# -----------------------------
# Dump vs JSON line capture
# -----------------------------
LINES_MAP = defaultdict(list)   # chunk_index -> [value lines]
_CURRENT_CHUNK_IDX_STACK = []   # for scoping

def _current_chunk_idx():
    return _CURRENT_CHUNK_IDX_STACK[-1] if _CURRENT_CHUNK_IDX_STACK else None

def dump_line(out, depth, text):
    """Write only to the text dump (NOT to JSON)."""
    out.write(("\t" * depth) + text + "\n")

def value_line(out, depth, text, *, to_idx=None):
    """Write to the text dump AND record as a value line for JSON."""
    out.write(("\t" * depth) + text + "\n")
    idx = to_idx if to_idx is not None else _current_chunk_idx()
    if idx is not None:
        LINES_MAP[idx].append(text)

def dump_hex_preview(out, depth, data, max_bytes=64):
    show = data[:max_bytes]
    hx = " ".join(f"{b:02X}" for b in show)
    more = "" if len(data) <= max_bytes else f" … (+{len(data)-max_bytes} bytes)"
    dump_line(out, depth, f"Hex: {hx}{more}")

# -----------------------------
# Percent & color readers
# -----------------------------
def _read_color_block(f, sub_end):
    pos0 = f.tell()
    inner = read_chunk(f)
    if not inner:
        f.seek(sub_end)
        return None
    cid, ln = inner
    if ln < 6 or pos0 + ln > sub_end:
        f.seek(pos0 + ln if ln >= 6 else sub_end)
        return None
    if cid == 0x0011 and ln >= 9:
        rgb = f.read(3)
        f.seek(pos0 + ln)
        return tuple(int(b) for b in rgb)
    elif cid in (0x0010, 0x0013) and ln >= 18:
        r, g, b = struct.unpack("<fff", f.read(12))
        f.seek(pos0 + ln)
        clamp = lambda x: int(max(0, min(255, round(x * 255))))
        return (clamp(r), clamp(g), clamp(b))
    f.seek(pos0 + ln)
    return None

def _read_pct_block(f, sub_end):
    pos = f.tell()
    inner = read_chunk(f)
    if not inner:
        return None
    icid, ln = inner
    if ln < 6 or pos + ln > sub_end:
        return None
    if icid == 0x0030 and ln >= 8:
        v = struct.unpack("<H", f.read(2))[0]
        f.seek(pos + ln)
        return v
    if icid == 0x0031 and ln >= 10:
        v = struct.unpack("<f", f.read(4))[0]
        f.seek(pos + ln)
        return round(v * 100.0, 2)
    f.seek(pos + ln)
    return None

# -----------------------------
# Chunk registry
# -----------------------------
CID_REG = {
    0x4D4D: {"name": "PRIMARY", "strategy": "container"},
    
    0xA08A: {"name": "MAT_TRANS_FALLOFF_IN", "strategy": "flat"},    
    0xA08C: {"name": "MAT_SOFTEN", "strategy": "flat"},

    0x0002: {"name": "M3D_VERSION", "strategy": "flat"},
    0x3D3D: {"name": "OBJECTINFO", "strategy": "container"},
    0x3D3E: {"name": "EDIT_CONFIG", "strategy": "flat"},

    0xAFFF: {"name": "MATERIAL", "strategy": "container"},
    0xA000: {"name": "MAT_NAME", "strategy": "auto"},
    0xA010: {"name": "MAT_AMBIENT", "strategy": "auto"},
    0xA020: {"name": "MAT_DIFFUSE", "strategy": "auto"},
    0xA030: {"name": "MAT_SPECULAR", "strategy": "auto"},
    0xA040: {"name": "MAT_SHININESS", "strategy": "auto"},
    0xA041: {"name": "MAT_SHIN2PCT", "strategy": "auto"},
    0xA050: {"name": "MAT_TRANSPARENCY", "strategy": "auto"},
    0xA052: {"name": "MAT_XPFALL", "strategy": "auto"},
    0xA053: {"name": "MAT_REFBLUR", "strategy": "auto"},
    0xA081: {"name": "MAT_TWO_SIDE", "strategy": "flat"},
    0xA084: {"name": "MAT_SELF_ILPCT", "strategy": "auto"},
    0xA087: {"name": "MAT_WIRESIZE", "strategy": "flat"},
    0xA100: {"name": "MAT_SHADING", "strategy": "flat"},
    0xA200: {"name": "MAT_TEXMAP", "strategy": "container"},
    0xA300: {"name": "MAT_MAP_FILEPATH", "strategy": "flat"},
    0xA351: {"name": "MAT_MAP_TILING", "strategy": "flat"},
    0xA353: {"name": "MAT_MAP_TEXBLUR", "strategy": "flat"},

    0x4000: {"name": "OBJECT", "strategy": "container"},
    0x4100: {"name": "OBJECT_MESH", "strategy": "container"},
    0x4110: {"name": "POINT_ARRAY", "strategy": "flat"},
    0x4111: {"name": "VERTEX_OPTIONS", "strategy": "flat"},
    0x4120: {"name": "OBJECT_FACES", "strategy": "container"},
    0x4130: {"name": "OBJECT_MATERIAL", "strategy": "flat"},
    0x4140: {"name": "OBJECT_UV", "strategy": "flat"},
    0x4150: {"name": "OBJECT_SMOOTH", "strategy": "flat"},
    0x4160: {"name": "OBJECT_TRANS_MATRIX", "strategy": "flat"},
    0x4165: {"name": "OBJECT_TRI_VISIBLE", "strategy": "flat"},
    0x4170: {"name": "MESH_TEXTURE_INFO", "strategy": "auto"},
    0x4190: {"name": "MESH_COLOR", "strategy": "auto"},
    0x4200: {"name": "FACE_MAP_CHANNEL", "strategy": "flat"},

    0x4600: {"name": "OBJECT_LIGHT", "strategy": "container"},
    0x4700: {"name": "OBJECT_CAMERA", "strategy": "container"},

    0xB000: {"name": "KFDATA", "strategy": "container"},
    0xB00A: {"name": "KFHDR", "strategy": "flat"},
    0xB008: {"name": "KFCURTIME_RANGE", "strategy": "flat"},
    0xB009: {"name": "KFCURTIME", "strategy": "flat"},
    0xB002: {"name": "OBJECT_NODE_TAG", "strategy": "container"},
    0xB003: {"name": "CAMERA_NODE_TAG", "strategy": "container"},
    0xB004: {"name": "TARGET_NODE_TAG", "strategy": "container"},
    0xB005: {"name": "LIGHT_NODE_TAG", "strategy": "container"},
    0xB006: {"name": "L_TARGET_NODE_TAG", "strategy": "container"},
    0xB007: {"name": "SPOTLIGHT_NODE_TAG", "strategy": "container"},
    0xB010: {"name": "NODE_HDR", "strategy": "flat"},
    0xB011: {"name": "INSTANCE_NAME", "strategy": "flat"},
    0xB013: {"name": "PIVOT", "strategy": "flat"},
    0xB014: {"name": "BOUNDBOX", "strategy": "flat"},
    0xB020: {"name": "POS_TRACK_TAG", "strategy": "flat"},
    0xB021: {"name": "ROT_TRACK_TAG", "strategy": "flat"},
    0xB022: {"name": "SCL_TRACK_TAG", "strategy": "flat"},

    0x7001: {"name": "VIEWPORT_LAYOUT", "strategy": "flat"},
    0x7011: {"name": "VIEWPORT_DATA", "strategy": "flat"},
    0x7012: {"name": "VIEWPORT_DATA_3", "strategy": "flat"},
    0x7020: {"name": "MESH_DISPLAY", "strategy": "flat"},
}

# Add helper/color/percent and KF ids so they aren't UNKNOWN
CID_REG.update({
    0x0030: {"name": "PERCENT_I", "strategy": "flat"},
    0x0031: {"name": "PERCENT_F", "strategy": "flat"},
    0x0010: {"name": "COLOR_FLOAT", "strategy": "auto"},
    0x0011: {"name": "COLOR_24", "strategy": "auto"},
    0x0013: {"name": "LIN_COLOR_24F", "strategy": "auto"},
    0xB030: {"name": "NODE_ID", "strategy": "flat"},
})

REF = {cid: meta["name"] for cid, meta in CID_REG.items()}

def cid_name(cid: int) -> str:
    meta = CID_REG.get(cid)
    return meta["name"] if meta else f"UNKNOWN_{cid:04X}"

def is_flat_chunk(cid: int) -> bool:
    meta = CID_REG.get(cid)
    return meta is not None and meta.get("strategy") == "flat"

def is_container_chunk(cid: int) -> bool:
    meta = CID_REG.get(cid)
    return meta is not None and meta.get("strategy") == "container"

def is_auto_chunk(cid: int) -> bool:
    meta = CID_REG.get(cid)
    return meta is None or meta.get("strategy") == "auto"

def maybe_nested(f, region_end, parent_cid=None):
    if parent_cid is not None and is_flat_chunk(parent_cid):
        return False
    pos = f.tell()
    if region_end - pos < 6:
        return False
    peek = f.read(6); f.seek(pos)
    if len(peek) < 6:
        return False
    inner_id, inner_len = struct.unpack("<HI", peek)
    return inner_len >= 6 and (pos + inner_len) <= region_end

# -----------------------------
# Viewport helpers (optional)
# -----------------------------
VIEW_ENUM = {
    0: "Top", 1: "Bottom", 2: "Left", 3: "Right",
    4: "Front", 5: "Back", 6: "User", 7: "Camera",
    8: "Light", 9: "Disabled"
}

VIEWPORT_LOG = []  # Optional per-run summary table (for viewports.md)

def _parse_viewport_tail(tail_bytes, view_type):
    out = {
        "zoom": None, "pan_x": None, "pan_y": None,
        "rect_l": None, "rect_t": None, "rect_r": None, "rect_b": None,
        "ref_name": None
    }
    buf = tail_bytes
    n = len(buf)
    off = 0

    def _read_float_at(o):
        if o + 4 <= n:
            (v,) = struct.unpack_from("<f", buf, o)
            if v == v and abs(v) < 1e12:
                return v
        return None

    z = _read_float_at(off)
    if z is not None:
        out["zoom"] = z; off += 4

    def _read_rect_int16(o):
        if o + 8 <= n:
            l, t, r, b = struct.unpack_from("<hhhh", buf, o)
            return l, t, r, b
        return None

    def _read_rect_int32(o):
        if o + 16 <= n:
            l, t, r, b = struct.unpack_from("<iiii", buf, o)
            return l, t, r, b
        return None

    px = _read_float_at(off)
    py = _read_float_at(off + 4) if px is not None else None
    if px is not None and py is not None:
        out["pan_x"] = px; out["pan_y"] = py; off += 8

    rect16 = _read_rect_int16(off)
    if rect16 is not None:
        out["rect_l"], out["rect_t"], out["rect_r"], out["rect_b"] = rect16
    else:
        rect32 = _read_rect_int32(off)
        if rect32 is not None:
            out["rect_l"], out["rect_t"], out["rect_r"], out["rect_b"] = rect32

    if view_type in (7, 8):  # Camera or Light → trailing c-string name
        name, _ = read_cstr_from_bytes(buf, off, n)
        if name and 1 <= len(name) <= 64:
            out["ref_name"] = name
    return out

# -----------------------------
# Chunk bookkeeping
# -----------------------------
def register_chunk(chunks, cid, length, offset, depth, parent):
    idx = len(chunks)
    chunks.append({
        "index": idx, "id": cid, "offset": offset, "size": length,
        "depth": depth, "parent": parent, "children": [],
        "payload_start": offset + 6, "payload_end": offset + length
    })
    if parent is not None and parent >= 0:
        chunks[parent]["children"].append(idx)
    _ = LINES_MAP[idx]  # ensure key exists
    return idx

# -----------------------------
# Specialized handlers
# -----------------------------
def decode_m3d_version(f, ln, depth, out, *, to_idx):
    if ln >= 10 and to_idx is not None:
        v = struct.unpack("<I", f.read(4))[0]
        value_line(out, depth, f"M3D Version: {v}", to_idx=to_idx)

def decode_mesh_version(f, ln, depth, out, *, to_idx):
    if ln >= 10 and to_idx is not None:
        v = struct.unpack("<I", f.read(4))[0]
        value_line(out, depth, f"Mesh Version: {v}", to_idx=to_idx)

def _is_printable(s: str) -> bool:
    if not s or not s.strip():
        return False
    return all((ord(c) >= 32 or c in "\t\n\r") for c in s)

def decode_kfhdr(f, ln, depth, out, *, to_idx):
    start = f.tell() - 6; end = start + ln
    name = read_cstr(f)
    if to_idx is not None and _is_printable(name):
        value_line(out, depth, f"KFHDR name: {name}", to_idx=to_idx)
    f.seek(end)

def decode_kfcurtime_range(f, ln, depth, out, *, to_idx):
    start = f.tell() - 6; end = start + ln
    vals = []
    while f.tell() + 4 <= end and len(vals) < 2:
        vals.append(struct.unpack("<I", f.read(4))[0])
    if to_idx is not None and vals:
        if len(vals) >= 2:
            value_line(out, depth, f"TIME_RANGE: start={vals[0]} end={vals[1]}", to_idx=to_idx)
        else:
            value_line(out, depth, f"TIME_RANGE: start={vals[0]}", to_idx=to_idx)
    f.seek(end)

def decode_kfcurtime(f, ln, depth, out, *, to_idx):
    start = f.tell() - 6; end = start + ln
    cur = None
    if f.tell() + 4 <= end:
        (cur,) = struct.unpack("<I", f.read(4))
    if to_idx is not None and cur is not None:
        value_line(out, depth, f"CURTIME: {cur}", to_idx=to_idx)
    f.seek(end)

def handle_material_texmap(f, ln, depth, out, chunks, anomalies, parent_idx):
    start = f.tell() - 6; end = start + ln
    while f.tell() < end:
        at = f.tell()
        sub = read_chunk(f)
        if not sub: break
        scid, slen = sub
        sidx = register_chunk(chunks, scid, slen, at, depth, parent_idx)
        sub_end = at + slen
        _CURRENT_CHUNK_IDX_STACK.append(sidx)
        try:
            dump_line(out, depth, f"{cid_name(scid)} (ID: 0x{scid:04X}, Length: {slen}) at Pos: {at}")
            if scid == 0x0030 and slen >= 8:
                pct = _read_pct_block(f, sub_end)
                if pct is not None:
                    value_line(out, depth, f"Map Amount: {pct}%", to_idx=sidx)
            elif scid == 0xA300:
                value_line(out, depth, f"Texture File: {read_cstr(f)}", to_idx=sidx)
            elif scid == 0xA351 and slen >= 8:
                til = struct.unpack("<H", f.read(2))[0]
                value_line(out, depth, f"Tiling Flags: 0x{til:04X}", to_idx=sidx)
            elif scid == 0xA353 and slen >= 10:
                blur = struct.unpack("<f", f.read(4))[0]
                value_line(out, depth, f"Texture Blur: {fmtf(blur)}", to_idx=sidx)
            else:
                if scid in CID_REG and (is_container_chunk(scid) or is_auto_chunk(scid) and maybe_nested(f, sub_end, scid)):
                    process_region(f, f.tell(), sub_end, depth + 1, out, chunks, anomalies, sidx)
                else:
                    data = f.read(max(0, slen - 6))
                    dump_line(out, depth, f"Unknown TexMap 0x{scid:04X}")
                    if data: dump_hex_preview(out, depth + 1, data)
        finally:
            _CURRENT_CHUNK_IDX_STACK.pop()
            f.seek(sub_end)
    f.seek(end)

def handle_material(f, ln, depth, out, chunks, anomalies, parent_idx):
    start = f.tell() - 6; end = start + ln
    while f.tell() < end:
        at = f.tell()
        sub = read_chunk(f)
        if not sub: break
        scid, slen = sub
        sidx = register_chunk(chunks, scid, slen, at, depth, parent_idx)
        sub_end = at + slen
        _CURRENT_CHUNK_IDX_STACK.append(sidx)
        try:
            dump_line(out, depth, f"{cid_name(scid)} (ID: 0x{scid:04X}, Length: {slen}) at Pos: {at}")
            if scid == 0xA000:
                value_line(out, depth, f"Material Name: {read_cstr(f)}", to_idx=sidx)
            elif scid in (0xA010, 0xA020, 0xA030):
                rgb = _read_color_block(f, sub_end)
                label = {0xA010: "Ambient", 0xA020: "Diffuse", 0xA030: "Specular"}[scid]
                if rgb:
                    value_line(out, depth, f"{label}: #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}", to_idx=sidx)
            elif scid in (0xA040, 0xA041, 0xA050, 0xA052, 0xA053, 0xA084):
                label = {
                    0xA040: "Shininess", 0xA041: "Shine Strength", 0xA050: "Transparency",
                    0xA052: "Transp Falloff", 0xA053: "Ref Blur", 0xA084: "Self Illumination",
                }[scid]
                pct = _read_pct_block(f, sub_end)
                if pct is not None:
                    value_line(out, depth, f"{label}: {pct}%", to_idx=sidx)
                else:
                    if scid == 0xA053 and (sub_end - f.tell()) >= 4:
                        try:
                            v = struct.unpack("<f", f.read(4))[0]
                            value_line(out, depth, f"{label} (float): {fmtf(v)}", to_idx=sidx)
                        except Exception:
                            pass
            elif scid == 0xA081 and slen == 6:
                value_line(out, depth, "Two-sided: ON", to_idx=sidx)            
            elif scid == 0xA08A and slen == 6:
                value_line(out, depth, "Opacity Falloff: IN (flag)", to_idx=sidx)
            elif scid == 0xA08C and slen == 6:
                value_line(out, depth, "Soften: ON", to_idx=sidx)
            elif scid == 0xA087 and slen >= 10:
                v = struct.unpack("<f", f.read(4))[0]
                value_line(out, depth, f"Wire Size: {fmtf(v)}", to_idx=sidx)
            elif scid == 0xA100 and slen >= 8:
                mode = struct.unpack("<H", f.read(2))[0]
                table = {0: "Wireframe", 1: "Flat", 2: "Gouraud", 3: "Phong", 4: "Metal"}
                value_line(out, depth, f"Shading: {table.get(mode, f'Unknown({mode})')}", to_idx=sidx)
            elif scid == 0xA200:
                handle_material_texmap(f, slen, depth + 1, out, chunks, anomalies, sidx)
            else:
                if scid in CID_REG and (is_container_chunk(scid) or is_auto_chunk(scid) and maybe_nested(f, sub_end, scid)):
                    process_region(f, f.tell(), sub_end, depth + 1, out, chunks, anomalies, sidx)
        finally:
            _CURRENT_CHUNK_IDX_STACK.pop()
            f.seek(sub_end)
    f.seek(end)

def handle_object_name(f, ln, depth, out, chunks, anomalies, parent_idx):
    start = f.tell() - 6; end = start + ln
    name = read_cstr(f)
    # name is a *value* of the OBJECT (0x4000) itself
    value_line(out, depth, f"Object Name: {name}", to_idx=parent_idx)
    if f.tell() < end:
        process_region(f, f.tell(), end, depth + 1, out, chunks, anomalies, parent_idx)
    f.seek(end)

def handle_object_material_flat(f, ln, depth, out, *, to_idx):
    """0x4130: <cstr name><u16 count><count * u16 face_idx> (flat)."""
    start = f.tell() - 6
    end = start + ln
    name = read_cstr(f)
    cnt = 0
    if f.tell() + 2 <= end:
        cnt = struct.unpack("<H", f.read(2))[0]
    value_line(out, depth, f"Material name: {name}", to_idx=to_idx)
    value_line(out, depth, f"Number of faces using this material: {cnt}", to_idx=to_idx)
    remaining = max(0, end - f.tell())
    read_cnt = min(cnt, remaining // 2)
    for _ in range(read_cnt):
        (face_idx,) = struct.unpack("<H", f.read(2))
        value_line(out, depth + 1, f"Face index: {face_idx}", to_idx=to_idx)
    if read_cnt < cnt:
        value_line(out, depth, f"[WARN] material face list truncated (read {read_cnt}/{cnt})", to_idx=to_idx)
    f.seek(end)

def handle_object_smooth_flat(f, ln, depth, out, *, to_idx):
    """0x4150: u32 per face (flat)."""
    start = f.tell() - 6
    end = start + ln
    count = max(0, (end - f.tell()) // 4)
    masks = []
    for _ in range(count):
        (mask,) = struct.unpack("<I", f.read(4))
        masks.append(mask)
    def first_group(m):
        if m == 0: return "0"
        for i in range(32):
            if (m >> i) & 1:
                return str(i + 1)
        return "0"
    if masks:
        display = ", ".join(first_group(m) for m in masks)
        value_line(out, depth, f"Smoothing Groups: ({display})", to_idx=to_idx)
    f.seek(end)

def handle_object_mesh(f, ln, depth, out, chunks, anomalies, parent_idx):
    start = f.tell() - 6
    end = start + ln
    while f.tell() < end:
        at = f.tell()
        sub = read_chunk(f)
        if not sub: break
        scid, slen = sub
        sidx = register_chunk(chunks, scid, slen, at, depth, parent_idx)
        sub_end = at + slen

        _CURRENT_CHUNK_IDX_STACK.append(sidx)
        try:
            dump_line(out, depth, f"{cid_name(scid)} (ID: 0x{scid:04X}, Length: {slen}) at Pos: {at}")

            if scid == 0x4110 and slen >= 8:
                if f.tell() + 2 > sub_end:
                    value_line(out, depth + 1, "Vertices: [truncated header]", to_idx=sidx)
                    f.seek(sub_end); continue
                vcount = struct.unpack("<H", f.read(2))[0]
                value_line(out, depth + 1, f"Vertices: {vcount}", to_idx=sidx)
                have = max(0, sub_end - f.tell())
                read_cnt = min(vcount, have // 12)
                for i in range(read_cnt):
                    x, y, z = struct.unpack("<fff", f.read(12))
                    value_line(out, depth + 1, f"Vertex[{i}]: {fmt3(x,y,z)}", to_idx=sidx)
                if read_cnt < vcount:
                    value_line(out, depth + 1, f"[WARN] vertex array truncated (read {read_cnt}/{vcount})", to_idx=sidx)
                f.seek(sub_end)

            elif scid == 0x4120 and slen >= 8:
                if f.tell() + 2 > sub_end:
                    value_line(out, depth + 1, "Faces: [truncated header]", to_idx=sidx)
                    f.seek(sub_end); continue
                num_faces = struct.unpack("<H", f.read(2))[0]
                value_line(out, depth + 1, f"Faces: {num_faces}", to_idx=sidx)
                entry_sz = 8
                have = max(0, sub_end - f.tell())
                read_cnt = min(num_faces, have // entry_sz)
                for i in range(read_cnt):
                    a, b, c, flags = struct.unpack("<HHHH", f.read(8))
                    value_line(out, depth + 1, f"Face[{i}]: ({a}, {b}, {c}) flags=0x{flags:04X}", to_idx=sidx)
                if read_cnt < num_faces:
                    value_line(out, depth + 1, f"[WARN] face array truncated (read {read_cnt}/{num_faces})", to_idx=sidx)
                if f.tell() < sub_end:
                    process_region(f, f.tell(), sub_end, depth + 2, out, chunks, anomalies, sidx)
                f.seek(sub_end)

            elif scid == 0x4130:
                handle_object_material_flat(f, slen, depth + 1, out, to_idx=sidx)
                f.seek(sub_end)

            elif scid == 0x4140 and slen >= 8:
                if f.tell() + 2 > sub_end:
                    value_line(out, depth + 1, "UVs: [truncated header]", to_idx=sidx)
                    f.seek(sub_end); continue
                uv_count = struct.unpack("<H", f.read(2))[0]
                value_line(out, depth + 1, f"UV count: {uv_count}", to_idx=sidx)
                have = max(0, sub_end - f.tell())
                read_cnt = min(uv_count, have // 8)
                for i in range(read_cnt):
                    u, v = struct.unpack("<ff", f.read(8))
                    value_line(out, depth + 1, f"UV[{i}]: ({fmtf(u)}, {fmtf(v)})", to_idx=sidx)
                if read_cnt < uv_count:
                    value_line(out, depth + 1, f"[WARN] UV array truncated (read {read_cnt}/{uv_count})", to_idx=sidx)
                f.seek(sub_end)

            elif scid == 0x4150:
                handle_object_smooth_flat(f, slen, depth + 1, out, to_idx=sidx)
                f.seek(sub_end)

            elif scid == 0x4160 and slen >= 6 + 48:
                mat = struct.unpack("<12f", f.read(48))
                mat_fmt = ", ".join(fmtf(v) for v in mat)
                value_line(out, depth + 1, f"Xform: ({mat_fmt})", to_idx=sidx)
                f.seek(sub_end)

            elif scid == 0x4165 and slen >= 7:
                vis = struct.unpack("<B", f.read(1))[0]
                value_line(out, depth + 1, f"Visible: {'yes' if vis else 'no'}", to_idx=sidx)
                f.seek(sub_end)

            elif scid == 0x4200 and slen >= 12:
                if f.tell() + 6 > sub_end:
                    value_line(out, depth + 1, "FACE_MAP_CHANNEL: [truncated header]", to_idx=sidx)
                    f.seek(sub_end); continue
                channel_i, uv_count = struct.unpack("<I H", f.read(6))
                value_line(out, depth + 1, f"UV Channel: {channel_i}  count={uv_count}", to_idx=sidx)
                uv_bytes = uv_count * 8
                if f.tell() + uv_bytes > sub_end:
                    need = uv_bytes; have = max(0, sub_end - f.tell())
                    value_line(out, depth + 1, f"[WARN] 0x4200 UV list truncated (need {need}, have {have})", to_idx=sidx)
                    f.seek(sub_end); continue
                for i in range(uv_count):
                    u, v = struct.unpack("<ff", f.read(8))
                    value_line(out, depth + 1, f"UV[{i}]: ({fmtf(u)}, {fmtf(v)})", to_idx=sidx)
                if f.tell() + 2 > sub_end:
                    value_line(out, depth + 1, "[WARN] 0x4200 missing face-count", to_idx=sidx)
                    f.seek(sub_end); continue
                fcnt = struct.unpack("<H", f.read(2))[0]
                faces_bytes = fcnt * 6
                if f.tell() + faces_bytes > sub_end:
                    got = max(0, sub_end - f.tell())
                    value_line(out, depth + 1, f"[WARN] 0x4200 UV face list truncated (need {faces_bytes}, have {got})", to_idx=sidx)
                    f.seek(sub_end); continue
                for i in range(fcnt):
                    a, b, c = struct.unpack("<HHH", f.read(6))
                    value_line(out, depth + 1, f"UVFace[{i}]: ({a}, {b}, {c})", to_idx=sidx)
                if f.tell() < sub_end:
                    rem = sub_end - f.tell()
                    if rem > 0:
                        tail = f.read(min(32, rem))
                        value_line(out, depth + 1, f"[info] 0x4200 trailing bytes: {rem} (first 32 shown)", to_idx=sidx)
                        dump_hex_preview(out, depth + 2, tail)
                f.seek(sub_end)

            else:
                if scid in CID_REG and (is_container_chunk(scid) or is_auto_chunk(scid) and maybe_nested(f, sub_end, scid)):
                    process_region(f, f.tell(), sub_end, depth + 2, out, chunks, anomalies, sidx)
                else:
                    f.seek(sub_end)

        finally:
            _CURRENT_CHUNK_IDX_STACK.pop()
            f.seek(sub_end)

    f.seek(end)

# -------- Keyframer node helpers --------
def _read_track_header(f, limit_end):
    start = f.tell()
    if start + 14 > limit_end:
        return None
    flags = struct.unpack("<H", f.read(2))[0]
    u1 = struct.unpack("<I", f.read(4))[0]
    u2 = struct.unpack("<I", f.read(4))[0]
    keys = struct.unpack("<I", f.read(4))[0]
    return {"flags": flags, "u1": u1, "u2": u2, "keys": keys}

def _read_key_header(f, limit_end):
    if f.tell() + 6 > limit_end:
        return None
    frame = struct.unpack("<I", f.read(4))[0]
    kflags = struct.unpack("<H", f.read(2))[0]
    info = {"flags": kflags}
    def _opt(bit): return (kflags & bit) != 0
    if _opt(0x01) and f.tell() + 4 <= limit_end:
        info["tension"] = struct.unpack("<f", f.read(4))[0]
    if _opt(0x02) and f.tell() + 4 <= limit_end:
        info["continuity"] = struct.unpack("<f", f.read(4))[0]
    if _opt(0x04) and f.tell() + 4 <= limit_end:
        info["bias"] = struct.unpack("<f", f.read(4))[0]
    if _opt(0x08) and f.tell() + 4 <= limit_end:
        info["ease_to"] = struct.unpack("<f", f.read(4))[0]
    if _opt(0x10) and f.tell() + 4 <= limit_end:
        info["ease_from"] = struct.unpack("<f", f.read(4))[0]
    return frame, info

def handle_kf_node(f, ln, depth, out, chunks, anomalies, parent_idx):
    start = f.tell() - 6; end = start + ln
    while f.tell() < end:
        at = f.tell()
        sub = read_chunk(f)
        if not sub: break
        scid, slen = sub
        sidx = register_chunk(chunks, scid, slen, at, depth, parent_idx)
        sub_end = at + slen
        _CURRENT_CHUNK_IDX_STACK.append(sidx)
        try:
            dump_line(out, depth, f"{cid_name(scid)} (ID: 0x{scid:04X}, Length: {slen}) at Pos: {at}")
            if scid == 0xB030 and slen >= 8:
                node_id = struct.unpack("<H", f.read(2))[0]
                value_line(out, depth + 1, f"NODE_ID: {node_id}", to_idx=sidx)
            elif scid == 0xB010:
                _handle_node_hdr(f, slen, depth + 1, out, to_idx=sidx)
            elif scid == 0xB011:
                name = read_cstr(f)
                value_line(out, depth + 1, f"INSTANCE_NAME: {name}", to_idx=sidx)
            elif scid == 0xB013 and slen >= 6 + 12:
                px, py, pz = struct.unpack("<fff", f.read(12))
                value_line(out, depth + 1, f"PIVOT: {fmt3(px,py,pz)}", to_idx=sidx)
            elif scid == 0xB014 and slen >= 6 + 24:
                minx, miny, minz, maxx, maxy, maxz = struct.unpack("<ffffff", f.read(24))
                value_line(out, depth + 1, f"BOUNDBOX: min={fmt3(minx,miny,minz)} max={fmt3(maxx,maxy,maxz)}", to_idx=sidx)
            elif scid == 0xB020:
                _handle_pos_track(f, slen, depth + 1, out, to_idx=sidx)
            elif scid == 0xB021:
                _handle_rot_track(f, slen, depth + 1, out, to_idx=sidx)
            elif scid == 0xB022:
                _handle_scl_track(f, slen, depth + 1, out, to_idx=sidx)
            else:
                if scid in CID_REG and (is_container_chunk(scid) or is_auto_chunk(scid) and maybe_nested(f, sub_end, scid)):
                    process_region(f, f.tell(), sub_end, depth + 2, out, chunks, anomalies, sidx)
                else:
                    f.seek(sub_end)
        finally:
            _CURRENT_CHUNK_IDX_STACK.pop()
            f.seek(sub_end)
    f.seek(end)

def _handle_node_hdr(f, ln, depth, out, *, to_idx):
    start = f.tell() - 6
    end = start + ln
    name = read_cstr(f)
    flag1 = struct.unpack("<H", f.read(2))[0] if f.tell() + 2 <= end else 0
    flag2 = struct.unpack("<H", f.read(2))[0] if f.tell() + 2 <= end else 0
    parent_id = struct.unpack("<H", f.read(2))[0] if f.tell() + 2 <= end else 0xFFFF
    value_line(out, depth, f"NODE_HDR: name='{name}', Flag1=0x{flag1:04X}, Flag2=0x{flag2:04X}, Parent={parent_id}", to_idx=to_idx)
    f.seek(end)

def _handle_pos_track(f, ln, depth, out, *, to_idx):
    start = f.tell() - 6; end = start + ln
    hdr = _read_track_header(f, end)
    if not hdr:
        f.seek(end); return
    value_line(out, depth, f"POS_TRACK_TAG: keys={hdr['keys']} flags=0x{hdr['flags']:04X}", to_idx=to_idx)
    for _ in range(hdr["keys"]):
        kh = _read_key_header(f, end)
        if not kh: break
        frame, info = kh
        if f.tell() + 12 > end: break
        x, y, z = struct.unpack("<fff", f.read(12))
        value_line(out, depth, f"\t@{frame}: pos={fmt3(x,y,z)} {info}", to_idx=to_idx)
    f.seek(end)

def _handle_rot_track(f, ln, depth, out, *, to_idx):
    start = f.tell() - 6; end = start + ln
    hdr = _read_track_header(f, end)
    if not hdr:
        f.seek(end); return
    value_line(out, depth, f"ROT_TRACK_TAG: keys={hdr['keys']} flags=0x{hdr['flags']:04X}", to_idx=to_idx)
    for _ in range(hdr["keys"]):
        kh = _read_key_header(f, end)
        if not kh: break
        frame, info = kh
        if f.tell() + 16 > end: break
        ang, ax, ay, az = struct.unpack("<ffff", f.read(16))
        value_line(out, depth, f"\t@{frame}: rot=angle({fmtf(ang)}) axis={fmt3(ax,ay,az)} {info}", to_idx=to_idx)
    f.seek(end)

def _handle_scl_track(f, ln, depth, out, *, to_idx):
    start = f.tell() - 6; end = start + ln
    hdr = _read_track_header(f, end)
    if not hdr:
        f.seek(end); return
    value_line(out, depth, f"SCL_TRACK_TAG: keys={hdr['keys']} flags=0x{hdr['flags']:04X}", to_idx=to_idx)
    for _ in range(hdr["keys"]):
        kh = _read_key_header(f, end)
        if not kh: break
        frame, info = kh
        if f.tell() + 12 > end: break
        sx, sy, sz = struct.unpack("<fff", f.read(12))
        value_line(out, depth, f"\t@{frame}: scale={fmt3(sx,sy,sz)} {info}", to_idx=to_idx)
    f.seek(end)

# -----------------------------
# Viewport / Display handler (JSON-aware)
# -----------------------------
def handle_viewport_block(f, ln, depth, out, chunks, anomalies, parent_idx):
    start = f.tell() - 6
    end = start + ln

    # Read the view type (u16) if present
    view_type = None
    if end - f.tell() >= 2:
        (view_type,) = struct.unpack("<H", f.read(2))
        view_name = VIEW_ENUM.get(view_type, f"#{view_type}")
        dump_line(out, depth, f"Viewport view: {view_name}")
    else:
        view_name = None
        dump_line(out, depth, "Viewport: [too short to read view type]")

    # Read tail and show a short hex preview in the text dump
    tail_len = max(0, end - f.tell())
    tail_bytes = b""
    if tail_len:
        tail_bytes = f.read(tail_len)
        dump_hex_preview(out, depth, tail_bytes, max_bytes=64)

    # Parse known fields from the tail
    parsed = _parse_viewport_tail(tail_bytes, view_type if view_type is not None else -1)

    def _fmt(v, nd=6):
        if v is None:
            return "—"
        try:
            return f"{v:.{nd}g}"
        except Exception:
            return str(v)

    zoom_s = _fmt(parsed["zoom"])
    panx_s = _fmt(parsed["pan_x"])
    pany_s = _fmt(parsed["pan_y"])
    rl, rt, rr, rb = parsed["rect_l"], parsed["rect_t"], parsed["rect_r"], parsed["rect_b"]
    rect_s = f"[{rl},{rt},{rr},{rb}]" if None not in (rl, rt, rr, rb) else "—"
    ref_s = parsed["ref_name"] if parsed["ref_name"] else "—"

    # 1) Human dump (structural)
    dump_line(out, depth, f"Viewport zoom={zoom_s} pan=({panx_s},{pany_s}) rect={rect_s} ref={ref_s}")

    # 2) Record a single compact value line into JSON on the current chunk
    if parent_idx is not None:
        value_line(out, depth, f"Viewport: view={view_name or '—'}, zoom={zoom_s}, pan=({panx_s},{pany_s}), rect={rect_s}, ref={ref_s}", to_idx=parent_idx)

    # 3) Append to an in-memory log for optional MD report
    VIEWPORT_LOG.append({
        "offset": start,
        "view_type": view_type if view_type is not None else -1,
        "view_name": view_name or "",
        "bytes": ln,
        "zoom": parsed["zoom"],
        "pan_x": parsed["pan_x"],
        "pan_y": parsed["pan_y"],
        "rect_l": parsed["rect_l"],
        "rect_t": parsed["rect_t"],
        "rect_r": parsed["rect_r"],
        "rect_b": parsed["rect_b"],
        "ref_name": parsed["ref_name"],
    })

    f.seek(end)

# -----------------------------
# SPECIAL dispatch
# -----------------------------
SPECIAL = {
    0x4000: handle_object_name,
    0xAFFF: handle_material,
    0x4100: handle_object_mesh,

    0x0002: lambda f, ln, d, out, *_: decode_m3d_version(f, ln, d, out, to_idx=_current_chunk_idx()),
    0x3D3E: lambda f, ln, d, out, *_: decode_mesh_version(f, ln, d, out, to_idx=_current_chunk_idx()),

    0x4130: lambda f, ln, d, out, *_args, **_kw: handle_object_material_flat(f, ln, d, out, to_idx=_current_chunk_idx()),
    0x4150: lambda f, ln, d, out, *_args, **_kw: handle_object_smooth_flat(f, ln, d, out, to_idx=_current_chunk_idx()),

    # Keyframer flat headers → parsed & included in JSON when values exist
    0xB00A: lambda f, ln, d, out, *_: decode_kfhdr(f, ln, d, out, to_idx=_current_chunk_idx()),
    0xB008: lambda f, ln, d, out, *_: decode_kfcurtime_range(f, ln, d, out, to_idx=_current_chunk_idx()),
    0xB009: lambda f, ln, d, out, *_: decode_kfcurtime(f, ln, d, out, to_idx=_current_chunk_idx()),

    # KF node trees
    0xB002: handle_kf_node,
    0xB003: handle_kf_node,
    0xB004: handle_kf_node,
    0xB005: handle_kf_node,
    0xB006: handle_kf_node,
    0xB007: handle_kf_node,

    # Viewport / Display (flat) — JSON-aware handler
    0x7001: handle_viewport_block,
    0x7011: handle_viewport_block,
    0x7012: handle_viewport_block,
    0x7020: handle_viewport_block,
}

# -----------------------------
# Core walker
# -----------------------------
def process_region(f, region_start, region_end, depth, out, chunks, anomalies, parent_idx):
    f.seek(region_start)
    file_len = f.seek(0, os.SEEK_END)
    f.seek(region_start)
    while f.tell() < region_end:
        at = f.tell()
        ch = read_chunk(f)
        if not ch:
            anomalies.append({"type": "truncated_header", "offset": at})
            break
        cid, length = ch
        if length < 6:
            anomalies.append({"type": "invalid_size", "cid": cid, "offset": at, "size": length})
            break
        chunk_end = at + length
        if chunk_end > file_len:
            anomalies.append({"type": "exceeds_file", "cid": cid, "offset": at, "declared_end": chunk_end, "file_len": file_len})
            chunk_end = min(chunk_end, file_len)

        idx = register_chunk(chunks, cid, length, at, depth, parent_idx)

        _CURRENT_CHUNK_IDX_STACK.append(idx)
        try:
            dump_line(out, depth, f"{cid_name(cid)} (ID: 0x{cid:04X}, Length: {length}) at Pos: {at}")
            payload_start = f.tell()

            try:
                handler = SPECIAL.get(cid)
                if handler is None:
                    if is_flat_chunk(cid):
                        f.seek(chunk_end)
                    elif is_container_chunk(cid) or is_auto_chunk(cid):
                        if is_container_chunk(cid) or maybe_nested(f, chunk_end, parent_cid=cid):
                            process_region(f, payload_start, chunk_end, depth + 1, out, chunks, anomalies, idx)
                        else:
                            f.seek(chunk_end)
                else:
                    handler(f, length, depth + 1, out, chunks, anomalies, idx)

            except Exception as ex:
                value_line(out, depth + 1, f"[ERROR] parsing 0x{cid:04X}: {ex}", to_idx=idx)
                f.seek(chunk_end)

        finally:
            _CURRENT_CHUNK_IDX_STACK.pop()
            f.seek(chunk_end)

# -----------------------------
# JSON writer (minimal keys)
# -----------------------------
def _node_view_minimal(ch):
    return {
        "id_hex": f"0x{ch['id']:04X}",
        "name": REF.get(ch["id"], f"UNKNOWN_{ch['id']:04X}"),
        # 'lines' added only if present
        # 'children' added only if non-empty
    }

def _build_nested_tree(chunks):
    idx_to_node = {ch["index"]: _node_view_minimal(ch) for ch in chunks}

    # Attach non-empty lines only
    for idx, lines in LINES_MAP.items():
        if lines:
            idx_to_node[idx]["lines"] = list(lines)

    # Attach children only when non-empty
    for ch in chunks:
        if ch["children"]:
            idx_to_node[ch["index"]]["children"] = [idx_to_node[cidx] for cidx in ch["children"]]

    roots = [idx_to_node[ch["index"]] for ch in chunks if ch["parent"] is None]
    return roots

def write_json(outdir, src_path, chunks, anomalies):
    p = outdir / "report.json"
    tree = _build_nested_tree(chunks)
    payload = {
        "file": os.path.basename(src_path),
        "size": int(Path(src_path).stat().st_size),
        "chunks": tree,
    }
    if anomalies:
        payload["anomalies"] = anomalies
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")

# -----------------------------
# Markdown reports
# -----------------------------
def write_summary(outdir, chunks, unknown_ids, anomalies):
    p = outdir / "summary.md"
    lines = [
        "# I3D File Analysis — Summary", "",
        f"- Total chunks: **{len(chunks)}**",
        f"- Unique IDs: **{len(set(ch['id'] for ch in chunks))}**",
        f"- Unknown IDs encountered: **{len(unknown_ids)}**",
        f"- Anomalies: **{len(anomalies)}**" if anomalies else "- Anomalies: **0**",
        "",
        "_Note: values like `0x0000`/`0x0005` inside payloads and `0x0064` within percent blocks are **data values**, not chunk IDs._"
    ]
    p.write_text("\n".join(lines), encoding="utf-8")

def write_chunk_tree(outdir, chunks):
    p = outdir / "chunk_tree.md"
    lines = ["# Chunk Tree", ""]
    for ch in chunks:
        nm = REF.get(ch["id"], f"UNKNOWN_{ch['id']:04X}")
        lines.append(f"{'  '*ch['depth']}- `0x{ch['id']:04X}` **{nm}** (off={ch['offset']}, size={ch['size']})")
    p.write_text("\n".join(lines), encoding="utf-8")

def write_chunks_by_cid(outdir, chunks):
    p = outdir / "chunks_by_cid.md"
    groups = defaultdict(list)
    for ch in chunks:
        groups[ch["id"]].append(ch)
    lines = ["# Chunks Grouped by CID", ""]
    for cid in sorted(groups.keys()):
        lines.append(f"## `0x{cid:04X}` — {REF.get(cid, 'UNKNOWN')}")
        for ch in groups[cid]:
            lines.append(f"- idx={ch['index']}, off={ch['offset']}, size={ch['size']}, depth={ch['depth']}")
        lines.append("")
    p.write_text("\n".join(lines), encoding="utf-8")

def write_unknown_ids(outdir, chunks):
    p = outdir / "unknown_ids.md"
    seen = {}
    for ch in chunks:
        if ch["id"] not in CID_REG:
            seen.setdefault(ch["id"], []).append(ch)
    lines = ["# Unknown Chunk IDs", ""]
    if not seen:
        lines.append("- None")
    else:
        for cid in sorted(seen.keys()):
            lines.append(f"- `0x{cid:04X}` ({len(seen[cid])} occurrence(s))")
    p.write_text("\n".join(lines), encoding="utf-8")

def write_unused_known_ids(outdir, chunks):
    p = outdir / "unused_known_ids.md"
    used = set(ch["id"] for ch in chunks)
    unused = [(cid, meta["name"]) for cid, meta in CID_REG.items() if cid not in used]
    lines = [
        "# Unused Known Chunk IDs", "",
        "| ID (hex) | ID (dec) | Name |",
        "|----------|----------:|------|"
    ]
    if not unused:
        lines.append("| — | — | — |")
    else:
        for cid, name in sorted(unused):
            lines.append(f"| `0x{cid:04X}` | {cid} | {name} |")
    p.write_text("\n".join(lines), encoding="utf-8")

def write_anomalies(outdir, anomalies):
    p = outdir / "anomalies.md"
    lines = ["# Anomalies", ""]
    if not anomalies:
        lines.append("- None")
    else:
        for a in anomalies:
            lines.append(f"- {a}")
    p.write_text("\n".join(lines), encoding="utf-8")

def write_viewports(outdir):
    p = outdir / "viewports.md"
    lines = ["# Viewports / Display Blocks", ""]
    if not VIEWPORT_LOG:
        lines.append("- None found")
    else:
        lines.append(f"- Count: **{len(VIEWPORT_LOG)}**\n")
        lines.append("| View | Zoom | Pan (x,y) | Rect (l,t,r,b) | Ref | Bytes | Offset |")
        lines.append("|------|------|-----------|----------------|-----|-------:|--------:|")
        for v in VIEWPORT_LOG:
            view = v["view_name"] or f"#{v['view_type']}"
            zoom = "" if v["zoom"] is None else f"{v['zoom']:.6g}"
            panx = "" if v["pan_x"] is None else f"{v['pan_x']:.6g}"
            pany = "" if v["pan_y"] is None else f"{v['pan_y']:.6g}"
            rect = "—" if None in (v["rect_l"], v["rect_t"], v["rect_r"], v["rect_b"]) else f"[{v['rect_l']},{v['rect_t']},{v['rect_r']},{v['rect_b']}]"
            ref  = v["ref_name"] or "—"
            lines.append(f"| {view} | {zoom or '—'} | ({panx or '—'},{pany or '—'}) | {rect} | {ref} | {v['bytes']} | {v['offset']} |")
        lines.append("")
    p.write_text("\n".join(lines), encoding="utf-8")

# -----------------------------
# Entry
# -----------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python i3d_analyzer.py file.i3d")
        sys.exit(2)
    src = Path(sys.argv[1])
    if not src.exists() or not src.is_file():
        print(f"File not found: {src}")
        sys.exit(3)

    full_base_name = os.path.basename(src)
    base_no_ext = os.path.splitext(full_base_name)[0]
    outdir = Path(src.with_suffix(""))
    outdir = Path(outdir.parent) / base_no_ext.lower()
    outdir.mkdir(parents=True, exist_ok=True)
    dump_path = outdir / f"{full_base_name}.dump.txt"

    chunks = []
    anomalies = []

    with src.open("rb") as f, dump_path.open("w", encoding="utf-8") as out:
        size = src.stat().st_size
        out.write(f"Analyzing: {src} (size={size})\n")
        process_region(f, 0, size, 0, out, chunks, anomalies, None)

    # JSON output
    write_json(outdir, str(src), chunks, anomalies)

    # Markdown reports (same set as requested)
    seen = set(ch["id"] for ch in chunks)
    unknown = sorted(seen - set(CID_REG.keys()))
    write_summary(outdir, chunks, unknown, anomalies)
    write_chunk_tree(outdir, chunks)
    write_chunks_by_cid(outdir, chunks)
    write_unknown_ids(outdir, chunks)
    write_unused_known_ids(outdir, chunks)
    write_anomalies(outdir, anomalies)
    write_viewports(outdir)  # optional, handy for debugging

    print(f"OK: wrote reports to {outdir.resolve()}")

if __name__ == "__main__":
    main()

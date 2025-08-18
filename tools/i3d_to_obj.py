#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
I3D → OBJ Converter for Hidden & Dangerous (verbose by default)
----------------------------------------------------------------
- Extracts mesh + materials from Illusion Softworks .i3d binaries
- Uses FACE_MAP_CHANNEL (0x4200) ONLY for UVs (never 0x4140)
- Respects smoothing groups (0x4150)
- Optional baking of OBJECT_TRANS_MATRIX (0x4160) into positions
- Free-form axis remap: --transform "(x, -y, -z)" applied to every vertex
  (DEFAULT transform is (x, -y, -z); pass "(x, y, z)" for identity)
- Output .obj + .mtl filenames == base name of the .i3d
- Output written alongside the source .i3d (same directory)
"""

import os
import sys
import struct
import argparse
import re
from collections import defaultdict
from typing import Callable, Tuple, Optional

# ---------- Small helpers ----------------------------------------------------

def log(msg: str) -> None:
    print(msg)

def read_chunk(f):
    """Return (cid, length, endpos) or None if EOF."""
    hdr = f.read(6)
    if len(hdr) < 6:
        return None
    cid, length = struct.unpack("<HI", hdr)
    endpos = f.tell() + (length - 6)
    return cid, length, endpos

def read_cstr(f):
    """Read a 0-terminated ASCII string."""
    out = bytearray()
    while True:
        b = f.read(1)
        if not b or b == b"\x00":
            break
        out.extend(b)
    return out.decode("ascii", errors="replace")

def read_u16(f):  return struct.unpack("<H", f.read(2))[0]
def read_u32(f):  return struct.unpack("<I", f.read(4))[0]
def read_f32(f):  return struct.unpack("<f", f.read(4))[0]

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def _safe_newmtl_name(name: str) -> str:
    """
    Sanitize material name so viewers bind it reliably.
    - Trim CR/LF/outer space
    - Collapse internal whitespace
    - Replace spaces with underscores (MS 3D Viewer prefers no spaces)
    """
    if name is None:
        return "default"
    name = name.replace("\r", "").replace("\n", "").strip()
    name = re.sub(r"\s+", " ", name)
    name = name.replace(" ", "_")
    return name if name else "default"

def make_transform(expr: str) -> Callable[[Tuple[float,float,float]], Tuple[float,float,float]]:
    """
    Build a callable that applies a user-specified expression to (x,y,z).
    Example: "(x, -y, -z)" or "(-x, y, z)"
    """
    expr = expr.strip()
    if not (expr.startswith("(") and expr.endswith(")")):
        raise ValueError("Transform must be a tuple like '(x, -y, -z)'")
    def _apply(v):
        x, y, z = v
        return eval(expr, {}, {"x": x, "y": y, "z": z})
    test = _apply((1.0, 2.0, 3.0))
    if not (isinstance(test, (tuple, list)) and len(test) == 3):
        raise ValueError("Transform must evaluate to a 3-tuple, e.g. (x, -y, -z)")
    return _apply

# ---------- Chunk IDs (3DS/I3D-flavored) ------------------------------------

PRIMARY                 = 0x4D4D
OBJECTINFO              = 0x3D3D
EDIT_CONFIG             = 0x3D3E

MATERIAL                = 0xAFFF
MAT_NAME                = 0xA000
MAT_TEXMAP              = 0xA200
MAT_TEX_NAME            = 0xA300

OBJECT                  = 0x4000
OBJECT_MESH             = 0x4100
POINT_ARRAY             = 0x4110
OBJECT_FACES            = 0x4120
OBJECT_MATERIAL         = 0x4130
OBJECT_UV_PRIMARY       = 0x4140  # ignored here
OBJECT_SMOOTH           = 0x4150  # u32 per face bitmask
OBJECT_TRANS_MATRIX     = 0x4160  # 3x4 (row-major)
FACE_MAP_CHANNEL        = 0x4200  # (u32 channel) + UVs + per-face vt triplets

# ---------- Core I3D parser --------------------------------------------------

class I3DMesh:
    def __init__(self):
        self.name          = "Object"
        self.vertices      = []      # [(x,y,z), ...]
        self.faces         = []      # [(vi, vj, vk), ...] (u16 indices)
        self.face_flags    = []      # [u16] (not used by OBJ)
        self.smooth_masks  = []      # [u32]
        self.mat_faces     = defaultdict(list)  # mtl_name -> [face_index, ...]
        self.uv_channels   = {}      # ch -> {"uv": [(u,v),...], "tris": [(ta,tb,tc), ...]}
        self.matrix_3x4    = None    # 3x4 row-major transform

    def apply_bake_transform(self):
        if not self.matrix_3x4 or not self.vertices:
            return
        m = self.matrix_3x4
        vx = lambda x,y,z: m[0][0]*x + m[0][1]*y + m[0][2]*z + m[0][3]
        vy = lambda x,y,z: m[1][0]*x + m[1][1]*y + m[1][2]*z + m[1][3]
        vz = lambda x,y,z: m[2][0]*x + m[2][1]*y + m[2][2]*z + m[2][3]
        self.vertices = [(vx(x,y,z), vy(x,y,z), vz(x,y,z)) for (x,y,z) in self.vertices]

class I3DDoc:
    def __init__(self):
        self.mesh          = I3DMesh()
        self.materials     = {}   # name -> {"map_Kd": "file.png" (basename), ...}
        self.mesh_version  = None

def parse_i3d(path: str) -> I3DDoc:
    doc = I3DDoc()
    log(f"[I3D] Loading: {path}")
    with open(path, "rb") as f:
        while True:
            ch = read_chunk(f)
            if not ch:
                break
            cid, _length, endpos = ch
            if cid == PRIMARY:
                _parse_primary(f, endpos, doc)
            f.seek(endpos)
    _post_parse_log(doc)
    return doc

def _parse_primary(f, endpos, doc: I3DDoc):
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _length, e2 = ch
        if cid == OBJECTINFO:
            _parse_objectinfo(f, e2, doc)
        else:
            f.seek(e2)

def _parse_objectinfo(f, endpos, doc: I3DDoc):
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _length, e2 = ch
        if cid == EDIT_CONFIG:
            if e2 - f.tell() >= 4:
                doc.mesh_version = read_u32(f)
        elif cid == MATERIAL:
            _parse_material(f, e2, doc)
        elif cid == OBJECT:
            _parse_object(f, e2, doc.mesh)
        f.seek(e2)

def _parse_material(f, endpos, doc: I3DDoc):
    name = None
    tex  = None
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _length, e2 = ch
        if cid == MAT_NAME:
            name = read_cstr(f)
        elif cid == MAT_TEXMAP:
            while f.tell() < e2:
                ch2 = read_chunk(f)
                if not ch2: break
                cid2, _len2, e3 = ch2
                if cid2 == MAT_TEX_NAME:
                    tex = read_cstr(f)
                f.seek(e3)
        f.seek(e2)
    if name:
        doc.materials[name] = {"map_Kd": os.path.basename(tex) if tex else None}
        log(f"[MAT] {name} -> {doc.materials[name]['map_Kd'] or '(no texture)'}")

def _parse_object(f, endpos, mesh: I3DMesh):
    mesh.name = read_cstr(f)
    log(f"[OBJ] Object: {mesh.name}")
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _length, e2 = ch
        if cid == OBJECT_MESH:
            _parse_object_mesh(f, e2, mesh)
        else:
            f.seek(e2)

def _parse_object_mesh(f, endpos, mesh: I3DMesh):
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _length, e2 = ch
        if cid == POINT_ARRAY:
            count = read_u16(f)
            mesh.vertices = [struct.unpack("<3f", f.read(12)) for _ in range(count)]
            log(f"[OBJ]   Vertices: {len(mesh.vertices)}")
        elif cid == OBJECT_FACES:
            _parse_faces_block(f, e2, mesh)
        elif cid == OBJECT_SMOOTH:
            face_count = len(mesh.faces)
            mesh.smooth_masks = [struct.unpack("<I", f.read(4))[0] for _ in range(face_count)]
            log(f"[OBJ]   Smoothing masks: {len(mesh.smooth_masks)}")
        elif cid == OBJECT_TRANS_MATRIX:
            data = struct.unpack("<12f", f.read(48))
            mesh.matrix_3x4 = [list(data[0:4]), list(data[4:8]), list(data[8:12])]
            log(f"[OBJ]   Transform matrix found")
        elif cid == FACE_MAP_CHANNEL:
            _parse_face_map_channel(f, mesh)
        else:
            pass
        f.seek(e2)

def _parse_faces_block(f, endpos, mesh: I3DMesh):
    face_count = read_u16(f)
    faces = []
    flags = []
    for _ in range(face_count):
        a, b, c = struct.unpack("<3H", f.read(6))
        faces.append((a, b, c))
        flags.append(read_u16(f))
    mesh.faces = faces
    mesh.face_flags = flags
    log(f"[OBJ]   Faces: {len(faces)}")
    while f.tell() < endpos:
        ch = read_chunk(f)
        if not ch: break
        cid, _length, e2 = ch
        if cid == OBJECT_MATERIAL:
            mname = read_cstr(f)
            n = read_u16(f)
            idxs = [read_u16(f) for _ in range(n)]
            mesh.mat_faces[mname].extend(idxs)
            log(f"[OBJ]   Mat group: {mname} -> {len(idxs)} face(s)")
        f.seek(e2)

def _parse_face_map_channel(f, mesh: I3DMesh):
    ch_index = read_u32(f)
    uv_count = read_u16(f)
    uvs = [struct.unpack("<2f", f.read(8)) for _ in range(uv_count)]
    face_count = read_u16(f)
    uv_tris = [struct.unpack("<3H", f.read(6)) for _ in range(face_count)]
    mesh.uv_channels[ch_index] = {"uv": uvs, "tris": uv_tris}
    log(f"[OBJ]   UVs: channel={ch_index} verts={len(uvs)} faces={len(uv_tris)}")

def _post_parse_log(doc: I3DDoc):
    m = doc.mesh
    log(f"[I3D] Loaded mesh='{m.name}' "
        f"(verts={len(m.vertices)}, faces={len(m.faces)}, mats={len(doc.materials)}, "
        f"uv_channels={sorted(m.uv_channels.keys()) or 'none'})")

# ---------- OBJ/MTL writer ---------------------------------------------------

def save_obj_mtl(base_out_path: str, doc: I3DDoc, uv_channel: int, bake: bool,
                 transform_expr: Optional[str]):
    """
    Writes <base>.obj and <base>.mtl in the same directory as the source I3D.
    - Positions from POINT_ARRAY (baked if requested), then apply --transform
    - UVs from FACE_MAP_CHANNEL(uv_channel) (as-is)
    - Faces honor per-material groupings, with vt indices from channel
    - Smoothing: emits 's off' or 's N' before faces
    - MTL uses basename-only map_Kd; material names sanitized (spaces→underscores)
    """
    mesh = doc.mesh

    if bake:
        log("[CFG] Baking transform into vertex positions: YES")
        mesh.apply_bake_transform()
    else:
        log("[CFG] Baking transform into vertex positions: NO")

    obj_path = base_out_path + ".obj"
    mtl_path = base_out_path + ".mtl"
    mtl_basename = os.path.basename(mtl_path)

    # Select UV channel (prefer requested; else choose one matching face count)
    ch = mesh.uv_channels.get(uv_channel)
    if not ch and mesh.uv_channels:
        for k, v in mesh.uv_channels.items():
            if len(v.get("tris", ())) == len(mesh.faces):
                log(f"[UV] Requested channel {uv_channel} not found; using channel {k} (matching face count)")
                ch = v; uv_channel = k
                break
        if not ch:
            fallback = sorted(mesh.uv_channels.keys())[0]
            log(f"[UV] Requested channel {uv_channel} not found; falling back to channel {fallback}")
            ch = mesh.uv_channels[fallback]

    vt_list, vt_tris = [], []
    if ch:
        vt_list = [(u, clamp(v, -1e9, 1e9)) for (u, v) in ch["uv"]]
        log("[UV] Using V as-is")
        vt_tris = ch["tris"]
    else:
        log("[UV] No FACE_MAP_CHANNEL found; OBJ will be written without vt.")

    # Ensure at least one material group
    if not mesh.mat_faces:
        mesh.mat_faces["default"] = list(range(len(mesh.faces)))

    # Sanitize material names (spaces→underscores) consistently
    if any(k != _safe_newmtl_name(k) for k in mesh.mat_faces.keys()):
        remapped = defaultdict(list)
        for k, v in mesh.mat_faces.items():
            remapped[_safe_newmtl_name(k)].extend(v)
        mesh.mat_faces = remapped

    sanitized_materials = {}
    for raw_name, props in doc.materials.items():
        mname = _safe_newmtl_name(raw_name)
        tex   = props.get("map_Kd")
        tex_bn = os.path.basename(tex) if tex else None
        sanitized_materials[mname] = {"map_Kd": tex_bn}

    # Stable order
    mat_order = sorted([m for m in mesh.mat_faces.keys() if m != "default"])
    if "default" in mesh.mat_faces:
        mat_order.append("default")

    # Build transform function (defaults to (x, -y, -z))
    expr = transform_expr if transform_expr is not None else "(x, -y, -z)"
    transform_fn = make_transform(expr)
    log(f"[CFG] Transform: {expr}")

    # --- Write MTL
    with open(mtl_path, "w", encoding="utf-8", newline="\n") as fm:
        for mname in mat_order:
            fm.write(f"newmtl {mname}\n")
            fm.write("Ka 0.000 0.000 0.000\n")
            fm.write("Kd 0.800 0.800 0.800\n")
            fm.write("Ks 0.000 0.000 0.000\n")
            fm.write("Ns 10.000\n")
            fm.write("d 1.0\n")
            fm.write("illum 2\n")
            tex_bn = sanitized_materials.get(mname, {}).get("map_Kd")
            if tex_bn:
                fm.write(f"map_Kd {tex_bn.replace(os.sep, '/')}\n")
            fm.write("\n")
    log(f"[MTL] Wrote: {mtl_path}")

    # --- Write OBJ
    with open(obj_path, "w", encoding="utf-8", newline="\n") as fo:
        fo.write("# Exported from I3D\n")
        fo.write(f"mtllib {mtl_basename}\n")
        fo.write(f"o {mesh.name}\n")

        # v (apply transform here)
        for (x, y, z) in mesh.vertices:
            X, Y, Z = transform_fn((x, y, z))
            fo.write(f"v {X:.6f} {Y:.6f} {Z:.6f}\n")

        # vt
        for (u, v) in vt_list:
            fo.write(f"vt {u:.6f} {v:.6f}\n")

        def smoothing_label(mask: int) -> str:
            if mask == 0:
                return "off"
            n = 1
            while n < 32:
                if mask & (1 << (n - 1)):
                    return str(n)
                n += 1
            return "1"

        for mname in mat_order:
            fo.write(f"usemtl {mname}\n")
            fo.write(f"g {mname}\n")
            for fi in mesh.mat_faces[mname]:
                fo.write(f"s {smoothing_label(mesh.smooth_masks[fi])}\n" if mesh.smooth_masks and fi < len(mesh.smooth_masks) else "s off\n")
                a, b, c = mesh.faces[fi]
                if vt_tris:
                    ta, tb, tc = vt_tris[fi]
                    fo.write(f"f {a+1}/{ta+1} {b+1}/{tb+1} {c+1}/{tc+1}\n")
                else:
                    fo.write(f"f {a+1} {b+1} {c+1}\n")

    log(f"[OBJ] Wrote: {obj_path}")

# ---------- CLI --------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="I3D → OBJ converter (Hidden & Dangerous dialect)")
    ap.add_argument("i3dfile", help="Path to source .i3d")
    ap.add_argument("--channel", type=int, default=1, help="FACE_MAP_CHANNEL index to read (default: 1)")
    ap.add_argument("--bake", action="store_true", help="Bake OBJECT_TRANS_MATRIX into vertex positions")
    ap.add_argument("--transform", type=str, default="(x, -y, -z)",
                    help="Custom axis remap as a tuple using x,y,z, e.g. '(x, -y, -z)'. Default is (x, -y, -z).")
    args = ap.parse_args()

    i3d_path = os.path.abspath(args.i3dfile)
    if not os.path.isfile(i3d_path):
        print(f"Error: I3D not found: {i3d_path}")
        sys.exit(2)

    base = os.path.splitext(os.path.basename(i3d_path))[0]
    out_dir = os.path.dirname(i3d_path)
    base_out_path = os.path.join(out_dir, base)

    log(f"[CFG] Input I3D  : {i3d_path}")
    log(f"[CFG] Output OBJ : {base_out_path}.obj")
    log(f"[CFG] Output MTL : {base_out_path}.mtl")
    log(f"[CFG] FACE_MAP_CHANNEL index: {args.channel}")
    log(f"[CFG] Bake transforms: {'YES' if args.bake else 'NO'}")
    log(f"[CFG] Transform: {args.transform}")

    doc = parse_i3d(i3d_path)
    save_obj_mtl(
        base_out_path,
        doc,
        uv_channel=args.channel,
        bake=args.bake,
        transform_expr=args.transform
    )
    log("[I3D] Done.")

if __name__ == "__main__":
    main()

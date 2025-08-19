#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#DONT USE

import os
import sys
import struct
import argparse
from collections import defaultdict, OrderedDict

# ---------------- 3DS / I3D Chunk IDs ----------------
PRIMARY                 = 0x4D4D
OBJECTINFO              = 0x3D3D
M3D_VERSION             = 0x0002
EDIT_CONFIG             = 0x3D3E  # mesh version (uint32 in this script)

# MATERIAL block + subchunks
MATERIAL                = 0xAFFF
MAT_NAME                = 0xA000
MAT_AMBIENT             = 0xA010
MAT_DIFFUSE             = 0xA020
MAT_SPECULAR            = 0xA030
MAT_SHININESS           = 0xA040
MAT_SHININESS_STRENGTH  = 0xA041
MAT_TRANSPARENCY        = 0xA050
MAT_XPFALL              = 0xA052  # transparency falloff
MAT_REFBLUR             = 0xA053  # reflection blurring
MAT_SHADING             = 0xA100  # shading type (short)
MAT_SELF_ILLUM          = 0xA084
MAT_WIRE_SIZE           = 0xA087
MAT_TWO_SIDE            = 0xA081

MAT_TEXMAP              = 0xA200
MAT_TEXNAME             = 0xA300
MAT_TILING              = 0xA351
MAT_TEXBLUR             = 0xA353

# Color/Percent sub-subchunks
COLOR_24                = 0x0011   # RGB bytes
PERCENT_I               = 0x0030   # 0..100 (uint16)

# OBJECT / MESH
OBJECT                  = 0x4000
OBJECT_MESH             = 0x4100
OBJECT_VERTICES         = 0x4110
OBJECT_FACES            = 0x4120
OBJECT_MAT_GROUP        = 0x4130
OBJECT_UV               = 0x4140   # not used for I3D
OBJECT_SMOOTH           = 0x4150
OBJECT_TRANS_MATRIX     = 0x4160

# I3D extension for UVs
FACE_MAP_CHANNEL        = 0x4200

# Keyframer (optional baseline)
EDITKEYFRAME            = 0xB000
KFDATA_KFHDR            = 0xB00A
KFDATA_OBJECT_NODE_TAG  = 0xB002
KFDATA_NODE_HDR         = 0xB010
KFDATA_INSTANCE_NAME    = 0xB011  # (unused in this minimal build)
KFDATA_PIVOT            = 0xB013
KFDATA_BOUNDBOX         = 0xB014  # (unused in this minimal build)

# ---------------- Helpers ----------------

def log(msg): print(msg, flush=True)

def pack_c_string(s: str) -> bytes:
    return s.encode('ascii', errors='replace') + b'\x00'

def build_chunk(chunk_id, payload=b"", children=None):
    if children is None:
        children = []
    size = 6 + len(payload) + sum(len(c) for c in children)
    return struct.pack("<HI", chunk_id, size) + payload + b"".join(children)

def write_color_subchunk(container_chunk_id, rgb):
    r = max(0, min(255, int(round(rgb[0] * 255))))
    g = max(0, min(255, int(round(rgb[1] * 255))))
    b = max(0, min(255, int(round(rgb[2] * 255))))
    color_payload = struct.pack("<BBB", r, g, b)
    color_child = build_chunk(COLOR_24, color_payload)
    return build_chunk(container_chunk_id, b"", [color_child])

def write_percent_chunk(value_0_to_1: float):
    v = max(0, min(100, int(round(float(value_0_to_1) * 100.0))))
    return build_chunk(PERCENT_I, struct.pack("<H", v))

# ---------------- OBJ/MTL Parsing ----------------

class OBJData:
    def __init__(self):
        self.v = []         # [(x,y,z)]
        self.vt = []        # [(u,v)]
        self.vn = []        # [(nx,ny,nz)]
        # faces grouped by material: OrderedDict to preserve appearance order
        # key: material name or None
        # val: list of dicts { 'tri': ((vi,ti,ni),(vi,ti,ni),(vi,ti,ni)), 'sg': smoothing_group_int }
        self.faces_by_mat = OrderedDict()
        self.mtl_file = None
        self.object_name = None

class MTLData:
    def __init__(self):
        self.materials = OrderedDict()  # name -> { 'Kd': (r,g,b), 'map_Kd': filename }

def parse_mtl(path):
    mtl = MTLData()
    if not path or not os.path.isfile(path):
        log(f"[MTL] No MTL found at: {path}")
        return mtl
    log(f"[MTL] Loading: {path}")
    current = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'): continue
            parts = s.split(None, 1)
            key = parts[0]
            val = parts[1] if len(parts) > 1 else ""
            if key == "newmtl":
                current = val.strip()
                mtl.materials[current] = {"Kd": (0.8, 0.8, 0.8)}
            elif key == "Kd" and current:
                nums = val.split()
                if len(nums) >= 3:
                    try:
                        mtl.materials[current]["Kd"] = (float(nums[0]), float(nums[1]), float(nums[2]))
                    except: pass
            elif key == "map_Kd" and current:
                tex = val.strip().split()[0]
                mtl.materials[current]["map_Kd"] = os.path.basename(tex)
    log(f"[MTL] Loaded materials: {len(mtl.materials)}")
    return mtl

def parse_obj(path):
    obj = OBJData()
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    log(f"[OBJ] Loading: {path}")

    base_dir = os.path.dirname(path)
    current_mat = None
    current_sgroup = 1

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'): continue
            parts = s.split()
            key = parts[0]
            vals = parts[1:]

            if key == "o":
                obj.object_name = " ".join(vals) if vals else obj.object_name
            elif key == "mtllib":
                candidate = " ".join(vals)
                obj.mtl_file = candidate if os.path.isabs(candidate) else os.path.join(base_dir, candidate)
            elif key == "usemtl":
                current_mat = " ".join(vals) if vals else None
                if current_mat not in obj.faces_by_mat:
                    obj.faces_by_mat[current_mat] = []
            elif key == "s":
                if not vals or vals[0].lower() == "off":
                    current_sgroup = 0
                else:
                    try: current_sgroup = int(vals[0])
                    except: current_sgroup = 1
            elif key == "v":
                if len(vals) >= 3:
                    obj.v.append((float(vals[0]), float(vals[1]), float(vals[2])))
            elif key == "vt":
                if len(vals) >= 2:
                    obj.vt.append((float(vals[0]), float(vals[1])))
            elif key == "vn":
                if len(vals) >= 3:
                    obj.vn.append((float(vals[0]), float(vals[1]), float(vals[2])))
            elif key == "f":
                if len(vals) < 3: continue

                def parse_ref(tok):
                    vi = ti = ni = None
                    if "/" in tok:
                        sp = tok.split("/")
                        if len(sp) == 3:
                            vi = int(sp[0]) if sp[0] else None
                            ti = int(sp[1]) if sp[1] else None
                            ni = int(sp[2]) if sp[2] else None
                        elif len(sp) == 2:
                            vi = int(sp[0]) if sp[0] else None
                            ti = int(sp[1]) if sp[1] else None
                        else:
                            vi = int(sp[0]) if sp[0] else None
                    else:
                        vi = int(tok)
                    return vi, ti, ni

                refs = [parse_ref(t) for t in vals]

                def fix_index(i, n):
                    if i is None: return None
                    return i - 1 if i > 0 else n + i

                if current_mat not in obj.faces_by_mat:
                    obj.faces_by_mat[current_mat] = []

                # fan triangulate
                for j in range(1, len(refs) - 1):
                    a, b, c = refs[0], refs[j], refs[j + 1]
                    tri = []
                    for ref in (a, b, c):
                        vi, ti, ni = ref
                        tri.append((
                            fix_index(vi, len(obj.v)),
                            fix_index(ti, len(obj.vt)) if ti is not None else None,
                            fix_index(ni, len(obj.vn)) if ni is not None else None
                        ))
                    obj.faces_by_mat[current_mat].append({'tri': tuple(tri), 'sg': current_sgroup})

    v_count = len(obj.v)
    vt_count = len(obj.vt)
    f_count = sum(len(lst) for lst in obj.faces_by_mat.values())
    log(f"[OBJ] Loaded: {v_count} verts, {vt_count} uvs, {len(obj.vn)} normals, {f_count} faces, {len(obj.faces_by_mat)} materials")
    return obj

# ---------------- Builders ----------------

def enforce_3ds_limits(verts_len, faces_len):
    if verts_len > 65535 or faces_len > 65535:
        raise ValueError(f"3DS/I3D per-mesh limits exceeded (verts={verts_len}, faces={faces_len}, both must be <= 65535).")

def is_two_sided_material(name: str) -> bool:
    if not name: return False
    s = name.lower()
    return "2sd" in s or "two" in s

def build_material_chunks(mtl: MTLData, used_mats_in_order):
    chunks = []
    if "_default" in used_mats_in_order and "_default" not in mtl.materials:
        mtl.materials["_default"] = {"Kd": (0.8, 0.8, 0.8)}
    for name in used_mats_in_order:
        props = mtl.materials.get(name, {})
        kd = props.get("Kd", (0.0, 0.0, 0.0))
        tex = props.get("map_Kd", None)

        sub = []
        sub.append(build_chunk(MAT_NAME, pack_c_string(name)))
        sub.append(write_color_subchunk(MAT_AMBIENT, (0.0, 0.0, 0.0)))
        sub.append(write_color_subchunk(MAT_DIFFUSE, kd))
        sub.append(write_color_subchunk(MAT_SPECULAR, (0.0, 0.0, 0.0)))
        sub.append(build_chunk(MAT_SHININESS,           write_percent_chunk(0.01)))  # ~1%
        sub.append(build_chunk(MAT_SHININESS_STRENGTH,  write_percent_chunk(0.05)))  # ~5%
        sub.append(build_chunk(MAT_TRANSPARENCY,        write_percent_chunk(0.0)))
        sub.append(build_chunk(MAT_XPFALL,              write_percent_chunk(0.0)))
        sub.append(build_chunk(MAT_REFBLUR,             write_percent_chunk(0.0)))
        sub.append(build_chunk(MAT_SHADING, struct.pack("<H", 3)))  # Phong
        sub.append(build_chunk(MAT_SELF_ILLUM, write_percent_chunk(0.0)))
        sub.append(build_chunk(MAT_WIRE_SIZE, struct.pack("<f", 1.0)))
        if is_two_sided_material(name):
            sub.append(build_chunk(MAT_TWO_SIDE, b""))
        if tex:
            tsubs = [
                write_percent_chunk(1.0),  # amount 100%
                build_chunk(MAT_TEXNAME, pack_c_string(os.path.basename(tex))),
                build_chunk(MAT_TILING, struct.pack("<H", 0)),
                build_chunk(MAT_TEXBLUR, struct.pack("<f", 0.07)),
            ]
            sub.append(build_chunk(MAT_TEXMAP, b"", tsubs))
        chunks.append(build_chunk(MATERIAL, b"", sub))
    return chunks

def edit_config_chunk(mesh_version=3):
    # Use uint32 so chunk length becomes 10, matching common dumps.
    return build_chunk(EDIT_CONFIG, struct.pack("<I", mesh_version))

def assemble_faces_uv_corners(obj: OBJData):
    """
    Build arrays using the natural appearance order from the OBJ:
      - faces_geo: [(vi0,vi1,vi2, mat_name), ...]
      - faces_uv : [(ti0,ti1,ti2), ...]
      - sgroups  : [sg, ...]
      - used_mats_in_order: [mat_name,...] (only those that have faces) with None -> "_default"
    """
    faces_geo, faces_uv, sgroups = [], [], []
    used_mats_in_order = []
    for key, recs in obj.faces_by_mat.items():
        if not recs:
            continue
        mk = key if key is not None else "_default"
        used_mats_in_order.append(mk)
        for rec in recs:
            (vi0, ti0, _), (vi1, ti1, _), (vi2, ti2, _) = rec['tri']
            faces_geo.append((vi0, vi1, vi2, mk))
            faces_uv.append((ti0, ti1, ti2))
            sg = rec.get('sg', 1)
            sgroups.append(int(sg) if isinstance(sg, int) else 1)
    if not used_mats_in_order:
        used_mats_in_order = ["_default"]
    return faces_geo, faces_uv, sgroups, used_mats_in_order

def smoothing_chunk_from_groups(sgroups):
    payload = bytearray()
    for sg in sgroups:
        if sg <= 0:
            mask = 0
        else:
            bit = min(31, sg - 1)
            mask = (1 << bit)
        payload += struct.pack("<I", mask)
    return build_chunk(OBJECT_SMOOTH, bytes(payload))

def build_uv_channel_dedup(obj: OBJData, faces_uv, *, flip_v=True, channel_index=1):
    """
    I3D-style 0x4200 that de-duplicates identical (u,v) pairs across all face corners
    in the order they are first encountered while walking faces.
    Typically yields uv_count < 3*face_count.
    """
    uv_index_of = {}   # (u,v) -> idx
    uv_list = []       # [(u,v)]
    uv_indices = []    # [(i0,i1,i2)] aligned with faces

    def get_idx(u, v):
        key = (u, v)
        idx = uv_index_of.get(key)
        if idx is None:
            idx = len(uv_list)
            uv_index_of[key] = idx
            uv_list.append((u, v))
        return idx

    for (ti0, ti1, ti2) in faces_uv:
        tri_idx = []
        for ti in (ti0, ti1, ti2):
            if ti is not None and 0 <= ti < len(obj.vt):
                u, v = obj.vt[ti]
                if flip_v: v = 1.0 - v
            else:
                u, v = 0.0, 0.0
            tri_idx.append(get_idx(float(u), float(v)))
        uv_indices.append(tuple(tri_idx))

    payload = struct.pack("<iH", int(channel_index), len(uv_list))
    for (u, v) in uv_list:
        payload += struct.pack("<ff", u, v)
    payload += struct.pack("<H", len(uv_indices))
    for (a, b, c) in uv_indices:
        payload += struct.pack("<HHH", a, b, c)
    return build_chunk(FACE_MAP_CHANNEL, payload)

def build_mesh_chunks(obj: OBJData, object_name: str, scale: float, flip_v=True):
    faces_geo, faces_uv, sgroups, used_mats_in_order = assemble_faces_uv_corners(obj)

    vertices = [(x * scale, -y * scale, -z * scale) for (x, y, z) in obj.v]
    enforce_3ds_limits(len(vertices), len(faces_geo))
    log(f"[I3D] Geometry: {len(vertices)} verts, {len(faces_geo)} faces; materials used: {len(used_mats_in_order)}")

    # 0x4110
    v_payload = struct.pack("<H", len(vertices)) + b"".join(struct.pack("<fff", *p) for p in vertices)
    vert_chunk = build_chunk(OBJECT_VERTICES, v_payload)

    # 0x4120 (+ 0x4130 groups)
    f_payload = struct.pack("<H", len(faces_geo))
    for (a, b, c, _mk) in faces_geo:
        if a is None or b is None or c is None:
            raise ValueError("Face has missing vertex index.")
        f_payload += struct.pack("<HHHH", a, b, c, 0)
    mat_to_indices = defaultdict(list)
    for idx, (_, _, _, mk) in enumerate(faces_geo):
        mat_to_indices[mk].append(idx)
    face_sub = []
    for mk in used_mats_in_order:
        idxs = mat_to_indices.get(mk, [])
        if not idxs: continue
        sub = pack_c_string(mk) + struct.pack("<H", len(idxs)) + b"".join(struct.pack("<H", i) for i in idxs)
        face_sub.append(build_chunk(OBJECT_MAT_GROUP, sub))
    faces_chunk = build_chunk(OBJECT_FACES, f_payload, face_sub)

    # 0x4150
    smooth_chunk = smoothing_chunk_from_groups(sgroups)

    # 0x4160 identity
    tm = [1.0,0.0,0.0,0.0,  0.0,1.0,0.0,0.0,  0.0,0.0,1.0,0.0]
    xform_chunk = build_chunk(OBJECT_TRANS_MATRIX, struct.pack("<ffffffffffff", *tm))

    # 0x4200 (I3D-style de-dup)
    uv4200_chunk = build_uv_channel_dedup(obj, faces_uv, flip_v=flip_v, channel_index=1)

    mesh_children = [vert_chunk, faces_chunk, smooth_chunk, xform_chunk, uv4200_chunk]
    mesh_chunk = build_chunk(OBJECT_MESH, b"", mesh_children)
    obj_chunk  = build_chunk(OBJECT, pack_c_string(object_name), [mesh_chunk])

    return obj_chunk, used_mats_in_order

# ---------------- Optional Keyframer (baseline) ----------------

def kf_header_chunk(scene_name: str, anim_len_frames=100, current_frame=0):
    """
    Minimal KFHDR (0xB00A): c-string scene name, uint32 anim length, uint32 current frame.
    """
    payload = pack_c_string(scene_name) + struct.pack("<II", int(anim_len_frames), int(current_frame))
    return build_chunk(KFDATA_KFHDR, payload)

def kf_node_hdr_chunk(node_name: str, flags1=0, flags2=0, hierarchy=-1):
    """
    NODE_HDR (0xB010): c-string name, int16 flags1, int16 flags2, int16 hierarchy.
    """
    payload = pack_c_string(node_name) + struct.pack("<hhh", int(flags1), int(flags2), int(hierarchy))
    return build_chunk(KFDATA_NODE_HDR, payload)

def kf_pivot_chunk(px=0.0, py=0.0, pz=0.0):
    """
    PIVOT (0xB013): 3 floats.
    """
    return build_chunk(KFDATA_PIVOT, struct.pack("<fff", float(px), float(py), float(pz)))

def build_kfdata_root(object_name: str, scene_name=None):
    """
    EDITKEYFRAME (0xB000) with:
      - KFHDR  (scene name, anim len, current frame)
      - OBJECT_NODE_TAG (node for our mesh)
          - NODE_HDR (name + flags + hierarchy)
          - PIVOT (0,0,0)
    Conservative, widely-accepted minimal setup.
    """
    hdr = kf_header_chunk(scene_name or object_name, anim_len_frames=100, current_frame=0)
    node_children = [
        kf_node_hdr_chunk(object_name, flags1=0, flags2=0, hierarchy=-1),
        kf_pivot_chunk(0.0, 0.0, 0.0),
    ]
    node = build_chunk(KFDATA_OBJECT_NODE_TAG, b"", node_children)
    return build_chunk(EDITKEYFRAME, b"", [hdr, node])

# ---------------- Top-level file build ----------------

def build_i3d_file(obj: OBJData, mtl: MTLData, object_name: str, scale: float,
                   flip_v=True, include_kf=False):
    version_chunk = build_chunk(M3D_VERSION, struct.pack("<I", 3))
    edit_cfg = edit_config_chunk(3)

    obj_chunk, used_mats_in_order = build_mesh_chunks(obj, object_name, scale, flip_v=flip_v)
    mat_chunks = build_material_chunks(mtl, used_mats_in_order)

    objectinfo_children = [version_chunk, edit_cfg] + mat_chunks + [obj_chunk]
    objectinfo = build_chunk(OBJECTINFO, b"", objectinfo_children)
    children = [objectinfo]

    if include_kf:
        kf = build_kfdata_root(object_name, scene_name=object_name)
        children.append(kf)

    return build_chunk(PRIMARY, b"", children)

# ---------------- CLI ----------------

def main():
    ap = argparse.ArgumentParser(description="Convert OBJ (+MTL) to I3D (3DS-derived) with 0x4200 UVs (I3D style).")
    ap.add_argument("obj", help="Path to input .obj")
    ap.add_argument("-o", "--out", help="Path to output .i3d (default: alongside .obj with same basename)")
    ap.add_argument("--name", help="Object name (default: OBJ 'o' or filename)")
    ap.add_argument("--scale", type=float, default=1.0, help="Uniform scale (default: 1.0)")
    ap.add_argument("--no-flip-v", action="store_true", help="Do NOT flip V (default flips: v = 1 - v)")
    ap.add_argument("--kf", action="store_true", help="Include minimal Keyframer (0xB000) data")
    args = ap.parse_args()

    in_obj = os.path.abspath(args.obj)
    if not os.path.isfile(in_obj):
        log(f"[ERR] OBJ not found: {in_obj}")
        sys.exit(1)

    out_path = os.path.abspath(args.out) if args.out else os.path.splitext(in_obj)[0] + ".i3d"

    obj = parse_obj(in_obj)
    mtl = parse_mtl(obj.mtl_file)
    object_name = args.name or obj.object_name or os.path.splitext(os.path.basename(in_obj))[0]

    log(f"[CFG] Object name : {object_name}")
    log(f"[CFG] Output I3D  : {out_path}")
    log(f"[CFG] Scale       : {args.scale}")
    log(f"[CFG] UV channel  : 1 (FACE_MAP_CHANNEL 0x4200, I3D de-dup)")
    log(f"[CFG] Flip V      : {'NO' if args.no_flip_v else 'YES (v = 1 - v)'}")
    log(f"[CFG] Keyframer   : {'ON' if args.kf else 'OFF'}")
    if len(obj.vt) == 0:
        log("[WARN] OBJ has no UVs; 0x4200 will contain (0,0) entries.")

    data = build_i3d_file(
        obj, mtl, object_name, args.scale,
        flip_v=(not args.no_flip_v),
        include_kf=args.kf
    )

    with open(out_path, "wb") as f:
        f.write(data)
    sz = os.path.getsize(out_path)
    log(f"[OK] Wrote I3D: {out_path} ({sz} bytes)")

if __name__ == "__main__":
    main()

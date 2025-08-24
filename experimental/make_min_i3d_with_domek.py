#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_min_i3d_with_domek.py
--------------------------
Create a minimal Hidden & Dangerous Deluxe mission folder that:
- Adds a camera + flat ground plane
- Adds a *named* object "domek" into scene.i3d as a placement marker
- Spawns the real external model "domek.i3d" at the same position/rotation via scene.scr

Usage:
  python make_min_i3d_with_domek.py MyMission --domek-pos 2 0 2 --domek-rot-y 45
"""

import sys, struct, argparse, math
from pathlib import Path
from typing import List, Tuple

# ---- Chunk IDs (3DS/I3D core)
PRIMARY        = 0x4D4D
M3D_VERSION    = 0x0002
OBJECTINFO     = 0x3D3D
OBJECT         = 0x4000
OBJECT_MESH    = 0x4100
POINT_ARRAY    = 0x4110
FACE_ARRAY     = 0x4120
OBJECT_UV      = 0x4140
OBJECT_CAMERA  = 0x4700
OBJECT_XFORM   = 0x4160  # placement matrix (optional but useful for instances)

# ---- Helpers
def u16(x: int) -> bytes: return struct.pack("<H", x)
def u32(x: int) -> bytes: return struct.pack("<I", x)
def f32(x: float) -> bytes: return struct.pack("<f", x)

def write_chunk(cid: int, payload: bytes) -> bytes:
    return u16(cid) + u32(6 + len(payload)) + payload

def chunk_m3d_version(v=3) -> bytes:
    return write_chunk(M3D_VERSION, u16(v))

def chunk_object(name: str, *subs: bytes) -> bytes:
    name_bytes = name.encode("ascii", "ignore") + b"\x00"
    return write_chunk(OBJECT, name_bytes + b"".join(subs))

def chunk_object_mesh(*subs: bytes) -> bytes:
    return write_chunk(OBJECT_MESH, b"".join(subs))

def chunk_point_array(verts: List[Tuple[float,float,float]]) -> bytes:
    body = u16(len(verts))
    for x,y,z in verts:
        body += f32(x)+f32(y)+f32(z)
    return write_chunk(POINT_ARRAY, body)

def chunk_face_array(faces: List[Tuple[int,int,int]]) -> bytes:
    body = u16(len(faces))
    for a,b,c in faces:
        body += u16(a)+u16(b)+u16(c)+u16(0)
    return write_chunk(FACE_ARRAY, body)

def chunk_object_uv(uvs: List[Tuple[float,float]]) -> bytes:
    body = u16(len(uvs))
    for u,v in uvs:
        body += f32(u)+f32(v)
    return write_chunk(OBJECT_UV, body)

def chunk_object_camera(pos=(0.0,5.0,10.0), target=(0.0,0.0,0.0), bank=0.0, lens=35.0) -> bytes:
    body = b"".join(f32(v) for v in (*pos, *target, bank, lens))
    return write_chunk(OBJECT_CAMERA, body)

def chunk_objectinfo(*subs: bytes) -> bytes:
    return write_chunk(OBJECTINFO, b"".join(subs))

def chunk_primary(*subs: bytes) -> bytes:
    return write_chunk(PRIMARY, b"".join(subs))

def chunk_object_xform_from_yaw(pos_xyz: Tuple[float,float,float], yaw_deg: float) -> bytes:
    """
    Build a simple placement matrix (row-major 3x4) using yaw about Y.
    3DS 0x4160 stores 12 floats: the 3x3 rotation rows followed by translation (x,y,z).
    """
    x, y, z = pos_xyz
    r = math.radians(yaw_deg)
    c, s = math.cos(r), math.sin(r)
    # Y-up rotation about Y (turntable yaw): 
    # [ c  0  s | x ]
    # [ 0  1  0 | y ]
    # [-s  0  c | z ]
    m = [ c, 0.0,  s,  x,
          0.0, 1.0, 0.0, y,
         -s, 0.0,  c,  z ]
    body = b"".join(f32(v) for v in m)
    return write_chunk(OBJECT_XFORM, body)

# ---- Scene
def make_scene(domek_pos=(2.0,0.0,2.0), domek_yaw_deg=0.0) -> bytes:
    # Ground: 10x10 plane at Y=0
    verts = [(-5,0,-5),(5,0,-5),(5,0,5),(-5,0,5)]
    faces = [(0,1,2),(0,2,3)]
    uvs   = [(0,0),(1,0),(1,1),(0,1)]

    ground = chunk_object("Ground01",
        chunk_object_mesh(
            chunk_point_array(verts),
            chunk_face_array(faces),
            chunk_object_uv(uvs)
        )
    )

    cam = chunk_object("Camera01", chunk_object_camera())

    # Add a *named* object "domek" with a transform.
    # This is a lightweight editor marker: the engine will resolve the real model at runtime.
    domek_marker = chunk_object("domek",
                        chunk_object_xform_from_yaw(domek_pos, domek_yaw_deg))

    return chunk_primary(
        chunk_m3d_version(3),
        chunk_objectinfo(cam, ground, domek_marker)
    )

# ---- SCR & README (engine-spawn of the real model)
SCR_TEMPLATE = """; Hidden & Dangerous Deluxe — minimal mission with external model reference
[MISSION]
NAME=NewMission
SCENE=scene.i3d

[PLAYER]
; Spawn at origin on the ground, eye-height ≈ 1.8
POSITION=0 1.8 0
DIRECTION=0 0 1

[OBJECT]
; Place external model by name. The engine looks up "domek" in models.dta (domek.i3d).
NAME=domek
POSITION={x:.3f} {y:.3f} {z:.3f}
; Yaw about Y axis in degrees:
YAW={yaw:.3f}

[GAME]
WIN_COND=NONE
LOSE_COND=NONE
"""

README_TEXT = """NewMission — Notes
===================
- scene.i3d: Camera01 + Ground01 + a named object "domek" (editor marker with transform).
- scene.scr: Spawns the external model "domek.i3d" at the same transform.

How it works:
- The mission file *does not* embed the domek geometry. It just provides a named placement ("domek").
- The game engine loads the real model "domek.i3d" from models.dta at runtime.
- Keep the file name "scene.i3d" — the loader expects that.

If the model doesn't appear:
- Ensure "domek.i3d" exists in models.dta (or your loose models folder if supported).
- Some builds use slightly different .scr keys. If needed, copy an [OBJECT] block from a stock mission's .scr and replace ours.
"""

def main():
    ap = argparse.ArgumentParser(description="Create minimal H&D mission with external domek model.")
    ap.add_argument("mission_name", nargs="?", default="NewMission")
    ap.add_argument("--domek-pos", nargs=3, type=float, default=[2.0, 0.0, 2.0],
                    metavar=("X","Y","Z"), help="domek position (default 2 0 2)")
    ap.add_argument("--domek-rot-y", type=float, default=0.0,
                    help="domek yaw rotation in degrees (default 0)")
    args = ap.parse_args()

    mission_dir = Path(args.mission_name)
    mission_dir.mkdir(parents=True, exist_ok=True)

    # Write scene.i3d
    i3d_data = make_scene(tuple(args.domek_pos), args.domek_rot_y)
    (mission_dir / "scene.i3d").write_bytes(i3d_data)

    # Write scene.scr with matching transform
    scr_text = SCR_TEMPLATE.format(x=args.domek_pos[0], y=args.domek_pos[1], z=args.domek_pos[2], yaw=args.domek_rot_y)
    (mission_dir / "scene.scr").write_text(scr_text, encoding="utf-8")

    # Write README
    (mission_dir / "README.txt").write_text(README_TEXT, encoding="utf-8")

    print(f"[OK] Created mission: {mission_dir}")
    print(f"  scene.i3d  ({len(i3d_data)} bytes)")
    print(f"  scene.scr  ({len(scr_text)} chars)")
    print(f"  README.txt ({len(README_TEXT)} chars)")
    print("Tip: pack into missions.dta or load as loose if your setup supports it.")

if __name__ == "__main__":
    main()

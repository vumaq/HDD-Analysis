#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_min_i3d.py
---------------
Create a minimal Hidden & Dangerous Deluxe mission folder:

  MyMission/
    scene.i3d   (camera + flat ground plane)
    scene.scr   (stub script with a player spawn)
    README.txt  (quick tips)

Usage:
  python make_min_i3d.py MyMission
  # default folder name: NewMission
"""

import sys, struct
from pathlib import Path
from typing import List, Tuple

# ---- Chunk IDs
PRIMARY        = 0x4D4D
M3D_VERSION    = 0x0002
OBJECTINFO     = 0x3D3D
OBJECT         = 0x4000
OBJECT_MESH    = 0x4100
POINT_ARRAY    = 0x4110
FACE_ARRAY     = 0x4120
OBJECT_UV      = 0x4140
OBJECT_CAMERA  = 0x4700

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

# ---- Scene
def make_scene() -> bytes:
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
    return chunk_primary(chunk_m3d_version(3), chunk_objectinfo(cam, ground))

# ---- Script & README content
SCR_TEXT = """; Hidden & Dangerous Deluxe — minimal mission script
; This simple stub places the player at the origin on a flat ground plane.
; If your build expects different keys, copy a PLAYER block from a stock mission and replace this.

[MISSION]
NAME=NewMission
SCENE=scene.i3d

[PLAYER]
; Spawn position (X Y Z). Z≈1.8 puts camera at human eye-height above ground Y=0.
POSITION=0 1.8 0

; Forward direction as a unit vector (X Y Z). Here, looking towards +Z.
DIRECTION=0 0 1

; Optional: initial weapon/loadout keys vary by build — keep empty for now.

[GAME]
; No explicit objectives — free walk.
WIN_COND=NONE
LOSE_COND=NONE
"""

README_TEXT = """NewMission — Quick Notes
========================
Files:
- scene.i3d  — minimal geometry (Ground01) + camera (Camera01)
- scene.scr  — minimal script with a player spawn at (0,1.8,0), facing +Z

How to use:
1) Put this folder where your H&D Deluxe expects custom missions (or pack into missions.dta).
2) Ensure the file is named *scene.i3d* (required by the loader).
3) If the mission loads but doesn’t spawn you, copy the PLAYER block from a known working mission’s .scr and paste over ours.

Tweaks:
- Move the spawn: edit POSITION in scene.scr.
- Face another way: change DIRECTION in scene.scr (must be a vector, e.g., 1 0 0 to face +X).
- Make the ground bigger: edit verts in make_min_i3d.py and re-generate.
"""

def main():
    mission_name = sys.argv[1] if len(sys.argv)>1 else "NewMission"
    mission_dir  = Path(mission_name)
    mission_dir.mkdir(parents=True, exist_ok=True)

    # Write scene.i3d
    out_i3d = mission_dir / "scene.i3d"
    data = make_scene()
    out_i3d.write_bytes(data)

    # Write scene.scr (stub) and README
    (mission_dir / "scene.scr").write_text(SCR_TEXT, encoding="utf-8")
    (mission_dir / "README.txt").write_text(README_TEXT, encoding="utf-8")

    print(f"[OK] Created mission folder: {mission_dir}")
    print(f"     wrote: scene.i3d  ({len(data)} bytes)")
    print(f"            scene.scr  ({len(SCR_TEXT)} chars)")
    print(f"            README.txt ({len(README_TEXT)} chars)")
    print("Tip: If your engine build uses different .scr keys, paste a PLAYER block from a stock mission over ours.")

if __name__=="__main__":
    main()

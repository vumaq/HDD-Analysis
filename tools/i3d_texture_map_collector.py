#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
I3D Texture Map Collector (local paths, script-dir output)

- Parses an I3D file and extracts texture/map filepaths from MAT_MAP_FILEPATH (0xA300).
- Accepts ANY file extension (not just PNG). Matching on disk is case-insensitive,
  but copied filenames keep the original case as written in the I3D.
- Copies found files from configured local search paths into the SAME FOLDER as this script.
- Missing files are reported to the console only (no files written).

Usage:
  python i3d_textures_fetch.py path/to/file.i3d
  # e.g.
  python i3d_textures_fetch.py domek.i3d
"""

import os
import sys
import json
import struct
import argparse
import shutil
from pathlib import Path
from typing import List, Set, Optional

# ---- Chunk IDs (subset we care about)
MATERIAL            = 0xAFFF
MAT_TEXMAP          = 0xA200
MAT_MAP_FILEPATH    = 0xA300

# ---- Binary helpers
def read_chunk(f):
    hdr = f.read(6)
    if len(hdr) < 6:
        return None
    return struct.unpack("<HI", hdr)

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
        return bs.decode("latin1", errors="replace")

def maybe_nested(f, region_end) -> bool:
    pos = f.tell()
    if region_end - pos < 6:
        return False
    peek = f.read(6); f.seek(pos)
    if len(peek) < 6:
        return False
    cid, ln = struct.unpack("<HI", peek)
    return ln >= 6 and pos + ln <= region_end

# ---- Extract texture basenames (ANY extension)
def collect_texture_basenames(i3d_path: Path) -> List[str]:
    basenames: List[str] = []
    seen_lower: Set[str] = set()

    size = i3d_path.stat().st_size
    with i3d_path.open("rb") as f:
        def walk_region(region_end):
            while f.tell() < region_end:
                at = f.tell()
                ch = read_chunk(f)
                if not ch:
                    break
                cid, length = ch
                if length < 6:
                    f.seek(region_end)
                    return
                chunk_end = at + length

                if cid == MATERIAL:
                    walk_region(chunk_end)

                elif cid == MAT_TEXMAP:
                    while f.tell() < chunk_end:
                        sat = f.tell()
                        sub = read_chunk(f)
                        if not sub:
                            break
                        scid, slen = sub
                        sub_end = sat + slen
                        if scid == MAT_MAP_FILEPATH:
                            tex_path = read_cstr(f).strip()
                            base = os.path.basename(tex_path)
                            if base:
                                key = base.lower()
                                if key not in seen_lower:
                                    seen_lower.add(key)
                                    basenames.append(base)  # preserve original case from I3D
                        f.seek(sub_end)

                else:
                    if maybe_nested(f, chunk_end):
                        walk_region(chunk_end)
                    else:
                        f.seek(chunk_end)

                f.seek(chunk_end)

        walk_region(size)

    return basenames

# ---- Config (auto-generate on first run)
DEFAULT_CONFIG = {
    "search_paths": [
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/maps",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/maps/censored",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/maps/faces",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/maps/gamemenu",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/maps/menu"           
    ] 
}
CONFIG_FILE = Path(__file__).with_name("i3d_textures.config.json")

def ensure_config_exists() -> dict:
    if not CONFIG_FILE.exists():
        print(f"[INIT] Creating default config: {CONFIG_FILE}")
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(DEFAULT_CONFIG, fh, indent=2)
        print("[INFO] Edit 'search_paths' in the config to point to your texture folders.")
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            cfg = DEFAULT_CONFIG.copy()
            if isinstance(data, dict):
                cfg.update(data)
            return cfg
    except Exception as e:
        print(f"[WARN] Failed to read config ({e}). Regenerating defaults.")
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(DEFAULT_CONFIG, fh, indent=2)
        return DEFAULT_CONFIG.copy()

# ---- Case-insensitive file search (top-level of each search_path)
def find_file_case_insensitive(directory: Path, filename: str) -> Optional[Path]:
    if not directory.exists() or not directory.is_dir():
        return None
    target = filename.lower()
    for f in directory.iterdir():
        if f.name.lower() == target:
            return f
    return None

# ---- Copy to script folder
def copy_maps_to_script_dir(basenames: List[str], cfg: dict):
    script_dir = Path(__file__).resolve().parent
    search_paths = [Path(p) for p in cfg.get("search_paths", [])]

    if not search_paths:
        print("[WARN] No search_paths configured; nothing to copy from.")
        return

    for base in basenames:
        src = None
        for sp in search_paths:
            hit = find_file_case_insensitive(sp, base)
            if hit:
                src = hit
                break

        if not src:
            print(f"[MISS] {base} not found in any search_paths")
            continue

        dst = script_dir / base
        if dst.exists():
            print(f"[SKIP] {dst.name} already exists in script folder")
            continue

        print(f"[COPY] {src} -> {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

# ---- CLI
def main():
    ap = argparse.ArgumentParser(description="Extract and copy texture files referenced by an I3D into the script folder.")
    ap.add_argument("i3d_file", help="Path to the .i3d file (e.g., domek.i3d)")
    args = ap.parse_args()

    i3d_path = Path(args.i3d_file)
    if not i3d_path.exists() or i3d_path.suffix.lower() != ".i3d":
        print(f"[ERR] Not a valid .i3d file: {i3d_path}")
        sys.exit(2)

    cfg = ensure_config_exists()

    basenames = collect_texture_basenames(i3d_path)
    if not basenames:
        print("[INFO] No texture filepaths referenced in this I3D.")
        return

    print(f"[INFO] Found {len(basenames)} map(s): {', '.join(basenames)}")
    copy_maps_to_script_dir(basenames, cfg)

if __name__ == "__main__":
    main()



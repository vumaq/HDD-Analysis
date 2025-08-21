#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
I3D Texture Map Collector (recursive + real BMP/PNG conversion)
---------------------------------------------------------------

- Parses an I3D file and extracts texture/map filepaths from MAT_MAP_FILEPATH (0xA300).
- Accepts ANY file extension (not just PNG). Matching on disk is case-insensitive.
- Copies found files from configured local search paths into the SAME FOLDER as this script.
- If a map is NOT found by exact filename:
    • Offers a recursive search under the configured search paths.
    • If still not found but a file with the SAME BASENAME (different extension) exists,
      offers to OPEN it with Pillow and **convert** it to the EXPECTED extension
      (only BMP <-> PNG supported), saving the output under the expected filename.

Usage:
  python i3d_textures_fetch.py path/to/file.i3d
  # e.g.
  python i3d_textures_fetch.py domek.i3d

Optional flags (for automation / no prompts):
  --auto-recursive        Try recursive search automatically when direct search fails.
  --auto-convert-ext      When only same-stem files with different extension are found,
                          convert them automatically to the expected extension (BMP<->PNG).
  --yes                   Answer YES to all prompts (implies both --auto-recursive and --auto-convert-ext).

Requires:
  pip install pillow
"""

import os
import sys
import json
import struct
import argparse
import shutil
from pathlib import Path
from typing import List, Set, Optional

try:
    from PIL import Image  # Pillow
except Exception:
    Image = None

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
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/censored",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/faces",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/gamemenu",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/menu"
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

# ---- Prompts
def ask_yn(prompt: str, default_yes: bool=False, force_yes: bool=False) -> bool:
    if force_yes:
        print(f"[AUTO] {prompt} -> YES")
        return True
    suffix = " [Y/n] " if default_yes else " [y/N] "
    try:
        ans = input(prompt + suffix).strip().lower()
    except EOFError:
        ans = ""
    if not ans:
        return default_yes
    return ans in ("y", "yes")

# ---- Case-insensitive file search
def find_file_case_insensitive(directory: Path, filename: str) -> Optional[Path]:
    """Non-recursive: return the first case-insensitive match of filename in directory."""
    if not directory.exists() or not directory.is_dir():
        return None
    target = filename.lower()
    for f in directory.iterdir():
        if f.name.lower() == target:
            return f
    return None

def find_file_case_insensitive_recursive(directory: Path, filename: str) -> Optional[Path]:
    """Recursive: return the first case-insensitive match of filename under directory."""
    if not directory.exists() or not directory.is_dir():
        return None
    target = filename.lower()
    for f in directory.rglob("*"):
        if f.is_file() and f.name.lower() == target:
            return f
    return None

def find_same_stem_any_ext(directory: Path, stem: str, recursive: bool=False) -> List[Path]:
    """Find files that match the given stem (case-insensitive), with ANY extension."""
    matches: List[Path] = []
    if not directory.exists() or not directory.is_dir():
        return matches
    stem_l = stem.lower()
    it = directory.rglob("*") if recursive else directory.iterdir()
    for f in it:
        try:
            if f.is_file() and f.stem.lower() == stem_l:
                matches.append(f)
        except Exception:
            continue
    return matches

# ---- Conversion (BMP <-> PNG only)
def convert_and_save(src: Path, dst: Path, expected_ext: str):
    """Convert between PNG <-> BMP using Pillow. Raises on failure if Pillow is missing."""
    if Image is None:
        raise RuntimeError("Pillow is required for conversion. Install with: pip install pillow")
    fmt = None
    if expected_ext.lower() == ".bmp":
        fmt = "BMP"
    elif expected_ext.lower() == ".png":
        fmt = "PNG"
    else:
        raise RuntimeError(f"Unsupported target extension '{expected_ext}'. Only .bmp and .png are supported.")
    with Image.open(src) as im:
        # For BMP, ensure mode is compatible (convert paletted/alpha as needed)
        if fmt == "BMP" and im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        if fmt == "PNG" and im.mode == "P":
            # Convert paletted to RGBA to preserve transparency
            im = im.convert("RGBA")
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, format=fmt)
    print(f"[CONVERT] {src.name} -> {dst.name} ({src.suffix.lower()}→{expected_ext.lower()})")

# ---- Main copy logic with fallbacks + conversion
def copy_maps_to_script_dir(basenames: List[str], cfg: dict, auto_recursive: bool=False, auto_convert_ext: bool=False, yes_all: bool=False):
    script_dir = Path(__file__).resolve().parent
    search_paths = [Path(p) for p in cfg.get("search_paths", [])]

    if not search_paths:
        print("[WARN] No search_paths configured; nothing to copy from.")
        return

    for base in basenames:
        expected_name = base
        expected_stem = Path(base).stem
        expected_ext  = Path(base).suffix  # includes leading dot

        # 1) Try non-recursive exact matches
        src = None
        for sp in search_paths:
            hit = find_file_case_insensitive(sp, expected_name)
            if hit:
                src = hit
                break

        # 2) Offer recursive exact search if not found
        do_recursive = False
        if not src:
            do_recursive = auto_recursive or yes_all or ask_yn(f"[MISS] {expected_name} not found. Search recursively under search_paths?", default_yes=False, force_yes=False)
            if do_recursive:
                for sp in search_paths:
                    hit = find_file_case_insensitive_recursive(sp, expected_name)
                    if hit:
                        src = hit
                        break

        # 3) If still not found, try same-stem any-extension; offer to convert between BMP/PNG
        if not src:
            candidates: List[Path] = []
            for sp in search_paths:
                candidates.extend(find_same_stem_any_ext(sp, expected_stem, recursive=False))
            if do_recursive:
                for sp in search_paths:
                    candidates.extend(find_same_stem_any_ext(sp, expected_stem, recursive=True))

            # Deduplicate while preserving order
            seen = set()
            uniq_candidates = []
            for c in candidates:
                key = str(c.resolve()).lower()
                if key not in seen:
                    seen.add(key)
                    uniq_candidates.append(c)

            # Filter out those that already have the expected extension (just in case)
            uniq_candidates = [c for c in uniq_candidates if c.suffix.lower() != expected_ext.lower()]

            if uniq_candidates:
                print(f"[HINT] Found same-stem file(s) with different extension for '{expected_stem}':")
                for i, c in enumerate(uniq_candidates, 1):
                    print(f"       {i}. {c.name}  ({c})")

                # Choose first candidate by default; prompt to convert
                chosen = uniq_candidates[0]
                if expected_ext.lower() in (".bmp", ".png") and chosen.suffix.lower() in (".bmp", ".png"):
                    do_convert = auto_convert_ext or yes_all or ask_yn(
                        f"[CONVERT] Convert '{chosen.name}' -> '{expected_name}' ({chosen.suffix.lower()}→{expected_ext.lower()})?",
                        default_yes=False, force_yes=False
                    )
                    if do_convert:
                        dst = script_dir / expected_name
                        if dst.exists():
                            print(f"[SKIP] {dst.name} already exists in script folder")
                        else:
                            try:
                                convert_and_save(chosen, dst, expected_ext)
                            except Exception as e:
                                print(f"[ERR] Conversion failed: {e}")
                        # Regardless of result, move to next basename
                        continue
                else:
                    print(f"[INFO] Conversion only supports BMP<->PNG. Found: {chosen.suffix.lower()} -> {expected_ext.lower()} (unsupported).")

        # 4) Exact src found -> copy as-is
        if src:
            dst = script_dir / expected_name
            if dst.exists():
                print(f"[SKIP] {dst.name} already exists in script folder")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                print(f"[COPY] {src} -> {dst}")
                shutil.copy2(src, dst)
            continue

        # 5) Still missing
        print(f"[MISS] {expected_name} not found (even after fallbacks).")

# ---- CLI
def main():
    ap = argparse.ArgumentParser(description="Extract and copy texture files referenced by an I3D into the script folder (with recursive search and BMP/PNG conversion fallback).")
    ap.add_argument("i3d_file", help="Path to the .i3d file (e.g., domek.i3d)")
    ap.add_argument("--auto-recursive", action="store_true", help="Try recursive search automatically when direct search fails.")
    ap.add_argument("--auto-convert-ext", action="store_true", help="Auto-convert same-stem BMP/PNG files to the expected extension when exact match is missing.")
    ap.add_argument("--yes", action="store_true", help="Answer YES to all prompts (implies --auto-recursive and --auto-convert-ext).")
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

    yes_all = bool(args.yes)
    auto_recursive = True if yes_all else bool(args.auto_recursive)
    auto_convert_ext = True if yes_all else bool(args.auto_convert_ext)

    copy_maps_to_script_dir(
        basenames,
        cfg,
        auto_recursive=auto_recursive,
        auto_convert_ext=auto_convert_ext,
        yes_all=yes_all
    )

if __name__ == "__main__":
    main()

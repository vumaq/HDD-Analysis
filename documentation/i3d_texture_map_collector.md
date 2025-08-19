# I3D Texture Map Collector

📂 [Download Script](../tools/i3d_texture_map_collector.py)

## Overview

The `i3d_texture_map_collector.py` script scans an **Illusion Softworks I3D** file for texture references and copies the found images into the **same folder as the script**, so they're ready for downstream tools like converters or viewers.

It parses material chunks to extract texture file paths, supports any image extension, and performs **case-insensitive** matching on disk while preserving original filename casing when copying.

---

## Features

-   **Texture path extraction** - reads `MAT_MAP_FILEPATH (0xA300)`
    entries from material blocks to discover referenced maps.
-   **Any extension supported** - not limited to PNG; TGA, BMP, JPG,
    etc., are all considered by basename.
-   **Case-insensitive lookup, case-preserving copy** - finds files
    regardless of on-disk casing; copied names keep the I3D's original
    case.
-   **Config-driven search paths** - auto-creates
    `i3d_textures.config.json` on first run; edit `search_paths` to your
    local texture directories.
-   **Safe copy behavior** - skips overwriting existing files in the
    script folder; logs missing textures to the console.
-   **Flat output** - all collected textures are copied directly into
    the script's directory.

---

## Usage

### Basic Collection

``` bash
python i3d_texture_map_collector.py domek.i3d
```

Scans `domek.i3d` for texture references and copies them into the script folder.

### First Run (Config Creation)

On first execution, the script creates a config file:

``` json
{
    "search_paths": [
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/maps",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/maps/censored",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/maps/faces",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/maps/gamemenu",
        "C:/Program Files (x86)/Take2/Hidden and Dangerous Deluxe/data/maps/maps/menu"
    ]
}
```

Edit this file to point to the directories where your textures are stored.

---

## Output Example

``` text
[INFO] Found 3 map(s): wall.png, roof.tga, glass.bmp
[COPY] C:/game/maps/textures/wall.png -> ./wall.png
[COPY] C:/game/maps/textures/roof.tga -> ./roof.tga
[MISS] glass.bmp not found in any search_paths
```

---

## Limitations

-   Does not recurse into subdirectories of `search_paths` (top-level only)
-   Missing files are not auto-downloaded; they must exist locally




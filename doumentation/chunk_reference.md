# I3D Chunk Reference

This document expands the meaning of all known chunk IDs from the
`CID_REG` table. Each entry includes the **chunk ID**, **official/common name**, and a
**detailed description** explaining its role, structure, and context in I3D files.

---

## Root / Edit

- **0x4D4D -- PRIMARY**  
  The root chunk of a I3D file. All other data chunks are contained within this. It establishes the start of the scene hierarchy.

- **0x0002 -- M3D_VERSION**  
  Stores the file format version as a 32-bit integer. Indicates compatibility with different generations of I3D exporters.

- **0x3D3D -- OBJECTINFO**  
  Container for all object- and material-related data used in editing. Includes meshes, cameras, lights, and associated materials.

- **0x3D3E -- EDIT_CONFIG**  
  Editor or mesh configuration block. Usually contains global mesh configuration data such as options flags or version metadata.

---

## Materials

- **0xAFFF -- MATERIAL**  
  Root material container. Holds all subchunks related to material definitions such as names, shading models, colors, and texture maps.

- **0xA000 -- MAT_NAME**  
  The name of the material as a null-terminated C-string. This is the identifier used to link geometry to a material.

- **0xA010 -- MAT_AMBIENT**  
  Ambient color information, stored via subchunks. Defines the low-light baseline color of the material.

- **0xA020 -- MAT_DIFFUSE**  
  Diffuse color data, defining the base color of the material under direct light.

- **0xA030 -- MAT_SPECULAR**  
  Specular highlight color (reflected light). Controls the tint of highlights on shiny surfaces.

- **0xA040 -- MAT_SHININESS**  
  A percent-based shininess value that controls how sharp or broad specular highlights appear.

- **0xA041 -- MAT_SHIN2PCT**  
  Shine strength, effectively scaling the shininess amount to produce stronger or weaker highlights.

- **0xA050 -- MAT_TRANSPARENCY**  
  Material transparency (percent). Higher values mean more transparency.

- **0xA052 -- MAT_XPFALL**  
  Transparency falloff (percent). Controls how transparency fades with depth or viewing angle.

- **0xA053 -- MAT_REFBLUR**  
  Reflection blur, which softens reflections using either a percent or float value.

- **0xA081 -- MAT_TWO_SIDE**  
  Boolean flag to enable two-sided rendering. Useful for thin geometry (like leaves or paper).

- **0xA084 -- MAT_SELF_ILPCT**  
  Self-illumination percentage. Controls how much the material appears to emit light.

- **0xA087 -- MAT_WIRESIZE**  
  Wireframe render size, stored as a float.

- **0xA08A -- MAT_TRANSP_FALLOFF_INOUT**  
  Boolean flag controlling inside vs outside falloff behavior for transparency.

- **0xA100 -- MAT_SHADING**  
  Shading model (u16 enum). Defines the lighting model (Phong, Blinn, etc.).

- **0xA200 -- MAT_TEXMAP**  
  Texture map container. Holds subchunks describing how a texture is applied.

- **0xA300 -- MAT_MAP_FILEPATH**  
  Path to the texture file as a C-string.

- **0xA351 -- MAT_MAP_TILING**  
  Texture tiling flags stored as a 16-bit integer. Encodes UV wrapping and mirroring.

- **0xA353 -- MAT_MAP_TEXBLUR**  
  Blur factor applied to texture lookups, stored as a float.

---

## Mesh

- **0x4000 -- OBJECT**  
  General object container (mesh, camera, light). Contains the object's name and its type-specific subchunks.

- **0x4100 -- OBJECT_MESH**  
  Marks this object as a mesh container. Holds vertex, face, and transformation data.

- **0x4110 -- POINT_ARRAY**  
  Vertex list. Begins with a count (u16), followed by that many (x,y,z) float triplets.

- **0x4111 -- VERTEX_OPTIONS**  
  Optional per-vertex flags. Rarely used.

- **0x4120 -- OBJECT_FACES**  
  Defines face indices. Begins with a count (u16), followed by triplets of vertex indices plus a flags word.  
  Can contain nested material and smoothing subchunks.

- **0x4130 -- OBJECT_MATERIAL**  
  Links a face subset to a material. Contains the material name, followed by indices of faces using it.

- **0x4140 -- OBJECT_UV**  
  UV mapping array. Count (u16) followed by (u,v) float pairs.

- **0x4150 -- OBJECT_SMOOTH**  
  Smoothing group assignments. Each face is assigned a 32-bit mask representing its smoothing group.

- **0x4160 -- OBJECT_TRANS_MATRIX**  
  Local transformation matrix for the object. Stored as 12 floats (3x4 matrix). Defines the orientation and position.

- **0x4165 -- OBJECT_TRI_VISIBLE**  
  Visibility flag for faces, stored as u8.

- **0x4170 -- MESH_TEXTURE_INFO**  
  Vendor-specific extension with extra texture mapping information.

- **0x4190 -- MESH_COLOR**  
  Vertex colors. Format varies between exporters.

- **0x4200 -- FACE_MAP_CHANNEL (I3D-specific)**  
  Defines an **extra UV channel** beyond the base set. Unlike standard I3D, I3D supports multi-channel mapping for more complex texture setups.  
  The chunk typically includes:
  - A channel identifier  
  - UV coordinates for that channel  
  - Per-face references into the UV set  

  This allows multiple textures to map differently onto the same geometry, a feature absent from legacy I3D files. Importers that don't handle this chunk will usually fail to reproduce correct UV layouts.

  [Understanding 4200](../documentation/understanding_4200.md)

---

## Light and Camera

- **0x4600 -- OBJECT_LIGHT**  
  Container for a light object definition. Holds parameters and subchunks for spotlight and intensity.

- **0x4610 -- SPOTLIGHT**  
  Spotlight parameters such as cone angle and falloff.

- **0x4620 -- LIGHT_OFF**  
  Marks the light as disabled.

- **0x4659 -- LIGHT_INNER_RANGE**  
  Inner attenuation range (float).

- **0x465A -- LIGHT_PARAM_FLOAT**  
  Generic float parameter for light attributes.

- **0x465B -- LIGHT_MULTIPLIER**  
  Intensity multiplier (float). Scales the light's brightness.

- **0x4680 -- LIGHT_AMBIENT_LIGHT**  
  Ambient light color definition.

- **0x4700 -- OBJECT_CAMERA**  
  Container for a camera object. Holds position, orientation, and lens parameters.

- **0x4710 -- CAM_PARAM_FLOAT**  
  Float parameter for cameras, such as focal length.

- **0x4720 -- OBJECT_CAM_RANGES**  
  Near and far clipping plane distances.

---

## Keyframer (Animation)

- **0xB000 -- KFDATA**  
  Root container for animation/keyframer data.

- **0xB00A -- KFHDR**  
  Header containing scene-wide animation metadata such as start and end frames.

- **0xB008 -- KFCURTIME_RANGE**  
  Defines the animation playback range (start and end).

- **0xB009 -- KFCURTIME**  
  Current frame/time marker.

- **0xB002 -- OBJECT_NODE_TAG**  
  Node tag for object animation tracks.

- **0xB003 -- CAMERA_NODE_TAG**  
  Node tag for camera animation tracks.

- **0xB004 -- TARGET_NODE_TAG**  
  Node tag for camera/light target tracks.

- **0xB005 -- LIGHT_NODE_TAG**  
  Node tag for light animation tracks.

- **0xB006 -- L_TARGET_NODE_TAG**  
  Node tag for light target animation tracks.

- **0xB007 -- SPOTLIGHT_NODE_TAG**  
  Node tag for spotlight animation tracks.

- **0xB010 -- NODE_HDR**  
  Node header. Stores object name, flags, and parent references.

- **0xB011 -- INSTANCE_NAME**  
  Instance name for duplicated objects.

- **0xB013 -- PIVOT**  
  Pivot point (3 floats). Defines the rotation/scaling pivot of the object.

- **0xB014 -- BOUNDBOX**  
  Bounding box of the object (min/max vectors).

- **0xB020 -- POS_TRACK_TAG**  
  Position track. Contains animation keyframes for translation.

- **0xB021 -- ROT_TRACK_TAG**  
  Rotation track. Stores keyframes in angle/axis format.

- **0xB022 -- SCL_TRACK_TAG**  
  Scale track. Holds per-key scaling values.

- **0xB030 -- NODE_ID**  
  Unique ID of the node (u16).

---

## Viewport / Display

- **0x7001 -- VIEWPORT_LAYOUT**  
  Viewport layout preferences.

- **0x7011 -- VIEWPORT_DATA**  
  General viewport settings.

- **0x7012 -- VIEWPORT_DATA_3**  
  Alternate form of viewport parameters.

- **0x7020 -- MESH_DISPLAY**  
  Mesh display preferences such as visibility toggles.

---

## Color / Percent

- **0x0010 -- COLOR_FLOAT**  
  Color defined as floating-point triplet.

- **0x0011 -- COLOR_24**  
  Color defined as three 8-bit integers (0–255).

- **0x0013 -- LIN_COLOR_24F**  
  Linear RGB color values as floats.

- **0x0030 -- PERCENT_I**  
  Percentage stored as unsigned 16-bit integer (0–100).

- **0x0031 -- PERCENT_F**  
  Percentage stored as float (0–1).

---

## Vendor / Unknown

- **0x0008 -- VENDOR_CONTAINER**  
  A vendor-specific container. Typically used by exporters to store proprietary data.

- **0xFFFF -- VENDOR_CONTAINER_END**  
  Marks the end of a vendor container.

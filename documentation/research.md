# 3DS file format

## 1. [3D-Studio File Format (.3ds)](https://paulbourke.net/dataformats/3ds/)

A detailed breakdown of the **.3ds file format**, used by Autodesk’s 3D Studio. The format is based on a chunk system, where each chunk contains an ID, length, and data. The primary chunk ID is `4D4Dh`, and within it, various sub-chunks define objects, materials, and other scene elements. The document includes a hierarchical diagram and a list of chunk IDs to help explain the structure of the format.

## 2. [3D Studio Material Library File Format (.mli)](https://www.graphicon.ru/oldgr/courses/cg2000s/files/3dsmli.html)

An in-depth look at the **.mli file format** used in 3D Studio. The .mli format is used for defining materials in 3D models, and each material is represented by various chunks that describe properties such as color, reflectivity, textures, and mapping details. The document explains the chunk system used within .mli files and how they are structured to define materials that are applied to 3D models in 3D Studio.

## 3. [3ds2iv: 3ds to Open Inventor Converter](https://merlin.fit.vutbr.cz/upload/IvProjects/2006/3ds2iv/3ds2iv.pdf)

This MSc thesis by Jaroslav Přibyl analyzes the **.3ds file format** and discusses the development of a converter that translates .3ds files into the **Open Inventor (.iv)** format. The document explores scene geometry, material handling, and the internal structure of .3ds files. It also covers how the converter processes object geometry, computes normals with smoothing groups, and generates the Open Inventor scene graph.

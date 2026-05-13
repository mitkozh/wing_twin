#!/usr/bin/env python3
"""
Mesh Export Script

Extracts surface mesh from Ansys/ParaView exported .vtkhdf or .cgns files
and exports to JSON for Unity.

The key operation is vtkDataSetSurfaceFilter which:
- Extracts only the outer surface (removes interior nodes)
- Converts 10-node quadratic tetrahedra to 4-node triangles

Usage:
    python scripts/mesh_export.py --input mesh/wing.vtkhdf --output mesh/mesh.json
"""

import argparse
import json

import numpy as np
import vtk
from vtkmodules.util.numpy_support import vtk_to_numpy


SCRIPT_DIR = __import__("pathlib").Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_MESH_DIR = PROJECT_ROOT / "mesh"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "mesh"


def export_surface_mesh(vtkhdf_path, out_json_path):
    """
    Extract surface mesh from .vtkhdf file and export to JSON.

    Args:
        vtkhdf_path: Path to .vtkhdf or .cgns file
        out_json_path: Path to output JSON file
    """

    reader = vtk.vtkHDFReader()
    reader.SetFileName(vtkhdf_path)
    reader.Update()

    data = reader.GetOutput()
    if data is None:
        raise ValueError(f"Could not read data from {vtkhdf_path}")

    block = data.GetBlock(0)
    if block is None:
        raise ValueError("No blocks found in VTK file")

    block1 = block.GetBlock(0)
    if block1 is None:
        raise ValueError("No sub-blocks found")

    surface_filter = vtk.vtkDataSetSurfaceFilter()
    surface_filter.SetInputData(block1)
    surface_filter.Update()
    surface = surface_filter.GetOutput()

    points_data = surface.GetPoints().GetData()
    vertices = vtk_to_numpy(points_data)

    cells_data = surface.GetPolys().GetData()
    cells = vtk_to_numpy(cells_data)

    triangles = []
    i = 0
    while i < len(cells):
        n = cells[i]
        i += 1
        if n == 3:
            triangles.append(cells[i:i+3].tolist())
        i += n

    output_data = {
        "vertices": vertices.tolist(),
        "triangles": triangles,
        "metadata": {
            "num_vertices": len(vertices),
            "num_triangles": len(triangles),
            "source": str(vtkhdf_path),
        }
    }

    with open(out_json_path, "w") as f:
        json.dump(output_data, f)

    print(f"Exported {len(vertices)} vertices, {len(triangles)} triangles")
    print(f"Saved to: {out_json_path}")
    return output_data


def main():
    parser = argparse.ArgumentParser(description="Export surface mesh from VTK-HDF file")
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Input .vtkhdf or .cgns file path"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output JSON file path"
    )
    parser.add_argument(
        "--list-available",
        action="store_true",
        help="List available mesh files in mesh/ folder"
    )
    args = parser.parse_args()

    if args.list_available:
        print("Available mesh files in mesh/:")
        for ext in ["*.vtkhdf", "*.cgns", "*.vtk"]:
            for f in DEFAULT_MESH_DIR.glob(ext):
                print(f"  {f.name}")
        return

    if args.input is None:
        mesh_files = list(DEFAULT_MESH_DIR.glob("*.vtkhdf")) + list(DEFAULT_MESH_DIR.glob("*.cgns"))
        if not mesh_files:
            print("No mesh files found in mesh/. Place .vtkhdf or .cgns files there.")
            print("Use --list-available to check, or specify --input manually.")
            return
        vtkhdf_path = str(mesh_files[0])
        print(f"Using: {vtkhdf_path}")
    else:
        vtkhdf_path = args.input

    if args.output is None:
        base_name = DEFAULT_MESH_DIR / vtkhdf_path.split("/")[-1].replace(".vtkhdf", "").replace(".cgns", "")
        out_json_path = str(DEFAULT_MESH_DIR / f"{base_name.name}_surface.json")
    else:
        out_json_path = args.output

    export_surface_mesh(vtkhdf_path, out_json_path)


if __name__ == "__main__":
    main()
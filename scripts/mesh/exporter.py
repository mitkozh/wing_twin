"""
Mesh exporter - exports VTK meshes to JSON for Unity.
"""

import json
from pathlib import Path
from typing import Optional, List

import numpy as np
import vtk
from vtkmodules.util.numpy_support import vtk_to_numpy


class MeshExporter:
    """
    Extracts surface mesh from VTK-HDF or CGNS files and exports to JSON.
    """

    def __init__(self, mesh_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        self.mesh_dir = mesh_dir or Path(__file__).parent.parent.parent / "mesh"
        self.output_dir = output_dir or self.mesh_dir

    def export_surface(self, vtkhdf_path: Path, out_json_path: Optional[Path] = None) -> dict:
        """
        Extract surface mesh from VTK file.

        Args:
            vtkhdf_path: Path to .vtkhdf or .cgns file
            out_json_path: Output JSON path (auto-generated if None)

        Returns:
            Dictionary with vertices, triangles, and metadata
        """
        if out_json_path is None:
            base_name = vtkhdf_path.stem
            out_json_path = self.output_dir / f"{base_name}_surface.json"

        reader = vtk.vtkHDFReader()
        reader.SetFileName(str(vtkhdf_path))
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

        print("block1 points:", block1.GetNumberOfPoints())
        print("block1 cells:", block1.GetNumberOfCells())
        surface_filter = vtk.vtkDataSetSurfaceFilter()
        surface_filter.SetInputData(block1)
        surface_filter.PassThroughPointIdsOn()
        surface_filter.PassThroughCellIdsOn()
        surface_filter.Update()
        surface = surface_filter.GetOutput()

        print("Available point data arrays:")
        pd = surface.GetPointData()
        for j in range(pd.GetNumberOfArrays()):
            print(j, pd.GetArrayName(j))

        full_points = vtk_to_numpy(block1.GetPoints().GetData())
        surface_points = vtk_to_numpy(surface.GetPoints().GetData())

        point_ids = []

        for sp in surface_points:
            matches = np.where(np.all(np.isclose(full_points, sp, atol=1e-8), axis=1))[0]

            if len(matches) == 0:
                raise ValueError(f"No full-mesh point found for surface point {sp}")

            point_ids.append(int(matches[0]))

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
            "node_ids": point_ids,  # Original FEA node IDs for each surface vertex
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
        print(f"Node ID mapping: {len(point_ids)} surface -> {max(point_ids) + 1 if point_ids else 0} original")
        return output_data

    def list_available(self) -> list:
        """List available mesh files."""
        files = []
        for ext in ["*.vtkhdf", "*.cgns", "*.vtk"]:
            files.extend(self.mesh_dir.glob(ext))
        return sorted(files)
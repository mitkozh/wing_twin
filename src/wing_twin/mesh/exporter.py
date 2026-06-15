"""
Mesh exporter - exports VTK meshes to JSON for Unity.
"""

import json
from pathlib import Path
from typing import Optional

import numpy as np
import vtk
from vtkmodules.util.numpy_support import vtk_to_numpy

from wing_twin.io.logger import get_logger

logger = get_logger(__name__)

_MESH_DIR = Path(__file__).resolve().parent.parent.parent.parent / "mesh"
_SURFACE_MESH_PATH = _MESH_DIR / "FinalMesh_surface.json"

_surface_node_ids: Optional[list[int]] = None
_section_nodes: Optional[dict[str, list[int]]] = None


def load_surface_node_ids() -> list[int]:
    """Lazy-load the ordered list of surface mesh node IDs."""
    global _surface_node_ids
    if _surface_node_ids is not None:
        return _surface_node_ids

    if not _SURFACE_MESH_PATH.exists():
        raise FileNotFoundError(f"Surface mesh not found: {_SURFACE_MESH_PATH}")

    with open(_SURFACE_MESH_PATH) as f:
        data = json.load(f)

    if "node_ids" not in data:
        raise KeyError(f"'node_ids' key missing from {_SURFACE_MESH_PATH}")

    node_ids = data["node_ids"]
    if not node_ids:
        raise ValueError(f"node_ids is empty in {_SURFACE_MESH_PATH}")

    _surface_node_ids = node_ids
    return _surface_node_ids


def load_section_nodes() -> dict[str, list[int]]:
    """Lazy-load node IDs grouped by wing section (root / middle / tip)."""
    global _section_nodes
    if _section_nodes is not None:
        return _section_nodes

    if not _SURFACE_MESH_PATH.exists():
        _section_nodes = {"root": [], "middle": [], "tip": []}
        return _section_nodes

    with open(_SURFACE_MESH_PATH) as f:
        data = json.load(f)

    vertices = data.get("vertices", [])
    node_ids = data.get("node_ids", [])

    if not vertices or not node_ids or len(vertices) != len(node_ids):
        _section_nodes = {"root": [], "middle": [], "tip": []}
        return _section_nodes

    span_min = min(v[0] for v in vertices)
    span_max = max(v[0] for v in vertices)
    span_range = span_max - span_min

    if span_range <= 0:
        _section_nodes = {"root": [], "middle": [], "tip": []}
        return _section_nodes

    third = span_range / 3.0
    sections: dict[str, list[int]] = {"root": [], "middle": [], "tip": []}
    for i, v in enumerate(vertices):
        nid = node_ids[i]
        pos = v[0] - span_min
        if pos < third:
            sections["root"].append(nid)
        elif pos < 2 * third:
            sections["middle"].append(nid)
        else:
            sections["tip"].append(nid)

    _section_nodes = sections
    return _section_nodes


class MeshExporter:
    """Extracts surface mesh from VTK-HDF or CGNS files and exports to JSON."""

    def __init__(self, mesh_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        self.mesh_dir = mesh_dir or Path(__file__).resolve().parent.parent.parent.parent / "mesh"
        self.output_dir = output_dir or self.mesh_dir

    def export_surface(self, vtkhdf_path: Path, out_json_path: Optional[Path] = None) -> dict:
        if out_json_path is None:
            out_json_path = self.output_dir / "FinalMesh_surface.json"

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

        logger.debug("block1 points: %d", block1.GetNumberOfPoints())
        logger.debug("block1 cells: %d", block1.GetNumberOfCells())
        surface_filter = vtk.vtkDataSetSurfaceFilter()
        surface_filter.SetInputData(block1)
        surface_filter.PassThroughPointIdsOn()
        surface_filter.PassThroughCellIdsOn()
        surface_filter.Update()
        surface = surface_filter.GetOutput()

        logger.debug("Available point data arrays:")
        pd = surface.GetPointData()
        for j in range(pd.GetNumberOfArrays()):
            logger.debug("%d %s", j, pd.GetArrayName(j))

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
            "node_ids": point_ids,
            "metadata": {
                "num_vertices": len(vertices),
                "num_triangles": len(triangles),
                "source": str(vtkhdf_path),
            }
        }

        with open(out_json_path, "w") as f:
            json.dump(output_data, f)

        logger.info("Exported %d vertices, %d triangles", len(vertices), len(triangles))
        logger.info("Saved to: %s", out_json_path)
        logger.info("Node ID mapping: %d surface -> %d original", len(point_ids), max(point_ids) + 1 if point_ids else 0)
        return output_data

    def list_available(self) -> list:
        files = []
        for ext in ["*.vtkhdf", "*.cgns", "*.vtk"]:
            files.extend(self.mesh_dir.glob(ext))
        return sorted(files)

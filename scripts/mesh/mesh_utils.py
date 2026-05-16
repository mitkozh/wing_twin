"""
Mesh utilities - load surface mesh and extract node mappings.
"""

import json
from pathlib import Path
from typing import Optional, List

PROJECT_ROOT = Path(__file__).parent.parent.parent


def get_mesh_node_ids(mesh_name: str = "FinalMesh_surface") -> List[int]:
    """Load node IDs from exported mesh JSON."""
    mesh_path = PROJECT_ROOT / "mesh" / f"{mesh_name}.json"
    
    if not mesh_path.exists():
        return None
    
    with open(mesh_path) as f:
        data = json.load(f)
    
    return data.get("node_ids")


def get_surface_stress_field(full_stress_field: List[float], mesh_name: str = "FinalMesh_surface") -> List[float]:
    """Extract stress values for surface nodes only."""
    node_ids = get_mesh_node_ids(mesh_name)
    
    if node_ids is None or not full_stress_field:
        return []
    
    return [full_stress_field[i] for i in node_ids if i < len(full_stress_field)]
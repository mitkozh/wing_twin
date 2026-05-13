# Mesh Files

Place `.vtkhdf` or `.cgns` files here for mesh export.

## Expected Files

- `wing.vtkhdf` or `wing.cgns` — Ansys/ParaView exported mesh with quadratic tetrahedra

## Usage

```bash
python scripts/mesh_export.py --input mesh/wing.vtkhdf --output mesh/mesh.json
```

The script uses `vtkDataSetSurfaceFilter` to automatically:
- Extract only the outer surface (removes interior elements)
- Convert 10-node quadratic tetrahedra to 4-node triangles
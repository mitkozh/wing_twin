"""
Wing Digital Twin Mesh Export CLI Entry Point.
"""

import argparse

from pathlib import Path

from scripts.config import PROJECT_ROOT
from scripts.mesh.exporter import MeshExporter


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

    mesh_dir = PROJECT_ROOT / "mesh"
    exporter = MeshExporter(mesh_dir=mesh_dir, output_dir=mesh_dir)

    if args.list_available:
        print("Available mesh files in mesh/:")
        for f in exporter.list_available():
            print(f"  {f.name}")
        return

    if args.input is None:
        mesh_files = exporter.list_available()
        if not mesh_files:
            print("No mesh files found in mesh/. Place .vtkhdf or .cgns files there.")
            print("Use --list-available to check, or specify --input manually.")
            return
        vtkhdf_path = mesh_files[0]
        print(f"Using: {vtkhdf_path}")
    else:
        from pathlib import Path
        vtkhdf_path = Path(args.input)

    if args.output is None:
        out_json_path = None
    else:
        from pathlib import Path
        out_json_path = Path(args.output)

    exporter.export_surface(vtkhdf_path, out_json_path)


if __name__ == "__main__":
    main()
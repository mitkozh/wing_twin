"""
CLI module - Command-line entry points.
"""

from .demo import main as demo_main
from .run import main as run_main
from .simulator import main as simulator_main
from .visualizer import main as visualizer_main
from .offline import main as offline_main
from .mesh_export import main as mesh_export_main

__all__ = [
    "demo_main",
    "run_main",
    "simulator_main",
    "visualizer_main",
    "offline_main",
    "mesh_export_main",
]
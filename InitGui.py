"""
InitGui.py
----------
Top-level FreeCAD GUI entry point.

FreeCAD scans every directory on its module path for a file called
``InitGui.py`` and executes it when the GUI starts.  This file simply
delegates to the workbench package.
"""

import sys
import os

# Make sure the package directory is importable when installed as a plain
# directory (not via pip / site-packages).
_addon_dir = os.path.dirname(__file__)
if _addon_dir not in sys.path:
    sys.path.insert(0, _addon_dir)

from freecad.HexLatticeMaker import init_gui   # noqa: F401, E402 – side-effect import

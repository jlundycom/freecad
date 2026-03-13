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
# NOTE: FreeCAD executes InitGui.py via exec() without setting __file__ in the
# namespace, so we guard against NameError.  When __file__ is unavailable,
# FreeCAD has already added the addon directory to sys.path, so no manual
# manipulation is needed.
try:
    _addon_dir = os.path.dirname(os.path.abspath(__file__))
    if _addon_dir not in sys.path:
        sys.path.insert(0, _addon_dir)
except NameError:
    pass  # FreeCAD already set up sys.path before executing this file

from freecad.HexLatticeMaker import init_gui   # noqa: F401, E402 – side-effect import

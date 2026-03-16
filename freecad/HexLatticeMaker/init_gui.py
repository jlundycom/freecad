"""
init_gui.py
-----------
FreeCAD GUI initialisation for the HexLatticeMaker workbench.

Loaded automatically by FreeCAD when the user activates the workbench.
"""

import os
import FreeCAD as App
import FreeCADGui as Gui

_DIR = os.path.dirname(__file__)
_ICON_PATH = os.path.join(_DIR, "Resources", "Icons")


# ---------------------------------------------------------------------------
# Command: CreateHexLatticePart
# ---------------------------------------------------------------------------

class CreateHexLatticePartCmd:
    """FreeCAD command that opens the dialog and creates the pieces."""

    def GetResources(self):
        return {
            "Pixmap":   os.path.join(_ICON_PATH, "HexLatticePart.svg"),
            "MenuText": "Create Hex Lattice Part",
            "ToolTip":  (
                "Create a parametric flat part filled with a hexagonal lattice, "
                "automatically sliced into finger-jointed pieces ≤ 220 mm."
            ),
        }

    def IsActive(self):
        return True   # always available

    def Activated(self):
        """Show dialog, then build and add shapes to the active document."""
        try:
            from .create_part_dialog import HexLatticeDialog
            from .hex_lattice_core   import create_all_pieces
        except ImportError:
            from create_part_dialog import HexLatticeDialog
            from hex_lattice_core   import create_all_pieces

        dlg = HexLatticeDialog(Gui.getMainWindow())
        if dlg.exec_() != dlg.Accepted:
            return

        params = dlg.get_params()
        _build_parts(params)


def _build_parts(params: dict):
    """Build pieces and add them to the FreeCAD document."""
    from .hex_lattice_core import create_all_pieces

    doc = App.activeDocument()
    if doc is None:
        doc = App.newDocument("HexLatticePart")

    App.Console.PrintMessage(
        f"[HexLatticeMaker] Creating pieces for "
        f"{params['width']} × {params['length']} × {params['height']} mm "
        f"(wall={params['wall_thickness']} mm, "
        f"max_piece={params['max_piece_size']} mm) …\n"
    )

    pieces = create_all_pieces(**params)

    for name, shape in pieces:
        obj = doc.addObject("Part::Feature", name)
        obj.Shape = shape

    doc.recompute()
    Gui.SendMsgToActiveView("ViewFit")
    App.Console.PrintMessage(
        f"[HexLatticeMaker] Done – {len(pieces)} piece(s) created.\n"
    )


# ---------------------------------------------------------------------------
# Command: CreateShelfWithLegs
# ---------------------------------------------------------------------------

class CreateShelfWithLegsCmd:
    """FreeCAD command that opens the shelf-with-legs dialog and creates parts."""

    def GetResources(self):
        return {
            "Pixmap":   os.path.join(_ICON_PATH, "ShelfWithLegs.svg"),
            "MenuText": "Create Shelf with Legs",
            "ToolTip":  (
                "Create a hex-lattice shelf panel with corner holes and "
                "four individual printable legs that plug into those holes "
                "to provide vertical support."
            ),
        }

    def IsActive(self):
        return True   # always available

    def Activated(self):
        """Show dialog, then build and add shapes to the active document."""
        try:
            from .create_part_dialog import ShelfWithLegsDialog
        except ImportError:
            from create_part_dialog import ShelfWithLegsDialog

        dlg = ShelfWithLegsDialog(Gui.getMainWindow())
        if dlg.exec_() != dlg.Accepted:
            return

        params = dlg.get_params()
        _build_shelf_with_legs(params)


def _build_shelf_with_legs(params: dict):
    """Build shelf pieces and leg parts, then add them to the FreeCAD document."""
    from .hex_lattice_core import create_shelf_with_legs

    doc = App.activeDocument()
    if doc is None:
        doc = App.newDocument("ShelfWithLegs")

    App.Console.PrintMessage(
        f"[HexLatticeMaker] Creating shelf with legs: "
        f"{params['width']} × {params['length']} × {params['height']} mm, "
        f"legs {params['leg_width']} × {params['leg_height']} mm …\n"
    )

    pieces = create_shelf_with_legs(**params)

    for name, shape, placement in pieces:
        obj = doc.addObject("Part::Feature", name)
        obj.Shape = shape
        obj.Placement = App.Placement(placement, App.Rotation())

    doc.recompute()
    Gui.SendMsgToActiveView("ViewFit")
    leg_count   = sum(1 for n, _s, _p in pieces if n.startswith("Leg_"))
    shelf_count = len(pieces) - leg_count
    App.Console.PrintMessage(
        f"[HexLatticeMaker] Done – {shelf_count} shelf piece(s) + "
        f"{leg_count} leg(s) created.\n"
    )


# ---------------------------------------------------------------------------
# Command: CreateBox
# ---------------------------------------------------------------------------

class CreateBoxCmd:
    """FreeCAD command that opens the box dialog and creates all box pieces."""

    def GetResources(self):
        return {
            "Pixmap":   os.path.join(_ICON_PATH, "HexLatticeBox.svg"),
            "MenuText": "Create Box",
            "ToolTip":  (
                "Create a hex-lattice open-top box whose five solid panels "
                "(bottom + four walls) all print flat with no supports.  "
                "Wall panels slide horizontally onto the bottom panel's edge "
                "step-joints and lock against vertical movement."
            ),
        }

    def IsActive(self):
        return True   # always available

    def Activated(self):
        """Show dialog, then build and add shapes to the active document."""
        try:
            from .create_part_dialog import BoxDialog
        except ImportError:
            from create_part_dialog import BoxDialog

        dlg = BoxDialog(Gui.getMainWindow())
        if dlg.exec_() != dlg.Accepted:
            return

        params = dlg.get_params()
        _build_box(params)


def _build_box(params: dict):
    """Build box pieces and add them to the FreeCAD document."""
    from .hex_lattice_core import create_box

    doc = App.activeDocument()
    if doc is None:
        doc = App.newDocument("HexLatticeBox")

    App.Console.PrintMessage(
        f"[HexLatticeMaker] Creating box: "
        f"{params['width']} × {params['length']} × {params['height']} mm "
        f"(wall height={params['box_height']} mm) …\n"
    )

    pieces = create_box(**params)

    for name, shape, placement in pieces:
        obj = doc.addObject("Part::Feature", name)
        obj.Shape = shape
        obj.Placement = placement

    doc.recompute()
    Gui.SendMsgToActiveView("ViewFit")
    App.Console.PrintMessage(
        f"[HexLatticeMaker] Done – {len(pieces)} piece(s) created.\n"
    )


# ---------------------------------------------------------------------------
# Workbench definition
# ---------------------------------------------------------------------------

class HexLatticeMakerWorkbench(Gui.Workbench):
    """HexLatticeMaker workbench."""

    MenuText = "HexLatticeMaker"
    ToolTip  = "Create parametric hex-lattice parts for 3-D printing"
    Icon     = os.path.join(_ICON_PATH, "HexLatticeMaker.svg")

    def GetClassName(self):
        return "Gui::PythonWorkbench"

    def Initialize(self):
        Gui.addCommand("HexLatticeMaker_CreatePart",      CreateHexLatticePartCmd())
        Gui.addCommand("HexLatticeMaker_CreateShelfLegs", CreateShelfWithLegsCmd())
        Gui.addCommand("HexLatticeMaker_CreateBox",       CreateBoxCmd())
        self.appendToolbar("HexLatticeMaker",
                           ["HexLatticeMaker_CreatePart",
                            "HexLatticeMaker_CreateShelfLegs",
                            "HexLatticeMaker_CreateBox"])
        self.appendMenu("Hex Lattice",
                        ["HexLatticeMaker_CreatePart",
                         "HexLatticeMaker_CreateShelfLegs",
                         "HexLatticeMaker_CreateBox"])
        App.Console.PrintLog("[HexLatticeMaker] Workbench initialised.\n")

    def Activated(self):
        App.Console.PrintLog("[HexLatticeMaker] Workbench activated.\n")

    def Deactivated(self):
        App.Console.PrintLog("[HexLatticeMaker] Workbench deactivated.\n")


Gui.addWorkbench(HexLatticeMakerWorkbench())

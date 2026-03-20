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
            "Pixmap":   os.path.join(_ICON_PATH, "HexLatticeMaker.svg"),
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
            "Pixmap":   os.path.join(_ICON_PATH, "HexLatticeMaker.svg"),
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
# Command: CreateGridfinityBox
# ---------------------------------------------------------------------------

class CreateGridfinityBoxCmd:
    """FreeCAD command that opens the Gridfinity dialog and creates the box."""

    def GetResources(self):
        return {
            "Pixmap":   os.path.join(_ICON_PATH, "HexLatticeMaker.svg"),
            "MenuText": "Create Gridfinity Box",
            "ToolTip":  (
                "Create a parametric Gridfinity-compatible storage box with "
                "customisable interior pockets, optional lid, and optional "
                "corner magnet holes."
            ),
        }

    def IsActive(self):
        return True   # always available

    def Activated(self):
        """Show dialog, then build and add shapes to the active document."""
        try:
            from .create_part_dialog import GridfinityDialog
        except ImportError:
            from create_part_dialog import GridfinityDialog

        dlg = GridfinityDialog(Gui.getMainWindow())
        if dlg.exec_() != dlg.Accepted:
            return

        params = dlg.get_params()
        _build_gridfinity_box(params)


def _build_gridfinity_box(params: dict):
    """Build gridfinity box parts and add them to the FreeCAD document.

    Workflow
    --------
    1. The raw box body (no container cuts) is added as a hidden
       ``Part::Feature`` named ``GF_Box_Body``.
    2. Each container pocket is added as a hidden ``Part::Feature`` with its
       geometry centred at the local origin and its world position set via
       the ``Placement`` attribute.
    3. A chain of ``Part::Cut`` objects is built — one per container — so
       that repositioning a container feature automatically updates the cut.
       The last (or only) cut is named ``GF_Box`` and left visible.
       Intermediate cuts are hidden.
    4. If no containers are provided, ``GF_Box_Body`` is renamed ``GF_Box``
       and made visible directly.
    5. The optional lid (``GF_Lid``) is added as a separate visible feature.
    """
    try:
        from .gridfinity_core import create_gridfinity_box, GRIDFINITY_UNIT
    except ImportError:
        from gridfinity_core import create_gridfinity_box, GRIDFINITY_UNIT

    doc = App.activeDocument()
    if doc is None:
        doc = App.newDocument("GridfinityBox")

    outer_x = params["grid_x"] * GRIDFINITY_UNIT
    outer_y = params["grid_y"] * GRIDFINITY_UNIT
    App.Console.PrintMessage(
        f"[HexLatticeMaker] Creating Gridfinity box "
        f"{params['grid_x']} × {params['grid_y']} units "
        f"({outer_x:.0f} × {outer_y:.0f} mm), "
        f"height={params['box_height']} mm …\n"
    )

    result = create_gridfinity_box(**{k: v for k, v in params.items()})

    # ------------------------------------------------------------------
    # 1. Box body (uncut) – hidden so only the final cut is visible
    # ------------------------------------------------------------------
    box_body_obj = doc.addObject("Part::Feature", "GF_Box_Body")
    box_body_obj.Shape = result["box_body"]
    box_body_obj.Visibility = False

    # ------------------------------------------------------------------
    # 2. Container cutter features – geometry centred at origin,
    #    positioned via Placement
    # ------------------------------------------------------------------
    container_objs = []
    for cspec in result["containers"]:
        cobj = doc.addObject("Part::Feature", cspec["name"])
        cobj.Shape = cspec["shape"]
        px, py, pz = cspec["placement"]
        cobj.Placement = App.Placement(App.Vector(px, py, pz), App.Rotation())
        cobj.Visibility = False
        container_objs.append(cobj)

    # ------------------------------------------------------------------
    # 3. Part::Cut chain – each cut links a container to the previous result
    #    so that moving the container updates the hole automatically
    # ------------------------------------------------------------------
    current_obj = box_body_obj
    for i, cobj in enumerate(container_objs):
        is_last  = (i == len(container_objs) - 1)
        cut_name = "GF_Box" if is_last else f"GF_Cut_{i + 1}"
        cut_obj  = doc.addObject("Part::Cut", cut_name)
        cut_obj.Base = current_obj
        cut_obj.Tool = cobj
        cut_obj.Visibility = is_last
        current_obj = cut_obj

    # If no containers were added, the box body is the final object
    if not container_objs:
        box_body_obj.Label = "GF_Box"
        box_body_obj.Visibility = True

    # ------------------------------------------------------------------
    # 4. Optional lid
    # ------------------------------------------------------------------
    if result.get("lid") is not None:
        lid_obj = doc.addObject("Part::Feature", "GF_Lid")
        lid_obj.Shape = result["lid"]

    doc.recompute()
    Gui.SendMsgToActiveView("ViewFit")
    container_count = len(container_objs)
    has_lid = result.get("lid") is not None
    App.Console.PrintMessage(
        f"[HexLatticeMaker] Done – Gridfinity box created "
        f"with {container_count} container pocket(s)"
        + (" + lid" if has_lid else "")
        + ".\n"
    )


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
        Gui.addCommand("HexLatticeMaker_CreateGFBox",     CreateGridfinityBoxCmd())
        self.appendToolbar("HexLatticeMaker",
                           ["HexLatticeMaker_CreatePart",
                            "HexLatticeMaker_CreateShelfLegs",
                            "HexLatticeMaker_CreateGFBox"])
        self.appendMenu("Hex Lattice",
                        ["HexLatticeMaker_CreatePart",
                         "HexLatticeMaker_CreateShelfLegs",
                         "HexLatticeMaker_CreateGFBox"])
        App.Console.PrintLog("[HexLatticeMaker] Workbench initialised.\n")

    def Activated(self):
        App.Console.PrintLog("[HexLatticeMaker] Workbench activated.\n")

    def Deactivated(self):
        App.Console.PrintLog("[HexLatticeMaker] Workbench deactivated.\n")


Gui.addWorkbench(HexLatticeMakerWorkbench())

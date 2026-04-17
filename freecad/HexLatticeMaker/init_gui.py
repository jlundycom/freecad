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
# Parametric FreeCAD feature classes (Part::FeaturePython)
# ---------------------------------------------------------------------------
# Objects created by this workbench are parametric: all input parameters are
# stored as FreeCAD document properties, and the geometry is rebuilt
# automatically when any property is changed via the Properties panel.

class _ViewProvider:
    """Minimal view provider for parametric HexLatticeMaker objects."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return os.path.join(_ICON_PATH, "HexLatticeMaker.svg")

    def attach(self, vobj):
        pass

    def updateData(self, fp, prop):
        pass

    def onChanged(self, vp, prop):
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


class _HexLatticeFlatFeature:
    """Parametric FreeCAD feature for a flat hex-lattice panel.

    All panel parameters are stored as document properties.  FreeCAD calls
    ``execute()`` automatically when any property is changed via the
    Properties panel, rebuilding the full compound shape.
    """

    _FLOAT_PROPS = [
        # (attr, group, description, default)
        ("Width",          "Dimensions",  "Part width (mm)",                        300.0),
        ("Length",         "Dimensions",  "Part length (mm)",                       300.0),
        ("Height",         "Dimensions",  "Part height / thickness (mm)",            10.0),
        ("PerimWidth",     "Lattice",     "Solid perimeter width (mm)",               6.0),
        ("HexSize",        "Lattice",     "Cell size — side length (mm)",             8.0),
        ("WallThickness",  "Lattice",     "Min wall thickness between cells (mm)",    1.5),
        ("MaxPieceSize",   "Slicing",     "Maximum printable piece size (mm)",      220.0),
        ("JointWidth",     "Joints",      "Bridge width (mm; 0 = auto)",              0.0),
        ("FingerW",        "Joints",      "Finger tab width (mm; 0 = auto)",          0.0),
        ("FingerSpacing",  "Joints",      "Gap between fingers (mm; 0 = contiguous)", 0.0),
        ("JointDepth",     "Joints",      "Tab penetration depth (mm; 0 = auto)",     0.0),
        ("SupportSpacing", "Structure",   "Support bar spacing (mm; 0 = none)",       0.0),
        ("SupportWidth",   "Structure",   "Support bar width (mm; 0 = auto)",         0.0),
        ("ScrewHoleDiam",  "ScrewJoints", "Screw hole diameter (mm)",                 3.5),
        ("ScrewSpacing",   "ScrewJoints", "Hole spacing along joint face (mm; 0 = midpoint)", 0.0),
    ]

    _BOOL_PROPS = [
        ("ScrewJoint", "ScrewJoints", "Add screw through-holes at every joint", False),
    ]

    def __init__(self, obj, params: dict):
        for attr, group, desc, default in self._FLOAT_PROPS:
            obj.addProperty("App::PropertyFloat", attr, group, desc)
            setattr(obj, attr, default)
        for attr, group, desc, default in self._BOOL_PROPS:
            obj.addProperty("App::PropertyBool", attr, group, desc)
            setattr(obj, attr, default)

        obj.addProperty(
            "App::PropertyEnumeration", "LatticeType", "Lattice",
            "Lattice pattern type",
        )
        try:
            from .hex_lattice_core import LATTICE_TYPES
        except ImportError:
            from hex_lattice_core import LATTICE_TYPES
        _lt_keys = list(LATTICE_TYPES.keys())
        obj.LatticeType = _lt_keys
        obj.LatticeType = _lt_keys[0]  # first key is the default (currently "solid")

        obj.addProperty(
            "App::PropertyEnumeration", "JointStyle", "Joints",
            "Joint style: step (default) or taper",
        )
        obj.JointStyle = ["step", "taper"]
        obj.JointStyle = "step"

        self._apply_params(obj, params)
        obj.Proxy = self

    # ------------------------------------------------------------------
    def _apply_params(self, obj, params: dict):
        _map = {
            "width":               "Width",
            "length":              "Length",
            "height":              "Height",
            "perim_width":         "PerimWidth",
            "hex_size":            "HexSize",
            "wall_thickness":      "WallThickness",
            "max_piece_size":      "MaxPieceSize",
            "lattice_type":        "LatticeType",
            "joint_width":         "JointWidth",
            "finger_w":            "FingerW",
            "finger_spacing":      "FingerSpacing",
            "joint_depth":         "JointDepth",
            "support_spacing":     "SupportSpacing",
            "support_width":       "SupportWidth",
            "joint_style":         "JointStyle",
            "screw_joint":         "ScrewJoint",
            "screw_hole_diameter": "ScrewHoleDiam",
            "screw_joint_spacing": "ScrewSpacing",
        }
        for py_key, attr in _map.items():
            if py_key in params and params[py_key] is not None:
                try:
                    setattr(obj, attr, params[py_key])
                except Exception:
                    pass

    def _collect_params(self, obj) -> dict:
        return {
            "width":               obj.Width,
            "length":              obj.Length,
            "height":              obj.Height,
            "perim_width":         obj.PerimWidth,
            "hex_size":            obj.HexSize,
            "wall_thickness":      obj.WallThickness or None,
            "max_piece_size":      obj.MaxPieceSize,
            "lattice_type":        obj.LatticeType,
            "joint_width":         obj.JointWidth or None,
            "finger_w":            obj.FingerW or None,
            "finger_spacing":      obj.FingerSpacing,
            "joint_depth":         obj.JointDepth or None,
            "support_spacing":     obj.SupportSpacing,
            "support_width":       obj.SupportWidth or None,
            "joint_style":         obj.JointStyle,
            "screw_joint":         obj.ScrewJoint,
            "screw_hole_diameter": obj.ScrewHoleDiam,
            "screw_joint_spacing": obj.ScrewSpacing,
        }

    def execute(self, obj):
        try:
            try:
                from .hex_lattice_core import create_all_pieces
            except ImportError:
                from hex_lattice_core import create_all_pieces
            import Part
        except ImportError as exc:
            App.Console.PrintWarning(
                f"[HexLatticeMaker] Cannot execute: {exc}\n"
            )
            return

        params = self._collect_params(obj)
        try:
            pieces = create_all_pieces(**params)
        except Exception as exc:
            App.Console.PrintError(
                f"[HexLatticeMaker] Geometry error in execute: {exc}\n"
            )
            return

        if not pieces:
            return
        obj.Shape = Part.makeCompound([shp for _, shp in pieces])

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


class _ShelfWithLegsFeature(_HexLatticeFlatFeature):
    """Parametric FreeCAD feature for a shelf panel with corner legs."""

    _EXTRA_FLOAT_PROPS = [
        ("LegHeight", "Legs", "Leg column height below shelf (mm)", 100.0),
        ("LegWidth",  "Legs", "Leg square cross-section side (mm)",  20.0),
    ]

    def __init__(self, obj, params: dict):
        super().__init__(obj, params)
        for attr, group, desc, default in self._EXTRA_FLOAT_PROPS:
            obj.addProperty("App::PropertyFloat", attr, group, desc)
            setattr(obj, attr, default)
        if "leg_height" in params:
            try:
                obj.LegHeight = params["leg_height"]
            except Exception:
                pass
        if "leg_width" in params:
            try:
                obj.LegWidth = params["leg_width"]
            except Exception:
                pass

    def _collect_params(self, obj) -> dict:
        params = super()._collect_params(obj)
        params["leg_height"] = obj.LegHeight
        params["leg_width"]  = obj.LegWidth
        return params

    def execute(self, obj):
        try:
            try:
                from .hex_lattice_core import create_shelf_with_legs
            except ImportError:
                from hex_lattice_core import create_shelf_with_legs
            import Part
        except ImportError as exc:
            App.Console.PrintWarning(
                f"[HexLatticeMaker] Cannot execute: {exc}\n"
            )
            return

        params = self._collect_params(obj)
        try:
            pieces = create_shelf_with_legs(**params)
        except Exception as exc:
            App.Console.PrintError(
                f"[HexLatticeMaker] Geometry error in execute: {exc}\n"
            )
            return

        if not pieces:
            return

        # Apply placement vectors to produce world-space shapes for the compound.
        shapes = []
        for _name, shape, pl_vec in pieces:
            if pl_vec.Length > 1e-9:
                moved = shape.copy()
                moved.translate(App.Vector(pl_vec.x, pl_vec.y, pl_vec.z))
                shapes.append(moved)
            else:
                shapes.append(shape)

        obj.Shape = Part.makeCompound(shapes)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


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
    """Build a parametric hex-lattice flat-panel feature and add it to the document."""
    doc = App.activeDocument()
    if doc is None:
        doc = App.newDocument("HexLatticePart")

    App.Console.PrintMessage(
        f"[HexLatticeMaker] Creating parametric hex-lattice flat panel "
        f"{params['width']} × {params['length']} × {params['height']} mm "
        f"(lattice={params.get('lattice_type', 'solid')}) …\n"
    )

    obj = doc.addObject("Part::FeaturePython", "HexLatticePart")
    _HexLatticeFlatFeature(obj, params)
    if hasattr(obj, "ViewObject") and obj.ViewObject:
        _ViewProvider(obj.ViewObject)

    doc.recompute()
    Gui.SendMsgToActiveView("ViewFit")
    App.Console.PrintMessage("[HexLatticeMaker] Done.\n")


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
    """Build a parametric shelf-with-legs feature and add it to the document."""
    doc = App.activeDocument()
    if doc is None:
        doc = App.newDocument("ShelfWithLegs")

    App.Console.PrintMessage(
        f"[HexLatticeMaker] Creating parametric shelf "
        f"{params['width']} × {params['length']} × {params['height']} mm, "
        f"legs {params['leg_width']} × {params['leg_height']} mm …\n"
    )

    obj = doc.addObject("Part::FeaturePython", "ShelfWithLegs")
    _ShelfWithLegsFeature(obj, params)
    if hasattr(obj, "ViewObject") and obj.ViewObject:
        _ViewProvider(obj.ViewObject)

    doc.recompute()
    Gui.SendMsgToActiveView("ViewFit")
    App.Console.PrintMessage("[HexLatticeMaker] Done.\n")



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

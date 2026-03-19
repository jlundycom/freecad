"""
gridfinity_core.py
------------------
Core geometry engine for the Gridfinity Box Builder FreeCAD plugin.

Gridfinity is a modular storage system based on a 42 × 42 mm grid unit.
This module creates parametric storage boxes whose interior pocket cutters
are returned as separate named shapes so they can be added to the FreeCAD
document as individual adjustable primitives.

Coordinate convention
---------------------
  X  = width direction  (grid_x units × GRIDFINITY_UNIT)
  Y  = length direction (grid_y units × GRIDFINITY_UNIT)
  Z  = height direction (box_height, measured from the bottom face)

Box interior
------------
The interior of the box has two zones in Z:

  z = 0 … shell_thickness          : bottom floor (solid)
  z = shell_thickness … floor_top  : solid interior base block (height = interior_height)
  z = floor_top … box_height       : open air cavity (accessible from the top)

where ``floor_top = shell_thickness + interior_height``.

Container holes are cut **downward** from ``floor_top`` into the solid interior
base.  Their depth must not exceed ``interior_height``.

Magnet holes
------------
Magnet holes are cylindrical pockets drilled **upward** from the bottom face
(z = 0) of the box floor, one at each of the four corners.  Optional corner
pads add extra solid material around each hole so there is sufficient wall
thickness to hold the magnet securely.

Lid
---
The lid is a flat rectangular plate that rests on top of the open box.  Its
XY footprint equals the box outer footprint; its height is ``lid_height``.
Optional magnet holes are drilled at the same XY corner centres used for the
box.

Primitives preservation
-----------------------
Container cutters and magnet-hole cutters are returned as independent shape
objects from :func:`create_gridfinity_box`.  Callers should add them as
separate ``Part::Feature`` document objects so the user can inspect and
adjust their parameters after creation.
"""

import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRIDFINITY_UNIT        = 42.0   # mm - grid cell width/length
GRIDFINITY_HEIGHT_UNIT = 7.0    # mm - standard height unit

# ---------------------------------------------------------------------------
# Pure-Python helpers  (no FreeCAD dependency – fully unit-testable)
# ---------------------------------------------------------------------------


def gridfinity_outer_dimensions(grid_x: int, grid_y: int) -> tuple:
    """Return ``(width, length)`` outer dimensions (mm) for *grid_x* × *grid_y* units.

    Parameters
    ----------
    grid_x : number of gridfinity units along X (≥ 1)
    grid_y : number of gridfinity units along Y (≥ 1)

    Returns
    -------
    (width, length) tuple in mm
    """
    return (float(grid_x) * GRIDFINITY_UNIT, float(grid_y) * GRIDFINITY_UNIT)


def magnet_corner_centres(
    outer_x: float,
    outer_y: float,
    shell_thickness: float,
    corner_pad: float = 0.0,
) -> list:
    """Return ``(cx, cy)`` centre positions for the four corner magnet holes.

    Each magnet hole is centred inside a corner block whose inset is
    ``(shell_thickness + corner_pad) / 2`` from the nearest outer edge.

    Parameters
    ----------
    outer_x, outer_y : outer box dimensions (mm)
    shell_thickness  : wall / floor thickness (mm)
    corner_pad       : additional padding added to corner thickness (mm)

    Returns
    -------
    list of four ``(cx, cy)`` tuples in order:
        [bottom-left, bottom-right, top-left, top-right]
    """
    offset = (shell_thickness + corner_pad) / 2.0
    return [
        (offset,              offset),               # bottom-left
        (outer_x - offset,    offset),               # bottom-right
        (offset,              outer_y - offset),     # top-left
        (outer_x - offset,    outer_y - offset),     # top-right
    ]


def validate_container(spec: dict, outer_x: float, outer_y: float) -> list:
    """Return a (possibly empty) list of error strings for *spec*.

    Parameters
    ----------
    spec    : container spec dict with keys ``type``, ``depth``, ``x``, ``y``
              and either ``radius`` (cylinder) or ``width`` + ``length`` (rect).
    outer_x, outer_y : box outer dimensions (mm) — used to check positions.

    Returns
    -------
    list of human-readable error strings (empty = valid).
    """
    errors = []
    ctype = spec.get("type")
    if ctype not in ("cylinder", "rectangle"):
        errors.append(f"Unknown container type {ctype!r}; must be 'cylinder' or 'rectangle'.")
        return errors

    depth = spec.get("depth", 0.0)
    if depth <= 0:
        errors.append("Container depth must be > 0.")

    x = spec.get("x", 0.0)
    y = spec.get("y", 0.0)

    if ctype == "cylinder":
        r = spec.get("radius", 0.0)
        if r <= 0:
            errors.append("Cylinder radius must be > 0.")
    else:  # rectangle
        w = spec.get("width", 0.0)
        l = spec.get("length", 0.0)
        if w <= 0:
            errors.append("Rectangle width must be > 0.")
        if l <= 0:
            errors.append("Rectangle length must be > 0.")

    return errors


# ---------------------------------------------------------------------------
# FreeCAD shape builders
# ---------------------------------------------------------------------------


def _require_freecad():
    """Raise ``ImportError`` with a helpful message if FreeCAD is not available."""
    try:
        import FreeCAD  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "FreeCAD Python bindings are required to build shapes. "
            "Run this code inside the FreeCAD environment."
        ) from exc


def make_container_shape(
    spec: dict,
    shell_thickness: float,
    interior_height: float,
    outer_x: float,
    outer_y: float,
) -> object:  # Part.Shape
    """Return a FreeCAD ``Part.Shape`` cutter for one container pocket.

    The cutter extends **downward** from the top of the solid interior base
    (``z = shell_thickness + interior_height``) by ``spec['depth']``.

    Parameters
    ----------
    spec             : container spec dict – see module docstring for keys.
    shell_thickness  : box floor / wall thickness (mm)
    interior_height  : height of the solid interior base block (mm)
    outer_x, outer_y : outer box dimensions (mm) – used for default positioning

    Returns
    -------
    A ``Part.Shape`` that can be used as a boolean-cut cutter.
    """
    _require_freecad()
    import FreeCAD as App
    import Part

    ctype = spec.get("type", "cylinder")
    depth = float(spec.get("depth", 10.0))
    x     = float(spec.get("x", outer_x / 2.0))
    y     = float(spec.get("y", outer_y / 2.0))

    # Cutter Z range: from top of interior base downward by depth
    z_top = shell_thickness + interior_height
    z_bot = z_top - depth

    if ctype == "cylinder":
        radius = float(spec.get("radius", 5.0))
        shape = Part.makeCylinder(
            radius, depth,
            App.Vector(x, y, z_bot),
            App.Vector(0.0, 0.0, 1.0),
        )
    else:  # rectangle
        width  = float(spec.get("width",  10.0))
        length = float(spec.get("length", 10.0))
        shape = Part.makeBox(
            width, length, depth,
            App.Vector(x - width / 2.0, y - length / 2.0, z_bot),
        )

    return shape


def make_magnet_hole_shape(
    cx: float,
    cy: float,
    radius: float,
    depth: float,
) -> object:  # Part.Shape
    """Return a cylindrical cutter for one magnet hole.

    The cylinder is drilled **upward** from the bottom face (z = 0) of the
    box floor.

    Parameters
    ----------
    cx, cy : XY centre of the magnet hole (mm)
    radius : radius of the cylindrical hole (mm)
    depth  : depth (height) of the hole (mm)

    Returns
    -------
    A ``Part.Shape`` cylinder positioned at the bottom face.
    """
    _require_freecad()
    import FreeCAD as App
    import Part

    return Part.makeCylinder(
        radius, depth,
        App.Vector(cx, cy, 0.0),
        App.Vector(0.0, 0.0, 1.0),
    )


def make_gridfinity_box(
    grid_x: int,
    grid_y: int,
    box_height: float,
    interior_height: float,
    shell_thickness: float,
    container_cutters: list = None,
    magnet_radius: float = 0.0,
    magnet_depth: float = 0.0,
    corner_pad: float = 0.0,
) -> object:  # Part.Shape
    """Build the gridfinity box body with all cavities and holes applied.

    The box cross-section (viewed from the side) is::

        z = box_height        ─── open top
        z = floor_top         ─── top of solid interior base (floor_top = shell + interior_h)
                              │ solid interior base │
        z = shell_thickness   ─── bottom of interior base / top of floor
                              │       floor         │
        z = 0                 ─── bottom face

    The four side walls run from z = 0 to z = box_height with thickness
    ``shell_thickness``.  The air cavity above the interior base is open to
    the top.  Container pockets are cut into the interior base from above.
    Magnet holes are drilled upward from z = 0 at the four corners.

    Parameters
    ----------
    grid_x, grid_y   : number of 42 mm grid units in X and Y
    box_height       : total external height (mm)
    interior_height  : height of the solid interior base block (mm)
    shell_thickness  : wall and floor thickness (mm)
    container_cutters: list of ``Part.Shape`` cutters (from
                       :func:`make_container_shape`); already computed so
                       they are NOT recomputed here.
    magnet_radius    : radius of each corner magnet hole (mm); 0 = none
    magnet_depth     : depth of each corner magnet hole (mm)
    corner_pad       : extra material added around each corner for magnets (mm)

    Returns
    -------
    ``Part.Shape`` of the finished box body.
    """
    _require_freecad()
    import FreeCAD as App
    import Part

    outer_x, outer_y = gridfinity_outer_dimensions(grid_x, grid_y)

    # ------------------------------------------------------------------
    # 1.  Start with a solid rectangular block (full outer dimensions)
    # ------------------------------------------------------------------
    body = Part.makeBox(outer_x, outer_y, box_height, App.Vector(0.0, 0.0, 0.0))

    # ------------------------------------------------------------------
    # 2.  Cut out the open air cavity above the solid interior base
    #     (the four walls remain; only the interior air space is removed)
    # ------------------------------------------------------------------
    cavity_x = outer_x - 2.0 * shell_thickness
    cavity_y = outer_y - 2.0 * shell_thickness
    cavity_h = box_height - shell_thickness - interior_height

    if cavity_x > 1e-9 and cavity_y > 1e-9 and cavity_h > 1e-9:
        air_cavity = Part.makeBox(
            cavity_x, cavity_y, cavity_h,
            App.Vector(
                shell_thickness,
                shell_thickness,
                shell_thickness + interior_height,
            ),
        )
        body = body.cut(air_cavity)

    # ------------------------------------------------------------------
    # 3.  Apply corner pads (extra solid material around magnet corners)
    # ------------------------------------------------------------------
    if corner_pad > 1e-9 and magnet_radius > 1e-9:
        centres = magnet_corner_centres(outer_x, outer_y, shell_thickness, corner_pad)
        pad_half = (shell_thickness + corner_pad) / 2.0
        for cx, cy in centres:
            pad = Part.makeBox(
                pad_half * 2.0, pad_half * 2.0, shell_thickness,
                App.Vector(cx - pad_half, cy - pad_half, 0.0),
            )
            body = body.fuse(pad)

    # ------------------------------------------------------------------
    # 4.  Cut container pocket holes into the interior base
    # ------------------------------------------------------------------
    for cutter in (container_cutters or []):
        body = body.cut(cutter)

    # ------------------------------------------------------------------
    # 5.  Drill magnet holes upward from the bottom face
    # ------------------------------------------------------------------
    if magnet_radius > 1e-9 and magnet_depth > 1e-9:
        centres = magnet_corner_centres(outer_x, outer_y, shell_thickness, corner_pad)
        for cx, cy in centres:
            hole = make_magnet_hole_shape(cx, cy, magnet_radius, magnet_depth)
            body = body.cut(hole)

    return body


def make_gridfinity_lid(
    grid_x: int,
    grid_y: int,
    shell_thickness: float,
    lid_height: float = 2.0,
    magnet_radius: float = 0.0,
    magnet_depth: float = 0.0,
    corner_pad: float = 0.0,
) -> object:  # Part.Shape
    """Build a flat lid for the gridfinity box.

    The lid is a solid rectangular plate whose XY footprint matches the box
    outer dimensions.  Optional magnet holes are drilled downward from the
    top face at the same corner positions used for the box.

    Parameters
    ----------
    grid_x, grid_y  : number of 42 mm grid units in X and Y
    shell_thickness : used only to compute magnet corner positions (mm)
    lid_height      : thickness of the lid plate (mm)
    magnet_radius   : radius of each corner magnet hole (mm); 0 = none
    magnet_depth    : depth of each corner magnet hole (mm); drilled from top
    corner_pad      : corner pad size matching the box (mm)

    Returns
    -------
    ``Part.Shape`` of the lid.
    """
    _require_freecad()
    import FreeCAD as App
    import Part

    outer_x, outer_y = gridfinity_outer_dimensions(grid_x, grid_y)

    lid = Part.makeBox(outer_x, outer_y, lid_height, App.Vector(0.0, 0.0, 0.0))

    # Drill magnet holes from the *top* face downward
    if magnet_radius > 1e-9 and magnet_depth > 1e-9:
        centres = magnet_corner_centres(outer_x, outer_y, shell_thickness, corner_pad)
        for cx, cy in centres:
            # Hole goes from z = lid_height down to z = lid_height - magnet_depth
            hole = Part.makeCylinder(
                magnet_radius, magnet_depth,
                App.Vector(cx, cy, lid_height - magnet_depth),
                App.Vector(0.0, 0.0, 1.0),
            )
            lid = lid.cut(hole)

    return lid


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def create_gridfinity_box(
    grid_x: int,
    grid_y: int,
    box_height: float,
    interior_height: float,
    shell_thickness: float,
    containers: list = None,
    make_lid: bool = False,
    lid_height: float = 2.0,
    magnet_radius: float = 0.0,
    magnet_depth: float = 0.0,
    corner_pad: float = 0.0,
) -> list:
    """Create all shapes for a gridfinity storage box.

    This is the primary entry point for callers.  It returns a flat list of
    ``(name, shape)`` pairs — one for the box body, one for each container
    cutter (so they are available as named FreeCAD objects that can be
    adjusted), and optionally one for the lid.

    Container cutter shapes are visible in the document tree and can be
    re-positioned, resized, or deleted by the user.  The box body already
    has the cuts applied.

    Parameters
    ----------
    grid_x, grid_y   : number of 42 mm grid units in X and Y (≥ 1)
    box_height       : total external height (mm)
    interior_height  : height of the solid interior base (mm).  Container
                       pockets are cut into this region from above.
    shell_thickness  : wall and floor thickness (mm)
    containers       : list of container spec dicts.  Each dict has:
                       ``type``   – ``'cylinder'`` or ``'rectangle'``
                       ``depth``  – pocket depth (mm)
                       ``x``, ``y`` – pocket centre in XY (mm)
                       For cylinder: ``radius`` (mm)
                       For rectangle: ``width``, ``length`` (mm)
    make_lid         : if True, include a lid shape in the results
    lid_height       : thickness of the lid (mm)
    magnet_radius    : radius of corner magnet holes (mm); 0 = no magnets
    magnet_depth     : depth of corner magnet holes (mm)
    corner_pad       : extra material thickness added around corner magnet
                       positions (mm); thickens corners for magnet support

    Returns
    -------
    list of ``(name: str, shape: Part.Shape)`` tuples:
        * ``"GF_Box"``                         — the finished box body
        * ``"GF_Container_Cyl_<N>"``           — each cylinder container cutter
        * ``"GF_Container_Rect_<N>"``          — each rectangle container cutter
        * ``"GF_Lid"`` (if make_lid is True)   — the lid plate
    """
    _require_freecad()

    outer_x, outer_y = gridfinity_outer_dimensions(grid_x, grid_y)
    results = []

    # ------------------------------------------------------------------
    # Build container cutter shapes (kept as separate named primitives)
    # ------------------------------------------------------------------
    cyl_idx  = 1
    rect_idx = 1
    container_cutters = []

    for spec in (containers or []):
        cutter = make_container_shape(
            spec, shell_thickness, interior_height, outer_x, outer_y
        )
        container_cutters.append(cutter)

        ctype = spec.get("type", "cylinder")
        if ctype == "cylinder":
            name = f"GF_Container_Cyl_{cyl_idx}"
            cyl_idx += 1
        else:
            name = f"GF_Container_Rect_{rect_idx}"
            rect_idx += 1

        results.append((name, cutter))

    # ------------------------------------------------------------------
    # Build box body (container cuts already applied inside make_gridfinity_box)
    # ------------------------------------------------------------------
    box_shape = make_gridfinity_box(
        grid_x, grid_y,
        box_height, interior_height, shell_thickness,
        container_cutters=container_cutters,
        magnet_radius=magnet_radius,
        magnet_depth=magnet_depth,
        corner_pad=corner_pad,
    )
    results.insert(0, ("GF_Box", box_shape))

    # ------------------------------------------------------------------
    # Optional lid
    # ------------------------------------------------------------------
    if make_lid:
        lid_shape = make_gridfinity_lid(
            grid_x, grid_y, shell_thickness,
            lid_height=lid_height,
            magnet_radius=magnet_radius,
            magnet_depth=magnet_depth,
            corner_pad=corner_pad,
        )
        results.append(("GF_Lid", lid_shape))

    return results

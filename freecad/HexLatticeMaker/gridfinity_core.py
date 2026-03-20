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

Container shape placement
-------------------------
Every container cutter shape is built **centred at the local origin** (0, 0, 0)
so that the FreeCAD Placement attribute controls its world position.  The
``z`` component of the placement vector is the world Z of the cutter's
geometric centre:

  z_center = shell_thickness + interior_height - depth / 2

See :func:`container_z_center` for the pure-Python helper.

Magnet holes
------------
Magnet holes are cylindrical pockets drilled **downward** from the **top**
face (z = box_height) of the box walls, one at each of the four corners.
This positions the magnets at the rim where the lid rests, allowing the lid
to attach magnetically.

The lid's magnet holes are drilled **upward** from the **bottom** face
(z = 0) of the lid, so that when the lid sits on top of the box both sets
of holes face each other and the magnets attract.

Gridfinity base chamfer
-----------------------
The outer bottom edges of the box carry a 45° chamfer of size
``GRIDFINITY_BASE_CHAMFER`` (2.15 mm, per the Gridfinity open standard).
This chamfer allows the box to be placed on a standard Gridfinity baseplate
and provides the characteristic stacking profile.  The chamfer is applied
to all four outer bottom edges of the box body before any other operations.

Corner magnet ridges — cylindrical, fully enclosed
---------------------------------------------------
When corner magnets are enabled a **full-height cylindrical ridge** is fused
at each corner, spanning z = 0 to z = box_height.  Its radius is
``magnet_radius + shell_thickness + corner_pad``.

The magnet cylinder centre is positioned at
``(shell_thickness + corner_pad + magnet_radius, …)`` from each outer edge.
This ensures a wall of exactly ``shell_thickness + corner_pad`` surrounds
the circular magnet pocket on **all radial sides**:

* Outer sides  — the existing box outer wall provides the enclosure.
* Inner sides  — the fused cylindrical ridge extends inward past the hole.
* Bottom       — the solid shelf below the hole (full height ridge minus the
  drilled depth) supports the magnet when glued.
* Top          — open, so the magnet can be inserted and glued.

Lid
---
The lid is a flat rectangular plate that rests on top of the open box.  Its
XY footprint equals the box outer footprint; its height is ``lid_height``.
Optional magnet holes are drilled upward from the bottom face (z = 0) at
the same XY corner centres used for the box.

Parametric Part::Cut chain
--------------------------
``create_gridfinity_box`` now returns a dict with:

  ``box_body``    : box shape **without** any container cuts applied
  ``containers``  : list of dicts {name, shape (at origin), placement (x,y,z)}
  ``lid``         : optional lid shape (``None`` if not requested)

The caller (:func:`_build_gridfinity_box` in ``init_gui.py``) creates each
container as a ``Part::Feature`` with a ``Placement``, then chains
``Part::Cut`` operations so that repositioning a container feature
automatically updates the cut in the box.
"""

import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRIDFINITY_UNIT        = 42.0   # mm - grid cell width/length
GRIDFINITY_HEIGHT_UNIT = 7.0    # mm - standard height unit
GRIDFINITY_BASE_CHAMFER = 2.15  # mm - 45° bottom outer-edge chamfer (Gridfinity spec)

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
    magnet_radius: float = 0.0,
) -> list:
    """Return ``(cx, cy)`` centre positions for the four corner magnet holes.

    When *magnet_radius* > 0 the centre is positioned so that a cylinder of
    that radius is **fully enclosed** by solid material on all radial sides,
    with a wall of at least ``shell_thickness + corner_pad`` between the hole
    and every outer face:

    .. code-block:: text

        offset = shell_thickness + corner_pad + magnet_radius

    When *magnet_radius* == 0 (default) the legacy formula is used:

    .. code-block:: text

        offset = (shell_thickness + corner_pad) / 2

    Parameters
    ----------
    outer_x, outer_y : outer box dimensions (mm)
    shell_thickness  : wall / floor thickness (mm)
    corner_pad       : additional wall thickness added around each corner (mm)
    magnet_radius    : radius of the cylindrical magnet pocket (mm).  Pass the
                       actual magnet radius to guarantee full enclosure.

    Returns
    -------
    list of four ``(cx, cy)`` tuples in order:
        [bottom-left, bottom-right, top-left, top-right]
    """
    if magnet_radius > 1e-9:
        # Fully-enclosed design: shell_thickness + corner_pad wall on every side
        offset = shell_thickness + corner_pad + magnet_radius
    else:
        # Legacy / no-magnet: centre of the wall material
        offset = (shell_thickness + corner_pad) / 2.0
    return [
        (offset,              offset),               # bottom-left
        (outer_x - offset,    offset),               # bottom-right
        (offset,              outer_y - offset),     # top-left
        (outer_x - offset,    outer_y - offset),     # top-right
    ]


def container_z_center(
    shell_thickness: float,
    interior_height: float,
    depth: float,
) -> float:
    """Return the world Z coordinate of the centre of a container pocket cutter.

    The cutter occupies the Z range
    ``[shell_thickness + interior_height - depth, shell_thickness + interior_height]``
    so its Z centre is:

    .. code-block:: text

        z_center = shell_thickness + interior_height - depth / 2

    This is the Z component used in the FreeCAD Placement for a container
    shape that is built centred at the local origin.

    Parameters
    ----------
    shell_thickness  : box floor / wall thickness (mm)
    interior_height  : height of the solid interior base block (mm)
    depth            : pocket depth (mm)

    Returns
    -------
    float: Z coordinate of the pocket centre in world space (mm)
    """
    return shell_thickness + interior_height - depth / 2.0


def gridfinity_base_chamfer_size() -> float:
    """Return the standard Gridfinity bottom outer-edge chamfer size (mm).

    The outer bottom edges of every Gridfinity-compatible bin carry a 45°
    chamfer of this size so they locate correctly in a Gridfinity baseplate.

    Returns
    -------
    float: ``GRIDFINITY_BASE_CHAMFER`` (2.15 mm)
    """
    return GRIDFINITY_BASE_CHAMFER


def magnet_ridge_radius(
    shell_thickness: float,
    magnet_radius: float = 0.0,
    corner_pad: float = 0.0,
) -> float:
    """Return the radius of the cylindrical corner ridge for magnet enclosure.

    The ridge cylinder has radius ``magnet_radius + shell_thickness + corner_pad``,
    which ensures a wall of exactly ``shell_thickness + corner_pad`` surrounds
    the circular magnet pocket on every radial side.

    Combined with :func:`magnet_corner_centres` (called with the same
    *magnet_radius* value), the ridge cylinder extends from the outer face
    (radius = 0 in world coordinates) through to the inner side, completely
    enclosing the cylindrical magnet pocket.

    Parameters
    ----------
    shell_thickness : wall / floor thickness (mm)
    magnet_radius   : radius of the cylindrical magnet pocket (mm)
    corner_pad      : extra wall thickness added around each corner (mm)

    Returns
    -------
    float: radius of the cylindrical ridge (mm)
    """
    return magnet_radius + shell_thickness + corner_pad


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
) -> tuple:
    """Return a ``(shape, placement)`` pair for one container pocket cutter.

    The shape is built **centred at the local origin** (0, 0, 0) so that it
    can be added to a FreeCAD document as a ``Part::Feature`` and positioned
    using its ``Placement`` attribute.  Moving the feature's Placement then
    automatically updates any ``Part::Cut`` that references it.

    The ``placement`` element is an ``(x, y, z)`` tuple giving the world
    position of the shape centre:

    * ``x``, ``y`` — the pocket XY centre from ``spec``
    * ``z``        — :func:`container_z_center` for the pocket depth

    Parameters
    ----------
    spec             : container spec dict – see module docstring for keys.
    shell_thickness  : box floor / wall thickness (mm)
    interior_height  : height of the solid interior base block (mm)
    outer_x, outer_y : outer box dimensions (mm) – used for default positioning

    Returns
    -------
    ``(shape, (x, y, z))`` where *shape* is centred at the local origin and
    *(x, y, z)* is its world placement vector.
    """
    _require_freecad()
    import FreeCAD as App
    import Part

    ctype  = spec.get("type", "cylinder")
    depth  = float(spec.get("depth", 10.0))
    cx     = float(spec.get("x", outer_x / 2.0))
    cy     = float(spec.get("y", outer_y / 2.0))
    z_ctr  = container_z_center(shell_thickness, interior_height, depth)

    if ctype == "cylinder":
        radius = float(spec.get("radius", 5.0))
        # Cylinder centred at origin: z = -depth/2 … +depth/2
        shape = Part.makeCylinder(
            radius, depth,
            App.Vector(0.0, 0.0, -depth / 2.0),
            App.Vector(0.0, 0.0, 1.0),
        )
    else:  # rectangle
        width  = float(spec.get("width",  10.0))
        length = float(spec.get("length", 10.0))
        # Box centred at origin
        shape = Part.makeBox(
            width, length, depth,
            App.Vector(-width / 2.0, -length / 2.0, -depth / 2.0),
        )

    return shape, (cx, cy, z_ctr)


def make_magnet_hole_shape(
    cx: float,
    cy: float,
    radius: float,
    depth: float,
    z_base: float = 0.0,
) -> object:  # Part.Shape
    """Return a cylindrical cutter for one magnet hole.

    Parameters
    ----------
    cx, cy : XY centre of the magnet hole (mm)
    radius : radius of the cylindrical hole (mm)
    depth  : depth (height) of the hole (mm)
    z_base : Z coordinate of the bottom of the cylinder (mm).
             For box top-face holes pass ``box_height - depth``.
             For lid bottom-face holes pass ``0.0`` (default).

    Returns
    -------
    A ``Part.Shape`` cylinder.
    """
    _require_freecad()
    import FreeCAD as App
    import Part

    return Part.makeCylinder(
        radius, depth,
        App.Vector(cx, cy, z_base),
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

        z = box_height        ─── open top  (magnet holes drilled down from here)
        z = floor_top         ─── top of solid interior base (floor_top = shell + interior_h)
                              │ solid interior base │
        z = shell_thickness   ─── bottom of interior base / top of floor
                              │       floor         │
        z = 0                 ─── bottom face

    The four side walls run from z = 0 to z = box_height with thickness
    ``shell_thickness``.  The air cavity above the interior base is open to
    the top.  Container pockets are cut into the interior base from above.
    Magnet holes are drilled **downward** from the **top** face at the four
    corners so that a lid with bottom-face magnet holes can attach.

    The outer bottom edges carry the standard Gridfinity 45° stacking chamfer
    so the box is compatible with Gridfinity baseplates.

    Parameters
    ----------
    grid_x, grid_y   : number of 42 mm grid units in X and Y
    box_height       : total external height (mm)
    interior_height  : height of the solid interior base block (mm)
    shell_thickness  : wall and floor thickness (mm)
    container_cutters: list of world-positioned ``Part.Shape`` cutters applied
                       via boolean cut.  When using the parametric
                       ``Part::Cut`` document workflow pass an empty list (the
                       default) and apply cuts in the document instead.
    magnet_radius    : radius of each corner magnet hole (mm); 0 = none
    magnet_depth     : depth of each corner magnet hole (mm); holes drilled
                       down from the top face (z = box_height).  The solid
                       material below each hole supports the magnet when glued.
    corner_pad       : extra wall thickness added around each magnet pocket (mm).
                       A cylindrical ridge of radius
                       ``magnet_radius + shell_thickness + corner_pad`` is fused
                       at each corner; the same thickness of material surrounds
                       the hole on all radial sides.

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
    # 1b. Apply Gridfinity base chamfer to the four outer bottom edges.
    #     A 45° chamfer of GRIDFINITY_BASE_CHAMFER mm (2.15 mm) is cut from
    #     each outer bottom edge so the box sits correctly on a Gridfinity
    #     baseplate and has the characteristic stacking profile.
    # ------------------------------------------------------------------
    c = GRIDFINITY_BASE_CHAMFER
    # Each cutter is a triangular prism whose cross-section is the right
    # triangle removed from the box corner.  The four edges share the same
    # chamfer profile but are extruded along different axes.

    # Front edge (y = 0, z = 0): triangle in YZ at x = 0, extruded in +X
    wire = Part.makePolygon([
        App.Vector(0.0, 0.0, 0.0),
        App.Vector(0.0, c,   0.0),
        App.Vector(0.0, 0.0, c),
        App.Vector(0.0, 0.0, 0.0),
    ])
    body = body.cut(Part.Face(wire).extrude(App.Vector(outer_x, 0.0, 0.0)))

    # Back edge (y = outer_y, z = 0)
    wire = Part.makePolygon([
        App.Vector(0.0, outer_y,     0.0),
        App.Vector(0.0, outer_y - c, 0.0),
        App.Vector(0.0, outer_y,     c),
        App.Vector(0.0, outer_y,     0.0),
    ])
    body = body.cut(Part.Face(wire).extrude(App.Vector(outer_x, 0.0, 0.0)))

    # Left edge (x = 0, z = 0): triangle in XZ at y = 0, extruded in +Y
    wire = Part.makePolygon([
        App.Vector(0.0, 0.0, 0.0),
        App.Vector(c,   0.0, 0.0),
        App.Vector(0.0, 0.0, c),
        App.Vector(0.0, 0.0, 0.0),
    ])
    body = body.cut(Part.Face(wire).extrude(App.Vector(0.0, outer_y, 0.0)))

    # Right edge (x = outer_x, z = 0)
    wire = Part.makePolygon([
        App.Vector(outer_x,     0.0, 0.0),
        App.Vector(outer_x - c, 0.0, 0.0),
        App.Vector(outer_x,     0.0, c),
        App.Vector(outer_x,     0.0, 0.0),
    ])
    body = body.cut(Part.Face(wire).extrude(App.Vector(0.0, outer_y, 0.0)))

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
    # 3.  Fuse full-height cylindrical corner ridges whenever magnets are
    #     active.  Each ridge is a cylinder of radius
    #     ``magnet_radius + shell_thickness + corner_pad`` spanning z = 0
    #     to z = box_height, centred at the magnet position.  The magnet
    #     hole (step 5) carves the top portion, leaving a solid shelf at
    #     z = box_height − magnet_depth so the magnet rests on something
    #     when glued.  The cylinder completely surrounds the circular pocket
    #     with an equal-thickness wall on all radial sides.
    # ------------------------------------------------------------------
    if magnet_radius > 1e-9:
        centres = magnet_corner_centres(
            outer_x, outer_y, shell_thickness, corner_pad, magnet_radius,
        )
        R_ridge = magnet_ridge_radius(shell_thickness, magnet_radius, corner_pad)
        for cx, cy in centres:
            ridge = Part.makeCylinder(
                R_ridge, box_height,
                App.Vector(cx, cy, 0.0),
                App.Vector(0.0, 0.0, 1.0),
            )
            body = body.fuse(ridge)

    # ------------------------------------------------------------------
    # 4.  Cut container pocket holes into the interior base
    # ------------------------------------------------------------------
    for cutter in (container_cutters or []):
        body = body.cut(cutter)

    # ------------------------------------------------------------------
    # 5.  Drill magnet holes downward from the TOP face (z = box_height)
    #     so that the lid's bottom-face magnets align with these holes.
    #     The cylindrical ridge (step 3) provides a full-thickness wall
    #     around the hole; the solid shelf below the hole supports the magnet.
    # ------------------------------------------------------------------
    if magnet_radius > 1e-9 and magnet_depth > 1e-9:
        centres = magnet_corner_centres(
            outer_x, outer_y, shell_thickness, corner_pad, magnet_radius,
        )
        for cx, cy in centres:
            hole = make_magnet_hole_shape(
                cx, cy, magnet_radius, magnet_depth,
                z_base=box_height - magnet_depth,
            )
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
    outer dimensions.  Optional magnet holes are drilled **upward** from the
    **bottom** face (z = 0) of the lid at the same corner positions used for
    the box, so that the lid magnets align with the box top-face magnets when
    the lid is placed on the box.

    Parameters
    ----------
    grid_x, grid_y  : number of 42 mm grid units in X and Y
    shell_thickness : used only to compute magnet corner positions (mm)
    lid_height      : thickness of the lid plate (mm)
    magnet_radius   : radius of each corner magnet hole (mm); 0 = none
    magnet_depth    : depth of each corner magnet hole (mm); drilled from
                      the **bottom** face (z = 0) upward
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

    # Drill magnet holes upward from the *bottom* face (z = 0)
    # so they face the matching holes in the box top face.
    # Pass magnet_radius to magnet_corner_centres so the holes are
    # positioned for full enclosure (same formula as the box).
    if magnet_radius > 1e-9 and magnet_depth > 1e-9:
        centres = magnet_corner_centres(
            outer_x, outer_y, shell_thickness, corner_pad, magnet_radius,
        )
        for cx, cy in centres:
            hole = make_magnet_hole_shape(cx, cy, magnet_radius, magnet_depth,
                                          z_base=0.0)
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
) -> dict:
    """Create all shapes for a gridfinity storage box.

    This is the primary entry point for callers.  It returns a dict with
    three keys:

    ``box_body``
        The finished box body shape **without** container cuts applied.
        Container cuts are instead wired up as ``Part::Cut`` document objects
        by the caller so that repositioning a container feature automatically
        re-cuts the box.

    ``containers``
        List of dicts, one per container pocket::

            {
                "name":      str,          # e.g. "GF_Container_Cyl_1"
                "shape":     Part.Shape,   # geometry centred at (0, 0, 0)
                "placement": (x, y, z),    # world position of shape centre
            }

        The shape is centred at its local origin.  Callers should set
        ``obj.Placement = App.Placement(App.Vector(*placement), App.Rotation())``
        and then use ``Part::Cut`` to link the shape to the box body.

    ``lid``
        A ``Part.Shape`` for the lid, or ``None`` when *make_lid* is False.

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
    magnet_depth     : depth of corner magnet holes (mm); drilled from the
                       top of the box and from the bottom of the lid
    corner_pad       : extra material thickness added at each top corner to
                       support magnet holes (mm)

    Returns
    -------
    dict with keys ``"box_body"``, ``"containers"``, ``"lid"``.
    """
    _require_freecad()

    outer_x, outer_y = gridfinity_outer_dimensions(grid_x, grid_y)

    # ------------------------------------------------------------------
    # Build container cutter shapes centred at origin with placement info
    # ------------------------------------------------------------------
    cyl_idx  = 1
    rect_idx = 1
    container_specs = []

    for spec in (containers or []):
        shape, placement = make_container_shape(
            spec, shell_thickness, interior_height, outer_x, outer_y
        )

        ctype = spec.get("type", "cylinder")
        if ctype == "cylinder":
            name = f"GF_Container_Cyl_{cyl_idx}"
            cyl_idx += 1
        else:
            name = f"GF_Container_Rect_{rect_idx}"
            rect_idx += 1

        container_specs.append({
            "name":      name,
            "shape":     shape,
            "placement": placement,
        })

    # ------------------------------------------------------------------
    # Build box body WITHOUT container cuts (cuts applied via Part::Cut
    # chain in the document so they remain parametric)
    # ------------------------------------------------------------------
    box_shape = make_gridfinity_box(
        grid_x, grid_y,
        box_height, interior_height, shell_thickness,
        container_cutters=[],   # cuts done via Part::Cut chain
        magnet_radius=magnet_radius,
        magnet_depth=magnet_depth,
        corner_pad=corner_pad,
    )

    # ------------------------------------------------------------------
    # Optional lid
    # ------------------------------------------------------------------
    lid_shape = None
    if make_lid:
        lid_shape = make_gridfinity_lid(
            grid_x, grid_y, shell_thickness,
            lid_height=lid_height,
            magnet_radius=magnet_radius,
            magnet_depth=magnet_depth,
            corner_pad=corner_pad,
        )

    return {
        "box_body":   box_shape,
        "containers": container_specs,
        "lid":        lid_shape,
    }


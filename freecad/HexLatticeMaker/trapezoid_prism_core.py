"""
trapezoid_prism_core.py
-----------------------
Geometry engine for the Trapezoid Prism Builder FreeCAD plugin.

Creates a parametric trapezoidal prism that can be split horizontally and
joined with a printed screw-and-nut assembly.

Coordinate convention
---------------------
  X  = width direction  (centred on X = 0)
  Y  = length direction (front face at Y = 0, back face at Y = length)
  Z  = height direction (bottom face at Z = 0)

Prism cross-section
-------------------
The prism is defined by two rectangular faces:

  Front face (Y = 0):  width = front_w,  height = front_h
  Back face  (Y = length): width = back_w, height = back_h

Each face is centred on X = 0.  The solid is obtained by lofting between the
two closed wire profiles.

Split pieces
------------
The prism is split into two pieces by a horizontal cutting plane at
Z = split_height:

  Bottom piece  Z = 0 … split_height
  Top piece     Z = split_height … max(front_h, back_h)

Screw assembly
--------------
When *add_screw* is True an integral screw post is added:

* The **screw post** is a cylinder centred at the XY midpoint of the prism.
  It is fused with the bottom piece and rises from Z = 0 to
  Z = max_h + nut_height, providing a threaded stub above the prism that
  the nut can engage.

* The **threaded region** spans from Z = split_height (bottom of the top
  piece) to Z = max_h + nut_height (top of the stub above the prism).
  Threading the full top piece gives the nut plenty of engagement as it is
  turned; the stub above the prism is the final engagement zone when the
  nut is fully seated.  Threads are approximated by revolved rings (one per
  pitch interval), each with a triangular cross-section.  This approach is
  robust across all FreeCAD/OCCT versions and produces geometry that prints
  well on FDM machines.

* The **clearance hole** in the top piece is a smooth cylinder of radius
  ``screw_radius + clearance`` drilled along the full height of the top piece.

* The **nut** is a separate hexagonal prism with a central smooth bore.
  It is placed at Z = max_h so that its **bottom face is flush with the top
  surface of the prism**.  The nut protrudes above the prism by nut_height.

All dimensions are in millimetres.
"""

import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default 3D-print-friendly thread pitch (mm).
# 3 mm pitch gives robust ridges for FDM printing; coarser than ISO M-series
# but much easier to print reliably on desktop printers.
DEFAULT_THREAD_PITCH: float = 3.0

# Thread radial depth as a fraction of pitch.
# ISO full-form depth ≈ 0.6495 × pitch; we use 0.5 for printability.
DEFAULT_THREAD_DEPTH_RATIO: float = 0.5

# Radial clearance added to the screw radius when sizing the clearance hole
# in the top piece so the screw can pass through without binding (mm).
DEFAULT_SCREW_CLEARANCE: float = 0.3

# ---------------------------------------------------------------------------
# Pure-Python helpers  (no FreeCAD dependency – fully unit-testable)
# ---------------------------------------------------------------------------


def validate_trapezoid_prism_params(
    front_w: float,
    front_h: float,
    back_w: float,
    back_h: float,
    length: float,
    split_height: float,
    add_screw: bool = True,
    screw_radius: float = 6.0,
    extend_amount: float = 20.0,
    nut_radius: float = 10.0,
    nut_height: float = 8.0,
    thread_pitch: float = DEFAULT_THREAD_PITCH,
) -> list:
    """Validate all parameters and return a (possibly empty) list of error strings.

    Parameters
    ----------
    front_w, front_h : width and height of the front face (mm)
    back_w, back_h   : width and height of the back face (mm)
    length           : depth of the prism, front-to-back (mm)
    split_height     : Z height at which the prism is split (mm)
    add_screw        : if True, also validate screw/nut parameters
    screw_radius     : shaft radius of the screw (mm)
    extend_amount    : how far the threaded post extends above the prism (mm)
    nut_radius       : outer (flat-to-flat) hex radius of the nut (mm)
    nut_height       : height of the nut (mm)
    thread_pitch     : thread pitch (mm)

    Returns
    -------
    list of str: error messages (empty list = valid)
    """
    errors: list = []

    if front_w <= 0.0:
        errors.append("front_w must be positive")
    if front_h <= 0.0:
        errors.append("front_h must be positive")
    if back_w <= 0.0:
        errors.append("back_w must be positive")
    if back_h <= 0.0:
        errors.append("back_h must be positive")
    if length <= 0.0:
        errors.append("length must be positive")

    if split_height <= 0.0:
        errors.append("split_height must be positive")
    else:
        max_h = max(front_h, back_h)
        if split_height >= max_h:
            errors.append(
                f"split_height ({split_height:.3g} mm) must be less than "
                f"the maximum face height ({max_h:.3g} mm)"
            )

    if add_screw:
        if screw_radius <= 0.0:
            errors.append("screw_radius must be positive")
        if nut_radius <= 0.0:
            errors.append("nut_radius must be positive")
        elif screw_radius > 0.0 and nut_radius <= screw_radius:
            errors.append(
                f"nut_radius ({nut_radius:.3g} mm) must be greater than "
                f"screw_radius ({screw_radius:.3g} mm)"
            )
        if nut_height <= 0.0:
            errors.append("nut_height must be positive")
        if thread_pitch <= 0.0:
            errors.append("thread_pitch must be positive")

    return errors


def compute_prism_vertices(
    front_w: float,
    front_h: float,
    back_w: float,
    back_h: float,
    length: float,
) -> list:
    """Return the eight corner vertices of the trapezoid prism.

    The prism is centred on X = 0.  The front face is at Y = 0 and the back
    face is at Y = *length*.

    Returns
    -------
    list of 8 ``(x, y, z)`` float tuples in the following order:

    Front face (Y = 0)
        [0] bottom-left  (–front_w/2,  0,  0)
        [1] bottom-right ( front_w/2,  0,  0)
        [2] top-right    ( front_w/2,  0,  front_h)
        [3] top-left     (–front_w/2,  0,  front_h)

    Back face (Y = length)
        [4] bottom-left  (–back_w/2,  length,  0)
        [5] bottom-right ( back_w/2,  length,  0)
        [6] top-right    ( back_w/2,  length,  back_h)
        [7] top-left     (–back_w/2,  length,  back_h)
    """
    hw_f = front_w / 2.0
    hw_b = back_w / 2.0
    return [
        # front face
        (-hw_f, 0.0,    0.0),
        ( hw_f, 0.0,    0.0),
        ( hw_f, 0.0,    front_h),
        (-hw_f, 0.0,    front_h),
        # back face
        (-hw_b, length, 0.0),
        ( hw_b, length, 0.0),
        ( hw_b, length, back_h),
        (-hw_b, length, back_h),
    ]


def interpolate_width_at_y(
    y: float,
    front_w: float,
    back_w: float,
    length: float,
) -> float:
    """Return the linearly interpolated prism width at depth *y*.

    Parameters
    ----------
    y        : depth position along the prism (0 = front, length = back)
    front_w  : width at the front face (mm)
    back_w   : width at the back face (mm)
    length   : total depth (mm)

    Returns
    -------
    float: interpolated width (mm)
    """
    if length <= 0.0:
        return float(front_w)
    t = max(0.0, min(1.0, y / length))
    return front_w + t * (back_w - front_w)


def interpolate_height_at_y(
    y: float,
    front_h: float,
    back_h: float,
    length: float,
) -> float:
    """Return the linearly interpolated prism height at depth *y*.

    Parameters
    ----------
    y        : depth position along the prism (0 = front, length = back)
    front_h  : height at the front face (mm)
    back_h   : height at the back face (mm)
    length   : total depth (mm)

    Returns
    -------
    float: interpolated height (mm)
    """
    if length <= 0.0:
        return float(front_h)
    t = max(0.0, min(1.0, y / length))
    return front_h + t * (back_h - front_h)


def compute_thread_params(
    screw_radius: float,
    thread_pitch: float = DEFAULT_THREAD_PITCH,
    thread_depth_ratio: float = DEFAULT_THREAD_DEPTH_RATIO,
) -> dict:
    """Return a dict describing the screw-thread geometry.

    Parameters
    ----------
    screw_radius       : shaft (minor) radius (mm)
    thread_pitch       : axial distance between adjacent thread crests (mm)
    thread_depth_ratio : thread radial depth as a fraction of pitch

    Returns
    -------
    dict with keys:

    ``minor_radius``
        Root / shaft radius (mm) — equals *screw_radius*.
    ``major_radius``
        Crest radius (mm) — ``screw_radius + depth``.
    ``pitch``
        Thread pitch (mm).
    ``depth``
        Radial thread depth (mm) — ``pitch × thread_depth_ratio``.
    """
    depth = thread_pitch * thread_depth_ratio
    return {
        "minor_radius": float(screw_radius),
        "major_radius": screw_radius + depth,
        "pitch":        float(thread_pitch),
        "depth":        depth,
    }


def compute_screw_heights(
    split_height: float,
    front_h: float,
    back_h: float,
    extend_amount: float,
    nut_height: float = 8.0,
) -> dict:
    """Return a dict describing the Z extents of the screw assembly.

    The screw post starts at Z = 0 (bottom of the bottom piece) and extends
    to Z = max_h + nut_height, providing a stub above the prism that the nut
    can thread onto.  Threads cover the **full height of the top piece** plus
    the stub above the prism, giving the nut plenty of engagement.  The nut's
    bottom face rests on the prism top surface (Z = max_h).

    Parameters
    ----------
    split_height   : Z height of the split plane (mm)
    front_h        : height of the front face (mm)
    back_h         : height of the back face (mm)
    extend_amount  : *deprecated — no longer used.*  Kept for backward
                     compatibility; callers may continue to pass it.
    nut_height     : thickness of the nut (mm).

    Returns
    -------
    dict with keys:

    ``max_prism_height``
        ``max(front_h, back_h)`` — total prism height (mm).
    ``top_piece_height``
        Height of the top piece — ``max_prism_height − split_height`` (mm).
    ``post_total_height``
        Full length of the screw post — ``max_prism_height + nut_height``.
    ``threaded_start_z``
        Z where the threaded section begins — ``split_height`` (bottom of
        top piece).
    ``threaded_end_z``
        Z where the threaded section ends — ``max_prism_height + nut_height``
        (top of stub above prism).
    ``nut_bottom_z``
        Z of the bottom face of the nut — ``max_prism_height``.  The nut
        bottom is flush with the prism top surface.
    """
    max_h = max(float(front_h), float(back_h))
    return {
        "max_prism_height":  max_h,
        "top_piece_height":  max_h - float(split_height),
        "post_total_height": max_h + float(nut_height),
        "threaded_start_z":  float(split_height),
        "threaded_end_z":    max_h + float(nut_height),
        "nut_bottom_z":      max_h,
    }


def compute_screw_center(
    length: float,
) -> tuple:
    """Return the ``(x, y)`` centre of the screw post in the XY plane.

    The post is centred on X = 0 (axis of symmetry of the prism) and at the
    midpoint of the prism length.

    Parameters
    ----------
    length : prism depth front-to-back (mm)

    Returns
    -------
    ``(x, y)`` tuple in mm: always ``(0.0, length / 2.0)``
    """
    return (0.0, length / 2.0)


def compute_nut_geometry(
    screw_radius: float,
    nut_flat_radius: float,
    nut_height: float,
    clearance: float = DEFAULT_SCREW_CLEARANCE,
    thread_depth: float = 0.0,
) -> dict:
    """Return a dict describing the nut geometry.

    Parameters
    ----------
    screw_radius    : screw shaft radius (mm)
    nut_flat_radius : flat-to-centre (apothem) of the hexagonal nut (mm)
    nut_height      : thickness of the nut (mm)
    clearance       : radial clearance so the nut slides onto the screw post (mm)
    thread_depth    : radial height of the thread ridges (mm).  The bore is
                      sized as ``screw_radius + thread_depth + clearance`` so
                      it clears the thread crests and can be assembled without
                      force.  Pass 0 (default) when the post has no threads.

    Returns
    -------
    dict with keys:

    ``bore_radius``
        Radius of the smooth central bore — ``screw_radius + thread_depth +
        clearance`` — so the nut slides freely over the thread crests.
    ``flat_radius``
        ``nut_flat_radius`` (apothem / inradius of the hex, mm).
    ``corner_radius``
        Circumradius of the hex — ``flat_radius / cos(30°)``.
    ``height``
        ``nut_height`` (mm).
    """
    return {
        "bore_radius":   screw_radius + thread_depth + clearance,
        "flat_radius":   float(nut_flat_radius),
        "corner_radius": nut_flat_radius / math.cos(math.pi / 6.0),
        "height":        float(nut_height),
    }


def compute_clearance_radius(
    screw_radius: float,
    clearance: float = DEFAULT_SCREW_CLEARANCE,
) -> float:
    """Return the radius of the clearance hole drilled in the top piece.

    Parameters
    ----------
    screw_radius : screw shaft radius (mm)
    clearance    : radial gap added to allow the screw to pass freely (mm)

    Returns
    -------
    float: clearance hole radius (mm)
    """
    return screw_radius + clearance


# ---------------------------------------------------------------------------
# FreeCAD-dependent helpers
# ---------------------------------------------------------------------------


def _require_freecad():
    """Raise ImportError with a helpful message when FreeCAD is not available."""
    try:
        import Part   # noqa: F401  – FreeCAD Part workbench
    except ImportError as exc:
        raise ImportError(
            "FreeCAD's Part module is required for shape creation. "
            "Run this code inside FreeCAD or with the FreeCAD Python interpreter."
        ) from exc


def _make_face_wire(cx, y, w, h):
    """Return a closed rectangular wire centred at (cx, y) in the XZ plane."""
    import Part
    import FreeCAD as App
    hw = w / 2.0
    pts = [
        App.Vector(cx - hw, y, 0.0),
        App.Vector(cx + hw, y, 0.0),
        App.Vector(cx + hw, y, h),
        App.Vector(cx - hw, y, h),
    ]
    return Part.makePolygon(pts, True)


def make_trapezoid_solid(
    front_w: float,
    front_h: float,
    back_w: float,
    back_h: float,
    length: float,
) -> object:
    """Return a FreeCAD ``Part.Shape`` for the full trapezoid prism.

    The prism is centred on X = 0, front face at Y = 0, back face at Y = *length*.

    Parameters
    ----------
    front_w, front_h : dimensions of the front rectangular face (mm)
    back_w, back_h   : dimensions of the back rectangular face (mm)
    length           : prism depth (mm)

    Returns
    -------
    Part.Shape (solid)
    """
    _require_freecad()
    import Part

    front_wire = _make_face_wire(0.0, 0.0,    front_w, front_h)
    back_wire  = _make_face_wire(0.0, length,  back_w,  back_h)
    return Part.makeLoft([front_wire, back_wire], True, False)


def _make_slice_box(x_half: float, y_half: float, z_lo: float, z_hi: float) -> object:
    """Return a large box for Boolean cutting in Z.

    The box spans ±*x_half* in X, ±*y_half* in Y, and [*z_lo*, *z_hi*] in Z.
    """
    import Part
    import FreeCAD as App
    w = x_half * 2.0
    d = y_half * 2.0
    h = z_hi - z_lo
    box = Part.makeBox(w, d, h, App.Vector(-x_half, -y_half, z_lo))
    return box


def _make_screw_post(
    cx: float,
    cy: float,
    shaft_r: float,
    post_height: float,
    thread_start_z: float,
    thread_end_z: float,
    thread_pitch: float,
    thread_depth_ratio: float = DEFAULT_THREAD_DEPTH_RATIO,
) -> object:
    """Return a FreeCAD solid representing the full screw post (shaft + threads).

    Thread ridges are created as **revolved rings** — one per pitch interval —
    rather than a helical sweep.  Each ring has a triangular cross-section
    (inner edge at the shaft surface, crest at the midpoint, inner edge again
    at the next pitch boundary) revolved 360° around the shaft axis.  This
    approach is robust across all FreeCAD / OCCT versions and produces clean,
    manifold solids that print well on FDM machines.

    Parameters
    ----------
    cx, cy           : XY centre (mm)
    shaft_r          : shaft radius (mm) — the minor radius
    post_height      : total post height from Z = 0 (mm)
    thread_start_z   : Z where threads begin (mm)
    thread_end_z     : Z where threads end (mm) — equals post top
    thread_pitch     : thread pitch (mm)
    thread_depth_ratio : depth = pitch × ratio

    Returns
    -------
    Part.Shape (solid)
    """
    import Part
    import FreeCAD as App

    depth   = thread_pitch * thread_depth_ratio
    major_r = shaft_r + depth

    # ── Shaft cylinder (full height from Z = 0) ─────────────────────────
    shaft = Part.makeCylinder(shaft_r, post_height, App.Vector(cx, cy, 0.0))

    thread_height = thread_end_z - thread_start_z
    if thread_height < thread_pitch:
        # Not enough height for even one full turn — return plain shaft
        return shaft

    # ── Revolved ring thread ridges ──────────────────────────────────────
    # Each ring covers exactly one pitch and has a symmetric triangular
    # profile: inner at shaft_r (bottom), crest at major_r (midpoint),
    # inner at shaft_r (top).  Revolving 360° around the shaft axis
    # produces a raised ring with a pointed crest — ideal for FDM printing.
    #
    # Only complete rings are created (int() truncation).  Any remaining
    # fraction of a pitch at the top of the extension is left as plain
    # shaft — a partial ring would produce a sharp half-tooth that is
    # fragile and difficult to print reliably on FDM machines.
    axis_pt  = App.Vector(cx, cy, 0.0)
    axis_dir = App.Vector(0.0, 0.0, 1.0)

    n_rings = int(thread_height / thread_pitch)
    ridges  = []
    for i in range(n_rings):
        z0  = thread_start_z + i * thread_pitch
        z_m = z0 + thread_pitch / 2.0
        z1  = z0 + thread_pitch

        v_bot   = App.Vector(cx + shaft_r, cy, z0)
        v_crest = App.Vector(cx + major_r, cy, z_m)
        v_top   = App.Vector(cx + shaft_r, cy, z1)

        wire  = Part.makePolygon([v_bot, v_crest, v_top, v_bot])
        face  = Part.Face(wire)
        ridge = face.revolve(axis_pt, axis_dir, 360.0)
        ridges.append(ridge)

    # At least one ring is guaranteed here because thread_height >= thread_pitch
    # was checked above and n_rings >= 1.

    # Fuse all ridges, then fuse the result with the shaft
    thread_body = ridges[0]
    for r in ridges[1:]:
        thread_body = thread_body.fuse(r)

    return shaft.fuse(thread_body)


def _make_hex_solid(cx: float, cy: float, z0: float, apothem: float, height: float) -> object:
    """Return a hexagonal prism centred at (cx, cy), starting at Z = z0.

    Parameters
    ----------
    cx, cy   : XY centre (mm)
    z0       : bottom Z of the hex prism (mm)
    apothem  : flat-to-centre (inradius) of the hexagon (mm)
    height   : height of the prism (mm)

    Returns
    -------
    Part.Shape (solid)
    """
    import Part
    import FreeCAD as App

    r = apothem / math.cos(math.pi / 6.0)   # circumradius
    pts = [
        App.Vector(cx + r * math.cos(math.pi / 6.0 + i * math.pi / 3.0),
                   cy + r * math.sin(math.pi / 6.0 + i * math.pi / 3.0),
                   z0)
        for i in range(6)
    ]
    pts.append(pts[0])                       # close the polygon
    wire = Part.makePolygon(pts)
    face = Part.Face(wire)
    return face.extrude(App.Vector(0.0, 0.0, height))


def make_nut_solid(
    cx: float,
    cy: float,
    z0: float,
    nut_flat_radius: float,
    nut_height: float,
    bore_radius: float,
) -> object:
    """Return a FreeCAD solid for the hexagonal nut with a central bore.

    Parameters
    ----------
    cx, cy          : XY centre (mm)
    z0              : Z of the nut bottom face (mm)
    nut_flat_radius : apothem (flat-to-centre) of the nut hex (mm)
    nut_height      : nut thickness (mm)
    bore_radius     : radius of the smooth central bore (mm)

    Returns
    -------
    Part.Shape (solid)
    """
    _require_freecad()
    import Part
    import FreeCAD as App

    hex_solid = _make_hex_solid(cx, cy, z0, nut_flat_radius, nut_height)
    bore = Part.makeCylinder(bore_radius, nut_height, App.Vector(cx, cy, z0))
    return hex_solid.cut(bore)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def create_trapezoid_prism_pieces(
    front_w: float,
    front_h: float,
    back_w: float,
    back_h: float,
    length: float,
    split_height: float,
    add_screw: bool = True,
    screw_radius: float = 6.0,
    extend_amount: float = 20.0,
    nut_flat_radius: float = 10.0,
    nut_height: float = 8.0,
    thread_pitch: float = DEFAULT_THREAD_PITCH,
    thread_depth_ratio: float = DEFAULT_THREAD_DEPTH_RATIO,
    clearance: float = DEFAULT_SCREW_CLEARANCE,
) -> list:
    """Create all pieces for a split trapezoid prism with optional screw assembly.

    Returns a list of ``(name, shape, placement_vector)`` tuples, where
    *placement_vector* is a ``FreeCAD.Vector`` describing the world position
    of the piece.  All pieces are already built at their final world
    positions, so the placement vector is ``(0, 0, 0)`` in every case (the
    geometry is in world coordinates).

    Pieces returned
    ---------------
    ``TP_Bottom``
        Lower half of the prism (Z = 0 … split_height).  When *add_screw*
        is True this piece includes the integral screw post fused to it.

    ``TP_Top``
        Upper half of the prism (Z = split_height … max_h).  When *add_screw*
        is True a smooth clearance hole is cut through the full height.

    ``TP_Nut`` *(only when add_screw is True)*
        Hexagonal nut with smooth central bore, placed at Z = max_h so its
        bottom face is flush with the prism top surface.

    Parameters
    ----------
    front_w, front_h   : front face dimensions (mm)
    back_w, back_h     : back face dimensions (mm)
    length             : prism depth front-to-back (mm)
    split_height       : Z of the split plane (mm)
    add_screw          : if True, add screw post and nut
    screw_radius       : screw shaft radius (mm)
    extend_amount      : kept for backward compatibility; no longer used
    nut_flat_radius    : hex nut apothem (flat-to-centre, mm)
    nut_height         : nut thickness (mm)
    thread_pitch       : thread pitch (mm)
    thread_depth_ratio : thread depth as fraction of pitch
    clearance          : radial clearance for screw hole (mm)

    Returns
    -------
    list of ``(name: str, shape: Part.Shape, placement: FreeCAD.Vector)``
    """
    _require_freecad()
    import Part
    import FreeCAD as App

    errors = validate_trapezoid_prism_params(
        front_w, front_h, back_w, back_h, length, split_height,
        add_screw=add_screw,
        screw_radius=screw_radius,
        extend_amount=extend_amount,
        nut_radius=nut_flat_radius,
        nut_height=nut_height,
        thread_pitch=thread_pitch,
    )
    if errors:
        raise ValueError("Invalid trapezoid prism parameters:\n" + "\n".join(f"  • {e}" for e in errors))

    max_h = max(front_h, back_h)
    origin = App.Vector(0.0, 0.0, 0.0)

    # Large half-extents for slice boxes (must fully contain the prism)
    _big = max(front_w, back_w, length, max_h) * 2.0 + 100.0

    # ── Full prism ───────────────────────────────────────────────────────
    full_prism = make_trapezoid_solid(front_w, front_h, back_w, back_h, length)

    # ── Cutting boxes ────────────────────────────────────────────────────
    # Upper box  (removes Z > split_height → leaves bottom piece)
    upper_box = _make_slice_box(_big, _big, split_height, max_h + _big)
    # Lower box  (removes Z < split_height → leaves top piece)
    lower_box = _make_slice_box(_big, _big, -_big, split_height)

    # ── Bottom piece ─────────────────────────────────────────────────────
    bottom_piece = full_prism.cut(upper_box)

    # ── Top piece ────────────────────────────────────────────────────────
    top_piece = full_prism.cut(lower_box)

    if add_screw:
        heights = compute_screw_heights(
            split_height, front_h, back_h, extend_amount,
            nut_height=nut_height,
        )
        cx, cy  = compute_screw_center(length)

        # Screw post (shaft + threads spanning full top-piece height)
        screw_post = _make_screw_post(
            cx, cy,
            shaft_r=screw_radius,
            post_height=heights["post_total_height"],
            thread_start_z=heights["threaded_start_z"],
            thread_end_z=heights["threaded_end_z"],
            thread_pitch=thread_pitch,
            thread_depth_ratio=thread_depth_ratio,
        )

        # Fuse screw post with bottom piece
        bottom_piece = bottom_piece.fuse(screw_post)

        # Clearance hole through the full height of the top piece
        hole_r = compute_clearance_radius(screw_radius, clearance)
        top_piece_h = heights["top_piece_height"]
        hole = Part.makeCylinder(hole_r, top_piece_h + 1.0,
                                 App.Vector(cx, cy, split_height - 0.5))
        top_piece = top_piece.cut(hole)

        # Nut — placed so its bottom face is flush with the prism top (Z = max_h)
        thread_depth = thread_pitch * thread_depth_ratio
        nut_geo = compute_nut_geometry(
            screw_radius, nut_flat_radius, nut_height, clearance,
            thread_depth=thread_depth,
        )
        nut_shape = make_nut_solid(
            cx, cy,
            z0=heights["nut_bottom_z"],
            nut_flat_radius=nut_geo["flat_radius"],
            nut_height=nut_geo["height"],
            bore_radius=nut_geo["bore_radius"],
        )

        pieces = [
            ("TP_Bottom", bottom_piece, origin),
            ("TP_Top",    top_piece,    origin),
            ("TP_Nut",    nut_shape,    origin),
        ]
    else:
        pieces = [
            ("TP_Bottom", bottom_piece, origin),
            ("TP_Top",    top_piece,    origin),
        ]

    return pieces

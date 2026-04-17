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

* The **screw axis** is perpendicular to the prism's top face.  When the
  front and back heights are equal the top face is horizontal and the axis is
  vertical.  When they differ the top face is a sloped plane and the axis is
  tilted in the YZ plane by the same slope angle — this is the only
  orientation in which the nut can sit flush on the top face.

* The **screw post** is a cylinder fused with the bottom piece.  Its base is
  at Z = 0 and its tip extends ``extend_amount`` mm **above** the prism's top
  face along the screw axis.  Threads cover from the split plane all the way
  to the post tip.  Threads are approximated by revolved rings (one per pitch
  interval), each with a triangular cross-section.  This approach is robust
  across all FreeCAD / OCCT versions and produces geometry that prints well on
  FDM machines.

* The **top piece** has two cuts along the screw axis:

  1. A smooth **clearance hole** (radius = shaft radius + clearance) from the
     split plane through the full height of the top piece.
  2. A **circular pocket** recessed ``pocket_depth`` mm downward from the top
     face.  The pocket radius is large enough for the hex nut to rotate freely
     inside (circumradius + clearance).  ``pocket_depth`` is configurable from
     zero (no pocket — nut bottom sits at the surface) up to ``nut_height``
     (nut fully recessed, nut top flush with the surface).

* The **nut** is a separate hexagonal piece with **matching internal thread
  grooves** so it can be threaded onto the screw post.  The user threads the
  nut onto the stub that protrudes above the surface, then rotates it into the
  circular pocket and tightens it downward.  When ``pocket_depth = nut_height``
  the nut is fully seated and its top face is flush with the prism's top
  surface.  ``extend_amount`` controls how long the threaded stub above the
  surface is, and therefore how much range of motion the nut has.

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
    pocket_depth: float = None,
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
    pocket_depth     : depth of the circular nut pocket in the top piece (mm);
                       None → defaults to nut_height; 0 = no pocket (nut bottom
                       at surface); values between 0 and nut_height are valid.

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
        elif extend_amount < nut_height and extend_amount > 0.0:
            errors.append(
                f"extend_amount ({extend_amount:.3g} mm) should be at least "
                f"nut_height ({nut_height:.3g} mm) so the nut can be started "
                "off the end of the stub before tightening"
            )
        if extend_amount <= 0.0:
            errors.append("extend_amount must be positive")
        if thread_pitch <= 0.0:
            errors.append("thread_pitch must be positive")
        if pocket_depth is not None and pocket_depth < 0.0:
            errors.append("pocket_depth must be >= 0 (0 = no pocket, nut sits above surface)")

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

    The screw post starts at Z = 0 (bottom of the bottom piece) and extends to
    ``max_h + extend_amount``, where ``extend_amount`` is the configurable stub
    length above the prism surface.  Threads cover the full height of the top
    piece plus the stub, giving the nut full engagement.  The nut is threaded
    onto the stub from above; when fully tightened its **top face is flush with
    the prism top surface** (it is seated in the hex pocket ``nut_height`` deep).

    Parameters
    ----------
    split_height   : Z height of the split plane (mm)
    front_h        : height of the front face (mm)
    back_h         : height of the back face (mm)
    extend_amount  : how far the threaded stub protrudes above the prism top
                     surface (mm).  The minimum useful value is ``nut_height``
                     so the nut can be started off the end of the stub.
    nut_height     : thickness of the nut (mm).

    Returns
    -------
    dict with keys:

    ``max_prism_height``
        ``max(front_h, back_h)`` — total prism height (mm).
    ``top_piece_height``
        Height of the top piece — ``max_prism_height − split_height`` (mm).
    ``post_total_height``
        Full length of the screw post — ``max_prism_height + extend_amount``.
    ``threaded_start_z``
        Z where the threaded section begins — ``split_height`` (bottom of
        top piece).
    ``threaded_end_z``
        Z where the threaded section ends — ``max_prism_height + extend_amount``
        (top of stub above prism).
    ``nut_bottom_z``
        Z of the nut's bottom face when fully tightened —
        ``max_prism_height − nut_height`` (pocket floor, ``nut_height`` below
        the prism top surface).
    """
    max_h = max(float(front_h), float(back_h))
    return {
        "max_prism_height":  max_h,
        "top_piece_height":  max_h - float(split_height),
        "post_total_height": max_h + float(extend_amount),
        "threaded_start_z":  float(split_height),
        "threaded_end_z":    max_h + float(extend_amount),
        "nut_bottom_z":      max_h - float(nut_height),
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


def compute_screw_axis(
    front_h: float,
    back_h: float,
    length: float,
) -> tuple:
    """Return the unit normal to the prism's top face (the screw axis direction).

    The screw must be perpendicular to the top face so that the nut can sit
    flush on it when tightened.  The top face is a plane whose Z coordinate
    varies linearly with Y:  ``z(y) = front_h + (back_h − front_h) × y / length``.

    The outward (upward) normal to this plane is
    ``(0, −(back_h − front_h)/length, 1)`` before normalisation.  When
    ``front_h == back_h`` the face is horizontal and the normal reduces to
    ``(0, 0, 1)`` (vertical).

    Parameters
    ----------
    front_h : height of the front face (mm)
    back_h  : height of the back face (mm)
    length  : prism depth front-to-back (mm); if ≤ 0 returns vertical

    Returns
    -------
    ``(nx, ny, nz)`` unit-normal tuple (all floats, ``nx`` is always 0.0)
    """
    if length <= 0.0:
        return (0.0, 0.0, 1.0)
    slope = (float(back_h) - float(front_h)) / float(length)
    ny    = -slope
    nz    = 1.0
    mag   = math.sqrt(ny * ny + nz * nz)
    return (0.0, ny / mag, nz / mag)


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
    base_pt,
    axis_dir,
    shaft_r: float,
    post_length: float,
    thread_start_t: float,
    thread_end_t: float,
    thread_pitch: float,
    thread_depth_ratio: float = DEFAULT_THREAD_DEPTH_RATIO,
) -> object:
    """Return a FreeCAD solid representing the full screw post (shaft + threads).

    The post is a cylinder of radius *shaft_r* and length *post_length* built
    along *axis_dir* starting from *base_pt*.  Thread ridges are created as
    **revolved rings** — one per pitch interval — between *thread_start_t* and
    *thread_end_t* (distances along the axis from *base_pt*).  Each ring has a
    triangular cross-section (inner at shaft surface → crest → inner) revolved
    360° around the screw axis.

    The axis direction must have ``nx == 0`` (the X component is always zero
    for this geometry) so that the radial direction used for the thread profile
    can safely be taken as the global X axis.

    Parameters
    ----------
    base_pt          : ``App.Vector`` — base of the post (at Z = 0)
    axis_dir         : ``App.Vector`` — unit direction along the post
    shaft_r          : shaft (minor) radius (mm)
    post_length      : total length of the shaft cylinder along *axis_dir* (mm)
    thread_start_t   : distance along axis from *base_pt* where threads begin (mm)
    thread_end_t     : distance along axis from *base_pt* where threads end (mm)
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

    # ── Shaft cylinder along the tilted axis ─────────────────────────────
    shaft = Part.makeCylinder(shaft_r, post_length, base_pt, axis_dir)

    thread_length = thread_end_t - thread_start_t
    if thread_length < thread_pitch:
        # Not enough length for even one full turn — return plain shaft
        return shaft

    # ── Revolved ring thread ridges ──────────────────────────────────────
    # The radial direction is always the global X axis because axis_dir has
    # no X component (nx = 0 always).  This guarantees the thread profile
    # plane always contains the screw axis.
    radial_dir = App.Vector(1.0, 0.0, 0.0)

    n_rings = int(thread_length / thread_pitch)
    ridges  = []
    for i in range(n_rings):
        t0  = thread_start_t + i * thread_pitch
        t_m = t0 + thread_pitch / 2.0
        t1  = t0 + thread_pitch

        # Axial positions along the screw axis + radial offsets
        v_bot   = base_pt + axis_dir * t0  + radial_dir * shaft_r
        v_crest = base_pt + axis_dir * t_m + radial_dir * major_r
        v_top   = base_pt + axis_dir * t1  + radial_dir * shaft_r

        wire  = Part.makePolygon([v_bot, v_crest, v_top, v_bot])
        face  = Part.Face(wire)
        ridge = face.revolve(base_pt, axis_dir, 360.0)
        ridges.append(ridge)

    thread_body = ridges[0]
    for r in ridges[1:]:
        thread_body = thread_body.fuse(r)

    return shaft.fuse(thread_body)


def _make_nut_thread_grooves(
    nut_bottom_pt,
    axis_dir,
    bore_r: float,
    major_r: float,
    nut_height: float,
    thread_pitch: float,
) -> object:
    """Return a solid representing the internal thread grooves for a nut bore.

    The grooves have the same triangular radial profile as the screw thread
    ridges, placed at *thread_pitch* intervals along the nut axis starting from
    *nut_bottom_pt*.  Subtracting the returned solid from the nut body
    (which starts with a smooth bore of radius *bore_r*) produces a threaded
    bore that mates with the screw post.

    At the narrow points (between grooves) the bore stays at *bore_r*
    (= shaft radius + clearance).  At each groove centre the bore widens to
    *major_r* (= shaft radius + thread depth + clearance), clearing the screw
    thread crests with the specified clearance.

    The axis direction must have ``nx == 0``.

    Parameters
    ----------
    nut_bottom_pt : ``App.Vector`` — centre of the nut's bottom face
    axis_dir      : ``App.Vector`` — unit screw axis direction (upward)
    bore_r        : tight bore radius between grooves (mm)
    major_r       : widest groove radius (mm) — must be > bore_r
    nut_height    : nut length along the axis (mm)
    thread_pitch  : thread pitch (mm)

    Returns
    -------
    Part.Solid, or ``None`` if *nut_height* < *thread_pitch*
    """
    import Part
    import FreeCAD as App

    n_rings = int(nut_height / thread_pitch)
    if n_rings < 1:
        return None

    radial_dir = App.Vector(1.0, 0.0, 0.0)
    grooves = []
    for i in range(n_rings):
        t0  = i * thread_pitch
        t_m = t0 + thread_pitch / 2.0
        t1  = t0 + thread_pitch

        # Triangular profile: bore wall (bore_r) → groove bottom (major_r) → bore wall
        v_inner_bot = nut_bottom_pt + axis_dir * t0  + radial_dir * bore_r
        v_outer_mid = nut_bottom_pt + axis_dir * t_m + radial_dir * major_r
        v_inner_top = nut_bottom_pt + axis_dir * t1  + radial_dir * bore_r

        wire   = Part.makePolygon([v_inner_bot, v_outer_mid, v_inner_top, v_inner_bot])
        face   = Part.Face(wire)
        groove = face.revolve(nut_bottom_pt, axis_dir, 360.0)
        grooves.append(groove)

    groove_body = grooves[0]
    for g in grooves[1:]:
        groove_body = groove_body.fuse(g)
    return groove_body


def _make_hex_solid(
    center_pt,
    axis_dir,
    apothem: float,
    height: float,
) -> object:
    """Return a hexagonal prism centred at *center_pt*, extruded along *axis_dir*.

    Parameters
    ----------
    center_pt : ``App.Vector`` — centre of the bottom hex face
    axis_dir  : ``App.Vector`` — unit direction (extrusion axis)
    apothem   : flat-to-centre (inradius) of the hexagon (mm)
    height    : height of the prism along *axis_dir* (mm)

    Returns
    -------
    Part.Shape (solid)

    Notes
    -----
    The axis direction must have ``nx == 0`` (global X is always in the plane
    of the hex face), so the local XY frame is:

    * **local_x** = ``(1, 0, 0)``  (global X)
    * **local_y** = ``axis_dir × local_x`` = ``(0, nz, −ny)``
    """
    import Part
    import FreeCAD as App

    circumradius = apothem / math.cos(math.pi / 6.0)

    # Build the local frame in the plane perpendicular to axis_dir.
    # Since axis_dir = (0, ny, nz), global X is always perpendicular.
    local_x = App.Vector(1.0, 0.0, 0.0)
    local_y = App.Vector(0.0, axis_dir.z, -axis_dir.y)  # axis_dir × local_x

    pts = []
    for i in range(6):
        angle = math.pi / 6.0 + i * math.pi / 3.0
        pt = (
            center_pt
            + local_x * (circumradius * math.cos(angle))
            + local_y * (circumradius * math.sin(angle))
        )
        pts.append(pt)
    pts.append(pts[0])          # close the polygon
    wire = Part.makePolygon(pts)
    face = Part.Face(wire)
    return face.extrude(axis_dir * height)


def make_nut_solid(
    entry_pt,
    axis_dir,
    nut_flat_radius: float,
    nut_height: float,
    bore_radius: float,
    thread_pitch: float = 0.0,
    thread_depth_ratio: float = DEFAULT_THREAD_DEPTH_RATIO,
) -> object:
    """Return a FreeCAD solid for the hexagonal nut with an optionally threaded bore.

    The nut is oriented along *axis_dir* so that its flat faces are
    perpendicular to the screw.  *entry_pt* is the centre of the nut's
    **bottom** face.

    When *thread_pitch* > 0 the bore receives matching internal thread grooves
    (same triangular ring profile as the external screw ridges) so the nut can
    be threaded onto the screw post.  The grooves widen the bore from the tight
    shaft-clearance diameter to the thread-crest-clearance diameter at each
    pitch interval.

    Parameters
    ----------
    entry_pt          : ``App.Vector`` — centre of the nut's bottom face
    axis_dir          : ``App.Vector`` — unit screw axis direction
    nut_flat_radius   : apothem (flat-to-centre) of the nut hex (mm)
    nut_height        : nut thickness (mm)
    bore_radius       : tight (narrow) bore radius between thread crests
                        = ``screw_radius + clearance`` (mm)
    thread_pitch      : thread pitch (mm); 0 = smooth bore (no threads)
    thread_depth_ratio : depth = pitch × ratio (only used when thread_pitch > 0)

    Returns
    -------
    Part.Solid
    """
    _require_freecad()
    import Part

    hex_solid = _make_hex_solid(entry_pt, axis_dir, nut_flat_radius, nut_height)

    # Smooth bore at the tight (shaft-clearance) radius
    bore = Part.makeCylinder(bore_radius, nut_height, entry_pt, axis_dir)
    nut_shape = hex_solid.cut(bore)

    if thread_pitch > 0.0:
        depth   = thread_pitch * thread_depth_ratio
        major_r = bore_radius + depth   # groove outer radius (thread crest clearance)
        grooves = _make_nut_thread_grooves(
            nut_bottom_pt = entry_pt,
            axis_dir      = axis_dir,
            bore_r        = bore_radius,
            major_r       = major_r,
            nut_height    = nut_height,
            thread_pitch  = thread_pitch,
        )
        if grooves is not None:
            nut_shape = nut_shape.cut(grooves)

    return nut_shape


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
    pocket_depth: float = None,
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
        Upper half of the prism (Z = split_height … prism top).  When
        *add_screw* is True the top piece has two cuts along the screw axis:
        a smooth clearance hole from the split plane through the full height
        of the top piece, and a **circular** nut pocket recessed
        ``pocket_depth`` mm downward from the top surface.  The pocket radius
        (circumradius of the hex nut + clearance) is large enough for the nut
        to be rotated into position.  When ``pocket_depth = 0`` no pocket is
        cut and the nut rests on top of the surface.

    ``TP_Nut`` *(only when add_screw is True)*
        Hexagonal nut with a threaded bore.  The nut is threaded onto the stub
        that protrudes ``extend_amount`` mm above the prism surface, then
        rotated into the circular pocket and tightened downward.  When
        ``pocket_depth = nut_height`` the nut is fully seated and its top face
        is flush with the prism's top surface.

    Parameters
    ----------
    front_w, front_h   : front face dimensions (mm)
    back_w, back_h     : back face dimensions (mm)
    length             : prism depth front-to-back (mm)
    split_height       : Z of the split plane (mm)
    add_screw          : if True, add screw post and nut
    screw_radius       : screw shaft radius (mm)
    extend_amount      : how far the threaded stub protrudes above the prism
                         top surface (mm); minimum useful value is nut_height
    nut_flat_radius    : hex nut apothem (flat-to-centre, mm)
    nut_height         : nut thickness (mm)
    thread_pitch       : thread pitch (mm)
    thread_depth_ratio : thread depth as fraction of pitch
    clearance          : radial clearance for screw hole (mm)
    pocket_depth       : depth of the circular nut pocket cut into the top
                         piece (mm); None → defaults to nut_height (fully
                         recessed); 0 = no pocket cut (nut sits above surface)

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
        import FreeCAD as App  # noqa: F811

        # ── Compute screw axis (perpendicular to the top face) ────────────
        nx, ny_n, nz_n = compute_screw_axis(front_h, back_h, length)
        axis_dir = App.Vector(nx, ny_n, nz_n)

        # ── Entry point: where the screw axis meets the top surface ───────
        cx, cy   = compute_screw_center(length)
        h_center = interpolate_height_at_y(cy, front_h, back_h, length)
        entry_pt = App.Vector(cx, cy, h_center)   # top surface at screw centre

        # ── Base point of the post at Z = 0 ───────────────────────────────
        # Walk downward along −axis_dir from entry_pt until Z = 0.
        # Δt = h_center / nz_n  (nz_n > 0 always)
        t_surface = h_center / nz_n        # axis-length: base → top surface
        base_pt   = App.Vector(cx, cy - t_surface * ny_n, 0.0)

        # ── Axis-length positions of key planes ───────────────────────────
        t_split = split_height / nz_n      # split plane
        # Stub above the surface: extend_amount (along the surface normal)
        t_stub  = extend_amount / nz_n     # axis-length of stub above surface

        # Default pocket_depth = nut_height (fully recessed, nut top flush)
        if pocket_depth is None:
            pocket_depth = float(nut_height)
        else:
            pocket_depth = float(pocket_depth)

        # Post extends from base through the surface and further by t_stub.
        # Threads run from the split plane all the way to the post tip.
        post_length    = t_surface + t_stub
        thread_start_t = t_split
        thread_end_t   = post_length

        # ── Screw post (tilted shaft + threads, tip above surface) ────────
        screw_post = _make_screw_post(
            base_pt,
            axis_dir,
            shaft_r        = screw_radius,
            post_length    = post_length,
            thread_start_t = thread_start_t,
            thread_end_t   = thread_end_t,
            thread_pitch   = thread_pitch,
            thread_depth_ratio = thread_depth_ratio,
        )
        bottom_piece = bottom_piece.fuse(screw_post)

        # ── Clearance hole through the full top piece ─────────────────────
        # Spans from just below the split plane to just above the top surface.
        hole_r = compute_clearance_radius(screw_radius, clearance)
        hole_start_pt = base_pt + axis_dir * (t_split - 1.0)
        hole_length   = (t_surface - t_split) + 2.0
        hole = Part.makeCylinder(hole_r, hole_length, hole_start_pt, axis_dir)
        top_piece = top_piece.cut(hole)

        # ── Circular pocket in the top piece ──────────────────────────────
        # A round pocket (radius = nut circumradius + clearance) allows the
        # hex nut to be rotated into position — a hex pocket would jam.
        # pocket_depth = 0 → no pocket (nut rests on surface).
        # pocket_depth = nut_height → nut fully recessed, top flush.
        nut_bottom_pt = entry_pt - axis_dir * pocket_depth
        if pocket_depth > 0.0:
            # pocket_r = circumradius of hex nut + clearance.
            # nut_flat_radius is the apothem (flat-to-centre inradius); the
            # circumradius (vertex-to-centre) = apothem / cos(30°).
            pocket_r = nut_flat_radius / math.cos(math.pi / 6.0) + clearance
            # Slight overcut (+0.5 mm) above entry_pt for clean Boolean cut.
            circular_pocket = Part.makeCylinder(
                pocket_r, pocket_depth + 0.5, nut_bottom_pt, axis_dir
            )
            top_piece = top_piece.cut(circular_pocket)

        # ── Nut (threaded bore, positioned at pocket floor) ───────────────
        # bore_radius = shaft clearance (tight between thread ridges)
        bore_r = screw_radius + clearance
        nut_shape = make_nut_solid(
            nut_bottom_pt,
            axis_dir,
            nut_flat_radius   = nut_flat_radius,
            nut_height        = nut_height,
            bore_radius       = bore_r,
            thread_pitch      = thread_pitch,
            thread_depth_ratio = thread_depth_ratio,
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

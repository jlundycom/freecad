"""
hex_lattice_core.py
-------------------
Core geometry engine for the HexLatticeMaker FreeCAD plugin.

Creates a parametric flat part filled with a hexagonal lattice, then slices
it into interlocking pieces no larger than MAX_PIECE_SIZE mm in any dimension.

Coordinate convention
---------------------
  X  = width direction
  Y  = length direction
  Z  = height direction (the part's thickness)

Hexagon convention
------------------
  Pointy-top hexagons (first vertex at 30° from +X).
  ``hex_size`` is the *side length* (= radius = vertex-to-center distance).

Piece slicing
-------------
  Pieces are cut at multiples of MAX_PIECE_SIZE along X and Y.
  At every cut a solid *bridge* of width ``perim_width`` is maintained
  (perim_width/2 on each side of the cut) so that the interlocking finger
  joints have enough wall thickness.

Finger joints
-------------
  Box / finger joints.  At each cut face, rectangular tabs and slots
  alternate along the face.  Complementary pieces are guaranteed to have
  the matching inverse pattern.

      this_side = 'left'   → piece is to the LEFT  of the cut (x < cut_pos)
      this_side = 'right'  → piece is to the RIGHT of the cut (x > cut_pos)
      this_side = 'bottom' → piece is BELOW the cut            (y < cut_pos)
      this_side = 'top'    → piece is ABOVE the cut            (y > cut_pos)

  'left'/'bottom' pieces carry tabs at *even* finger positions (0, 2, 4 …).
  'right'/'top'   pieces carry tabs at *odd*  finger positions (1, 3, 5 …).
  This guarantees adjacent pieces are exactly complementary.

  Tab geometry
  ~~~~~~~~~~~~
  tab_w  = perim_width          (width of each tab/slot along the face)
  tab_d  = perim_width / 2      (depth of each tab into the adjacent piece)
  fit    = FIT_CLEARANCE        (bilateral assembly clearance)

  Left piece tab  (x-cut):  x ∈ [cut, cut+tab_d],    y ∈ [seg_s+fit/2, seg_e-fit/2]
  Right piece slot (x-cut): x ∈ [cut, cut+tab_d+fit], y ∈ [seg_s-fit/2, seg_e+fit/2]
"""

import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PIECE_SIZE = 220.0   # mm  – maximum dimension of a printable piece
FIT_CLEARANCE  = 0.15    # mm  – assembly clearance (bilateral)
MIN_SEG_RATIO  = 0.25    # minimum fraction of tab_w for an end-segment to be kept


# ---------------------------------------------------------------------------
# Helpers that work without FreeCAD (used in unit tests)
# ---------------------------------------------------------------------------

def compute_cuts(total_dim: float, max_piece_size: float = MAX_PIECE_SIZE) -> list:
    """Return a list of cut positions along a single dimension.

    Pieces will be in the range [0, cuts[0]], [cuts[0], cuts[1]], …
    Each span is ≤ *max_piece_size*.
    """
    cuts = []
    pos = max_piece_size
    while pos < total_dim - 0.01:         # 0.01 mm epsilon – no cut at the very edge
        cuts.append(float(pos))
        pos += max_piece_size
    return cuts


def hex_centers(
    gx0: float, gx1: float,
    gy0: float, gy1: float,
    hex_size: float,
    wall_t: float,
) -> list:
    """Yield (cx, cy) hex-grid centers that fall *inside* the interior region.

    The grid uses pointy-top hexagons.  ``wall_t`` is the desired minimum
    wall thickness between adjacent cells.
    """
    grid_s = hex_size + wall_t
    h_sp   = grid_s * math.sqrt(3)      # horizontal center-to-center
    v_sp   = 1.5 * grid_s               # vertical   center-to-center

    centers = []
    # Guard against degenerate / zero-area regions
    if gx1 <= gx0 or gy1 <= gy0:
        return centers
    n_cols = int((gx1 - gx0) / h_sp) + 3
    n_rows = int((gy1 - gy0) / v_sp) + 3

    for row in range(-1, n_rows + 1):
        cy = gy0 + row * v_sp + v_sp * 0.5   # offset by ½ to center in region
        offset = (h_sp * 0.5) if (row % 2 != 0) else 0.0
        for col in range(-1, n_cols + 1):
            cx = gx0 + col * h_sp + offset + h_sp * 0.5
            if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                centers.append((cx, cy))
    return centers


def is_excluded(
    cx: float, cy: float,
    hex_size: float,
    perim_w: float,
    total_w: float,
    total_l: float,
    x_cuts: list,
    y_cuts: list,
) -> bool:
    """Return True if a hex hole centered at (cx, cy) should be suppressed.

    Suppressed zones
    ~~~~~~~~~~~~~~~~
    * Outer perimeter bands (within ``perim_w`` of any edge).
    * Bridge bands at every cut (within ``perim_w/2`` of any cut line).

    A hex is suppressed if its *bounding circle* (radius = hex_size) overlaps
    any exclusion zone.
    """
    r = hex_size          # bounding-circle radius of a regular hexagon = side length

    # Outer perimeter bands
    if cx - r < perim_w:               return True
    if cx + r > total_w - perim_w:     return True
    if cy - r < perim_w:               return True
    if cy + r > total_l - perim_w:     return True

    # Bridge bands at cut lines
    bridge_half = perim_w * 0.5
    for xc in x_cuts:
        if abs(cx - xc) < r + bridge_half:
            return True
    for yc in y_cuts:
        if abs(cy - yc) < r + bridge_half:
            return True

    return False


# ---------------------------------------------------------------------------
# FreeCAD geometry builders
# ---------------------------------------------------------------------------

def _require_freecad():
    """Lazy import so that unit-tests that don't need FreeCAD can still load
    the module."""
    try:
        import FreeCAD as App   # noqa: F401
        import Part             # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "FreeCAD is not available in the current Python environment."
        ) from exc


def make_hex_prism(cx: float, cy: float, side: float, height: float):
    """Return a FreeCAD Part.Shape: hexagonal prism (pointy-top)."""
    import FreeCAD as App
    import Part

    verts = []
    for k in range(6):
        ang = math.radians(30.0 + 60.0 * k)   # pointy-top: first vertex at 30°
        verts.append(App.Vector(cx + side * math.cos(ang),
                                cy + side * math.sin(ang),
                                0.0))
    verts.append(verts[0])
    wire = Part.makePolygon(verts)
    face = Part.Face(wire)
    return face.extrude(App.Vector(0.0, 0.0, height))


def _fuse_shapes(shapes):
    """Fuse a list of shapes into one.  Returns None for an empty list.

    Uses ``multiFuse`` when more than one shape is present so that OCCT can
    execute a single multi-operand boolean union instead of O(N) chained
    pairwise operations – significantly faster for large hex lattices.
    """
    if not shapes:
        return None
    if len(shapes) == 1:
        return shapes[0]
    return shapes[0].multiFuse(shapes[1:])


def _cut_shapes(base, cutters):
    """Subtract each shape in *cutters* from *base*."""
    for c in cutters:
        base = base.cut(c)
    return base


# ---------------------------------------------------------------------------
# Finger-joint builder
# ---------------------------------------------------------------------------

def finger_joint(
    axis: str,
    cut_pos: float,
    face_start: float,
    face_end: float,
    height: float,
    tab_w: float,
    tab_d: float,
    this_side: str,
) -> tuple:
    """Return (tabs, slots) lists of Part.Shape objects for one cut face.

    Parameters
    ----------
    axis       : 'x' or 'y'  – axis *perpendicular* to the cut face
    cut_pos    : coordinate of the cut plane along *axis*
    face_start : start of the face range in the *parallel* axis
    face_end   : end   of the face range in the *parallel* axis
    height     : Z height of the part
    tab_w      : finger width  (along the face)
    tab_d      : finger depth  (into the adjacent piece)
    this_side  : 'left'|'right' for x-cuts; 'bottom'|'top' for y-cuts
    """
    import FreeCAD as App
    import Part

    fit       = FIT_CLEARANCE
    tabs      = []
    slots     = []

    # 'left'/'bottom' pieces: tabs at even finger positions (0, 2, 4 …)
    first_is_tab = this_side in ('left', 'bottom')

    finger_idx = 0
    pos        = face_start

    while pos < face_end - 1e-6:
        seg_s = pos
        seg_e = min(pos + tab_w, face_end)
        seg_l = seg_e - seg_s

        # Drop very short end segments (less than MIN_SEG_RATIO × tab_w)
        if seg_l < tab_w * MIN_SEG_RATIO:
            break

        is_tab = (finger_idx % 2 == 0) == first_is_tab

        if axis == 'x':
            if is_tab:
                if this_side == 'left':
                    # Tab extends in +X from cut_pos
                    t = Part.makeBox(tab_d,
                                     seg_l - fit,
                                     height,
                                     App.Vector(cut_pos,
                                                seg_s + fit * 0.5,
                                                0.0))
                else:  # 'right'
                    # Tab extends in -X from cut_pos
                    t = Part.makeBox(tab_d,
                                     seg_l - fit,
                                     height,
                                     App.Vector(cut_pos - tab_d,
                                                seg_s + fit * 0.5,
                                                0.0))
                tabs.append(t)
            else:
                # Slot (subtracted from body) to receive the opposite tab
                if this_side == 'left':
                    # Opposite ('right') tab comes from cut_pos-tab_d to cut_pos
                    s = Part.makeBox(tab_d + fit,
                                     seg_l + fit,
                                     height,
                                     App.Vector(cut_pos - tab_d - fit,
                                                seg_s - fit * 0.5,
                                                0.0))
                else:  # 'right'
                    # Opposite ('left') tab comes from cut_pos to cut_pos+tab_d
                    s = Part.makeBox(tab_d + fit,
                                     seg_l + fit,
                                     height,
                                     App.Vector(cut_pos,
                                                seg_s - fit * 0.5,
                                                0.0))
                slots.append(s)

        else:  # axis == 'y'
            if is_tab:
                if this_side == 'bottom':
                    # Tab extends in +Y from cut_pos
                    t = Part.makeBox(seg_l - fit,
                                     tab_d,
                                     height,
                                     App.Vector(seg_s + fit * 0.5,
                                                cut_pos,
                                                0.0))
                else:  # 'top'
                    # Tab extends in -Y from cut_pos
                    t = Part.makeBox(seg_l - fit,
                                     tab_d,
                                     height,
                                     App.Vector(seg_s + fit * 0.5,
                                                cut_pos - tab_d,
                                                0.0))
                tabs.append(t)
            else:
                if this_side == 'bottom':
                    # Opposite ('top') tab comes from cut_pos-tab_d to cut_pos
                    s = Part.makeBox(seg_l + fit,
                                     tab_d + fit,
                                     height,
                                     App.Vector(seg_s - fit * 0.5,
                                                cut_pos - tab_d - fit,
                                                0.0))
                else:  # 'top'
                    # Opposite ('bottom') tab comes from cut_pos to cut_pos+tab_d
                    s = Part.makeBox(seg_l + fit,
                                     tab_d + fit,
                                     height,
                                     App.Vector(seg_s - fit * 0.5,
                                                cut_pos,
                                                0.0))
                slots.append(s)

        pos        += tab_w
        finger_idx += 1

    return tabs, slots


# ---------------------------------------------------------------------------
# Single-piece builder
# ---------------------------------------------------------------------------

def make_piece(
    ix: int, iy: int,
    x0: float, x1: float,
    y0: float, y1: float,
    total_w: float, total_l: float,
    height: float,
    perim_w: float,
    hex_size: float,
    wall_t: float,
    x_cuts: list,
    y_cuts: list,
) -> object:  # returns Part.Shape
    """Build one interlocking piece of the hex-lattice panel.

    Parameters
    ----------
    ix, iy   : piece grid indices (used for naming; not needed for geometry)
    x0 … y1  : nominal piece bounds (at cut lines)
    total_w/l: full-part dimensions
    height   : part thickness (Z)
    perim_w  : solid perimeter width
    hex_size : hexagon side length
    wall_t   : minimum wall thickness between adjacent hex cells
    x_cuts   : list of X-cut positions
    y_cuts   : list of Y-cut positions
    """
    import FreeCAD as App
    import Part

    tab_w  = perim_w
    tab_d  = perim_w * 0.5

    # ------------------------------------------------------------------
    # 1. Base rectangular body
    # ------------------------------------------------------------------
    body = Part.makeBox(x1 - x0, y1 - y0, height,
                        App.Vector(x0, y0, 0.0))

    # ------------------------------------------------------------------
    # 2. Hexagonal lattice holes
    # ------------------------------------------------------------------
    # Interior bounds of the entire part (global perimeter exclusion zone)
    gx0 = perim_w
    gx1 = total_w - perim_w
    gy0 = perim_w
    gy1 = total_l - perim_w

    if gx1 > gx0 and gy1 > gy0:
        centers = hex_centers(gx0, gx1, gy0, gy1, hex_size, wall_t)
        hex_holes = []

        # Clip box is constant for the whole piece – create it once.
        clip_box = Part.makeBox(x1 - x0, y1 - y0, height,
                                App.Vector(x0, y0, 0.0))

        for cx, cy in centers:
            if is_excluded(cx, cy, hex_size, perim_w,
                           total_w, total_l, x_cuts, y_cuts):
                continue
            # Hex must overlap this piece's region
            if (cx + hex_size < x0 or cx - hex_size > x1 or
                    cy + hex_size < y0 or cy - hex_size > y1):
                continue

            prism = make_hex_prism(cx, cy, hex_size, height)

            # Only run the (expensive) common() clip for hexes that actually
            # straddle a piece boundary.  Interior hexes are added as-is.
            if (cx - hex_size < x0 + 1e-6 or cx + hex_size > x1 - 1e-6 or
                    cy - hex_size < y0 + 1e-6 or cy + hex_size > y1 - 1e-6):
                clipped = prism.common(clip_box)
                if clipped.Volume > 1e-9:
                    hex_holes.append(clipped)
            else:
                hex_holes.append(prism)

        if hex_holes:
            holes_union = _fuse_shapes(hex_holes)
            body = body.cut(holes_union)

    # ------------------------------------------------------------------
    # 3. Finger joints on each cut face
    # ------------------------------------------------------------------
    # ── Left face (x = x0): this piece is to the RIGHT of that cut
    if x0 > 1e-6:
        tabs, slots = finger_joint('x', x0, y0, y1,
                                   height, tab_w, tab_d, 'right')
        body = _cut_shapes(_fuse_shapes([body] + tabs) if tabs else body, slots)

    # ── Right face (x = x1): this piece is to the LEFT of that cut
    if x1 < total_w - 1e-6:
        tabs, slots = finger_joint('x', x1, y0, y1,
                                   height, tab_w, tab_d, 'left')
        body = _cut_shapes(_fuse_shapes([body] + tabs) if tabs else body, slots)

    # ── Bottom face (y = y0): this piece is ABOVE (top side of) that cut
    if y0 > 1e-6:
        tabs, slots = finger_joint('y', y0, x0, x1,
                                   height, tab_w, tab_d, 'top')
        body = _cut_shapes(_fuse_shapes([body] + tabs) if tabs else body, slots)

    # ── Top face (y = y1): this piece is BELOW (bottom side of) that cut
    if y1 < total_l - 1e-6:
        tabs, slots = finger_joint('y', y1, x0, x1,
                                   height, tab_w, tab_d, 'bottom')
        body = _cut_shapes(_fuse_shapes([body] + tabs) if tabs else body, slots)

    return body


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def create_all_pieces(
    width: float,
    length: float,
    height: float,
    perim_width: float,
    hex_size: float,
    wall_thickness: float = None,
    max_piece_size: float = MAX_PIECE_SIZE,
) -> list:
    """Create all interlocking pieces for a hex-lattice flat panel.

    Parameters
    ----------
    width, length, height : overall part dimensions (mm)
    perim_width           : solid border width and finger-joint bridge thickness
    hex_size              : hexagon cell side length (mm)
    wall_thickness        : minimum wall between hex cells (mm).
                            Defaults to ``max(1.2, hex_size * 0.15)``.
    max_piece_size        : maximum printable piece length/width (mm).
                            Panels larger than this are sliced into pieces.
                            The dialog limits this to 1–220 mm to avoid
                            printer exclusion zones.

    Returns
    -------
    list of (name: str, shape: Part.Shape)
        Names are ``Piece_0_0``, ``Piece_0_1``, … (X-index, Y-index).
    """
    _require_freecad()

    if wall_thickness is None:
        wall_thickness = max(1.2, hex_size * 0.15)

    x_cuts   = compute_cuts(width,  max_piece_size)
    y_cuts   = compute_cuts(length, max_piece_size)
    x_bounds = [0.0] + x_cuts + [width]
    y_bounds = [0.0] + y_cuts + [length]

    pieces = []
    for ix, (x0, x1) in enumerate(zip(x_bounds[:-1], x_bounds[1:])):
        for iy, (y0, y1) in enumerate(zip(y_bounds[:-1], y_bounds[1:])):
            shape = make_piece(
                ix, iy,
                x0, x1, y0, y1,
                width, length,
                height, perim_width, hex_size,
                wall_thickness,
                x_cuts, y_cuts,
            )
            pieces.append((f"Piece_{ix}_{iy}", shape))

    return pieces

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

Finger joints — Stepped Shelf Style (default)
----------------------------------------------
  At each cut face, alternating stepped shelf joints replace the old tapered
  box joints.  Each finger position has **both** a tab and a slot — at
  opposite halves of the part height — so every finger simultaneously
  provides a horizontal locking surface.

  Assembly is horizontal (pieces slide together in X or Y).  The alternating
  steps lock the assembled pieces against vertical (Z) movement:

      this_side = 'left'   → piece is to the LEFT  of the cut (x < cut_pos)
      this_side = 'right'  → piece is to the RIGHT of the cut (x > cut_pos)
      this_side = 'bottom' → piece is BELOW the cut            (y < cut_pos)
      this_side = 'top'    → piece is ABOVE the cut            (y > cut_pos)

  'left'/'bottom' pieces: even fingers have LOWER tab (z=0..h/2) and an
      upper slot (z=h/2..h) to receive the opposite piece's upper tab.
  'left'/'bottom' pieces: odd fingers have UPPER tab (z=h/2..h) and a
      lower slot (z=0..h/2) to receive the opposite piece's lower tab.
  'right'/'top' pieces carry the complementary pattern.

  Step geometry
  ~~~~~~~~~~~~~
  tab_w  = finger_w  (or joint_w when finger_w is not specified)
                                 (width of each finger along the cut face)
  tab_d  = joint_w / 3           (default depth of each tab; fingers fill 2/3 of
                                   the bridge half-width, leaving 1/3 as solid
                                   backing — override with the joint_depth param)
  Note: finger_w and joint_w are independent.  A 20 mm-wide tab can sit inside
  a 10 mm bridge zone with a 4 mm depth, leaving 1 mm solid on each side.
  fit    = FIT_CLEARANCE         (bilateral assembly clearance along the face)
  half_h = height / 2            (Z step boundary)

  Lower tab (even fingers on left/bottom piece):
      Tab  (fused):  x ∈ [cut, cut+tab_d],         z ∈ [0, half_h]
      Slot (cut):    x ∈ [cut−tab_d−fit, cut],      z ∈ [half_h, height]
  Upper tab (odd fingers on left/bottom piece):
      Tab  (fused):  x ∈ [cut, cut+tab_d],         z ∈ [half_h, height]
      Slot (cut):    x ∈ [cut−tab_d−fit, cut],      z ∈ [0, half_h]

  Vertical locking
  ~~~~~~~~~~~~~~~~
  * Even fingers: left's lower-tab top surface (z=half_h) bears against the
    right piece's solid body → prevents upward (+Z) movement.
  * Odd fingers: left's upper-tab bottom surface (z=half_h) bears against
    the right piece's solid body → prevents downward (−Z) movement.
  * Together, every pair of adjacent fingers (one even + one odd) fully locks
    both Z directions.  A minimum of two fingers per face is recommended.

  Legacy tapered joints
  ~~~~~~~~~~~~~~~~~~~~~
  The original taper-draft box joint (TAPER_RATIO = 0.20) is still available
  via ``joint_style='taper'`` in :func:`make_piece`.  The TAPER_RATIO
  constant is retained for backward compatibility.
"""

import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PIECE_SIZE   = 220.0   # mm  – maximum dimension of a printable piece
FIT_CLEARANCE    = 0.15    # mm  – assembly clearance (bilateral)
MIN_SEG_RATIO    = 0.25    # minimum fraction of tab_w for an end-segment to be kept
PIN_RADIUS_RATIO = 0.25    # round through-pin radius = leg_width × PIN_RADIUS_RATIO
TAPER_RATIO      = 0.20    # finger-joint draft: top depth = tab_d*(1+ratio),
                           #                     bottom depth = tab_d*(1-ratio)
_GEOM_EPS        = 1e-9    # geometry epsilon: threshold for discarding near-zero extents


# ---------------------------------------------------------------------------
# Tiling abstraction
# ---------------------------------------------------------------------------

#: Ordered mapping of tiling key → display name for the UI dropdown.
#: See TILING_PLAN.md for the plan to add the remaining semi-regular tilings.
LATTICE_TYPES = {
    "hexagonal":              "Hexagonal (6.6.6)",
    "square":                 "Square (4.4.4.4)",
    "triangular":             "Triangular (3.3.3.3.3.3)",
    "trihexagonal":           "Trihexagonal (3.6.3.6)",
    "truncated_square":       "Truncated Square (4.8.8)",
    "snub_square":                 "Snub Square (3.3.4.3.4)",
    "elongated_triangular":        "Elongated Triangular (3.3.3.4.4)",
    "truncated_hexagonal":         "Truncated Hexagonal (3.12.12)",
    "small_rhombitrihexagonal":    "Small Rhombitrihexagonal (3.4.6.4)",
    "great_rhombitrihexagonal":    "Great Rhombitrihexagonal (4.6.12)",
    "snub_hexagonal":              "Snub Hexagonal (3.3.3.3.6)",
}


class TilingProvider:
    """Abstract base for euclidean uniform tiling providers.

    Subclasses implement :meth:`get_cells` to return cell centre coordinates
    and polygon descriptors for a given rectangular interior region.

    To add a new tiling:

    1. Subclass ``TilingProvider`` and override ``display_name``,
       ``cell_circumradius``, and ``get_cells``.
    2. Register the instance in ``_TILING_PROVIDERS``.
    3. Add an entry to ``LATTICE_TYPES``.

    See ``TILING_PLAN.md`` in the repository root for implementation guidance
    for the remaining semi-regular tilings.
    """

    #: Human-readable name shown in the UI dropdown.
    display_name: str = ""

    def cell_circumradius(self, cell_size: float) -> float:
        """Circumradius of a single cell polygon (mm).

        Used for bounding-circle exclusion and overlap checks.  For tilings
        with multiple polygon types (semi-regular), return the circumradius
        of the *largest* polygon so that no cell is incorrectly pruned.

        Parameters
        ----------
        cell_size : polygon side length (mm)

        Returns
        -------
        float : circumradius of the cell polygon with the given side length
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement cell_circumradius()"
        )

    def get_cells(
        self,
        gx0: float, gx1: float,
        gy0: float, gy1: float,
        cell_size: float,
        wall_t: float,
    ) -> list:
        """Return cell descriptors that fall inside the interior region.

        Parameters
        ----------
        gx0, gx1, gy0, gy1 : axis-aligned interior region bounds (mm)
        cell_size           : polygon side length (mm)
        wall_t              : minimum wall thickness between adjacent cells (mm)

        Returns
        -------
        list of ``(cx, cy, n_sides, rotation_deg)`` tuples
            cx, cy       : cell centre coordinates (mm)
            n_sides      : number of sides of the regular polygon
            rotation_deg : angle in degrees of the first vertex from +X
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement get_cells()"
        )


class HexagonalTilingProvider(TilingProvider):
    """Regular hexagonal tiling — Schläfli symbol {6}, vertex figure 6.6.6.

    Uses pointy-top hexagons (first vertex at 30° from +X).  The grid is the
    standard offset-row hex grid: odd rows are shifted right by half the
    horizontal spacing.
    """

    display_name = "Hexagonal (6.6.6)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Circumradius of a regular hexagon equals its side length.
        return cell_size

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        grid_s = cell_size + wall_t
        h_sp   = grid_s * math.sqrt(3)   # horizontal centre-to-centre
        v_sp   = 1.5 * grid_s            # vertical   centre-to-centre

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_cols = int((gx1 - gx0) / h_sp) + 3
        n_rows = int((gy1 - gy0) / v_sp) + 3

        for row in range(-1, n_rows + 1):
            cy     = gy0 + row * v_sp + v_sp * 0.5
            offset = (h_sp * 0.5) if (row % 2 != 0) else 0.0
            for col in range(-1, n_cols + 1):
                cx = gx0 + col * h_sp + offset + h_sp * 0.5
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 6, 30.0))

        return cells


class SquareTilingProvider(TilingProvider):
    """Regular square tiling — Schläfli symbol {4}, vertex figure 4.4.4.4.

    Squares are axis-aligned (flat sides on top/bottom/left/right), which
    corresponds to a first-vertex angle of 45° from +X.
    """

    display_name = "Square (4.4.4.4)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Circumradius of a square with side s = s * sqrt(2) / 2.
        return cell_size * math.sqrt(2) / 2.0

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        step = cell_size + wall_t

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_cols = int((gx1 - gx0) / step) + 3
        n_rows = int((gy1 - gy0) / step) + 3

        for row in range(-1, n_rows + 1):
            cy = gy0 + row * step + step * 0.5
            for col in range(-1, n_cols + 1):
                cx = gx0 + col * step + step * 0.5
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 4, 45.0))

        return cells


class TriangularTilingProvider(TilingProvider):
    """Regular triangular tiling — Schläfli symbol {3}, vertex figure 3.3.3.3.3.3.

    Equilateral triangles in alternating up-pointing (▲, rotation=90°) and
    down-pointing (▽, rotation=270°) orientations.

    Each horizontal strip of height ``h = step * sqrt(3) / 2`` (where
    ``step = cell_size + wall_t``) holds one row of UP centroids and one row
    of DOWN centroids.  Odd-numbered strips are shifted right by ``step / 2``
    relative to even-numbered strips so that the triangles mesh correctly.

    Strip ``r`` cell-centre formulae::

        row_x_offset = (r % 2) * (step / 2)

        UP   centroid: cx = gx0 + col * step + step / 2 + row_x_offset
                       cy = gy0 + r * h + h / 3

        DOWN centroid: cx = gx0 + col * step + step     + row_x_offset
                       cy = gy0 + r * h + 2 * h / 3

    This rectangular-strip layout avoids any oblique drift, so the pattern
    tiles uniformly regardless of how high (large Y) the region extends.
    """

    display_name = "Triangular (3.3.3.3.3.3)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Circumradius of an equilateral triangle with side s = s / sqrt(3).
        return cell_size / math.sqrt(3)

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        step = cell_size + wall_t
        h    = step * math.sqrt(3) / 2.0   # strip height

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_rows = int((gy1 - gy0) / h)    + 3
        n_cols = int((gx1 - gx0) / step) + 3

        for row in range(-1, n_rows + 1):
            # Even strips: row_x_offset=0; odd strips: row_x_offset=step/2.
            # This alternating shift makes adjacent strips mesh into a proper
            # triangular tiling with no oblique drift as Y grows.
            row_x_offset = (row % 2) * (step * 0.5)

            for col in range(-1, n_cols + 1):
                # UP-pointing triangle (▲): apex at top, rotation = 90°
                cx = gx0 + col * step + step * 0.5 + row_x_offset
                cy = gy0 + row * h + h / 3.0
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 90.0))

                # DOWN-pointing triangle (▽): apex at bottom, rotation = 270°
                cx = gx0 + col * step + step + row_x_offset
                cy = gy0 + row * h + h * 2.0 / 3.0
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 270.0))

        return cells


class TrihexagonalTilingProvider(TilingProvider):
    """Semi-regular trihexagonal tiling — Schläfli vertex figure 3.6.3.6.

    Alternating equilateral triangles and regular hexagons, all sharing the
    same edge length.  Each hexagon is surrounded by 6 triangles; each
    triangle is surrounded by 3 hexagons.

    The hexagon centres lie on a triangular lattice with vectors::

        a1 = (2·step, 0)
        a2 = (step,   step·√3)

    where ``step = cell_size + wall_t``.  Each unit cell (one lattice point)
    holds three polygons:

    * Hexagon (flat-top)  : offset ``(0,       0          )``  n=6, rot=0°
    * Down-pointing △    : offset ``(step,    step/√3    )``  n=3, rot=270°
    * Up-pointing   △    : offset ``(2·step,  2·step/√3  )``  n=3, rot=90°

    The column range for each row is extended by ``extra_cols`` to compensate
    for the oblique X-drift introduced by the ``a2`` vector, ensuring uniform
    coverage at all Y positions.
    """

    display_name = "Trihexagonal (3.6.3.6)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Largest polygon is the hexagon; circumradius of hexagon = side length.
        return cell_size

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        step = cell_size + wall_t
        a1x  = 2.0 * step          # first lattice vector  (2·step, 0)
        a2x  = step                # second lattice vector (step, step·√3)
        a2y  = step * math.sqrt(3)

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_rows = int((gy1 - gy0) / a2y) + 3
        n_cols = int((gx1 - gx0) / a1x) + 3

        # Each row shifts x by a2x = step = a1x/2.  Over n_rows rows the
        # accumulated x-drift is n_rows·step.  In column units (a1x = 2·step
        # per column) that is n_rows/2.  Pre-compute and add to col_start so
        # the left boundary is always covered regardless of row index.
        extra_cols = int(math.ceil(n_rows / 2.0)) + 2

        inv_sqrt3 = 1.0 / math.sqrt(3)  # precompute for speed

        for row in range(-1, n_rows + 1):
            ly = gy0 + row * a2y
            for col in range(-1 - extra_cols, n_cols + 1):
                lx = gx0 + col * a1x + row * a2x

                # Hexagon (flat-top): first vertex at 0° from +X
                cx, cy = lx, ly
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 6, 0.0))

                # Down-pointing triangle (▽): apex at bottom, rotation = 270°
                cx = lx + step
                cy = ly + step * inv_sqrt3
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 270.0))

                # Up-pointing triangle (▲): apex at top, rotation = 90°
                cx = lx + 2.0 * step
                cy = ly + 2.0 * step * inv_sqrt3
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 90.0))

        return cells


class TruncatedSquareTilingProvider(TilingProvider):
    """Semi-regular truncated square tiling — Schläfli vertex figure 4.8.8.

    Regular octagons and squares sharing the same edge length.  At every
    vertex one square and two octagons meet (interior angles 90° + 135° +
    135° = 360°).  Each octagon borders 4 squares (at cardinal directions)
    and 4 other octagons (at diagonal directions) alternately.

    The layout uses a square lattice with period::

        a = step · (2 + √2)   where step = cell_size + wall_t

    Each unit cell contains two of each polygon type:

    * Octagon : offset ``(0,      0      )``  n=8, rot=22.5°
    * Octagon : offset ``(a/2,    a/2    )``  n=8, rot=22.5°
    * Square  : offset ``(a/2,    0      )``  n=4, rot=45°
    * Square  : offset ``(0,      a/2    )``  n=4, rot=45°

    where ``a/2 = step · (2+√2)/2``.  The octagon rotation of 22.5° gives
    flat sides on top and bottom (apothems pointing along cardinal and diagonal
    directions) so that edge-sharing with both neighbour types is geometrically
    exact at wall_t = 0.

    The lattice is strictly rectangular (a1 ⊥ a2), so no oblique drift
    occurs; the standard ±1 row/column margin is sufficient.
    """

    display_name = "Truncated Square (4.8.8)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Largest polygon is the octagon.  Circumradius of a regular octagon
        # with side s: R = s / (2 · sin(π/8))
        return cell_size / (2.0 * math.sin(math.pi / 8.0))

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        step   = cell_size + wall_t
        half_a = step * (2.0 + math.sqrt(2)) / 2.0   # = a/2
        a      = 2.0 * half_a                          # lattice period

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_cols = int((gx1 - gx0) / a) + 3
        n_rows = int((gy1 - gy0) / a) + 3

        for row in range(-1, n_rows + 1):
            ly = gy0 + row * a
            for col in range(-1, n_cols + 1):
                lx = gx0 + col * a

                # Octagon at lattice point (0, 0)
                if gx0 <= lx <= gx1 and gy0 <= ly <= gy1:
                    cells.append((lx, ly, 8, 22.5))

                # Octagon at cell centre (a/2, a/2)
                cx = lx + half_a
                cy = ly + half_a
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 8, 22.5))

                # Square at (a/2, 0)  — between horizontal octagon neighbours
                cx = lx + half_a
                if gx0 <= cx <= gx1 and gy0 <= ly <= gy1:
                    cells.append((cx, ly, 4, 45.0))

                # Square at (0, a/2)  — between vertical octagon neighbours
                cy = ly + half_a
                if gx0 <= lx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((lx, cy, 4, 45.0))

        return cells


class SnubSquareTilingProvider(TilingProvider):
    """Semi-regular snub square tiling — Schläfli vertex figure 3.3.4.3.4.

    The *right-handed* (counter-clockwise) chiral variant.  Every vertex is
    surrounded by three equilateral triangles and two squares in the cyclic
    order 3, 3, 4, 3, 4.  All polygons share the same edge length.

    The tiling has wallpaper-group **p4** symmetry (four-fold rotational
    symmetry, no reflections), making it chiral.

    The layout uses an oblique square Bravais lattice with primitive vectors::

        a1 = step · ( (2+√3)/2,    1/2    )
        a2 = step · ( −1/2,        (2+√3)/2 )

    where ``step = cell_size + wall_t``.  Both vectors have magnitude
    ``step · √(2+√3)``.  Each unit cell (one lattice point) holds six
    polygons:

    * Square S0 : offset ``(0,                  0               )``  n=4, rot=45°
    * Square S1 : offset ``(step·(1+√3)/4,      step·(3+√3)/4  )``  n=4, rot=75°
    * Triangle T1: offset ``(step·(3+√3)/6,      0               )``  n=3, rot=0°
    * Triangle T2: offset ``(step·(3+2√3)/6,     step/2          )``  n=3, rot=60°
    * Triangle T3: offset ``(0,                  step·(3+√3)/6  )``  n=3, rot=90°
    * Triangle T4: offset ``(step·(1+√3)/2,      step·(3+√3)/3  )``  n=3, rot=30°

    The basis offsets satisfy ``T1 + T2 = a1`` and ``T3 + T4 = a1 + a2``,
    confirming four triangles and two squares per primitive cell with total
    area ``step²·(2+√3)`` as expected.

    The ``a2`` vector has a negative x-component (``−step/2``), introducing
    a leftward x-drift of ``step/2`` per row.  Over ``n_rows`` rows the
    accumulated drift is ``n_rows·step/2``.  In column units this is
    ``n_rows / (2+√3)``, so the column range is extended on the right by
    ``extra_cols = ⌈n_rows / (2+√3)⌉ + 2`` to ensure full coverage.

    Symmetrically, the ``a1`` vector has a positive y-component (``+step/2``),
    introducing an upward y-drift of ``step/2`` per column.  Large column
    indices therefore require negative row indices to still place polygon
    centres in the lower part of the region.  The row loop starts at
    ``-1 - extra_rows_neg`` where
    ``extra_rows_neg = ⌈n_cols / (2+√3)⌉ + 2``.
    """

    display_name = "Snub Square (3.3.4.3.4)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Largest polygon is the square; circumradius of square with side s
        # is s·√2/2.
        return cell_size * math.sqrt(2) / 2.0

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        step = cell_size + wall_t
        sq3  = math.sqrt(3)

        # ── oblique primitive lattice vectors ──────────────────────────────
        a1x =  step * (2.0 + sq3) / 2.0   # ≈ 1.866·step  (rightward + upward)
        a1y =  step * 0.5
        a2x = -step * 0.5                  # leftward drift per row
        a2y =  step * (2.0 + sq3) / 2.0   # ≈ 1.866·step  (upward)

        # ── basis offsets from lattice point ──────────────────────────────
        # Square S0: axis-aligned (rot=45°)
        sq0_dx, sq0_dy = 0.0, 0.0

        # Square S1: snub-rotated (rot=75°) at cell centre (a1+a2)/2
        sq1_dx = step * (1.0 + sq3) / 4.0   # ≈ 0.683·step
        sq1_dy = step * (3.0 + sq3) / 4.0   # ≈ 1.183·step

        # Triangles — T1+T2 = a1, T3+T4 = a1+a2
        t1_dx = step * (3.0 + sq3) / 6.0             # ≈ 0.789·step
        t1_dy = 0.0
        t2_dx = step * (3.0 + 2.0 * sq3) / 6.0      # ≈ 1.077·step
        t2_dy = step * 0.5
        t3_dx = 0.0
        t3_dy = step * (3.0 + sq3) / 6.0             # ≈ 0.789·step
        t4_dx = step * (1.0 + sq3) / 2.0             # ≈ 1.366·step
        t4_dy = step * (3.0 + sq3) / 3.0             # ≈ 1.577·step

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_rows = int((gy1 - gy0) / a2y) + 3
        n_cols = int((gx1 - gx0) / a1x) + 3

        # a2x < 0: leftward x-drift accumulates as row increases.  Over n_rows
        # rows the total drift is n_rows·|a2x| = n_rows·step/2.  In column
        # units (a1x per column) that is n_rows/(2+√3).  Extend the column
        # range on the right by extra_cols so no cell is missed.
        extra_cols = int(math.ceil(n_rows / (2.0 + sq3))) + 2

        # a1y > 0: upward y-drift accumulates as col increases.  Over n_cols
        # columns the total drift is n_cols·a1y = n_cols·step/2.  In row
        # units (a2y per row) that is n_cols/(2+√3).  Extend the row range
        # downward by extra_rows_neg so the bottom-right of the region is
        # fully covered regardless of width.
        extra_rows_neg = int(math.ceil(n_cols / (2.0 + sq3))) + 2

        for row in range(-1 - extra_rows_neg, n_rows + 1):
            for col in range(-1, n_cols + 1 + extra_cols):
                lx = gx0 + col * a1x + row * a2x
                ly = gy0 + col * a1y + row * a2y

                # Square S0 — rot=45°
                cx, cy = lx + sq0_dx, ly + sq0_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 4, 45.0))

                # Square S1 — rot=75°
                cx, cy = lx + sq1_dx, ly + sq1_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 4, 75.0))

                # Triangle T1 — rot=0° (apex right)
                cx, cy = lx + t1_dx, ly + t1_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 0.0))

                # Triangle T2 — rot=60° (apex upper-right)
                cx, cy = lx + t2_dx, ly + t2_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 60.0))

                # Triangle T3 — rot=90° (apex up)
                cx, cy = lx + t3_dx, ly + t3_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 90.0))

                # Triangle T4 — rot=30° (apex upper-right)
                cx, cy = lx + t4_dx, ly + t4_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 30.0))

        return cells


class ElongatedTriangularTilingProvider(TilingProvider):
    """Semi-regular elongated triangular tiling — Schläfli vertex figure 3.3.3.4.4.

    Alternating strips of squares and equilateral triangles, all sharing the
    same edge length.  At every vertex two adjacent squares and three
    equilateral triangles meet in the cyclic order 3, 3, 3, 4, 4.  Both
    polygon types share every edge with a neighbour of the other type
    (square edges are shared with triangles; triangle base edges are shared
    with squares).

    The layout uses an oblique lattice with primitive vectors::

        a1 = step · (1,      0              )
        a2 = step · (−1/2,   (2+√3)/2       )

    where ``step = cell_size + wall_t``.  Each unit cell (one lattice point)
    holds three polygons:

    * Square  : offset ``(step/2,   step/2            )``  n=4, rot=45°
    * Up-△    : offset ``(step/2,   step·(6+√3)/6     )``  n=3, rot=90°
    * Down-△  : offset ``(0,        step·(3+√3)/3     )``  n=3, rot=270°

    The ``a2`` vector has a negative x-component (``−step/2``), introducing
    a leftward x-drift of ``step/2`` per row.  Over ``n_rows`` rows the
    accumulated drift is ``n_rows·step/2``.  In column units (one column =
    one ``a1x = step``) that is ``n_rows/2``.  The column range is extended
    on the right by ``extra_cols = ⌈n_rows/2⌉ + 2`` to ensure full coverage
    at all Y positions.
    """

    display_name = "Elongated Triangular (3.3.3.4.4)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Largest polygon is the square; circumradius of a square with side s
        # is s · √2 / 2.
        return cell_size * math.sqrt(2) / 2.0

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        step = cell_size + wall_t
        sq3  = math.sqrt(3)
        h    = step * sq3 / 2.0           # equilateral-triangle height

        # Primitive lattice vectors
        a1x  = step
        a2x  = -step / 2.0
        a2y  = step * (2.0 + sq3) / 2.0  # = step + h

        # Basis offsets from the lattice point (lx, ly)
        sq_dx = step / 2.0
        sq_dy = step / 2.0
        up_dx = step / 2.0
        up_dy = step + h / 3.0            # = step + step·√3/6 = step·(6+√3)/6
        dn_dx = 0.0
        dn_dy = step + 2.0 * h / 3.0     # = step + step·√3/3 = step·(3+√3)/3

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_rows = int((gy1 - gy0) / a2y) + 3
        n_cols = int((gx1 - gx0) / a1x) + 3

        # a2x < 0: leftward x-drift accumulates as row increases.  Over
        # n_rows rows the total drift is n_rows·step/2.  In column units
        # (a1x = step per column) that is n_rows/2.  Extend the column range
        # on the right by extra_cols so no cell is missed at large row values.
        extra_cols = int(math.ceil(n_rows / 2.0)) + 2

        for row in range(-1, n_rows + 1):
            ly = gy0 + row * a2y
            for col in range(-1, n_cols + 1 + extra_cols):
                lx = gx0 + col * a1x + row * a2x

                # Square — rot=45°
                cx, cy = lx + sq_dx, ly + sq_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 4, 45.0))

                # Up-pointing triangle (▲) — rot=90° (apex up)
                cx, cy = lx + up_dx, ly + up_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 90.0))

                # Down-pointing triangle (▽) — rot=270° (apex down)
                cx, cy = lx + dn_dx, ly + dn_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 270.0))

        return cells


class TruncatedHexagonalTilingProvider(TilingProvider):
    """Semi-regular truncated hexagonal tiling — Schläfli vertex figure 3.12.12.

    Equilateral triangles and regular 12-gons (dodecagons), all sharing the
    same edge length.  At every vertex one triangle and two dodecagons meet
    (interior angles 60° + 150° + 150° = 360°).  Each triangle is surrounded
    by three dodecagons; each dodecagon borders six triangles and six other
    dodecagons alternately.

    The tiling can be seen as the truncation of the regular hexagonal tiling:
    every vertex of the hexagonal tiling is replaced by a small equilateral
    triangle, expanding each hexagon into a regular 12-gon.

    The 12-gon centres form a triangular Bravais lattice with period::

        a = step · (2 + √3)   where step = cell_size + wall_t

    and lattice vectors::

        a1 = (a,    0         )
        a2 = (a/2,  a · √3/2  )

    Each unit cell (one lattice point) holds three polygons:

    * Dodecagon (flat-top, rot=15°) : offset ``(0,       0         )``
    * Down-△ (apex down, rot=30°)   : offset ``(a/2,     a · √3/6  )``
    * Up-△   (apex up,   rot=90°)   : offset ``(a,       a · √3/3  )``

    Every triangle vertex lies exactly on a vertex of a neighbouring
    dodecagon (verified analytically).

    The positive ``a2x = a/2`` introduces a rightward x-drift of ``a/2``
    per row.  For large row indices (high Y) the lattice points move to the
    right, so cells at the *left* edge of the region need extra negative
    column indices to be covered.  The column range is extended leftward by::

        extra_cols = ⌈n_rows / 2⌉ + 2

    (identical to the trihexagonal provider which has the same 0.5
    column-unit drift per row).
    """

    display_name = "Truncated Hexagonal (3.12.12)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Largest polygon is the dodecagon.  Circumradius of a regular 12-gon
        # with side s: R = s / (2 · sin(π/12))
        return cell_size / (2.0 * math.sin(math.pi / 12.0))

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        step = cell_size + wall_t
        sq3  = math.sqrt(3)
        a    = step * (2.0 + sq3)   # lattice period = step · (2+√3)

        # Primitive lattice vectors
        a1x = a
        a2x = a / 2.0
        a2y = a * sq3 / 2.0

        # Basis offsets from the lattice point (lx, ly)
        dn_dx = a / 2.0            # down-pointing triangle (apex down, rot=30°)
        dn_dy = a * sq3 / 6.0
        up_dx = a                  # up-pointing triangle   (apex up,   rot=90°)
        up_dy = a * sq3 / 3.0

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_rows = int((gy1 - gy0) / a2y) + 3
        n_cols = int((gx1 - gx0) / a1x) + 3

        # a2x = a/2 > 0: rightward x-drift per row.  For high row indices the
        # lattice points shift right, so more negative column values are needed
        # to cover the left edge of the region.  Extend column range leftward.
        extra_cols = int(math.ceil(n_rows / 2.0)) + 2

        for row in range(-1, n_rows + 1):
            ly = gy0 + row * a2y
            for col in range(-1 - extra_cols, n_cols + 1):
                lx = gx0 + col * a1x + row * a2x

                # Dodecagon (flat-top) — first vertex at 15° from +X
                if gx0 <= lx <= gx1 and gy0 <= ly <= gy1:
                    cells.append((lx, ly, 12, 15.0))

                # Down-pointing triangle (▽) — apex down, rot=30°
                cx, cy = lx + dn_dx, ly + dn_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 30.0))

                # Up-pointing triangle (▲) — apex up, rot=90°
                cx, cy = lx + up_dx, ly + up_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 90.0))

        return cells


class SmallRhombitrihexagonalTilingProvider(TilingProvider):
    """Semi-regular small rhombitrihexagonal tiling — Schläfli vertex figure 3.4.6.4.

    Equilateral triangles, squares, and regular hexagons sharing the same
    edge length.  At every vertex one triangle, two squares, and one hexagon
    meet in the cyclic order 3, 4, 6, 4 (interior angles 60°+90°+120°+90°=360°).

    All six edges of each hexagon are shared with squares; triangles fill the
    corner gaps between each adjacent pair of squares at every hex vertex.
    Each triangle has all three of its edges shared with squares (it touches
    no hexagon directly).

    The layout uses a hexagonal Bravais lattice with primitive vectors::

        A1 = step · ( √3·(1+√3)/2,  (1+√3)/2  )
        A2 = step · ( 0,             1+√3       )

    where ``step = cell_size + wall_t`` and every hexagon occupies one
    lattice point.  The lattice period is ``a = step·(1+√3)``.

    Each unit cell (one lattice point) holds six polygons:

    * Hexagon  : offset ``(0,         0      )``  n=6, rot=0°
    * Square A : offset ``(a·√3/4,    a/4    )``  n=4, rot=75°   (angle 30°)
    * Square B : offset ``(0,         a/2    )``  n=4, rot=135°  (angle 90°)
    * Square C : offset ``(−a·√3/4,   a/4    )``  n=4, rot=195°  (angle 150°)
    * Triangle A: offset ``(a/√3,     0      )``  n=3, rot=60°   (angle 0°)
    * Triangle B: offset ``(a/(2·√3), a/2    )``  n=3, rot=0°    (angle 60°)

    The positive ``A1y = a/2`` introduces an upward y-drift of ``a/2`` per
    column.  Over ``n_cols`` columns the total drift is ``n_cols·a/2``.  In
    row units (one row = ``A2y = a``) that is ``n_cols/2``.  The row range is
    extended downward by ``extra_rows = ⌈n_cols/2⌉ + 2`` to ensure full
    coverage at all X positions.  There is no x-drift from the row index
    (``A2x = 0``), so no extra column compensation is needed.
    """

    display_name = "Small Rhombitrihexagonal (3.4.6.4)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Largest polygon is the hexagon; circumradius of a regular hexagon
        # with side s is s itself.
        return cell_size

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        step = cell_size + wall_t
        sq3  = math.sqrt(3)
        a    = step * (1.0 + sq3)   # lattice period = step·(1+√3)

        # Primitive lattice vectors
        # A1 = (a·√3/2, a/2)  — diagonal (no pure-X step)
        # A2 = (0,      a  )  — purely vertical
        A1x = a * sq3 / 2.0
        A1y = a / 2.0
        A2y = a                     # A2x = 0 (no x-drift per row)

        # Basis offsets from the lattice point (lx, ly)
        # --- Squares at angles 30°, 90°, 150° from the hex centre ---
        sq1_dx =  A1x / 2.0         # = a·√3/4
        sq1_dy =  A1y / 2.0         # = a/4
        sq2_dx =  0.0
        sq2_dy =  A2y / 2.0         # = a/2
        sq3_dx = -A1x / 2.0         # = -a·√3/4
        sq3_dy = (A2y - A1y) / 2.0  # = a/4

        # --- Triangles at angles 0° and 60° from the hex centre ---
        tri1_dx =  a / sq3           # = a/√3
        tri1_dy =  0.0
        tri2_dx =  a / (2.0 * sq3)  # = a/(2·√3)
        tri2_dy =  a / 2.0

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_cols = int((gx1 - gx0) / A1x) + 3
        n_rows = int((gy1 - gy0) / A2y) + 3

        # A1y > 0: upward y-drift accumulates as column index increases.
        # For col = n_cols, the y-baseline is n_cols·A1y = n_cols·a/2.
        # To place polygon centres at the *bottom* of the region with this
        # offset, negative row values are needed.  In row units (A2y = a):
        # row_min = -n_cols/2.  Extend row range downward by extra_rows.
        extra_rows = int(math.ceil(n_cols / 2.0)) + 2

        for col in range(-1, n_cols + 1):
            lx = gx0 + col * A1x    # x depends only on col (A2x = 0)
            for row in range(-1 - extra_rows, n_rows + 1):
                ly = gy0 + col * A1y + row * A2y

                # Hexagon (flat-top) — first vertex at 0° (rightmost)
                if gx0 <= lx <= gx1 and gy0 <= ly <= gy1:
                    cells.append((lx, ly, 6, 0.0))

                # Square A — at angle 30° from hex centre, rot=75°
                cx, cy = lx + sq1_dx, ly + sq1_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 4, 75.0))

                # Square B — at angle 90° from hex centre, rot=135°
                cx, cy = lx + sq2_dx, ly + sq2_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 4, 135.0))

                # Square C — at angle 150° from hex centre, rot=195°
                cx, cy = lx + sq3_dx, ly + sq3_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 4, 195.0))

                # Triangle A — at angle 0° from hex centre, rot=60°
                cx, cy = lx + tri1_dx, ly + tri1_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 60.0))

                # Triangle B — at angle 60° from hex centre, rot=0°
                cx, cy = lx + tri2_dx, ly + tri2_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 3, 0.0))

        return cells


class GreatRhombitrihexagonalTilingProvider(TilingProvider):
    """Semi-regular great rhombitrihexagonal (truncated trihexagonal) tiling
    — Schläfli vertex figure 4.6.12.

    Squares, regular hexagons, and regular dodecagons sharing the same edge
    length.  At every vertex one square, one hexagon, and one dodecagon meet
    in the cyclic order 4, 6, 12 (interior angles 90°+120°+150°=360°).

    Each dodecagon is surrounded by alternating squares and hexagons (6 of
    each); each hexagon borders 3 squares and 3 dodecagons in alternation;
    each square borders 2 hexagons and 2 dodecagons on its four edges.

    The layout uses a hexagonal Bravais lattice with primitive vectors::

        A1 = (a,   0       )
        A2 = (a/2, a·√3/2  )

    where ``a = step·(3+√3)`` and ``step = cell_size + wall_t``.  One
    dodecagon occupies each lattice point.

    Each unit cell holds **six** polygons:

    * Dodecagon : at (0,     0       ) rot=15°
    * Hexagon A : at (a/2,   a·√3/6  ) rot=0°   (direction 30° from 12-gon)
    * Hexagon B : at (0,     a·√3/3  ) rot=0°   (direction 90° from 12-gon)
    * Square A  : at (a/2,   0       ) rot=45°  (direction 0°)
    * Square B  : at (a/4,   a·√3/4  ) rot=105° (direction 60°)
    * Square C  : at (−a/4,  a·√3/4  ) rot=165° (direction 120°)

    Per unit cell: **1 dodecagon, 2 hexagons, 3 squares** (ratio 1:2:3).

    The positive ``A2x = a/2`` introduces a rightward x-drift of ``a/2``
    per row.  Over ``n_rows`` rows the total drift is ``n_rows·a/2``.  In
    column units (``A1x = a``) that is ``n_rows/2``.  The column range is
    extended leftward by ``extra_cols = ⌈n_rows/2⌉ + 2`` to ensure full
    coverage at all Y positions.  There is no y-drift from the column index
    (``A1y = 0``), so no extra row compensation is needed.
    """

    display_name = "Great Rhombitrihexagonal (4.6.12)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Largest polygon is the dodecagon.
        # R_12 = cell_size / (2·sin(π/12)) = cell_size·(√6+√2)/2
        return cell_size * (math.sqrt(6.0) + math.sqrt(2.0)) / 2.0

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        step = cell_size + wall_t
        sq3  = math.sqrt(3.0)
        a    = step * (3.0 + sq3)      # lattice period

        # Primitive lattice vectors
        # A1 = (a,   0    ) — purely horizontal
        # A2 = (a/2, a√3/2) — diagonal; A2x = a/2 causes rightward x-drift per row
        A1x = a
        A2x = a / 2.0
        A2y = a * sq3 / 2.0

        # Basis offsets from the lattice point (lx, ly)
        # --- Hexagons at directions 30° and 90° from the dodecagon centre ---
        hex_a_dx =  a / 2.0           # direction 30°: (a/2,  a√3/6)
        hex_a_dy =  a * sq3 / 6.0
        hex_b_dx =  0.0               # direction 90°: (0,    a√3/3)
        hex_b_dy =  a * sq3 / 3.0

        # --- Squares at directions 0°, 60°, 120° from the dodecagon centre ---
        sq_a_dx =  a / 2.0            # direction  0°: (a/2,  0     ) rot=45°
        sq_a_dy =  0.0
        sq_b_dx =  a / 4.0            # direction 60°: (a/4,  a√3/4 ) rot=105°
        sq_b_dy =  a * sq3 / 4.0
        sq_c_dx = -a / 4.0            # direction 120°: (−a/4, a√3/4 ) rot=165°
        sq_c_dy =  a * sq3 / 4.0

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_cols = int((gx1 - gx0) / A1x) + 3
        n_rows = int((gy1 - gy0) / A2y) + 3

        # A2x > 0: rightward x-drift accumulates as row index increases.
        # For row = n_rows, the x-baseline has shifted rightward by n_rows·a/2.
        # In column units (A1x = a) that is n_rows/2.  Extend the column range
        # leftward so that polygon centres near gx0 at large row values are
        # still captured.
        extra_cols = int(math.ceil(n_rows / 2.0)) + 2

        for row in range(-1, n_rows + 1):
            ly = gy0 + row * A2y
            for col in range(-1 - extra_cols, n_cols + 1):
                lx = gx0 + col * A1x + row * A2x

                # Dodecagon at lattice point — rot=15° (first vertex at 15°)
                if gx0 <= lx <= gx1 and gy0 <= ly <= gy1:
                    cells.append((lx, ly, 12, 15.0))

                # Hexagon A — direction 30° from dodecagon, rot=0°
                cx, cy = lx + hex_a_dx, ly + hex_a_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 6, 0.0))

                # Hexagon B — direction 90° from dodecagon, rot=0°
                cx, cy = lx + hex_b_dx, ly + hex_b_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 6, 0.0))

                # Square A — direction 0° from dodecagon, rot=45°
                cx, cy = lx + sq_a_dx, ly + sq_a_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 4, 45.0))

                # Square B — direction 60° from dodecagon, rot=105°
                cx, cy = lx + sq_b_dx, ly + sq_b_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 4, 105.0))

                # Square C — direction 120° from dodecagon, rot=165°
                cx, cy = lx + sq_c_dx, ly + sq_c_dy
                if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                    cells.append((cx, cy, 4, 165.0))

        return cells


class SnubHexagonalTilingProvider(TilingProvider):
    """Snub hexagonal (snub trihexagonal) tiling — Schläfli vertex figure 3.3.3.3.6.

    Each vertex is surrounded by four equilateral triangles and one regular
    hexagon (in that cyclic order).  The tiling is **chiral**; only the
    right-handed variant is generated here (the left-handed mirror image
    would require negating all y-offsets in the basis).

    The layout uses an oblique Bravais lattice with primitive vectors::

        A1 = step × (5/2,   √3/2  )
        A2 = step × ( 1/2, 3√3/2  )

    where ``step = cell_size + wall_t``.  One hexagon occupies each lattice
    point; **8 equilateral triangles** fill the remaining space of each unit
    cell (proven by the area identity: 3√3/2 + 8·√3/4 = 7√3/2 = |A1 × A2|).

    Each unit cell holds **1 hexagon and 8 triangles**:

    * Hexagon          at ``(0, 0)``,                    rot=0°
    * Triangle 1       at ``(+step,   -step·√3/3)``,     rot=90°  (edge V₅V₀)
    * Triangle 2       at ``(+step,   +step·√3/3)``,     rot=30°  (edge V₀V₁)
    * Triangle 3       at ``(0,       +2·step·√3/3)``,   rot=90°  (edge V₁V₂)
    * Triangle 4       at ``(-step,   +step·√3/3)``,     rot=30°  (edge V₂V₃)
    * Triangle 5       at ``(-step,   -step·√3/3)``,     rot=90°  (edge V₃V₄)
    * Triangle 6       at ``(0,       -2·step·√3/3)``,   rot=30°  (edge V₄V₅)
    * Triangle 7       at ``(-step/2, +5·step·√3/6)``,   rot=30°  (inner gap)
    * Triangle 8       at ``(+step,   +2·step·√3/3)``,   rot=90°  (inner gap)

    **Drift compensation** (both lattice vectors have positive x and y
    components):

    * ``A1y = step·√3/2 > 0``: upward y-drift per column index.  Extend the
      row range downward by ``extra_rows_bot = ⌈n_cols/3⌉ + 2``.
    * ``A2x = step/2 > 0``: rightward x-drift per row index.  Extend the
      column range leftward by ``extra_cols = ⌈n_rows/5⌉ + 2``.
    """

    display_name = "Snub Hexagonal (3.3.3.3.6)"

    def cell_circumradius(self, cell_size: float) -> float:
        # Largest polygon is the hexagon.
        # For a regular hexagon, circumradius = edge length.
        return cell_size

    def get_cells(self, gx0, gx1, gy0, gy1, cell_size, wall_t):
        step = cell_size + wall_t
        sq3  = math.sqrt(3.0)

        # Primitive lattice vectors
        A1x = step * 2.5           # 5/2
        A1y = step * sq3 / 2.0
        A2x = step / 2.0
        A2y = step * 3.0 * sq3 / 2.0

        # Pre-compute triangle basis offsets (ox, oy, rot_deg)
        # 6 "edge" triangles surrounding the hexagon + 2 "gap" triangles
        s3_3  = sq3 / 3.0           # √3/3 = 1/√3
        s2_3  = sq3 * 2.0 / 3.0    # 2√3/3
        s5_6  = sq3 * 5.0 / 6.0    # 5√3/6

        basis = [
            # (ox, oy, rot_deg)
            ( step,          -step * s3_3,  90.0),   # tri 1  V₅V₀
            ( step,           step * s3_3,  30.0),   # tri 2  V₀V₁
            ( 0.0,            step * s2_3,  90.0),   # tri 3  V₁V₂
            (-step,           step * s3_3,  30.0),   # tri 4  V₂V₃
            (-step,          -step * s3_3,  90.0),   # tri 5  V₃V₄
            ( 0.0,           -step * s2_3,  30.0),   # tri 6  V₄V₅
            (-step / 2.0,     step * s5_6,  30.0),   # tri 7  inner gap near V₂
            ( step,           step * s2_3,  90.0),   # tri 8  inner gap near V₁
        ]

        cells = []
        if gx1 <= gx0 or gy1 <= gy0:
            return cells

        n_cols = int((gx1 - gx0) / A1x) + 3
        n_rows = int((gy1 - gy0) / A2y) + 3

        # A1y > 0: upward y-drift per col → extend row range downward
        extra_rows_bot = int(math.ceil(n_cols / 3.0)) + 2
        # A2x > 0: rightward x-drift per row → extend col range leftward
        extra_cols = int(math.ceil(n_rows / 5.0)) + 2

        for row in range(-1 - extra_rows_bot, n_rows + 2):
            for col in range(-1 - extra_cols, n_cols + 2):
                lx = gx0 + col * A1x + row * A2x
                ly = gy0 + col * A1y + row * A2y

                # Hexagon at lattice point — rot=0° (vertex at 0°, flat-side top)
                if gx0 <= lx <= gx1 and gy0 <= ly <= gy1:
                    cells.append((lx, ly, 6, 0.0))

                # Triangles
                for ox, oy, rot in basis:
                    cx = lx + ox
                    cy = ly + oy
                    if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                        cells.append((cx, cy, 3, rot))

        return cells


#: Registry mapping each LATTICE_TYPES key to its TilingProvider instance.
_TILING_PROVIDERS = {
    "hexagonal":                     HexagonalTilingProvider(),
    "square":                        SquareTilingProvider(),
    "triangular":                    TriangularTilingProvider(),
    "trihexagonal":                  TrihexagonalTilingProvider(),
    "truncated_square":              TruncatedSquareTilingProvider(),
    "snub_square":                   SnubSquareTilingProvider(),
    "elongated_triangular":          ElongatedTriangularTilingProvider(),
    "truncated_hexagonal":           TruncatedHexagonalTilingProvider(),
    "small_rhombitrihexagonal":      SmallRhombitrihexagonalTilingProvider(),
    "great_rhombitrihexagonal":      GreatRhombitrihexagonalTilingProvider(),
    "snub_hexagonal":                SnubHexagonalTilingProvider(),
}


def get_tiling_provider(key: str) -> TilingProvider:
    """Return the :class:`TilingProvider` for *key*.

    Parameters
    ----------
    key : one of the keys in :data:`LATTICE_TYPES`

    Raises
    ------
    ValueError
        If *key* is not a known lattice type.
    """
    provider = _TILING_PROVIDERS.get(key)
    if provider is None:
        raise ValueError(
            f"Unknown lattice type {key!r}. "
            f"Valid types: {list(LATTICE_TYPES.keys())}"
        )
    return provider


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
    leg_zones: list = (),
    cell_r: float = None,
) -> bool:
    """Return True if a cell hole centered at (cx, cy) should be suppressed.

    .. note::
        This function is retained as a public utility for callers that need
        an explicit exclusion test.  The :func:`make_piece` geometry builder
        no longer uses it: instead, holes are cut across the **full** shelf
        region and solid exclusion-zone blocks are fused back via
        :func:`_build_exclusion_solids`, which produces cleanly truncated
        polygon holes at zone boundaries rather than omitting cells entirely.

    Suppressed zones
    ~~~~~~~~~~~~~~~~
    * Outer perimeter bands (within ``perim_w`` of any edge).
    * Bridge bands at every cut (within ``perim_w/2`` of any cut line).
    * Leg support areas: axis-aligned rectangles supplied via *leg_zones*
      as ``(x0, y0, x1, y1)`` tuples.  Any cell whose bounding circle
      overlaps a leg zone is suppressed so that the solid leg-corner
      material is preserved.

    A cell is suppressed if its *bounding circle* overlaps any exclusion zone.

    Parameters
    ----------
    hex_size : cell side length (mm).  Used as the bounding-circle radius
               when *cell_r* is not provided (backward-compatible default for
               hexagonal tilings, where circumradius = side length).
    cell_r   : circumradius of the cell polygon (mm).  When provided, this
               overrides the ``hex_size`` default so that non-hexagonal cells
               (squares, triangles, …) are checked with the correct radius.
    """
    r = hex_size if cell_r is None else cell_r

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

    # Leg support zones (axis-aligned rectangles)
    for lx0, ly0, lx1, ly1 in leg_zones:
        if cx + r > lx0 and cx - r < lx1 and cy + r > ly0 and cy - r < ly1:
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
    """Return a FreeCAD Part.Shape: hexagonal prism (pointy-top).

    .. deprecated::
        Prefer :func:`make_polygon_prism` with ``n_sides=6, rotation_deg=30``.
        This function is kept for backward compatibility.
    """
    return make_polygon_prism(cx, cy, 6, 30.0, side, height)


def make_polygon_prism(
    cx: float, cy: float,
    n_sides: int,
    rotation_deg: float,
    side: float,
    height: float,
):
    """Return a FreeCAD Part.Shape: regular n-gon prism.

    Parameters
    ----------
    cx, cy       : centre of the polygon (mm)
    n_sides      : number of sides (3 = equilateral triangle, 4 = square,
                   6 = hexagon, etc.)
    rotation_deg : angle of the first vertex from the +X axis (degrees).
                   Convention used by :class:`TilingProvider` implementations:

                   * Hexagon (6): 30° → pointy-top
                   * Square  (4): 45° → axis-aligned (flat sides on top/bottom)
                   * Triangle UP (3): 90° → apex at top, flat base at bottom
                   * Triangle DN (3): 270° → apex at bottom, flat base at top
    side         : side length of the regular polygon (mm)
    height       : prism height in the Z direction (mm)
    """
    import FreeCAD as App
    import Part

    # Circumradius: R = side / (2 · sin(π / n))
    R = side / (2.0 * math.sin(math.pi / n_sides))

    verts = []
    for k in range(n_sides):
        ang = math.radians(rotation_deg + k * 360.0 / n_sides)
        verts.append(App.Vector(cx + R * math.cos(ang),
                                cy + R * math.sin(ang),
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
# Tapered-prism helpers (finger-joint draft geometry)
# ---------------------------------------------------------------------------

def _make_tapered_prism_x(
    x0_bot: float, x1_bot: float,
    x0_top: float, x1_top: float,
    y_start: float, y_extent: float,
    height: float,
) -> object:  # returns Part.Shape
    """Return a tapered prism for an X-axis finger joint.

    The cross-section (viewed along Y) is a trapezoid:
      * z = 0      : x from ``x0_bot`` to ``x1_bot``
      * z = height : x from ``x0_top`` to ``x1_top``

    The prism is extruded in +Y by ``y_extent`` starting at ``y_start``.
    """
    import FreeCAD as App
    import Part

    pts = [
        App.Vector(x0_bot, y_start, 0.0),
        App.Vector(x1_bot, y_start, 0.0),
        App.Vector(x1_top, y_start, height),
        App.Vector(x0_top, y_start, height),
        App.Vector(x0_bot, y_start, 0.0),   # close
    ]
    wire = Part.makePolygon(pts)
    face = Part.Face(wire)
    return face.extrude(App.Vector(0.0, y_extent, 0.0))


def _make_tapered_prism_y(
    y0_bot: float, y1_bot: float,
    y0_top: float, y1_top: float,
    x_start: float, x_extent: float,
    height: float,
) -> object:  # returns Part.Shape
    """Return a tapered prism for a Y-axis finger joint.

    The cross-section (viewed along X) is a trapezoid:
      * z = 0      : y from ``y0_bot`` to ``y1_bot``
      * z = height : y from ``y0_top`` to ``y1_top``

    The prism is extruded in +X by ``x_extent`` starting at ``x_start``.
    """
    import FreeCAD as App
    import Part

    pts = [
        App.Vector(x_start, y0_bot, 0.0),
        App.Vector(x_start, y1_bot, 0.0),
        App.Vector(x_start, y1_top, height),
        App.Vector(x_start, y0_top, height),
        App.Vector(x_start, y0_bot, 0.0),   # close
    ]
    wire = Part.makePolygon(pts)
    face = Part.Face(wire)
    return face.extrude(App.Vector(x_extent, 0.0, 0.0))


# ---------------------------------------------------------------------------
# Finger-joint helpers
# ---------------------------------------------------------------------------

def _centered_joint_range(
    face_start: float,
    face_end: float,
    joint_span: float,
) -> tuple:
    """Return ``(loop_start, loop_end)`` for a finger-joint zone centred in a face.

    When *joint_span* is ``0`` or ≥ the face length, the full face
    ``(face_start, face_end)`` is returned unchanged.  When *joint_span* is
    positive and smaller than the face length, equal solid margins are left on
    both sides so that the finger-joint region is centred on the face.

    This is a pure helper (no FreeCAD dependency) so it can be unit-tested
    independently of the geometry builders.

    Parameters
    ----------
    face_start, face_end : extent of the cut face in the parallel axis (mm)
    joint_span           : desired active length of the finger-joint zone (mm).
                           ``0`` means "use the entire face".
    """
    face_len = face_end - face_start
    if joint_span <= 0.0 or joint_span >= face_len - _GEOM_EPS:
        return face_start, face_end
    margin = (face_len - joint_span) * 0.5
    return face_start + margin, face_end - margin


def _x_joint_y_extents(
    y0: float,
    y1: float,
    total_l: float,
    tab_d: float,
) -> tuple:
    """Return effective ``(face_start, face_end)`` for an X-axis cut face.

    At 4-way intersections (where an X-cut and a Y-cut cross), both X-face
    tabs and Y-face slots would occupy overlapping 3D regions near the corner,
    causing geometry conflicts.  This helper leaves a flat zone of width
    *tab_d* at each end of the X-face that borders a Y-face joint, so only
    the Y-direction handles interlocking at those corners.

    A Y-face joint exists at the piece boundary when that boundary is an
    internal cut (i.e. ``y0 > 0`` or ``y1 < total_l``).  Outer shelf edges
    have no Y-face joint, so no flat zone is needed there.

    Pure helper — no FreeCAD dependency, fully unit-testable.

    Parameters
    ----------
    y0, y1   : Y bounds of the piece
    total_l  : total shelf length (Y dimension)
    tab_d    : finger tab depth; used as the flat-zone width
    """
    eff_y0 = y0 + tab_d if y0 > _GEOM_EPS else y0
    eff_y1 = y1 - tab_d if y1 < total_l - _GEOM_EPS else y1
    return eff_y0, eff_y1


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
    finger_spacing: float = 0.0,
) -> tuple:
    """Return (tabs, slots) lists of Part.Shape objects for one cut face.

    Parameters
    ----------
    axis            : 'x' or 'y'  – axis *perpendicular* to the cut face
    cut_pos         : coordinate of the cut plane along *axis*
    face_start      : start of the face range in the *parallel* axis
    face_end        : end   of the face range in the *parallel* axis
    height          : Z height of the part
    tab_w           : finger width (along the face, mm)
    tab_d           : finger depth (into the adjacent piece); this is the
                      *nominal* depth at the mid-height.  The actual depth is
                      tapered: ``tab_d * (1 - TAPER_RATIO)`` at z = 0
                      (narrow / bottom), ``tab_d * (1 + TAPER_RATIO)`` at
                      z = height (wide / top).
    this_side       : 'left'|'right' for x-cuts; 'bottom'|'top' for y-cuts
    finger_spacing  : gap between consecutive fingers (mm).  ``0`` (default)
                      places fingers contiguously, filling the entire face.
                      When positive, N fingers are centred on the face with
                      *finger_spacing* flat zones between them.
    """
    import FreeCAD as App  # noqa: F401 – kept for completeness; used by helpers
    import Part             # noqa: F401

    fit    = FIT_CLEARANCE
    tabs   = []
    slots  = []

    # Tapered depths: wider at z=height (top), narrower at z=0 (bottom).
    # Assembly direction is from the top; the narrower bottom provides a
    # positive support contact once the pieces are fully engaged.
    td_bot = tab_d * (1.0 - TAPER_RATIO)   # depth at z = 0
    td_top = tab_d * (1.0 + TAPER_RATIO)   # depth at z = height

    # 'left'/'bottom' pieces: tabs at even finger positions (0, 2, 4 …)
    first_is_tab = this_side in ('left', 'bottom')

    # Build the list of finger start positions.
    # When finger_spacing == 0: fill the face contiguously (original behaviour).
    # When finger_spacing  > 0: centre N discrete fingers on the face, each
    #   separated by finger_spacing mm of flat (no-tab) material.
    face_len = face_end - face_start
    if finger_spacing > 0.0:
        period = tab_w + finger_spacing
        n_fingers = max(1, int((face_len + finger_spacing) / period))
        total_span = n_fingers * tab_w + (n_fingers - 1) * finger_spacing
        margin = max(0.0, (face_len - total_span) * 0.5)
        finger_starts = [face_start + margin + i * period for i in range(n_fingers)]
    else:
        n_cont = max(1, int(face_len / tab_w) + 1)
        finger_starts = [face_start + i * tab_w for i in range(n_cont)]

    for finger_idx, pos in enumerate(finger_starts):
        seg_s = pos
        seg_e = min(pos + tab_w, face_end)
        seg_l = seg_e - seg_s

        # Skip (don't break) so that subsequent centred fingers within the
        # face can still be placed even if this one clips the boundary.
        if seg_l < tab_w * MIN_SEG_RATIO:
            continue

        is_tab = (finger_idx % 2 == 0) == first_is_tab

        if axis == 'x':
            y0  = seg_s + fit * 0.5
            dy  = seg_l - fit
            y0s = seg_s - fit * 0.5
            dys = seg_l + fit

            if is_tab:
                if this_side == 'left':
                    # Tab extends in +X from cut_pos; wider at top, narrower at bottom
                    t = _make_tapered_prism_x(
                        cut_pos, cut_pos + td_bot,
                        cut_pos, cut_pos + td_top,
                        y0, dy, height,
                    )
                else:  # 'right'
                    # Tab extends in -X from cut_pos
                    t = _make_tapered_prism_x(
                        cut_pos - td_bot, cut_pos,
                        cut_pos - td_top, cut_pos,
                        y0, dy, height,
                    )
                tabs.append(t)
            else:
                # Slot (subtracted from body) to receive the opposite tab
                if this_side == 'left':
                    # Opposite ('right') tab extends in -X; slot accepts it
                    s = _make_tapered_prism_x(
                        cut_pos - td_bot - fit, cut_pos,
                        cut_pos - td_top - fit, cut_pos,
                        y0s, dys, height,
                    )
                else:  # 'right'
                    # Opposite ('left') tab extends in +X; slot accepts it
                    s = _make_tapered_prism_x(
                        cut_pos, cut_pos + td_bot + fit,
                        cut_pos, cut_pos + td_top + fit,
                        y0s, dys, height,
                    )
                slots.append(s)

        else:  # axis == 'y'
            x0  = seg_s + fit * 0.5
            dx  = seg_l - fit
            x0s = seg_s - fit * 0.5
            dxs = seg_l + fit

            if is_tab:
                if this_side == 'bottom':
                    # Tab extends in +Y from cut_pos
                    t = _make_tapered_prism_y(
                        cut_pos, cut_pos + td_bot,
                        cut_pos, cut_pos + td_top,
                        x0, dx, height,
                    )
                else:  # 'top'
                    # Tab extends in -Y from cut_pos
                    t = _make_tapered_prism_y(
                        cut_pos - td_bot, cut_pos,
                        cut_pos - td_top, cut_pos,
                        x0, dx, height,
                    )
                tabs.append(t)
            else:
                if this_side == 'bottom':
                    # Opposite ('top') tab extends in -Y; slot accepts it
                    s = _make_tapered_prism_y(
                        cut_pos - td_bot - fit, cut_pos,
                        cut_pos - td_top - fit, cut_pos,
                        x0s, dxs, height,
                    )
                else:  # 'top'
                    # Opposite ('bottom') tab extends in +Y; slot accepts it
                    s = _make_tapered_prism_y(
                        cut_pos, cut_pos + td_bot + fit,
                        cut_pos, cut_pos + td_top + fit,
                        x0s, dxs, height,
                    )
                slots.append(s)

    return tabs, slots


# ---------------------------------------------------------------------------
# Stepped shelf joint (new default)
# ---------------------------------------------------------------------------

def _step_joint_z_extents(
    finger_idx: int,
    height: float,
    this_side: str,
) -> tuple:
    """Return ``(tab_z0, tab_z1, slot_z0, slot_z1)`` for a step-joint finger.

    Pure helper — no FreeCAD dependency, fully unit-testable.

    The step boundary is at ``height / 2``.  'left'/'bottom' pieces start
    with a lower tab (z = 0 … h/2) at even finger indices; 'right'/'top'
    pieces have the complementary pattern.

    Parameters
    ----------
    finger_idx : 0-based finger index along the cut face
    height     : total part height (Z dimension)
    this_side  : 'left' | 'right' | 'bottom' | 'top'
    """
    half_h = height * 0.5
    first_is_lower   = this_side in ('left', 'bottom')
    tab_at_lower_half = (finger_idx % 2 == 0) == first_is_lower
    if tab_at_lower_half:
        return 0.0, half_h, half_h, height
    else:
        return half_h, height, 0.0, half_h


def step_joint(
    axis: str,
    cut_pos: float,
    face_start: float,
    face_end: float,
    height: float,
    tab_w: float,
    tab_d: float,
    this_side: str,
    finger_spacing: float = 0.0,
) -> tuple:
    """Return (tabs, slots) lists of Part.Shape objects for a stepped shelf joint.

    Unlike the tapered box joint (which makes each finger *either* a tab *or*
    a slot), every finger here has **both** a half-height tab **and** a
    half-height slot at the complementary Z level.  The alternating step
    pattern locks assembled pieces against vertical (Z) movement while still
    allowing horizontal (X or Y) assembly.

    Parameters
    ----------
    axis            : 'x' or 'y' — axis *perpendicular* to the cut face
    cut_pos         : coordinate of the cut plane along *axis*
    face_start      : start of the face range in the *parallel* axis
    face_end        : end   of the face range in the *parallel* axis
    height          : Z height of the part
    tab_w           : finger width (along the face, mm)
    tab_d           : finger depth (into the adjacent piece, mm)
    this_side       : 'left'|'right' for x-cuts; 'bottom'|'top' for y-cuts
    finger_spacing  : gap between consecutive fingers (mm).  ``0`` (default)
                      places fingers contiguously, filling the entire face.
                      When positive, N fingers are centred on the face with
                      *finger_spacing* flat zones between them.

    Returns
    -------
    (tabs, slots)
        *tabs*  – shapes to be **fused** onto the piece body (protruding steps)
        *slots* – shapes to be **cut** from the piece body (receiving notches)
    """
    import Part
    import FreeCAD as App

    fit    = FIT_CLEARANCE
    tabs   = []
    slots  = []

    # Build the list of finger start positions.
    # When finger_spacing == 0: fill the face contiguously (original behaviour).
    # When finger_spacing  > 0: centre N discrete fingers on the face, each
    #   separated by finger_spacing mm of flat (no-tab) material.
    face_len = face_end - face_start
    if finger_spacing > 0.0:
        period = tab_w + finger_spacing
        n_fingers = max(1, int((face_len + finger_spacing) / period))
        total_span = n_fingers * tab_w + (n_fingers - 1) * finger_spacing
        margin = max(0.0, (face_len - total_span) * 0.5)
        finger_starts = [face_start + margin + i * period for i in range(n_fingers)]
    else:
        n_cont = max(1, int(face_len / tab_w) + 1)
        finger_starts = [face_start + i * tab_w for i in range(n_cont)]

    for finger_idx, pos in enumerate(finger_starts):
        seg_s = pos
        seg_e = min(pos + tab_w, face_end)
        seg_l = seg_e - seg_s

        # Skip (don't break) so that subsequent centred fingers within the
        # face can still be placed even if this one clips the boundary.
        if seg_l < tab_w * MIN_SEG_RATIO:
            continue

        # Z extents for this finger (tab half and slot half)
        tab_z0, tab_z1, slt_z0, slt_z1 = _step_joint_z_extents(
            finger_idx, height, this_side
        )

        # Along-face extents: tab (tight) and slot (loose)
        face_t_s = seg_s + fit * 0.5       # tab face start
        face_t_l = seg_l - fit             # tab face length
        face_s_s = seg_s - fit * 0.5       # slot face start
        face_s_l = seg_l + fit             # slot face length

        if axis == 'x':
            if this_side == 'left':
                # Tab protrudes in +X; slot receives right's tab (extends in −X)
                tx0, tx1 = cut_pos, cut_pos + tab_d
                sx0, sx1 = cut_pos - tab_d - fit, cut_pos
            else:  # 'right'
                # Tab protrudes in −X; slot receives left's tab (extends in +X)
                tx0, tx1 = cut_pos - tab_d, cut_pos
                sx0, sx1 = cut_pos, cut_pos + tab_d + fit

            if face_t_l > _GEOM_EPS and tab_z1 - tab_z0 > _GEOM_EPS:
                tabs.append(Part.makeBox(
                    tx1 - tx0, face_t_l, tab_z1 - tab_z0,
                    App.Vector(tx0, face_t_s, tab_z0)))

            if face_s_l > _GEOM_EPS and slt_z1 - slt_z0 > _GEOM_EPS:
                slots.append(Part.makeBox(
                    sx1 - sx0, face_s_l, slt_z1 - slt_z0,
                    App.Vector(sx0, face_s_s, slt_z0)))

        else:  # axis == 'y'
            if this_side == 'bottom':
                # Tab protrudes in +Y; slot receives top's tab (extends in −Y)
                ty0, ty1 = cut_pos, cut_pos + tab_d
                sy0, sy1 = cut_pos - tab_d - fit, cut_pos
            else:  # 'top'
                # Tab protrudes in −Y; slot receives bottom's tab (extends in +Y)
                ty0, ty1 = cut_pos - tab_d, cut_pos
                sy0, sy1 = cut_pos, cut_pos + tab_d + fit

            if face_t_l > _GEOM_EPS and tab_z1 - tab_z0 > _GEOM_EPS:
                tabs.append(Part.makeBox(
                    face_t_l, ty1 - ty0, tab_z1 - tab_z0,
                    App.Vector(face_t_s, ty0, tab_z0)))

            if face_s_l > _GEOM_EPS and slt_z1 - slt_z0 > _GEOM_EPS:
                slots.append(Part.makeBox(
                    face_s_l, sy1 - sy0, slt_z1 - slt_z0,
                    App.Vector(face_s_s, sy0, slt_z0)))

    return tabs, slots


# ---------------------------------------------------------------------------
# Single-piece builder
# ---------------------------------------------------------------------------

def _build_exclusion_solids(
    piece_x0: float, piece_x1: float,
    piece_y0: float, piece_y1: float,
    height: float,
    total_w: float, total_l: float,
    perim_w: float,
    x_cuts: list,
    y_cuts: list,
    leg_zones: list,
    joint_w: float = None,
    support_spacing: float = 0.0,
    support_width: float = 0.0,
) -> list:
    """Return a list of FreeCAD ``Part.Shape`` boxes for all exclusion zones
    that overlap the piece region ``[piece_x0, piece_x1] × [piece_y0, piece_y1]``.

    Exclusion zones are areas that must remain **solid** in the finished piece:

    * **Perimeter frame** — four strips of width *perim_w* along every outer
      edge of the shelf (bottom, top, left, right).
    * **Cut bridges** — a band of half-width *joint_w / 2* on each side of
      every X-cut and Y-cut line, keeping the finger-joint bridge material
      intact.  When *joint_w* is not supplied it defaults to *perim_w*.
    * **Interior support bars** — when *support_spacing* > 0, solid bars of
      width *support_width* run in both X and Y directions at intervals of
      *support_spacing* mm, forming a structural grid within the tiling.
    * **Leg support rectangles** — the full footprint of each leg corner
      supplied via *leg_zones*.

    Each zone box is clipped to the piece bounds before being added, so only
    the portion that overlaps this piece is included.  The caller fuses these
    boxes back into the piece body (after cutting the full tiling holes) to
    produce cleanly truncated polygon holes at zone boundaries instead of
    entirely suppressing cells whose centres fall inside a zone.

    Parameters
    ----------
    joint_w         : bridge-band half-width used at cut lines (mm).
                      Defaults to *perim_w* when not specified.
    support_spacing : spacing between interior support bars (mm).
                      ``0`` (default) disables support bars entirely.
    support_width   : full width of each interior support bar (mm).
                      Defaults to *joint_w* when not specified.
    """
    import FreeCAD as App
    import Part

    if joint_w is None:
        joint_w = perim_w
    if support_width <= 0.0:
        support_width = joint_w

    solids = []

    def _clip_and_add(zx0, zx1, zy0, zy1):
        """Clip a zone rect to the piece bounds and append a box if non-empty."""
        cx0 = max(zx0, piece_x0)
        cx1 = min(zx1, piece_x1)
        cy0 = max(zy0, piece_y0)
        cy1 = min(zy1, piece_y1)
        if cx1 > cx0 + _GEOM_EPS and cy1 > cy0 + _GEOM_EPS:
            solids.append(
                Part.makeBox(cx1 - cx0, cy1 - cy0, height,
                             App.Vector(cx0, cy0, 0.0))
            )

    # ── Perimeter frame (4 outer strips) ─────────────────────────────────
    pw = perim_w
    bottom_strip = (0.0,          total_w, 0.0,          pw)
    top_strip    = (0.0,          total_w, total_l - pw, total_l)
    left_strip   = (0.0,          pw,      0.0,          total_l)
    right_strip  = (total_w - pw, total_w, 0.0,          total_l)
    for strip in (bottom_strip, top_strip, left_strip, right_strip):
        _clip_and_add(*strip)

    # ── Bridge bands at cut lines ─────────────────────────────────────────
    bridge_half = joint_w * 0.5
    for xc in x_cuts:
        _clip_and_add(xc - bridge_half, xc + bridge_half, 0.0, total_l)
    for yc in y_cuts:
        _clip_and_add(0.0, total_w, yc - bridge_half, yc + bridge_half)

    # ── Interior support bars ─────────────────────────────────────────────
    if support_spacing > _GEOM_EPS:
        bar_half = support_width * 0.5
        # Y-direction bars (parallel to Y axis; vertical bars across the width)
        bar_x = support_spacing
        while bar_x < total_w - _GEOM_EPS:
            _clip_and_add(bar_x - bar_half, bar_x + bar_half, 0.0, total_l)
            bar_x += support_spacing
        # X-direction bars (parallel to X axis; horizontal bars across the length)
        bar_y = support_spacing
        while bar_y < total_l - _GEOM_EPS:
            _clip_and_add(0.0, total_w, bar_y - bar_half, bar_y + bar_half)
            bar_y += support_spacing

    # ── Leg support rectangles ────────────────────────────────────────────
    for lx0, ly0, lx1, ly1 in leg_zones:
        _clip_and_add(lx0, lx1, ly0, ly1)

    return solids


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
    leg_zones: list = (),
    lattice_type: str = "hexagonal",
    joint_w: float = None,
    finger_w: float = None,
    finger_spacing: float = 0.0,
    support_spacing: float = 0.0,
    support_width: float = None,
    joint_depth: float = None,
    joint_style: str = "step",
) -> object:  # returns Part.Shape
    """Build one interlocking piece of the lattice panel.

    Tiling approach
    ~~~~~~~~~~~~~~~
    The tiling is generated for the **full shelf region** ``[0, total_w] ×
    [0, total_l]``, including areas that must remain solid (perimeter band,
    cut bridges, leg zones).  All polygon holes are cut into the base body
    first so that the tiling is perfectly regular across the entire surface.

    Exclusion zones (perimeter frame, cut bridges, leg rectangles, optional
    support bars) are then **fused back** as solid geometry on top of the
    tiled body.  Any polygon hole that overlaps an exclusion zone is cleanly
    *truncated* at the zone boundary rather than being omitted entirely.

    Parameters
    ----------
    ix, iy         : piece grid indices (used for naming; not needed for geometry)
    x0 … y1        : nominal piece bounds (at cut lines)
    total_w/l      : full-part dimensions
    height         : part thickness (Z)
    perim_w        : solid **outer** perimeter width (mm).  Controls the four
                     frame strips at the shelf edges.
    hex_size       : cell side length (mm).  Named ``hex_size`` for backward
                     compatibility; for non-hexagonal tilings this is the side
                     length of the cell polygon.
    wall_t         : minimum wall thickness between adjacent cells
    x_cuts         : list of X-cut positions
    y_cuts         : list of Y-cut positions
    leg_zones      : list of ``(x0, y0, x1, y1)`` rectangles that must remain
                     solid (e.g. leg-corner footprints).  The full footprint is
                     restored after hole cutting via a boolean fuse.
    lattice_type   : one of the keys in :data:`LATTICE_TYPES`
                     (default ``"hexagonal"``).
    joint_w        : **bridge** width (mm).  Controls the solid band
                     half-width ``(joint_w / 2)`` on each side of every cut
                     line.  This is the *solid-line* width of the joint.
                     Defaults to *perim_w* for backward compatibility.
    finger_w       : **tab / finger width** (mm) — how wide each individual
                     finger tab is along the cut face.  Independent of
                     *joint_w*, so e.g. ``joint_w=10, finger_w=20,
                     joint_depth=4`` gives a 10 mm-wide solid bridge with
                     20 mm-wide fingers that penetrate 4 mm deep (leaving
                     1 mm solid backing on each side).
                     Defaults to ``None`` → falls back to *joint_w*.
    finger_spacing : gap between consecutive fingers (mm).  ``0`` (default)
                     places fingers contiguously, filling the entire cut face.
                     When > 0, N fingers are centred on the face with
                     *finger_spacing* mm of flat (un-tabbed) material between
                     them.
    support_spacing: spacing between interior support bars (mm).
                     ``0`` (default) disables support bars entirely.  When > 0,
                     solid bars of width *support_width* are fused at regular
                     intervals in both X and Y, creating a structural grid.
    support_width  : full width of each interior support bar (mm).
                     Defaults to *joint_w* when not specified.
    joint_depth    : how far each finger tab penetrates into the adjacent
                     piece in the direction perpendicular to the cut face (mm).
                     Must be less than ``joint_w / 2`` to leave solid backing
                     beyond the tab tips (preventing fingers from reaching
                     lattice voids in the adjacent piece).
                     Defaults to ``None`` → ``joint_w / 3`` (fingers fill 2/3
                     of the bridge half-width, leaving 1/3 as a solid support
                     bar behind the slot).
    joint_style    : ``'step'`` (default) — alternating stepped shelf joints
                     that lock assembled pieces against vertical movement.
                     ``'taper'`` — legacy tapered box joints (draft angle in Z).
    """
    import FreeCAD as App
    import Part

    if joint_w is None:
        joint_w = perim_w
    if support_width is None:
        support_width = joint_w

    tab_w  = finger_w if (finger_w is not None and finger_w > 0.0) else joint_w
    tab_d  = (joint_depth if (joint_depth is not None and joint_depth > 0.0)
              else joint_w / 3.0)

    # ------------------------------------------------------------------
    # 1. Base rectangular body
    # ------------------------------------------------------------------
    body = Part.makeBox(x1 - x0, y1 - y0, height,
                        App.Vector(x0, y0, 0.0))

    # ------------------------------------------------------------------
    # 2. Lattice holes — tiled across the full shelf region
    # ------------------------------------------------------------------
    # Generate cells for the entire shelf (0 … total_w × 0 … total_l) so
    # that the grid is consistent and includes the perimeter/bridge zones.
    # Cells in exclusion zones are NOT skipped here; they will be restored
    # by the boolean fuse in step 3.

    provider = get_tiling_provider(lattice_type)
    cells    = provider.get_cells(0.0, total_w, 0.0, total_l, hex_size, wall_t)
    cell_r   = provider.cell_circumradius(hex_size)
    cell_holes = []

    # Clip box is constant for the whole piece – create it once.
    clip_box = Part.makeBox(x1 - x0, y1 - y0, height,
                            App.Vector(x0, y0, 0.0))

    for cx, cy, n_sides, rotation_deg in cells:
        # Cell must overlap this piece's region
        if (cx + cell_r < x0 or cx - cell_r > x1 or
                cy + cell_r < y0 or cy - cell_r > y1):
            continue

        prism = make_polygon_prism(cx, cy, n_sides, rotation_deg,
                                   hex_size, height)

        # Only run the (expensive) common() clip for cells that actually
        # straddle a piece boundary.  Interior cells are added as-is.
        if (cx - cell_r < x0 + 1e-6 or cx + cell_r > x1 - 1e-6 or
                cy - cell_r < y0 + 1e-6 or cy + cell_r > y1 - 1e-6):
            clipped = prism.common(clip_box)
            if clipped.Volume > 1e-9:
                cell_holes.append(clipped)
        else:
            cell_holes.append(prism)

    if cell_holes:
        holes_union = _fuse_shapes(cell_holes)
        body = body.cut(holes_union)

    # ------------------------------------------------------------------
    # 3. Restore exclusion zones via boolean fuse
    # ------------------------------------------------------------------
    # Build solid boxes for all exclusion zones that overlap this piece
    # (perimeter frame, cut bridges, leg footprints) and fuse them back.
    # This truncates any polygon holes at zone boundaries, ensuring the
    # solid perimeter/bridge material is always intact.

    excl_solids = _build_exclusion_solids(
        x0, x1, y0, y1,
        height,
        total_w, total_l,
        perim_w,
        x_cuts, y_cuts,
        leg_zones,
        joint_w=joint_w,
        support_spacing=support_spacing,
        support_width=support_width,
    )
    if excl_solids:
        excl_union = _fuse_shapes(excl_solids)
        body = body.fuse(excl_union)

    # ------------------------------------------------------------------
    # 4. Joints on each cut face
    # ------------------------------------------------------------------
    _joint_fn = step_joint if joint_style == 'step' else finger_joint

    # For X-axis cut faces, leave flat corner zones at Y-cut boundaries
    # (where 4 pieces meet) to prevent X-face tabs from intersecting the
    # Y-face slot geometry.  Y-face joints span the full X range unchanged
    # so they provide the sole interlocking at those corners.
    xj_y0, xj_y1 = _x_joint_y_extents(y0, y1, total_l, tab_d)

    # ── Left face (x = x0): this piece is to the RIGHT of that cut
    if x0 > 1e-6 and xj_y1 > xj_y0 + _GEOM_EPS:
        tabs, slots = _joint_fn('x', x0, xj_y0, xj_y1,
                                height, tab_w, tab_d, 'right',
                                finger_spacing=finger_spacing)
        body = _cut_shapes(_fuse_shapes([body] + tabs) if tabs else body, slots)

    # ── Right face (x = x1): this piece is to the LEFT of that cut
    if x1 < total_w - 1e-6 and xj_y1 > xj_y0 + _GEOM_EPS:
        tabs, slots = _joint_fn('x', x1, xj_y0, xj_y1,
                                height, tab_w, tab_d, 'left',
                                finger_spacing=finger_spacing)
        body = _cut_shapes(_fuse_shapes([body] + tabs) if tabs else body, slots)

    # ── Bottom face (y = y0): this piece is ABOVE (top side of) that cut
    if y0 > 1e-6:
        tabs, slots = _joint_fn('y', y0, x0, x1,
                                height, tab_w, tab_d, 'top',
                                finger_spacing=finger_spacing)
        body = _cut_shapes(_fuse_shapes([body] + tabs) if tabs else body, slots)

    # ── Top face (y = y1): this piece is BELOW (bottom side of) that cut
    if y1 < total_l - 1e-6:
        tabs, slots = _joint_fn('y', y1, x0, x1,
                                height, tab_w, tab_d, 'bottom',
                                finger_spacing=finger_spacing)
        body = _cut_shapes(_fuse_shapes([body] + tabs) if tabs else body, slots)

    return body


# ---------------------------------------------------------------------------
# Corner-hole / leg geometry helpers
# ---------------------------------------------------------------------------

def corner_hole_positions(
    width: float,
    length: float,
    perim_w: float,
) -> list:
    """Return the (cx, cy) centres of the four corner leg-hole positions.

    Each hole is centred at ``perim_w / 2`` inward from the nearest corner so
    that it falls entirely within the solid perimeter band.

    Parameters
    ----------
    width, length : overall shelf dimensions (mm)
    perim_w       : solid perimeter / bridge width (mm)

    Returns
    -------
    list of four (cx, cy) tuples in order:
        [bottom-left, bottom-right, top-left, top-right]
    """
    offset = perim_w * 0.5
    return [
        (offset,           offset),            # bottom-left
        (width - offset,   offset),            # bottom-right
        (offset,           length - offset),   # top-left
        (width - offset,   length - offset),   # top-right
    ]


def leg_flush_placements(
    width: float,
    length: float,
    leg_height: float,
    leg_width: float,
) -> list:
    """Return the assembly placement ``(px, py, pz)`` for each corner leg.

    Legs are positioned **flush** with the shelf outer edge: the outer corner
    of each leg aligns exactly with the nearest shelf corner so that no part
    of the leg protrudes beyond the shelf footprint.

    The leg geometry is a box built at the local origin
    ``(0, 0, 0) … (leg_width, leg_width, leg_height + peg_depth)``.
    Applying the returned placement vector as a FreeCAD ``Placement`` maps
    that local geometry to the correct world position:

    * body column   → z = ``-leg_height … 0``   (below the shelf bottom face)
    * tenon peg     → z = ``0 … peg_depth``       (inside the blind socket)

    Parameters
    ----------
    width, length : shelf panel dimensions (mm)
    leg_height    : height of the support column below the shelf (mm)
    leg_width     : side length of the square leg cross-section (mm)

    Returns
    -------
    list of four ``(px, py, pz)`` tuples in order:
        [bottom-left, bottom-right, top-left, top-right]
    """
    return [
        (0.0,               0.0,                -leg_height),  # bottom-left
        (width - leg_width, 0.0,                -leg_height),  # bottom-right
        (0.0,               length - leg_width, -leg_height),  # top-left
        (width - leg_width, length - leg_width, -leg_height),  # top-right
    ]


def make_leg(
    leg_width: float,
    leg_height: float,
    peg_depth: float,
    shelf_height: float = 0.0,
) -> object:  # Part.Shape
    """Return a FreeCAD Part.Shape for a single shelf leg with tenon peg.

    The part is created in **print orientation**: base at z = 0, peg pointing
    upward.

    Geometry
    --------
    ::

        z = leg_height + shelf_height  ── top of round through-pin (flush with shelf top)
             │  pin   │  ← cylindrical pin, radius = leg_width × PIN_RADIUS_RATIO
        z = leg_height + peg_depth  ── top of square tenon
             │  tenon │  ← square tenon, same width as body, enters blind hole
        z = leg_height  ────────────  ← shoulder rests on shelf underside
             │  body  │  ← main support column
        z = 0  ─────────────────────  ← print-bed face / bottom of leg

    When positioned in the assembly (via :func:`create_shelf_with_legs`) the
    leg is translated so that the shoulder sits at z = 0 (shelf bottom face),
    the body hangs below (z = -leg_height), the square tenon protrudes upward
    into the shelf's blind corner hole (z = 0 … peg_depth), and the round
    through-pin rises through the full shelf height ending flush with the
    shelf top face (z = 0 … shelf_height in world space).

    Parameters
    ----------
    leg_width    : side length of the square cross-section for both body and peg (mm)
    leg_height   : height of the support column below the shelf (mm)
    peg_depth    : height of the square tenon that enters the shelf blind hole (mm)
    shelf_height : shelf panel height (mm).  When > 0 a cylindrical through-pin
                   of radius ``leg_width × PIN_RADIUS_RATIO`` is fused to the
                   leg at its centre, running from the shoulder
                   (z = leg_height) to the shelf top (z = leg_height + shelf_height).
    """
    import FreeCAD as App
    import Part

    total_height = leg_height + peg_depth
    body = Part.makeBox(
        leg_width, leg_width, total_height,
        App.Vector(0.0, 0.0, 0.0),
    )

    if shelf_height > 0.0:
        pin_radius = leg_width * PIN_RADIUS_RATIO
        cx = leg_width * 0.5
        cy = leg_width * 0.5
        pin = Part.makeCylinder(
            pin_radius,
            shelf_height,
            App.Vector(cx, cy, leg_height),
            App.Vector(0.0, 0.0, 1.0),
        )
        body = body.fuse(pin)

    return body


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------

def create_all_pieces(
    width: float,
    length: float,
    height: float,
    perim_width: float,
    hex_size: float,
    wall_thickness: float = None,
    max_piece_size: float = MAX_PIECE_SIZE,
    lattice_type: str = "hexagonal",
    joint_width: float = None,
    finger_w: float = None,
    finger_spacing: float = 0.0,
    support_spacing: float = 0.0,
    support_width: float = None,
    joint_depth: float = None,
    joint_style: str = "step",
) -> list:
    """Create all interlocking pieces for a lattice flat panel.

    Parameters
    ----------
    width, length, height : overall part dimensions (mm)
    perim_width           : solid **outer** perimeter width (mm).  Controls the
                            four frame strips at the panel edges.
    hex_size              : cell side length (mm).  Named ``hex_size`` for
                            backward compatibility; applies to any tiling.
    wall_thickness        : minimum wall between cells (mm).
                            Defaults to ``max(1.2, hex_size * 0.15)``.
    max_piece_size        : maximum printable piece length/width (mm).
                            Panels larger than this are sliced into pieces.
                            The dialog limits this to 1–220 mm to avoid
                            printer exclusion zones.
    lattice_type          : one of the keys in :data:`LATTICE_TYPES`
                            (default ``"hexagonal"``).
    joint_width           : **bridge** width (mm) — the solid-line width of the
                            joint zone.  Controls bridge-band half-width at cut
                            lines.  Defaults to *perim_width*.
    finger_w              : **tab / finger width** (mm) — the width of each
                            individual finger tab along the cut face.
                            Independent of *joint_width*; defaults to
                            *joint_width* when ``None``.
    finger_spacing        : gap between consecutive fingers (mm).  ``0``
                            (default) places fingers contiguously (full face).
                            When > 0, N centred fingers are placed with
                            *finger_spacing* flat gaps between them.
    support_spacing       : spacing between interior support bars (mm).
                            ``0`` (default) disables support bars.
    support_width         : full width of each interior support bar (mm).
                            Defaults to *joint_width*.
    joint_depth           : how far each finger tab penetrates into the adjacent
                            piece (mm).  ``None`` → ``joint_width / 3``.
    joint_style           : ``'step'`` (default) — alternating stepped shelf
                            joints.  ``'taper'`` — legacy tapered box joints.

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
                lattice_type=lattice_type,
                joint_w=joint_width,
                finger_w=finger_w,
                finger_spacing=finger_spacing,
                support_spacing=support_spacing,
                support_width=support_width,
                joint_depth=joint_depth,
                joint_style=joint_style,
            )
            pieces.append((f"Piece_{ix}_{iy}", shape))

    return pieces


def create_shelf_with_legs(
    width: float,
    length: float,
    height: float,
    perim_width: float,
    hex_size: float,
    wall_thickness: float = None,
    max_piece_size: float = MAX_PIECE_SIZE,
    leg_height: float = 100.0,
    leg_width: float = 20.0,
    lattice_type: str = "hexagonal",
    joint_width: float = None,
    finger_w: float = None,
    finger_spacing: float = 0.0,
    support_spacing: float = 0.0,
    support_width: float = None,
    joint_depth: float = None,
    joint_style: str = "step",
) -> list:
    """Create all interlocking shelf pieces plus four individual corner legs.

    The shelf panel has a **blind corner socket** at each corner: a square
    hole that goes ``peg_depth = height × 0.6`` deep from the bottom face,
    leaving solid material above so the hole is enclosed on all sides.  Each
    leg is a square prism whose top ``peg_depth`` portion is a tenon that
    plugs into the socket; the leg body hangs below the shelf.

    Assembly layout (Z axis, shelf at z = 0 … height)::

        z = height          ────────── shelf top face
                            │ shelf │
        z = peg_depth       ────╔══╗── top of blind socket (enclosed, supported)
                            │   ║  ║  ← blind hole receives the peg
        z = 0               ────╚══╝── shelf bottom face / leg shoulder
                                │  │  ← peg (top of leg, inside shelf)
        z = -leg_height     ────┴──┘── bottom of leg

    Parameters
    ----------
    width, length, height : overall shelf panel dimensions (mm)
    perim_width           : solid **outer** perimeter width (mm).  Controls the
                            four frame strips at the panel edges.
    hex_size              : cell side length (mm).  Named ``hex_size`` for
                            backward compatibility; applies to any tiling.
    wall_thickness        : minimum wall between cells (mm).
                            Defaults to ``max(1.2, hex_size * 0.15)``.
    max_piece_size        : maximum printable piece size (mm)
    leg_height            : height of the support column below the shelf (mm)
    leg_width             : side length of the square leg / peg cross-section (mm).
                            Must be less than ``perim_width`` so that the socket
                            fits entirely within the solid perimeter band.
    lattice_type          : one of the keys in :data:`LATTICE_TYPES`
                            (default ``"hexagonal"``).
    joint_width           : **bridge** width (mm) — the solid-line width of the
                            joint zone.  Controls bridge-band half-width at cut
                            lines.  Defaults to *perim_width*.
    finger_w              : **tab / finger width** (mm) — the width of each
                            individual finger tab along the cut face.
                            Independent of *joint_width*; defaults to
                            *joint_width* when ``None``.
    finger_spacing        : gap between consecutive fingers (mm).  ``0``
                            (default) places fingers contiguously (full face).
                            When > 0, N centred fingers are placed with
                            *finger_spacing* flat gaps between them.
    support_spacing       : spacing between interior support bars (mm).
                            ``0`` (default) disables support bars.
    support_width         : full width of each interior support bar (mm).
                            Defaults to *joint_width*.
    joint_depth           : how far each finger tab penetrates into the adjacent
                            piece (mm).  ``None`` → ``joint_width / 3``.
    joint_style           : ``'step'`` (default) — alternating stepped shelf
                            joints.  ``'taper'`` — legacy tapered box joints.

    Returns
    -------
    list of (name: str, shape: Part.Shape, placement: App.Vector)
        Shelf pieces are named ``Piece_X_Y`` with identity placement;
        legs are named ``Leg_0_BottomLeft`` … ``Leg_3_TopRight`` with a
        placement vector that positions each leg flush with the nearest shelf
        corner (body below the shelf, peg inside the blind socket).
        Callers should apply ``obj.Placement = App.Placement(placement,
        App.Rotation())`` when adding objects to the document.
    """
    _require_freecad()
    import FreeCAD as App
    import Part

    if wall_thickness is None:
        wall_thickness = max(1.2, hex_size * 0.15)

    # Depth of the blind socket (tenon engagement depth).
    # 60 % of shelf height gives a strong grip while leaving 40 % solid above.
    peg_depth = height * 0.6

    x_cuts   = compute_cuts(width,  max_piece_size)
    y_cuts   = compute_cuts(length, max_piece_size)
    x_bounds = [0.0] + x_cuts + [width]
    y_bounds = [0.0] + y_cuts + [length]

    # ------------------------------------------------------------------
    # Flush leg placements and derived hole centres.
    # Each leg's outer corner aligns with the nearest shelf corner; the
    # blind socket centre is the peg centre = leg BL + leg_width / 2.
    # ------------------------------------------------------------------
    placements  = leg_flush_placements(width, length, leg_height, leg_width)
    corner_ctrs = [
        (px + leg_width * 0.5, py + leg_width * 0.5)
        for px, py, _pz in placements
    ]

    # Leg exclusion zones: the full square footprint of each leg.
    # Hex cells whose bounding circle overlaps a zone are suppressed so
    # that the solid leg-corner material is never interrupted by a hex hole.
    leg_zones = [
        (px, py, px + leg_width, py + leg_width)
        for px, py, _pz in placements
    ]

    hole_size = leg_width + FIT_CLEARANCE
    hole_half = hole_size * 0.5

    # Each cutter removes material from z=0 up to z=peg_depth (blind hole)
    hole_cutters = []
    for cx, cy in corner_ctrs:
        hole_cutters.append(
            Part.makeBox(
                hole_size, hole_size, peg_depth,
                App.Vector(cx - hole_half, cy - hole_half, 0.0),
            )
        )

    # Cylindrical through-hole cutters: full shelf height, centred on each
    # leg's round through-pin.  Slightly wider than the pin for a clearance fit.
    pin_radius      = leg_width * PIN_RADIUS_RATIO
    pin_hole_radius = pin_radius + FIT_CLEARANCE * 0.5
    pin_hole_cutters = []
    for cx, cy in corner_ctrs:
        pin_hole_cutters.append(
            Part.makeCylinder(
                pin_hole_radius,
                height,
                App.Vector(cx, cy, 0.0),
                App.Vector(0.0, 0.0, 1.0),
            )
        )

    # ------------------------------------------------------------------
    # Build shelf pieces and cut blind sockets where they overlap.
    # Shelf pieces carry an identity placement (origin unchanged).
    # ------------------------------------------------------------------
    results = []
    for ix, (x0, x1) in enumerate(zip(x_bounds[:-1], x_bounds[1:])):
        for iy, (y0, y1) in enumerate(zip(y_bounds[:-1], y_bounds[1:])):
            shape = make_piece(
                ix, iy,
                x0, x1, y0, y1,
                width, length,
                height, perim_width, hex_size,
                wall_thickness,
                x_cuts, y_cuts,
                leg_zones=leg_zones,
                lattice_type=lattice_type,
                joint_w=joint_width,
                finger_w=finger_w,
                finger_spacing=finger_spacing,
                support_spacing=support_spacing,
                support_width=support_width,
                joint_depth=joint_depth,
                joint_style=joint_style,
            )

            # Cut blind sockets and round through-holes that intersect this piece
            for cutter, (cx, cy) in zip(hole_cutters, corner_ctrs):
                h_x0 = cx - hole_half
                h_x1 = cx + hole_half
                h_y0 = cy - hole_half
                h_y1 = cy + hole_half
                if h_x1 > x0 and h_x0 < x1 and h_y1 > y0 and h_y0 < y1:
                    shape = shape.cut(cutter)

            for pin_cutter, (cx, cy) in zip(pin_hole_cutters, corner_ctrs):
                if (cx + pin_hole_radius > x0 and cx - pin_hole_radius < x1
                        and cy + pin_hole_radius > y0 and cy - pin_hole_radius < y1):
                    shape = shape.cut(pin_cutter)

            results.append((f"Piece_{ix}_{iy}", shape, App.Vector(0.0, 0.0, 0.0)))

    # ------------------------------------------------------------------
    # Build legs at the local origin; placement applied by the caller.
    #
    # Leg geometry (print orientation, base at z = 0):
    #   body column     z = 0 … leg_height
    #   square tenon    z = leg_height … leg_height + peg_depth
    #   round through-pin z = leg_height … leg_height + height (flush with shelf top)
    #
    # Placement vector shifts z = 0 of the leg to z = -leg_height in world
    # space (shoulder sits at shelf bottom face), so the tenon protrudes into
    # the blind socket and the round pin rises through the full shelf height.
    # ------------------------------------------------------------------
    corner_labels = ["BottomLeft", "BottomRight", "TopLeft", "TopRight"]
    for i, (label, (px, py, pz)) in enumerate(zip(corner_labels, placements)):
        results.append((
            f"Leg_{i}_{label}",
            make_leg(leg_width, leg_height, peg_depth, shelf_height=height),
            App.Vector(px, py, pz),
        ))

    return results


# ---------------------------------------------------------------------------
# Box geometry helpers and top-level entry point
# ---------------------------------------------------------------------------

def _wall_bottom_slots(
    x0: float,
    x1: float,
    bottom_thickness: float,
    tab_w: float,
    tab_d: float,
    bottom_this_side: str,
    finger_spacing: float = 0.0,
) -> list:
    """Return slot shapes to be **cut** from a box wall panel's inner face.

    The slots are in the wall's **printed-flat** coordinate system::

        X  = x0 .. x1             (wall piece X bounds)
        Y  = 0  .. bottom_thickness   (only the joint zone at the bottom edge)
        Z  = 0  .. tab_d + FIT_CLEARANCE  (from the inner face, print_Z = 0)

    When the wall panel is assembled (rotated 90° into a vertical position)
    these slots receive the bottom panel's step-joint edge tabs, locking the
    wall against vertical (Z) movement.

    Parameters
    ----------
    x0, x1            : X bounds of this wall piece (global frame)
    bottom_thickness   : thickness of the bottom panel = step half-height (mm)
    tab_w              : joint tab width (mm)
    tab_d              : joint tab depth / penetration (mm)
    bottom_this_side   : the ``this_side`` value used by ``step_joint`` on
                         the bottom panel for this edge.  Must be one of
                         ``'top'``, ``'bottom'``, ``'left'``, ``'right'``.
    finger_spacing     : gap between consecutive tabs (mm); ``0`` = contiguous.
    """
    import Part
    import FreeCAD as App

    fit = FIT_CLEARANCE
    slt_depth = tab_d + fit

    # Build finger start positions consistent with what step_joint uses for
    # the bottom panel's matching edge (face_start=x0, face_end=x1).
    face_len = x1 - x0
    if finger_spacing > 0.0:
        period = tab_w + finger_spacing
        n_fingers = max(1, int((face_len + finger_spacing) / period))
        total_span = n_fingers * tab_w + (n_fingers - 1) * finger_spacing
        margin = max(0.0, (face_len - total_span) * 0.5)
        finger_starts = [x0 + margin + i * period for i in range(n_fingers)]
    else:
        n_cont = max(1, int(face_len / tab_w) + 1)
        finger_starts = [x0 + i * tab_w for i in range(n_cont)]

    slots = []
    for finger_idx, pos in enumerate(finger_starts):
        seg_s = pos
        seg_e = min(pos + tab_w, x1)
        seg_l = seg_e - seg_s
        if seg_l < tab_w * MIN_SEG_RATIO:
            continue

        # Slot face extent in X (minus assembly clearance, same as step_joint)
        x_s = seg_s + fit * 0.5
        x_l = seg_l - fit
        if x_l <= _GEOM_EPS:
            continue

        # The slot must receive the bottom panel tab at these Z extents.
        # _step_joint_z_extents gives (tab_z0, tab_z1, ...) for the bottom
        # panel's this_side — our slot must span that same Z range (+fit).
        tab_z0, tab_z1, _, _ = _step_joint_z_extents(
            finger_idx, bottom_thickness, bottom_this_side
        )
        # In the wall's print-flat coords: print_Y = bottom-panel assembled Z
        slt_y0 = tab_z0
        slt_y1 = tab_z1 + fit

        if slt_y1 - slt_y0 > _GEOM_EPS and slt_depth > _GEOM_EPS:
            # Slot at X=[x_s..x_s+x_l], Y=[slt_y0..slt_y1], Z=[0..slt_depth]
            # (Z=0 is the inner face, print-flat orientation)
            slots.append(Part.makeBox(
                x_l, slt_y1 - slt_y0, slt_depth,
                App.Vector(x_s, slt_y0, 0.0)
            ))

    return slots


def _make_box_wall_piece(
    ix: int,
    x0: float, x1: float,
    total_w: float,
    wall_printed_h: float,
    bottom_thickness: float,
    thickness: float,
    perim_w: float,
    hex_size: float,
    wall_t: float,
    x_cuts: list,
    bottom_this_side: str,
    lattice_type: str = "hexagonal",
    joint_w: float = None,
    finger_spacing: float = 0.0,
    support_spacing: float = 0.0,
    support_width: float = None,
    joint_depth: float = None,
    joint_style: str = "step",
) -> object:  # Part.Shape
    """Build one piece of a box wall panel.

    The piece is in **print-flat orientation**::

        X  = x0 .. x1              (wall width, horizontal split position)
        Y  = 0  .. wall_printed_h  (= bottom_thickness + box_height)
        Z  = 0  .. thickness       (= panel thickness / wall depth in assembly)

    The bottom ``bottom_thickness`` mm (Y = 0 .. bottom_thickness) is kept
    solid (no lattice holes) so the step-joint slots cut into the inner face
    (Z = 0) have clean geometry.

    Horizontal cuts (X direction) produce the same interlocking step joints as
    flat panels.  There are no vertical (Y direction) cuts.
    """
    if joint_w is None:
        joint_w = perim_w
    tab_d = (joint_depth if (joint_depth is not None and joint_depth > 0.0)
             else joint_w * 0.5)

    # The joint zone (Y=0..bottom_thickness) is kept solid via a leg_zone so
    # that the slot cuts always have material to work with.
    joint_zone = [(0.0, 0.0, total_w, bottom_thickness)]

    # Build the wall piece using make_piece (flat lattice panel, no Y splits).
    shape = make_piece(
        ix, 0,
        x0, x1, 0.0, wall_printed_h,
        total_w, wall_printed_h,
        thickness, perim_w, hex_size,
        wall_t,
        x_cuts, [],          # no y_cuts
        leg_zones=joint_zone,
        lattice_type=lattice_type,
        joint_w=joint_w,
        finger_spacing=finger_spacing,
        support_spacing=support_spacing,
        support_width=support_width,
        joint_depth=joint_depth,
        joint_style=joint_style,
    )

    # Cut bottom-edge slots from the inner face (Z=0) at alternating Y levels.
    slots = _wall_bottom_slots(
        x0, x1,
        bottom_thickness,
        joint_w, tab_d,
        bottom_this_side,
        finger_spacing,
    )
    if slots:
        shape = _cut_shapes(shape, slots)

    return shape


def _add_bottom_edge_tabs(
    shape,
    x0: float, x1: float,
    y0: float, y1: float,
    thickness: float,
    tab_w: float,
    tab_d: float,
    this_side: str,
    finger_spacing: float = 0.0,
) -> object:
    """Fuse step-joint tabs onto a bottom panel piece at one outer edge.

    Used by :func:`create_box` to add wall-mating tabs on each exposed outer
    face of the bottom panel.  Only the **tabs** (protruding shapes) are
    fused; the complementary slots are omitted — wall panels carry only the
    receiving slots (one-sided joint design).

    The caller is responsible for choosing the correct *this_side*:

    * ``'top'``    → front edge (Y = 0):  axis='y', cut_pos=0,  face=x0..x1
    * ``'bottom'`` → back edge  (Y = L):  axis='y', cut_pos=y1, face=x0..x1
    * ``'right'``  → left edge  (X = 0):  axis='x', cut_pos=0,  face=y0..y1
    * ``'left'``   → right edge (X = W):  axis='x', cut_pos=x1, face=y0..y1

    Parameters
    ----------
    shape          : existing Part.Shape of the bottom piece
    x0, x1        : X bounds of this bottom piece
    y0, y1        : Y bounds of this bottom piece (face range for left/right)
    thickness      : bottom panel Z thickness (= step joint height)
    tab_w          : joint tab width (mm)
    tab_d          : joint tab penetration depth (mm)
    this_side      : 'top', 'bottom', 'right', or 'left'
    finger_spacing : gap between consecutive tabs (mm); 0 = contiguous
    """
    # Map this_side → (axis, cut_pos, face_start, face_end)
    _edge_params = {
        'top':    ('y', 0.0, x0,  x1),
        'bottom': ('y', y1,  x0,  x1),
        'right':  ('x', 0.0, y0,  y1),
        'left':   ('x', x1,  y0,  y1),
    }
    axis, cut_pos, face_s, face_e = _edge_params[this_side]
    tabs, _ = step_joint(axis, cut_pos, face_s, face_e,
                         thickness, tab_w, tab_d, this_side,
                         finger_spacing=finger_spacing)
    if tabs:
        shape = _fuse_shapes([shape] + tabs)
    return shape


def create_box(
    width: float,
    length: float,
    box_height: float,
    height: float,
    perim_width: float,
    hex_size: float,
    wall_thickness: float = None,
    max_piece_size: float = MAX_PIECE_SIZE,
    lattice_type: str = "hexagonal",
    joint_width: float = None,
    finger_spacing: float = 0.0,
    support_spacing: float = 0.0,
    support_width: float = None,
    joint_depth: float = None,
    joint_style: str = "step",
) -> list:
    """Create all interlocking pieces for an open-top lattice box.

    The box has five solid faces: a flat **bottom panel** and four **wall
    panels** (front, back, left, right).  All pieces are designed to be
    **printed flat** (large face on the print bed) with no support material.

    Assembly
    --------
    Each wall slides **horizontally** (parallel to the bottom panel) into its
    final position, engaging with step-joint tabs on the bottom panel's outer
    edges.  The alternating stepped-shelf joint pattern locks every wall
    against vertical movement once assembled, so the bottom panel is both
    supported by and supports the walls — enabling the box to be hung upside-
    down without the bottom falling out.

    Piece anatomy
    ~~~~~~~~~~~~~
    * **Bottom** (``Bottom_IX_IY``): ``width × length × height`` flat panel.
      Step-joint tabs protrude outward from all four edges to receive the
      wall panels.  May be split into multiple pieces when larger than
      *max_piece_size*.

    * **Front / Back walls** (``FrontWall_I`` / ``BackWall_I``):
      ``width × (height + box_height) × height`` flat panels.  The lower
      ``height`` mm (in print-Y) is the joint zone with step-joint slots on
      the inner face (print-Z = 0).  May be split horizontally.

    * **Left / Right walls** (``LeftWall_I`` / ``RightWall_I``):
      ``(length - 2 × height) × (height + box_height) × height`` flat panels.
      Shorter than front/back so they fit between them during assembly.

    Assembly order (suggested)::

        1. Place bottom panel.
        2. Slide front wall inward (+Y) until its inner face is flush with
           the bottom panel's front edge.
        3. Slide back wall inward (−Y).
        4. Slide left wall inward (+X) — fits between front and back.
        5. Slide right wall inward (−X).

    Splitting long walls
    ~~~~~~~~~~~~~~~~~~~~
    Walls wider than *max_piece_size* are sliced at even intervals.  Each
    split introduces a horizontal step joint (same as the bottom panel's
    cut joints) that locks the sub-pieces against vertical movement.  The
    horizontal split joints are perpendicular to the wall-bottom joint and
    do not obstruct assembly.

    Parameters
    ----------
    width, length : outer floor dimensions of the box (mm)
    box_height    : interior wall height above the bottom panel (mm)
    height        : panel material thickness (mm).  Used as the Z dimension
                    of every printed piece.
    perim_width   : solid outer perimeter width (mm).  Controls the lattice-
                    free border on every panel and the bridge-band width at
                    cut lines.
    hex_size      : cell side length (mm)
    wall_thickness: minimum cell-wall thickness (mm).
                    Defaults to ``max(1.2, hex_size * 0.15)``.
    max_piece_size: maximum printable piece length / width (mm).
    lattice_type  : one of the keys in :data:`LATTICE_TYPES`
                    (default ``"hexagonal"``).
    joint_width   : joint tab width (mm).  Defaults to *perim_width*.
    finger_spacing: gap between consecutive joint tabs (mm); 0 = contiguous.
    support_spacing: spacing between interior support bars (mm); 0 = none.
    support_width : support bar width (mm); defaults to *joint_width*.
    joint_depth   : tab penetration depth (mm); ``None`` → ``joint_width / 2``.
    joint_style   : ``'step'`` (default) or ``'taper'``.

    Returns
    -------
    list of (name: str, shape: Part.Shape, placement: App.Placement)
        Pieces in **assembled orientation**.  The bottom panel lies flat
        at Z = 0 … T.  Each wall is placed vertically in its correct world
        position so the assembled box is visible directly in FreeCAD.

        Assembly placement summary::

            Bottom_*   : identity  (X = 0…W, Y = 0…L, Z = 0…T)
            FrontWall_*: outer face Y = −T,  inner face Y = 0
            BackWall_* : inner face Y = L,   outer face Y = L+T
            LeftWall_* : outer face X = −T,  inner face X = 0
            RightWall_*: inner face X = W,   outer face X = W+T

        The slicer is responsible for laying each piece flat for printing.
        Names: ``Bottom_IX_IY``, ``FrontWall_I``, ``BackWall_I``,
        ``LeftWall_I``, ``RightWall_I``.
    """
    _require_freecad()
    import FreeCAD as App

    if wall_thickness is None:
        wall_thickness = max(1.2, hex_size * 0.15)

    if joint_width is None:
        joint_width = perim_width
    tab_d = (joint_depth if (joint_depth is not None and joint_depth > 0.0)
             else joint_width * 0.5)

    T = height          # panel / wall thickness
    W = width           # outer box width
    L = length          # outer box length

    # Pre-compute assembly placements for each wall orientation.
    #
    # FreeCAD Placement: world_pos = Rotation * local_pos + Base
    #
    # Front wall — 90° around X-axis, no translation.
    #   R_x90: (x,y,z) → (x, −z, y)
    #   Inner face (local Z=0) → world Y=0; outer face → world Y=−T.
    _rot_x90 = App.Rotation(App.Vector(1, 0, 0), 90)
    _place_front = App.Placement(App.Vector(0.0, 0.0,   0.0), _rot_x90)
    _place_back  = App.Placement(App.Vector(0.0, L + T, 0.0), _rot_x90)

    # Right wall — 120° around (1,1,1): (x,y,z) → (z, x, y).
    #   Inner face (local Z=0) → world X=W; outer face → world X=W+T.
    _rot_r = App.Rotation(App.Vector(1,  1,  1), 120)
    _place_right = App.Placement(App.Vector(W, T, 0.0), _rot_r)

    # Left wall — 120° around (1,−1,−1): (x,y,z) → (−z, −x, y).
    #   Inner face (local Z=0) → world X=0; outer face → world X=−T.
    #   Span direction (local X) is reversed: piece X=0 lands at world Y=L−T.
    _rot_l = App.Rotation(App.Vector(1, -1, -1), 120)
    _place_left  = App.Placement(App.Vector(-T, T, 0.0), _rot_l)

    # -----------------------------------------------------------------------
    # 1. Bottom panel pieces (same as create_all_pieces, plus edge tabs)
    # -----------------------------------------------------------------------
    x_cuts_b = compute_cuts(W, max_piece_size)
    y_cuts_b = compute_cuts(L, max_piece_size)
    x_bounds_b = [0.0] + x_cuts_b + [W]
    y_bounds_b = [0.0] + y_cuts_b + [L]

    _id_placement = App.Placement()   # identity — bottom panel stays flat

    results = []

    for ix, (bx0, bx1) in enumerate(zip(x_bounds_b[:-1], x_bounds_b[1:])):
        for iy, (by0, by1) in enumerate(zip(y_bounds_b[:-1], y_bounds_b[1:])):
            shape = make_piece(
                ix, iy,
                bx0, bx1, by0, by1,
                W, L,
                T, perim_width, hex_size,
                wall_thickness,
                x_cuts_b, y_cuts_b,
                lattice_type=lattice_type,
                joint_w=joint_width,
                finger_spacing=finger_spacing,
                support_spacing=support_spacing,
                support_width=support_width,
                joint_depth=joint_depth,
                joint_style=joint_style,
            )

            # Add step-joint tabs on exposed outer edges so walls can lock in.
            # Front edge (y = 0): bottom panel is 'top' of that cut.
            if by0 < _GEOM_EPS:
                shape = _add_bottom_edge_tabs(
                    shape, bx0, bx1, by0, by1,
                    T, joint_width, tab_d, 'top', finger_spacing,
                )
            # Back edge (y = L): bottom panel is 'bottom' of that cut.
            if by1 > L - _GEOM_EPS:
                shape = _add_bottom_edge_tabs(
                    shape, bx0, bx1, by0, by1,
                    T, joint_width, tab_d, 'bottom', finger_spacing,
                )
            # Left edge (x = 0): bottom panel is 'right' of that cut.
            # Tabs only in the region between front/back walls (Y = T .. L-T).
            if bx0 < _GEOM_EPS:
                eff_y0 = max(by0, T)
                eff_y1 = min(by1, L - T)
                if eff_y1 > eff_y0 + _GEOM_EPS:
                    shape = _add_bottom_edge_tabs(
                        shape, bx0, bx1, eff_y0, eff_y1,
                        T, joint_width, tab_d, 'right', finger_spacing,
                    )
            # Right edge (x = W): bottom panel is 'left' of that cut.
            if bx1 > W - _GEOM_EPS:
                eff_y0 = max(by0, T)
                eff_y1 = min(by1, L - T)
                if eff_y1 > eff_y0 + _GEOM_EPS:
                    shape = _add_bottom_edge_tabs(
                        shape, bx0, bx1, eff_y0, eff_y1,
                        T, joint_width, tab_d, 'left', finger_spacing,
                    )

            results.append((f"Bottom_{ix}_{iy}", shape, _id_placement))

    # -----------------------------------------------------------------------
    # 2. Wall panels — built flat, placed in assembled orientation
    # -----------------------------------------------------------------------
    # Printed height of every wall = T (joint zone) + box_height (lattice zone)
    wall_h = T + box_height

    # Front wall: width = W, assembly direction +Y (bottom panel 'top' edge)
    fw_x_cuts = compute_cuts(W, max_piece_size)
    fw_x_bounds = [0.0] + fw_x_cuts + [W]
    for i, (wx0, wx1) in enumerate(zip(fw_x_bounds[:-1], fw_x_bounds[1:])):
        shape = _make_box_wall_piece(
            i, wx0, wx1,
            total_w=W,
            wall_printed_h=wall_h,
            bottom_thickness=T,
            thickness=T,
            perim_w=perim_width,
            hex_size=hex_size,
            wall_t=wall_thickness,
            x_cuts=fw_x_cuts,
            bottom_this_side='top',
            lattice_type=lattice_type,
            joint_w=joint_width,
            finger_spacing=finger_spacing,
            support_spacing=support_spacing,
            support_width=support_width,
            joint_depth=joint_depth,
            joint_style=joint_style,
        )
        results.append((f"FrontWall_{i}", shape, _place_front))

    # Back wall: same width = W, assembly direction −Y (bottom panel 'bottom')
    for i, (wx0, wx1) in enumerate(zip(fw_x_bounds[:-1], fw_x_bounds[1:])):
        shape = _make_box_wall_piece(
            i, wx0, wx1,
            total_w=W,
            wall_printed_h=wall_h,
            bottom_thickness=T,
            thickness=T,
            perim_w=perim_width,
            hex_size=hex_size,
            wall_t=wall_thickness,
            x_cuts=fw_x_cuts,
            bottom_this_side='bottom',
            lattice_type=lattice_type,
            joint_w=joint_width,
            finger_spacing=finger_spacing,
            support_spacing=support_spacing,
            support_width=support_width,
            joint_depth=joint_depth,
            joint_style=joint_style,
        )
        results.append((f"BackWall_{i}", shape, _place_back))

    # Left / Right walls: width = L - 2*T (fits between front/back walls).
    side_w = max(L - 2.0 * T, _GEOM_EPS)
    sw_x_cuts = compute_cuts(side_w, max_piece_size)
    sw_x_bounds = [0.0] + sw_x_cuts + [side_w]

    for i, (wx0, wx1) in enumerate(zip(sw_x_bounds[:-1], sw_x_bounds[1:])):
        # Left wall (bottom panel 'right' edge)
        shape = _make_box_wall_piece(
            i, wx0, wx1,
            total_w=side_w,
            wall_printed_h=wall_h,
            bottom_thickness=T,
            thickness=T,
            perim_w=perim_width,
            hex_size=hex_size,
            wall_t=wall_thickness,
            x_cuts=sw_x_cuts,
            bottom_this_side='right',
            lattice_type=lattice_type,
            joint_w=joint_width,
            finger_spacing=finger_spacing,
            support_spacing=support_spacing,
            support_width=support_width,
            joint_depth=joint_depth,
            joint_style=joint_style,
        )
        results.append((f"LeftWall_{i}", shape, _place_left))

    for i, (wx0, wx1) in enumerate(zip(sw_x_bounds[:-1], sw_x_bounds[1:])):
        # Right wall (bottom panel 'left' edge)
        shape = _make_box_wall_piece(
            i, wx0, wx1,
            total_w=side_w,
            wall_printed_h=wall_h,
            bottom_thickness=T,
            thickness=T,
            perim_w=perim_width,
            hex_size=hex_size,
            wall_t=wall_thickness,
            x_cuts=sw_x_cuts,
            bottom_this_side='left',
            lattice_type=lattice_type,
            joint_w=joint_width,
            finger_spacing=finger_spacing,
            support_spacing=support_spacing,
            support_width=support_width,
            joint_depth=joint_depth,
            joint_style=joint_style,
        )
        results.append((f"RightWall_{i}", shape, _place_right))

    return results

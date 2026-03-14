# Euclidean Uniform Tiling — Implementation Plan

This document records the architecture and the planned work for adding all 11
euclidean uniform tilings to the HexLatticeMaker FreeCAD plugin.

---

## Architecture Overview

Every tiling is a subclass of `TilingProvider` (defined in
`freecad/HexLatticeMaker/hex_lattice_core.py`).

```python
class TilingProvider:
    display_name: str = ""

    def cell_circumradius(self, cell_size: float) -> float:
        """Circumradius of a single cell polygon for bounding-circle checks."""
        ...

    def get_cells(
        self,
        gx0: float, gx1: float,
        gy0: float, gy1: float,
        cell_size: float,
        wall_t: float,
    ) -> list:  # [(cx, cy, n_sides, rotation_deg), ...]
        ...
```

**Registration steps for a new tiling**:

1. Subclass `TilingProvider`.
2. Set `display_name` to a human-readable string (shown in the dropdown).
3. Implement `cell_circumradius(cell_size)` — use the circumradius of the
   *largest* polygon in the tiling so that no cell is incorrectly pruned.
4. Implement `get_cells()` using an oblique lattice approach (see below).
5. Add an instance to `_TILING_PROVIDERS` with the chosen key.
6. Add the same `key → display_name` entry to `LATTICE_TYPES`.

The `make_polygon_prism(cx, cy, n_sides, rotation_deg, side, height)` helper
already handles arbitrary regular n-gons, so only the cell layout logic
(`get_cells`) needs to be implemented for new tilings.

---

## Oblique Lattice Approach

Each tiling is described by:

* **Lattice vectors** `a1` and `a2` (in mm), derived from
  `step = cell_size + wall_t`.
* **Basis cells** — a list of `(offset_x, offset_y, n_sides, rotation_deg)`
  relative to each lattice point.

The iteration pattern is:

```python
for row in range(-extra, n_rows + extra):
    for col in range(-extra, n_cols + extra):
        lx = gx0 + col * a1x + row * a2x
        ly = gy0 + col * a1y + row * a2y
        for (ox, oy, n, rot) in basis:
            cx, cy = lx + ox, ly + oy
            if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                cells.append((cx, cy, n, rot))
```

The extra margin (typically 2–4) ensures no cells near the boundary are missed
due to the oblique coordinate system.

---

## Implemented Tilings (Phase 1 + Phase 2)

| Key | Display Name | Schläfli | Cell types |
|-----|-------------|----------|-----------|
| `hexagonal` | Hexagonal (6.6.6) | `{6}` | Regular hexagon |
| `square` | Square (4.4.4.4) | `{4}` | Regular square |
| `triangular` | Triangular (3.3.3.3.3.3) | `{3}` | Equilateral triangle (up + down) |
| `trihexagonal` | Trihexagonal (3.6.3.6) | `r{6}` | Equilateral triangle + regular hexagon |
| `truncated_square` | Truncated Square (4.8.8) | `t{4}` | Regular square + regular octagon |
| `snub_square` | Snub Square (3.3.4.3.4) | `s{4}` | Regular square + equilateral triangle |
| `elongated_triangular` | Elongated Triangular (3.3.3.4.4) | — | Regular square + equilateral triangle |
| `truncated_hexagonal` | Truncated Hexagonal (3.12.12) | `t{6}` | Equilateral triangle + regular 12-gon |
| `small_rhombitrihexagonal` | Small Rhombitrihexagonal (3.4.6.4) | `r{3,6}` | Equilateral triangle + square + regular hexagon |
| `great_rhombitrihexagonal` | Great Rhombitrihexagonal (4.6.12) | `t{3,6}` | Square + regular hexagon + regular 12-gon |

---

## Planned Tilings (Phase 2+)

The following semi-regular tilings have *multiple* polygon types per unit cell.
Each row below outlines the lattice vectors and basis cells needed; sizes are
given as multiples of `step = cell_size + wall_t`.

---

### ~~Trihexagonal (3.6.3.6)~~ — **DONE** (key `trihexagonal`)

Implemented in `TrihexagonalTilingProvider`.  Lattice `a1 = (2·step, 0)`,
`a2 = (step, step·√3)`.  Basis: hexagon at `(0, 0)`, down-triangle at
`(step, step/√3)`, up-triangle at `(2·step, 2·step/√3)`.

---

### ~~Truncated Square (4.8.8)~~ — **DONE** (key `truncated_square`)

Implemented in `TruncatedSquareTilingProvider`.  Rectangular lattice with
`a = step·(2+√2)`.  Unit cell holds 2 octagons (at `(0,0)` and `(a/2,a/2)`)
and 2 squares (at `(a/2,0)` and `(0,a/2)`).  All polygons share the same
edge length; octagons use rotation 22.5°, squares use rotation 45°.

---

### ~~Snub Square (3.3.4.3.4)~~ — **DONE** (key `snub_square`)

Implemented in `SnubSquareTilingProvider`.  Oblique square Bravais lattice
with `a1 = step·((2+√3)/2, 1/2)`, `a2 = step·(-1/2, (2+√3)/2)`.  Six
polygons per cell: S0 at `(0,0)` rot=45°, S1 at `(step·(1+√3)/4,
step·(3+√3)/4)` rot=75°, plus four triangles at rotations 0°/30°/60°/90°.
Row loop starts at `-1 - extra_rows_neg` (symmetric to `extra_cols`) to
cover the bottom-right of wide regions where upward y-drift from `a1y > 0`
would otherwise miss cells.

---

### ~~Elongated Triangular (3.3.3.4.4)~~ — **DONE** (key `elongated_triangular`)

Implemented in `ElongatedTriangularTilingProvider`.  Alternating strips of
squares and equilateral triangles.  Oblique lattice `a1 = (step, 0)`,
`a2 = (−step/2, step·(2+√3)/2)`.  Basis: square at `(step/2, step/2)`,
up-triangle at `(step/2, step·(6+√3)/6)` rot=90°, down-triangle at
`(0, step·(3+√3)/3)` rot=270°.  Column range extended right by
`extra_cols = ⌈n_rows/2⌉ + 2` to compensate for leftward `a2x`-drift.

---

### ~~Truncated Hexagonal (3.12.12)~~ — **DONE** (key `truncated_hexagonal`)

Implemented in `TruncatedHexagonalTilingProvider`.  Equilateral triangles and
regular 12-gons (dodecagons) sharing the same edge length.  Triangular Bravais
lattice with period `a = step·(2+√3)` and vectors `a1 = (a, 0)`,
`a2 = (a/2, a√3/2)`.  Basis: dodecagon at `(0,0)` rot=15°, down-triangle at
`(a/2, a√3/6)` rot=30°, up-triangle at `(a, a√3/3)` rot=90°.  Column range
extended leftward by `extra_cols = ⌈n_rows/2⌉ + 2` to compensate for rightward
`a2x`-drift (identical formula to the trihexagonal provider).  Every triangle
vertex lies exactly on a vertex of a neighbouring dodecagon (verified
analytically).

---

### ~~Small Rhombitrihexagonal (3.4.6.4)~~  — **DONE** (key `small_rhombitrihexagonal`)

Implemented in `SmallRhombitrihexagonalTilingProvider`.

Hexagonal Bravais lattice with primitive vectors `A1 = step·(√3·(1+√3)/2, (1+√3)/2)`,
`A2 = step·(0, 1+√3)` where `a = step·(1+√3)` is the lattice period.

All six edges of every hexagon are shared with squares; triangles fill the corner
gaps between adjacent square pairs at each hex vertex.  Each unit cell holds:

* Hexagon at `(0, 0)`, rot=0° (flat-top)
* Square A at `(a·√3/4, a/4)`, rot=75° — angle 30° from hex centre
* Square B at `(0, a/2)`, rot=135° — angle 90° from hex centre
* Square C at `(−a·√3/4, a/4)`, rot=195° — angle 150° from hex centre
* Triangle A at `(a/√3, 0)`, rot=60° — angle 0° from hex centre
* Triangle B at `(a/(2·√3), a/2)`, rot=0° — angle 60° from hex centre

The positive `A1y = a/2` produces an upward y-drift per column index; the row
range is extended downward by `extra_rows = ⌈n_cols/2⌉ + 2` to compensate.
Polygon ratio: 2 triangles : 3 squares : 1 hexagon per unit cell ✓.

---

### Snub Hexagonal (3.3.3.3.6)  — symbol `s{6}`

Hexagons surrounded by groups of four triangles each; the remaining gap
triangles tile between adjacent hexagons.  **Chiral** — only the right-handed
variant is implemented (the left-handed one would require negating all y-offsets).

#### Derivation

With `step = cell_size + wall_t` and hexagon rotation `α = 0°` (vertex at 0° /
right), a hexagon `H₀` centred at the origin has vertices
`Vₖ = (cos(60k°), sin(60k°)) × step` for `k = 0…5`.

For the right-handed chirality, the nearest hexagon `H₁` can be placed so that
triangles fit edge-to-edge.  Working out the constraint that all shared vertices
lie exactly one `step` apart fixes `H₁` at:

```
H₁ = step × (5/2, √3/2)
```

The lattice vectors follow:

```
A₁ = step × (5/2,   √3/2)      # primary column direction
A₂ = step × ( 1/2, 3√3/2)      # primary row direction
```

**Unit cell area check** (with s = step = 1):

```
|A₁ × A₂| = |5/2 · 3√3/2 − √3/2 · 1/2| = 14√3/4 = 7√3/2
```

Area of 1 hexagon + 8 triangles (each with edge length s = 1):

```
3√3/2  +  8 · √3/4  =  3√3/2 + 2√3  =  7√3/2  ✓
```

So the unit cell holds **1 hexagon and 8 equilateral triangles**.

#### Why 8 triangles?

Each hexagon vertex `Vₖ` is surrounded by 4 triangles (vertex figure `3.3.3.3.6`).
Six vertices × 4 triangles / (average triangle-vertex incidence accounting for
shared vs. unique vertices) = 8 unique triangles per unit cell.  Verification:

```
T = 8H  (from Euler / area argument)
with H = 1 → T = 8  ✓
```

Enumerating all 18 triangle centres adjacent to `H₀` and reducing modulo the
lattice produces exactly **8 equivalence classes** — one representative per unit
cell triangle.

#### Basis cells

Place the hexagon at `(0, 0)` rot=0°.  Place 8 triangles at the following offsets
`(dx, dy)` (in units of `step`) with the given rotation.  There are no
duplicates: no two offsets in this list differ by an integer combination of `A₁`
and `A₂`.

| # | `dx` | `dy` | `rot` | Triangle type |
|---|------|------|-------|---------------|
| 1 | `+step` | `-step·√3/3` | 90° | edge tri at `V₅V₀` |
| 2 | `+step` | `+step·√3/3` | 30° | edge tri at `V₀V₁` |
| 3 | `0`     | `+2·step·√3/3` | 90° | edge tri at `V₁V₂` |
| 4 | `-step` | `+step·√3/3` | 30° | edge tri at `V₂V₃` |
| 5 | `-step` | `-step·√3/3` | 90° | edge tri at `V₃V₄` |
| 6 | `0`     | `-2·step·√3/3` | 30° | edge tri at `V₄V₅` |
| 7 | `-step/2` | `+5·step·√3/6` | 30° | inner gap tri near `V₂` |
| 8 | `+step` | `+2·step·√3/3` | 90° | inner gap tri near `V₁` |

The 6 edge triangles alternate `rot=90°` (△, apex up) and `rot=30°` (▽, apex
down) around the hexagon.  The 2 inner gap triangles fill the space between
consecutive pairs of edge triangles that would otherwise leave a hole.

`√3/3 = 1/√3`, `2√3/3 = 2/√3`, `5√3/6 = 5/(2√3)` — use
`math.sqrt(3.0)` throughout.

#### Drift compensation

`A₁y = step·√3/2 > 0`: every additional column index pushes `ly` upward.
Need to start the row loop at `-extra_rows_bot` to cover cells in the lower-left
that would otherwise be missed:

```
extra_rows_bot = ceil(n_cols / 3) + 2
```

`A₂x = step/2 > 0`: every additional row index pushes `lx` rightward.
Need to start the col loop at `-extra_cols` to cover cells in the left that
would otherwise be missed:

```
extra_cols = ceil(n_rows / 5) + 2
```

#### Loop skeleton

```python
sq3 = math.sqrt(3.0)
A1x, A1y = step * 2.5,        step * sq3 / 2.0
A2x, A2y = step / 2.0,        step * 3.0 * sq3 / 2.0

n_cols = int((gx1 - gx0) / A1x) + 3
n_rows = int((gy1 - gy0) / A2y) + 3

extra_rows_bot = int(math.ceil(n_cols / 3.0)) + 2
extra_cols     = int(math.ceil(n_rows / 5.0)) + 2

basis = [
    # (ox, oy, n_sides, rot_deg)
    ( step,           -step * sq3 / 3.0,  3,  90.0),
    ( step,            step * sq3 / 3.0,  3,  30.0),
    ( 0,           2 * step * sq3 / 3.0,  3,  90.0),
    (-step,            step * sq3 / 3.0,  3,  30.0),
    (-step,           -step * sq3 / 3.0,  3,  90.0),
    ( 0,          -2 * step * sq3 / 3.0,  3,  30.0),
    (-step / 2.0,  5 * step * sq3 / 6.0,  3,  30.0),
    ( step,        2 * step * sq3 / 3.0,  3,  90.0),
]

for row in range(-1 - extra_rows_bot, n_rows + 2):
    for col in range(-1 - extra_cols, n_cols + 2):
        lx = gx0 + col * A1x + row * A2x
        ly = gy0 + col * A1y + row * A2y
        # hexagon
        cx, cy = lx, ly
        if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
            cells.append((cx, cy, 6, 0.0))
        # triangles
        for ox, oy, n, rot in basis:
            cx, cy = lx + ox, ly + oy
            if gx0 <= cx <= gx1 and gy0 <= cy <= gy1:
                cells.append((cx, cy, n, rot))
```

#### `cell_circumradius`

The largest polygon is the hexagon; for a regular hexagon the circumradius equals
the edge length:

```python
def cell_circumradius(self, cell_size: float) -> float:
    return cell_size
```

#### Key

| Property | Value |
|----------|-------|
| Schläfli symbol | `s{6}` |
| Suggested key | `snub_hexagonal` |
| Suggested class name | `SnubHexagonalTilingProvider` |
| Chirality | Right-handed (α = 0°) |
| Polygons per unit cell | 1 hexagon + 8 triangles |
| `cell_circumradius` | `cell_size` |

---

### ~~Great Rhombitrihexagonal (4.6.12)~~ — **DONE** (key `great_rhombitrihexagonal`)

Squares, hexagons, and dodecagons.

* **Lattice**: triangular.
* **Basis**: 1 square + 1 hexagon + 1 dodecagon per unit cell.
* **Circumradius**: use dodecagon circumradius = `cell_size / (2 sin(π/12))`

---

## Testing Checklist for New Tilings

For each new tiling added, the following tests should be written in
`tests/test_geometry.py` inside `TestTilingCells`:

- [ ] Non-empty output for a representative region.
- [ ] All cell centres lie within `[gx0, gx1] × [gy0, gy1]`.
- [ ] No duplicate centres (within floating-point tolerance).
- [ ] Correct `n_sides` for each polygon type in the basis.
- [ ] Empty region returns `[]`.
- [ ] `cell_circumradius` returns the expected value (formula check).
- [ ] (Optional) Near-neighbour distance at `wall_t=0` matches the known
  geometric value for the tiling.

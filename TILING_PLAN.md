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

## Implemented Tilings (Phase 1 + Phase 2 start)

| Key | Display Name | Schläfli | Cell types |
|-----|-------------|----------|-----------|
| `hexagonal` | Hexagonal (6.6.6) | `{6}` | Regular hexagon |
| `square` | Square (4.4.4.4) | `{4}` | Regular square |
| `triangular` | Triangular (3.3.3.3.3.3) | `{3}` | Equilateral triangle (up + down) |
| `trihexagonal` | Trihexagonal (3.6.3.6) | `r{6}` | Equilateral triangle + regular hexagon |

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

### Truncated Square (4.8.8)  — symbol `t{4}`

Squares surrounded by octagons.

* **Lattice**: square, `a1 = (s4 + s8*d, 0)`, `a2 = (0, s4 + s8*d)`,
  where `s4` = square side, `s8` = octagon side, `d = 1 + √2`.
* **Basis** (1 square + 2 octagons per unit cell — exact offsets depend on
  relative sizes; typically both polygon types share a common side length).
* **Circumradius**: use octagon circumradius = `cell_size / (2 sin(π/8))`

---

### Snub Square (3.3.4.3.4)  — symbol `s{4}`

Squares surrounded by groups of triangles.

* **Lattice**: oblique (chiral), derived from `step`.
* **Basis**: 1 square + 4 triangles per unit cell.
* Note: this tiling is *chiral* — left- and right-handed variants exist.
  A practical implementation may choose one chirality (e.g. clockwise).

---

### Elongated Triangular (3.3.3.4.4)  — vertex figure 3.3.3.4.4

Rows of squares alternating with rows of double-triangle strips.

* **Lattice**: rectangular, `a1 = (step, 0)`, `a2 = (0, h_sq + h_tri)`.
* **Basis**: 1 square + 2 triangles per unit cell.

---

### Truncated Hexagonal (3.12.12)  — symbol `t{6}`

Triangles surrounded by dodecagons (12-gons).

* **Lattice**: triangular.
* **Basis**: 1 triangle + 2 dodecagons per unit cell.
* **Circumradius**: use dodecagon circumradius = `cell_size / (2 sin(π/12))`

---

### Small Rhombitrihexagonal (3.4.6.4)  — symbol `r{3,6}`

Triangles, squares, and hexagons.

* **Lattice**: triangular.
* **Basis**: 1 triangle + 3 squares + 1 hexagon per unit cell.

---

### Snub Hexagonal (3.3.3.3.6)  — symbol `s{6}`

Hexagons surrounded by groups of triangles (chiral).

* **Lattice**: oblique (chiral).
* **Basis**: 1 hexagon + 5 triangles per unit cell.
* Note: chiral — same implementation note as snub square.

---

### Great Rhombitrihexagonal (4.6.12)  — symbol `t{3,6}`

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

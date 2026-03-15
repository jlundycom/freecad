# HexLatticeMaker – FreeCAD Plugin

A FreeCAD workbench and macro that creates **parametric flat panels filled with
a hexagonal lattice**, then automatically slices them into **interlocking
finger-jointed pieces ≤ 220 × 220 × 220 mm** so each piece fits on a standard
FDM 3-D printer bed.

---

## Features

| Feature | Detail |
|---------|--------|
| **Hex lattice infill** | Pointy-top regular hexagons (user-specified side length) fill the interior of the panel leaving a solid perimeter. |
| **Solid perimeter** | A user-specified border (in mm) is kept fully solid around all edges. |
| **Auto-slicing** | Panels wider or longer than 220 mm are automatically sliced into pieces along X and Y. |
| **Finger-joint interlocks** | Each cut face has alternating rectangular tabs and slots. Adjacent pieces have the complementary pattern so they lock together. |
| **Cut bridges** | The material within `perim_width / 2` of every cut line is solid (no hex voids), providing a strong base for the finger-joint. |
| **Weight-bearing** | Multiple full-height finger tabs provide excellent shear and tension resistance. For extra strength apply CA glue or use M3 bolts through the bridge area. |
| **FDM-friendly clearance** | Default assembly clearance is 0.15 mm (bilateral), designed for typical FFF/FDM printers. |
| **Multiple tilings** | Choose from 5 euclidean uniform tiling patterns via the dropdown (see below). |

---

## Supported Tilings

The `lattice_type` parameter (workbench dropdown or keyword argument) selects
the infill pattern.  All polygons in a given tiling share the same side length
(`hex_size` in the dialog).

| Key | Display Name | Vertex Figure | Polygon Types |
|-----|-------------|---------------|---------------|
| `hexagonal` | Hexagonal (6.6.6) | 6.6.6 | Regular hexagon |
| `square` | Square (4.4.4.4) | 4.4.4.4 | Square |
| `triangular` | Triangular (3.3.3.3.3.3) | 3.3.3.3.3.3 | Equilateral triangle |
| `trihexagonal` | Trihexagonal (3.6.3.6) | 3.6.3.6 | Triangle + hexagon |
| `truncated_square` | Truncated Square (4.8.8) | 4.8.8 | Square + octagon |

More semi-regular tilings are planned; see `TILING_PLAN.md` for the roadmap.

---

## Installation

### Option A – FreeCAD Addon Manager (recommended)

1. Open FreeCAD ▸ **Tools ▸ Addon Manager**.
2. Search for **HexLatticeMaker** and click **Install**.
3. Restart FreeCAD.

### Option B – Manual installation

```bash
# Clone (or copy) this repo into FreeCAD's user Mod directory
git clone https://github.com/jlundycom/freecad \
    ~/.local/share/FreeCAD/Mod/HexLatticeMaker
```

Restart FreeCAD.  The **HexLatticeMaker** workbench will appear in the
workbench selector.

### Option C – Macro (no installation needed)

Copy `HexLatticeMaker.FCMacro` to your FreeCAD macro directory
(`~/.local/share/FreeCAD/Macro/` on Linux, `%APPDATA%\FreeCAD\Macro\` on
Windows), then run it from **Macro ▸ Macros …**.

---

## Usage

### From the Workbench

1. Switch to the **HexLatticeMaker** workbench.
2. Click the toolbar button (or **Hex Lattice ▸ Create Hex Lattice Part**).
3. Fill in the dialog:

   | Field | Description | Default |
   |-------|-------------|---------|
   | Width (X) | Total X dimension of the flat panel | 300 mm |
   | Length (Y) | Total Y dimension of the flat panel | 300 mm |
   | Height (Z) | Panel thickness | 10 mm |
   | Perimeter width | Solid border around edges *and* the material used for finger-joint bridges | 6 mm |
   | Hexagon size | Side length of each regular hexagonal void cell | 8 mm |

4. Click **OK** and wait.  Each piece appears as a separate `Part::Feature`
   object named `Piece_X_Y` (X = column, Y = row).
5. Select a piece ▸ **File ▸ Export** ▸ choose STL or 3MF format ▸ slice and
   print.

### From the Macro

Run `HexLatticeMaker.FCMacro` from **Macro ▸ Macros …** – the same dialog
appears.

---

## Geometry Details

### Hexagonal grid

```
grid_spacing      = hex_size + wall_thickness
horizontal c-to-c = grid_spacing × √3
vertical   c-to-c = grid_spacing × 1.5
wall_thickness    = max(1.2 mm,  hex_size × 0.15)
```

Hexagons are suppressed within:
- the outer **perimeter band** (`perim_width` from each edge), and
- the **bridge bands** (`perim_width / 2` on each side of every cut line).

### Finger joints

```
tab_width = perim_width
tab_depth = perim_width / 2
clearance = 0.15 mm  (bilateral)
```

At every cut face, tabs and slots alternate in a period of `tab_width`.
`left` / `bottom` pieces carry tabs at *even* finger positions;
`right` / `top` pieces carry tabs at *odd* positions – ensuring adjacent
pieces are always complementary.

### Slicing example

A 500 × 300 × 10 mm panel with `perim_width = 6 mm` and `hex_size = 8 mm`:

```
X cuts:  [220]   → 2 columns  → pieces [0,220] and [220,500]
Y cuts:  []      → 1 row      → 2 pieces total
```

Each piece has finger joints on the shared X = 220 face.  The bridge region
`[217, 223]` (± 3 mm) is kept solid.

---

## File Structure

```
HexLatticeMaker/
├── freecad/
│   └── HexLatticeMaker/
│       ├── __init__.py              Package marker
│       ├── hex_lattice_core.py      Core geometry engine
│       ├── create_part_dialog.py    Qt input dialog
│       ├── init_gui.py              Workbench + command registration
│       └── Resources/
│           └── Icons/
│               └── HexLatticeMaker.svg
├── tests/
│   ├── __init__.py
│   └── test_geometry.py            Pure-Python unit tests (no FreeCAD needed)
├── HexLatticeMaker.FCMacro          Standalone macro
├── InitGui.py                       Top-level FreeCAD entry point
├── package.xml                      FreeCAD Addon Manager metadata
└── README.md
```

---

## Running Tests

The unit tests require only Python 3.8+ and `pytest`; **FreeCAD is not needed**:

```bash
pip install pytest
pytest tests/
```

---

## Tips for Weight-Bearing Assemblies

1. **Increase `perim_width`** (e.g., 8–12 mm) for thicker, stronger finger
   joints.
2. **Apply CA glue** (super-glue) to the joint faces before assembly for a
   permanent, very strong bond.
3. **M3 bolts**: drill or print 3.2 mm through-holes in the bridge area and
   use M3 × 10 mm bolts + hex nuts for a re-assemblable joint.
4. **Print orientation**: print pieces flat (Z = layer direction matches panel
   height).  This maximises layer adhesion at the joint faces.
5. **Material**: PETG or ASA is recommended for structural parts; ABS is
   acceptable; PLA is adequate for light-duty use.

---

## License

LGPL-2.1-or-later – see [LICENSE](LICENSE).

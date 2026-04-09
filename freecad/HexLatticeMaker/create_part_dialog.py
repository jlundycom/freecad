"""
create_part_dialog.py
---------------------
Qt dialog that prompts the user for hex-lattice part dimensions.

Also contains :class:`GridfinityDialog` for the gridfinity box builder.
"""

try:
    from PySide2 import QtWidgets, QtCore
except ImportError:
    from PySide6 import QtWidgets, QtCore

try:
    from .hex_lattice_core import LATTICE_TYPES
except ImportError:
    from hex_lattice_core import LATTICE_TYPES


class HexLatticeDialog(QtWidgets.QDialog):
    """Modal dialog for hex-lattice part creation parameters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Hex Lattice Part")
        self.setMinimumWidth(360)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        self._form = form

        def _spin(lo, hi, default, dec=1, suffix=" mm"):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setValue(default)
            w.setDecimals(dec)
            w.setSuffix(suffix)
            return w

        self.width_spin      = _spin(10.0,  5000.0, 300.0)
        self.length_spin     = _spin(10.0,  5000.0, 300.0)
        self.height_spin     = _spin( 1.0,   220.0,  10.0)
        self.perim_spin      = _spin( 1.0,   100.0,   6.0)
        self.hex_spin        = _spin( 1.0,   100.0,   8.0)
        self.wall_spin       = _spin( 0.5,    10.0,   1.5, dec=2)
        self.max_piece_spin  = _spin(10.0,   220.0, 220.0)

        # Joint / bridge parameters
        # joint_width (UI label: "Bridge width"): solid-line width of the bridge
        #   zone at cut lines.  This is the full width of the solid band that
        #   spans the cut (bridge half-width = joint_width / 2 on each side).
        #   Defaults to perim_width at run-time if 0.
        self.joint_width_spin = _spin(0.0, 100.0, 0.0)
        self.joint_width_spin.setSpecialValueText("= Perimeter width")

        # tab_width (UI label: "Tab/finger width"): independent width of each
        #   individual finger tab along the cut face.  Separate from bridge
        #   width, so e.g. a 10 mm bridge with 20 mm tabs is valid.
        #   Defaults to joint_width at run-time if 0.
        self.tab_width_spin = _spin(0.0, 200.0, 0.0)
        self.tab_width_spin.setSpecialValueText("= Bridge width")

        # finger_spacing: gap between consecutive fingers; 0 = contiguous.
        self.finger_spacing_spin = _spin(0.0, 5000.0, 0.0)
        self.finger_spacing_spin.setSpecialValueText("Contiguous (0 = no gap)")

        # joint_depth: how far each finger penetrates into the adjacent piece.
        #   0 = use the default (= joint_width / 3).
        #   Should be less than joint_width / 2 to leave solid material beyond
        #   the tab tips; values at or above bridge half-width cause fingers to
        #   reach the lattice void area (allowed but not recommended).
        self.joint_depth_spin = _spin(0.0, 100.0, 0.0)
        self.joint_depth_spin.setSpecialValueText("= One-third bridge width")

        # Interior support bars
        self.support_spacing_spin = _spin(0.0, 5000.0, 0.0)
        self.support_spacing_spin.setSpecialValueText("None (0 = disabled)")

        self.support_width_spin = _spin(0.0, 100.0, 0.0)
        self.support_width_spin.setSpecialValueText("= Joint width")

        # Lattice type combobox – populated from the core's LATTICE_TYPES dict
        self.lattice_combo = QtWidgets.QComboBox()
        for key, display_name in LATTICE_TYPES.items():
            self.lattice_combo.addItem(display_name, key)

        form.addRow("Width  (X):",                  self.width_spin)
        form.addRow("Length (Y):",                  self.length_spin)
        form.addRow("Height (Z):",                  self.height_spin)
        form.addRow("Perimeter width:",             self.perim_spin)
        form.addRow("Bridge width\n(0 = same as perimeter):",
                    self.joint_width_spin)
        form.addRow("Tab/finger width\n(0 = same as bridge width):",
                    self.tab_width_spin)
        form.addRow("Finger spacing\n(0 = contiguous, no gap):",
                    self.finger_spacing_spin)
        form.addRow("Joint depth\n(0 = one-third bridge width):",
                    self.joint_depth_spin)
        form.addRow("Support bar spacing\n(0 = none):",
                    self.support_spacing_spin)
        form.addRow("Support bar width\n(0 = same as joint width):",
                    self.support_width_spin)
        form.addRow("Lattice type:",                self.lattice_combo)
        form.addRow("Cell size\n(side length):",    self.hex_spin)
        form.addRow("Wall thickness:",              self.wall_spin)
        form.addRow("Max piece size:",              self.max_piece_spin)

        # Info label (exposed as self._info_label so subclasses can update text)
        self._info_label = QtWidgets.QLabel(
            "<i>Parts wider/longer than <b>Max piece size</b> are automatically\n"
            "sliced into interlocking finger-joint pieces for 3-D printing.\n"
            "<b>Bridge width</b> sets the width (mm) of the solid zone on each "
            "side of every cut line (defaults to Perimeter width when 0). "
            "<b>Tab/finger width</b> sets the width of each individual finger "
            "tab along the cut face — independent of Bridge width (0 = same as "
            "Bridge width). "
            "<b>Finger spacing</b> sets the gap (mm) between consecutive fingers "
            "— areas between fingers are flat. 0 means fingers are contiguous "
            "(no gap, fills the full face). "
            "<b>Joint depth</b> controls how far each finger penetrates into the "
            "adjacent piece: should be less than half of Bridge width to leave "
            "solid backing behind the slot "
            "(0 = one-third of bridge width). "
            "<b>Support bar spacing</b> adds internal solid ribs every N mm in "
            "both X and Y for extra rigidity (0 = no ribs).</i>"
        )
        self._info_label.setWordWrap(True)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        main = QtWidgets.QVBoxLayout()
        main.addLayout(form)
        main.addWidget(self._info_label)
        main.addWidget(buttons)
        self.setLayout(main)

    # ------------------------------------------------------------------
    def get_params(self) -> dict:
        """Return the dialog values as a plain dictionary."""
        joint_w  = self.joint_width_spin.value()
        tab_w    = self.tab_width_spin.value()
        joint_d  = self.joint_depth_spin.value()
        sup_w    = self.support_width_spin.value()
        return {
            "width":            self.width_spin.value(),
            "length":           self.length_spin.value(),
            "height":           self.height_spin.value(),
            "perim_width":      self.perim_spin.value(),
            # joint_width=None tells make_piece() to fall back to perim_width
            "joint_width":      joint_w if joint_w > 0.0 else None,
            # finger_w=None tells make_piece() to fall back to joint_width
            "finger_w":         tab_w if tab_w > 0.0 else None,
            "finger_spacing":   self.finger_spacing_spin.value(),
            # joint_depth=None tells make_piece() to fall back to joint_w/3
            "joint_depth":      joint_d if joint_d > 0.0 else None,
            "support_spacing":  self.support_spacing_spin.value(),
            # support_width=None tells make_piece() to fall back to joint_w
            "support_width":    sup_w if sup_w > 0.0 else None,
            "hex_size":         self.hex_spin.value(),
            "wall_thickness":   self.wall_spin.value(),
            "max_piece_size":   self.max_piece_spin.value(),
            "lattice_type":     self.lattice_combo.currentData(),
        }


class ShelfWithLegsDialog(HexLatticeDialog):
    """Modal dialog for shelf-with-legs creation parameters.

    Extends :class:`HexLatticeDialog` with additional fields for:

    * **Leg height** – total printed height of each corner leg.
    * **Leg width** – side length of the square leg cross-section.
      Must be smaller than the perimeter width so the corner holes fit
      entirely within the solid perimeter band.
    * **Screw joints** – optional flat lugs with through-holes added to
      all outer faces of the shelf pieces and legs, enabling a screw (or
      heat-set insert + screw) connection at the shelf/leg interface.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Shelf with Legs")

        def _spin(lo, hi, default, dec=1, suffix=" mm"):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setValue(default)
            w.setDecimals(dec)
            w.setSuffix(suffix)
            return w

        self.leg_height_spin = _spin(10.0, 2000.0, 100.0)
        self.leg_width_spin  = _spin( 5.0,   100.0,  20.0)

        self._form.addRow("Leg height:",                 self.leg_height_spin)
        self._form.addRow("Leg width\n(cross-section):", self.leg_width_spin)

        # ── Screw joints ───────────────────────────────────────────────
        self.screw_joint_check = QtWidgets.QCheckBox("Add screw-joint lugs")
        self.screw_joint_check.setChecked(False)

        self.screw_joint_thickness_spin = _spin(1.0, 20.0, 3.0, dec=2)
        self.screw_joint_spacing_spin   = _spin(0.0, 5000.0, 0.0)
        self.screw_joint_spacing_spin.setSpecialValueText("Single lug at midpoint")
        self.screw_hole_diameter_spin   = _spin(1.0, 20.0, 3.5, dec=2)

        # Disable spinners until checkbox is ticked
        for w in (self.screw_joint_thickness_spin,
                  self.screw_joint_spacing_spin,
                  self.screw_hole_diameter_spin):
            w.setEnabled(False)

        self.screw_joint_check.toggled.connect(
            self.screw_joint_thickness_spin.setEnabled)
        self.screw_joint_check.toggled.connect(
            self.screw_joint_spacing_spin.setEnabled)
        self.screw_joint_check.toggled.connect(
            self.screw_hole_diameter_spin.setEnabled)

        # Lay out the screw-joint section as a sub-grid so controls are
        # visually grouped under the checkbox.
        screw_grid = QtWidgets.QGridLayout()
        screw_grid.addWidget(self.screw_joint_check, 0, 0, 1, 4)
        screw_grid.addWidget(QtWidgets.QLabel("  Lug thickness:"),   1, 0)
        screw_grid.addWidget(self.screw_joint_thickness_spin,        1, 1)
        screw_grid.addWidget(QtWidgets.QLabel("  Hole diameter:"),   1, 2)
        screw_grid.addWidget(self.screw_hole_diameter_spin,          1, 3)
        screw_grid.addWidget(QtWidgets.QLabel("  Lug spacing\n  (0 = one per edge):"), 2, 0)
        screw_grid.addWidget(self.screw_joint_spacing_spin,          2, 1)

        self._form.addRow("Screw joints:", screw_grid)

        # Update the shared info label text
        self._info_label.setText(
            "<i>Parts wider/longer than <b>Max piece size</b> are automatically "
            "sliced into interlocking finger-joint pieces for 3-D printing. "
            "<b>Bridge width</b> controls the solid band at cut lines "
            "(defaults to Perimeter width when 0). "
            "<b>Tab/finger width</b> sets the width of each individual finger "
            "tab along the cut face (0 = same as Bridge width). "
            "<b>Joint depth</b> controls how far each finger penetrates: smaller "
            "values leave a solid base in the bridge band across the join "
            "(0 = one-third of bridge width). "
            "<b>Support bar spacing</b> adds internal solid ribs every N mm (0 = none). "
            "<b>Leg width</b> must be smaller than <b>Perimeter width</b> so "
            "that the corner holes fit within the solid perimeter band. "
            "<b>Screw joints</b>: when enabled, flat rectangular lugs with a "
            "centred vertical through-hole are added to all outer faces of "
            "each shelf piece and each leg at the shelf/leg interface (world "
            "z = 0). Place a heat-set insert in one lug and thread a screw "
            "through the other to create a strong mechanical connection. "
            "<b>Lug thickness</b> sets the Z height of each lug. "
            "<b>Hole diameter</b> sets the screw/insert hole size (same on "
            "both the shelf lug and the leg lug). "
            "<b>Lug spacing</b> controls how many lugs appear along each outer "
            "shelf edge: 0 places one lug at the midpoint; a positive value "
            "places lugs at that centre-to-centre interval.</i>"
        )

    # ------------------------------------------------------------------
    def get_params(self) -> dict:
        """Return dialog values including leg and screw-joint parameters."""
        params = super().get_params()
        params["leg_height"]            = self.leg_height_spin.value()
        params["leg_width"]             = self.leg_width_spin.value()
        params["screw_joint"]           = self.screw_joint_check.isChecked()
        params["screw_joint_thickness"] = self.screw_joint_thickness_spin.value()
        params["screw_joint_spacing"]   = self.screw_joint_spacing_spin.value()
        params["screw_hole_diameter"]   = self.screw_hole_diameter_spin.value()
        return params


try:
    from .gridfinity_core import GRIDFINITY_UNIT as _GF_UNIT
except ImportError:
    try:
        from gridfinity_core import GRIDFINITY_UNIT as _GF_UNIT
    except ImportError:
        _GF_UNIT = 42.0  # fallback if module not yet available

# Default grid size used when no spinner reference is available
_DEFAULT_GRID_SIZE = 2


# ===========================================================================
# Gridfinity Box Builder dialog
# ===========================================================================

class _ContainerTableWidget(QtWidgets.QWidget):
    """Embedded widget that manages the list of container pocket specs.

    Displays a :class:`~PySide2.QtWidgets.QTableWidget` with one row per
    container.  Toolbar buttons allow the user to add a cylinder pocket, add
    a rectangle pocket, or remove the currently selected row.

    Default XY positions for new containers are spread across the gridfinity
    grid cells so that each new pocket lands in a different cell rather than
    all defaulting to the same centre.  Pass *grid_x_ref* and *grid_y_ref*
    (references to the parent dialog's grid-size spinners) so that the
    computed default positions update when the grid size changes.
    """

    # Column indices
    _COL_TYPE   = 0
    _COL_X      = 1
    _COL_Y      = 2
    _COL_DEPTH  = 3
    _COL_RADIUS = 4   # cylinder
    _COL_WIDTH  = 5   # rectangle
    _COL_LENGTH = 6   # rectangle

    _HEADERS = ["Type", "X (mm)", "Y (mm)", "Depth (mm)",
                "Radius (mm)", "Width (mm)", "Length (mm)"]

    def __init__(self, parent=None, grid_x_ref=None, grid_y_ref=None):
        super().__init__(parent)
        self._grid_x_ref = grid_x_ref
        self._grid_y_ref = grid_y_ref

        self._table = QtWidgets.QTableWidget(0, len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)

        btn_add_cyl  = QtWidgets.QPushButton("Add Cylinder")
        btn_add_rect = QtWidgets.QPushButton("Add Rectangle")
        btn_remove   = QtWidgets.QPushButton("Remove Selected")

        btn_add_cyl.clicked.connect(self._add_cylinder)
        btn_add_rect.clicked.connect(self._add_rectangle)
        btn_remove.clicked.connect(self._remove_selected)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(btn_add_cyl)
        btn_row.addWidget(btn_add_rect)
        btn_row.addWidget(btn_remove)
        btn_row.addStretch()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    def _next_default_xy(self) -> tuple:
        """Return a spread (x, y) default position for the next new container.

        Positions cycle through the centres of each gridfinity grid cell
        in row-major order (left-to-right, bottom-to-top) so that successive
        containers land in different cells rather than all overlapping.
        """
        row = self._table.rowCount()
        gx = self._grid_x_ref.value() if self._grid_x_ref is not None else _DEFAULT_GRID_SIZE
        gy = self._grid_y_ref.value() if self._grid_y_ref is not None else _DEFAULT_GRID_SIZE
        total_cells = gx * gy
        cell_idx = row % total_cells
        cell_col = cell_idx % gx
        cell_row = cell_idx // gx
        x = (cell_col + 0.5) * _GF_UNIT
        y = (cell_row + 0.5) * _GF_UNIT
        return round(x, 1), round(y, 1)

    # ------------------------------------------------------------------
    def _add_cylinder(self):
        row = self._table.rowCount()
        x, y = self._next_default_xy()
        self._table.insertRow(row)
        self._table.setItem(row, self._COL_TYPE,   QtWidgets.QTableWidgetItem("cylinder"))
        self._table.setItem(row, self._COL_X,      QtWidgets.QTableWidgetItem(str(x)))
        self._table.setItem(row, self._COL_Y,      QtWidgets.QTableWidgetItem(str(y)))
        self._table.setItem(row, self._COL_DEPTH,  QtWidgets.QTableWidgetItem("10.0"))
        self._table.setItem(row, self._COL_RADIUS, QtWidgets.QTableWidgetItem("8.0"))
        self._table.setItem(row, self._COL_WIDTH,  QtWidgets.QTableWidgetItem(""))
        self._table.setItem(row, self._COL_LENGTH, QtWidgets.QTableWidgetItem(""))
        # Make type cell read-only
        item = self._table.item(row, self._COL_TYPE)
        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)

    def _add_rectangle(self):
        row = self._table.rowCount()
        x, y = self._next_default_xy()
        self._table.insertRow(row)
        self._table.setItem(row, self._COL_TYPE,   QtWidgets.QTableWidgetItem("rectangle"))
        self._table.setItem(row, self._COL_X,      QtWidgets.QTableWidgetItem(str(x)))
        self._table.setItem(row, self._COL_Y,      QtWidgets.QTableWidgetItem(str(y)))
        self._table.setItem(row, self._COL_DEPTH,  QtWidgets.QTableWidgetItem("10.0"))
        self._table.setItem(row, self._COL_RADIUS, QtWidgets.QTableWidgetItem(""))
        self._table.setItem(row, self._COL_WIDTH,  QtWidgets.QTableWidgetItem("20.0"))
        self._table.setItem(row, self._COL_LENGTH, QtWidgets.QTableWidgetItem("20.0"))
        item = self._table.item(row, self._COL_TYPE)
        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)

    def _remove_selected(self):
        rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self._table.removeRow(row)

    # ------------------------------------------------------------------
    def _cell_float(self, row: int, col: int, default: float = 0.0) -> float:
        item = self._table.item(row, col)
        if item is None or item.text().strip() == "":
            return default
        try:
            return float(item.text())
        except ValueError:
            return default

    def get_containers(self) -> list:
        """Return a list of container spec dicts from the table contents."""
        containers = []
        for row in range(self._table.rowCount()):
            ctype_item = self._table.item(row, self._COL_TYPE)
            if ctype_item is None:
                continue
            ctype = ctype_item.text().strip().lower()

            spec = {
                "type":  ctype,
                "x":     self._cell_float(row, self._COL_X,     21.0),
                "y":     self._cell_float(row, self._COL_Y,     21.0),
                "depth": self._cell_float(row, self._COL_DEPTH, 10.0),
            }
            if ctype == "cylinder":
                spec["radius"] = self._cell_float(row, self._COL_RADIUS, 8.0)
            else:
                spec["width"]  = self._cell_float(row, self._COL_WIDTH,  20.0)
                spec["length"] = self._cell_float(row, self._COL_LENGTH, 20.0)

            containers.append(spec)
        return containers


class GridfinityDialog(QtWidgets.QDialog):
    """Modal dialog for gridfinity box creation parameters.

    Presents controls for:

    * Grid size (X × Y units of ``GRIDFINITY_UNIT`` mm each)
    * Box height, interior base height, and shell wall thickness
    * An open-ended list of container pockets (cylinders or rectangles)
    * Optional lid with configurable height
    * Optional corner magnet holes with radius, depth, and corner pad
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Gridfinity Box")
        self.setMinimumWidth(520)

        # ── Helper ─────────────────────────────────────────────────────
        def _int_spin(lo, hi, default):
            w = QtWidgets.QSpinBox()
            w.setRange(lo, hi)
            w.setValue(default)
            return w

        def _spin(lo, hi, default, dec=1, suffix=" mm"):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setValue(default)
            w.setDecimals(dec)
            w.setSuffix(suffix)
            return w

        # ── Box dimensions ─────────────────────────────────────────────
        self.grid_x_spin         = _int_spin(1, 50, 2)
        self.grid_y_spin         = _int_spin(1, 50, 2)
        self.box_height_spin     = _spin(5.0, 500.0,  42.0)
        self.interior_h_spin     = _spin(1.0, 490.0,  21.0)
        self.shell_spin          = _spin(0.5,  50.0,   2.0, dec=2)

        # ── Container table ────────────────────────────────────────────
        # Pass grid spinner references so default positions spread across cells
        self._container_widget = _ContainerTableWidget(
            grid_x_ref=self.grid_x_spin,
            grid_y_ref=self.grid_y_spin,
        )

        # ── Lid ────────────────────────────────────────────────────────
        self.lid_check      = QtWidgets.QCheckBox("Create lid")
        self.lid_height_spin = _spin(0.5, 50.0, 2.0)
        self.lid_height_spin.setEnabled(False)
        self.lid_check.toggled.connect(self.lid_height_spin.setEnabled)

        # ── Magnets ────────────────────────────────────────────────────
        self.magnet_check      = QtWidgets.QCheckBox("Add corner magnet holes")
        self.magnet_radius_spin = _spin(0.1, 20.0, 3.0, dec=2)
        self.magnet_depth_spin  = _spin(0.1, 20.0, 2.0, dec=2)
        self.corner_pad_spin    = _spin(0.0, 20.0, 1.0, dec=2)
        for w in (self.magnet_radius_spin, self.magnet_depth_spin,
                  self.corner_pad_spin):
            w.setEnabled(False)
        self.magnet_check.toggled.connect(self.magnet_radius_spin.setEnabled)
        self.magnet_check.toggled.connect(self.magnet_depth_spin.setEnabled)
        self.magnet_check.toggled.connect(self.corner_pad_spin.setEnabled)

        # ── Layout ─────────────────────────────────────────────────────
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)

        # Grid X / Y on one row
        grid_row = QtWidgets.QHBoxLayout()
        grid_row.addWidget(self.grid_x_spin)
        grid_row.addWidget(QtWidgets.QLabel("×"))
        grid_row.addWidget(self.grid_y_spin)
        grid_row.addStretch()
        form.addRow(f"Grid size (X × Y units of {_GF_UNIT:.0f} mm):", grid_row)

        form.addRow("Total box height:",                  self.box_height_spin)
        form.addRow("Interior base height\n(solid, pockets cut into here):",
                    self.interior_h_spin)
        form.addRow("Shell thickness\n(walls & floor):",  self.shell_spin)

        # Lid section
        lid_layout = QtWidgets.QHBoxLayout()
        lid_layout.addWidget(self.lid_check)
        lid_layout.addWidget(QtWidgets.QLabel("  Height:"))
        lid_layout.addWidget(self.lid_height_spin)
        lid_layout.addStretch()
        form.addRow("Lid:", lid_layout)

        # Magnet section
        magnet_layout = QtWidgets.QGridLayout()
        magnet_layout.addWidget(self.magnet_check,  0, 0, 1, 4)
        magnet_layout.addWidget(QtWidgets.QLabel("  Radius:"),   1, 0)
        magnet_layout.addWidget(self.magnet_radius_spin,         1, 1)
        magnet_layout.addWidget(QtWidgets.QLabel("  Depth:"),    1, 2)
        magnet_layout.addWidget(self.magnet_depth_spin,          1, 3)
        magnet_layout.addWidget(QtWidgets.QLabel("  Corner pad:"), 2, 0)
        magnet_layout.addWidget(self.corner_pad_spin,              2, 1)
        form.addRow("Magnets:", magnet_layout)

        info = QtWidgets.QLabel(
            f"<i><b>Grid size</b>: each unit is {_GF_UNIT:.0f} × {_GF_UNIT:.0f} mm. "
            "<b>Interior base height</b>: the solid block inside the box into "
            "which container pockets are carved from the top. "
            "<b>Container pockets</b>: add cylinders or rectangles; their "
            "shapes are kept as separate FreeCAD objects linked to the box "
            "via Part::Cut — moving a pocket shape repositions the hole. "
            "New containers are placed at grid-cell centres automatically. "
            "<b>Magnet holes</b> are drilled at the top rim of the box walls "
            "and at the bottom face of the lid so they align when the lid is "
            "placed on the box. "
            "<b>Corner pad</b>: extra solid material fused at each top corner "
            "to provide wall thickness around the magnet holes.</i>"
        )
        info.setWordWrap(True)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        main = QtWidgets.QVBoxLayout(self)
        main.addLayout(form)
        main.addWidget(QtWidgets.QLabel("<b>Container pockets:</b>"))
        main.addWidget(self._container_widget)
        main.addWidget(info)
        main.addWidget(buttons)

    # ------------------------------------------------------------------
    def _on_accept(self):
        """Validate before accepting the dialog."""
        # Basic sanity: interior_height must fit inside the box
        shell = self.shell_spin.value()
        ih    = self.interior_h_spin.value()
        bh    = self.box_height_spin.value()
        if shell + ih >= bh:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid dimensions",
                "Shell thickness + interior base height must be less than "
                "total box height (to leave an open cavity at the top).",
            )
            return
        if self.magnet_check.isChecked():
            md  = self.magnet_depth_spin.value()
            # Magnet holes are drilled downward from the top of the box walls;
            # depth must not exceed the total box height.
            if md >= bh:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid magnet depth",
                    f"Magnet depth ({md:.2f} mm) must be less than "
                    f"total box height ({bh:.2f} mm).",
                )
                return
            # If a lid is enabled, its magnet holes are drilled from the
            # bottom face; depth must not exceed the lid thickness.
            if self.lid_check.isChecked():
                lh = self.lid_height_spin.value()
                if md > lh:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Invalid magnet depth for lid",
                        f"Magnet depth ({md:.2f} mm) exceeds lid height "
                        f"({lh:.2f} mm). Reduce magnet depth or increase "
                        "lid height.",
                    )
                    return
        self.accept()

    # ------------------------------------------------------------------
    def get_params(self) -> dict:
        """Return the dialog values as a plain dictionary."""
        use_magnets = self.magnet_check.isChecked()
        return {
            "grid_x":           self.grid_x_spin.value(),
            "grid_y":           self.grid_y_spin.value(),
            "box_height":       self.box_height_spin.value(),
            "interior_height":  self.interior_h_spin.value(),
            "shell_thickness":  self.shell_spin.value(),
            "containers":       self._container_widget.get_containers(),
            "make_lid":         self.lid_check.isChecked(),
            "lid_height":       self.lid_height_spin.value(),
            "magnet_radius":    self.magnet_radius_spin.value() if use_magnets else 0.0,
            "magnet_depth":     self.magnet_depth_spin.value()  if use_magnets else 0.0,
            "corner_pad":       self.corner_pad_spin.value()    if use_magnets else 0.0,
        }

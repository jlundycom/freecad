"""
create_part_dialog.py
---------------------
Qt dialog that prompts the user for hex-lattice part dimensions.
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
        # joint_width (UI label: "Finger width"): inner bridge width at cut
        #   lines and finger-joint tab width.  Named joint_width internally for
        #   backward compatibility; displayed as "Finger width" to users.
        #   Defaults to perim_width (same field value) at run-time if 0.
        self.joint_width_spin = _spin(0.0, 100.0, 0.0)
        self.joint_width_spin.setSpecialValueText("= Perimeter width")

        # finger_spacing: gap between consecutive fingers; 0 = contiguous.
        self.finger_spacing_spin = _spin(0.0, 5000.0, 0.0)
        self.finger_spacing_spin.setSpecialValueText("Contiguous (0 = no gap)")

        # joint_depth: how far each finger penetrates into the adjacent piece.
        #   0 = use the default (= joint_width / 2, i.e. full bridge half-width).
        #   A smaller positive value leaves solid material beyond the tab tips,
        #   forming a continuous support bar across the cut line.
        self.joint_depth_spin = _spin(0.0, 100.0, 0.0)
        self.joint_depth_spin.setSpecialValueText("= Half joint width")

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
        form.addRow("Finger width\n(0 = same as perimeter):",
                    self.joint_width_spin)
        form.addRow("Finger spacing\n(0 = contiguous, no gap):",
                    self.finger_spacing_spin)
        form.addRow("Joint depth\n(0 = half joint width):",
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
            "<b>Finger width</b> sets the width (mm) of each interlocking tab "
            "(defaults to Perimeter width when 0). "
            "<b>Finger spacing</b> sets the gap (mm) between consecutive fingers "
            "— areas between fingers are flat. 0 means fingers are contiguous "
            "(no gap, fills the full face). "
            "<b>Joint depth</b> controls how far each finger penetrates into the "
            "adjacent piece: a smaller value leaves a solid base in the bridge "
            "band, forming a continuous support bar across the join "
            "(0 = half of finger width). "
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
        joint_d  = self.joint_depth_spin.value()
        sup_w    = self.support_width_spin.value()
        return {
            "width":            self.width_spin.value(),
            "length":           self.length_spin.value(),
            "height":           self.height_spin.value(),
            "perim_width":      self.perim_spin.value(),
            # joint_width=None tells make_piece() to fall back to perim_width
            "joint_width":      joint_w if joint_w > 0.0 else None,
            "finger_spacing":   self.finger_spacing_spin.value(),
            # joint_depth=None tells make_piece() to fall back to joint_w/2
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

    Extends :class:`HexLatticeDialog` with two additional fields:

    * **Leg height** – total printed height of each corner leg.
    * **Leg width** – side length of the square leg cross-section.
      Must be smaller than the perimeter width so the corner holes fit
      entirely within the solid perimeter band.
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

        # Update the shared info label text (avoids any duplicate-widget issues)
        self._info_label.setText(
            "<i>Parts wider/longer than <b>Max piece size</b> are automatically "
            "sliced into interlocking finger-joint pieces for 3-D printing. "
            "<b>Joint bridge width</b> controls the bridge band at cut lines and "
            "the finger-joint tab size (defaults to Perimeter width when 0). "
            "<b>Joint length</b> limits how much of each cut face carries finger "
            "joints (0 = full face). "
            "<b>Joint depth</b> controls how far each finger penetrates: smaller "
            "values leave a solid base in the bridge band across the join "
            "(0 = half of joint bridge width). "
            "<b>Support bar spacing</b> adds internal solid ribs every N mm (0 = none). "
            "<b>Leg width</b> must be smaller than <b>Perimeter width</b> so "
            "that the corner holes fit within the solid perimeter band. "
            "The top of each leg is a peg that inserts into a blind hole in "
            "the shelf; the leg body rests below the shelf.</i>"
        )

    # ------------------------------------------------------------------
    def get_params(self) -> dict:
        """Return dialog values including leg dimensions."""
        params = super().get_params()
        params["leg_height"] = self.leg_height_spin.value()
        params["leg_width"]  = self.leg_width_spin.value()
        return params

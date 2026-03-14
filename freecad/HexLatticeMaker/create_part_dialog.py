"""
create_part_dialog.py
---------------------
Qt dialog that prompts the user for hex-lattice part dimensions.
"""

try:
    from PySide2 import QtWidgets, QtCore
except ImportError:
    from PySide6 import QtWidgets, QtCore


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

        form.addRow("Width  (X):",              self.width_spin)
        form.addRow("Length (Y):",              self.length_spin)
        form.addRow("Height (Z):",              self.height_spin)
        form.addRow("Perimeter width:",         self.perim_spin)
        form.addRow("Hexagon size\n(side length):", self.hex_spin)
        form.addRow("Wall thickness:",          self.wall_spin)
        form.addRow("Max piece size:",          self.max_piece_spin)

        # Info label
        info = QtWidgets.QLabel(
            "<i>Parts wider/longer than <b>Max piece size</b> are automatically\n"
            "sliced into interlocking finger-joint pieces for 3-D printing.\n"
            "<b>Wall thickness</b> sets the material between hex cells.</i>"
        )
        info.setWordWrap(True)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        main = QtWidgets.QVBoxLayout()
        main.addLayout(form)
        main.addWidget(info)
        main.addWidget(buttons)
        self.setLayout(main)

    # ------------------------------------------------------------------
    def get_params(self) -> dict:
        """Return the dialog values as a plain dictionary."""
        return {
            "width":          self.width_spin.value(),
            "length":         self.length_spin.value(),
            "height":         self.height_spin.value(),
            "perim_width":    self.perim_spin.value(),
            "hex_size":       self.hex_spin.value(),
            "wall_thickness": self.wall_spin.value(),
            "max_piece_size": self.max_piece_spin.value(),
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

        self._form.addRow("Leg height:",            self.leg_height_spin)
        self._form.addRow("Leg width\n(cross-section):", self.leg_width_spin)

        # Update the info label to mention legs
        info_label = QtWidgets.QLabel(
            "<i>Parts wider/longer than <b>Max piece size</b> are automatically\n"
            "sliced into interlocking finger-joint pieces for 3-D printing.\n"
            "<b>Leg width</b> must be smaller than <b>Perimeter width</b> so\n"
            "that the corner holes fit within the solid perimeter band.</i>"
        )
        info_label.setWordWrap(True)
        # Replace the existing info label (second widget in the main layout)
        main_layout = self.layout()
        old_info = main_layout.itemAt(1).widget()
        main_layout.replaceWidget(old_info, info_label)
        old_info.deleteLater()

    # ------------------------------------------------------------------
    def get_params(self) -> dict:
        """Return dialog values including leg dimensions."""
        params = super().get_params()
        params["leg_height"] = self.leg_height_spin.value()
        params["leg_width"]  = self.leg_width_spin.value()
        return params

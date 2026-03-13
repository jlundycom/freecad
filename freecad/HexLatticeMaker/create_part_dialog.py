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

        def _spin(lo, hi, default, dec=1, suffix=" mm"):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setValue(default)
            w.setDecimals(dec)
            w.setSuffix(suffix)
            return w

        self.width_spin  = _spin(10.0,  5000.0, 300.0)
        self.length_spin = _spin(10.0,  5000.0, 300.0)
        self.height_spin = _spin( 1.0,   220.0,  10.0)
        self.perim_spin  = _spin( 1.0,   100.0,   6.0)
        self.hex_spin    = _spin( 1.0,   100.0,   8.0)

        form.addRow("Width  (X):",              self.width_spin)
        form.addRow("Length (Y):",              self.length_spin)
        form.addRow("Height (Z):",              self.height_spin)
        form.addRow("Perimeter width:",         self.perim_spin)
        form.addRow("Hexagon size\n(side length):", self.hex_spin)

        # Info label
        info = QtWidgets.QLabel(
            "<i>Parts larger than 220 mm are automatically sliced into\n"
            "interlocking finger-joint pieces for 3-D printing.</i>"
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
            "width":       self.width_spin.value(),
            "length":      self.length_spin.value(),
            "height":      self.height_spin.value(),
            "perim_width": self.perim_spin.value(),
            "hex_size":    self.hex_spin.value(),
        }

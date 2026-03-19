"""
tests/test_gridfinity.py
------------------------
Pure-Python unit tests for the geometry helpers in gridfinity_core.

These tests intentionally do NOT require FreeCAD to be installed; they
exercise only the functions that depend solely on the standard library.
"""

import math
import sys
import os

# ---------------------------------------------------------------------------
# Make the package importable regardless of how the tests are invoked
# ---------------------------------------------------------------------------
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from freecad.HexLatticeMaker.gridfinity_core import (
    GRIDFINITY_UNIT,
    GRIDFINITY_HEIGHT_UNIT,
    gridfinity_outer_dimensions,
    magnet_corner_centres,
    validate_container,
)

import pytest


# ===========================================================================
# Constants
# ===========================================================================

class TestConstants:
    def test_gridfinity_unit(self):
        assert GRIDFINITY_UNIT == 42.0

    def test_gridfinity_height_unit(self):
        assert GRIDFINITY_HEIGHT_UNIT == 7.0


# ===========================================================================
# gridfinity_outer_dimensions
# ===========================================================================

class TestGridfinityOuterDimensions:
    def test_1x1(self):
        w, l = gridfinity_outer_dimensions(1, 1)
        assert w == 42.0
        assert l == 42.0

    def test_2x3(self):
        w, l = gridfinity_outer_dimensions(2, 3)
        assert w == 84.0
        assert l == 126.0

    def test_4x4(self):
        w, l = gridfinity_outer_dimensions(4, 4)
        assert w == 168.0
        assert l == 168.0

    def test_returns_floats(self):
        w, l = gridfinity_outer_dimensions(1, 1)
        assert isinstance(w, float)
        assert isinstance(l, float)

    def test_width_proportional_to_grid_x(self):
        w1, _ = gridfinity_outer_dimensions(1, 1)
        w3, _ = gridfinity_outer_dimensions(3, 1)
        assert w3 == pytest.approx(3.0 * w1)

    def test_length_proportional_to_grid_y(self):
        _, l1 = gridfinity_outer_dimensions(1, 1)
        _, l5 = gridfinity_outer_dimensions(1, 5)
        assert l5 == pytest.approx(5.0 * l1)


# ===========================================================================
# magnet_corner_centres
# ===========================================================================

class TestMagnetCornerCentres:
    def _call(self, outer_x=84.0, outer_y=84.0, shell=2.0, pad=0.0):
        return magnet_corner_centres(outer_x, outer_y, shell, pad)

    def test_returns_four_points(self):
        centres = self._call()
        assert len(centres) == 4

    def test_all_inside_box(self):
        outer_x, outer_y = 84.0, 84.0
        centres = self._call(outer_x=outer_x, outer_y=outer_y)
        for cx, cy in centres:
            assert 0.0 < cx < outer_x, f"cx={cx} out of range"
            assert 0.0 < cy < outer_y, f"cy={cy} out of range"

    def test_symmetry_x(self):
        """Left pair and right pair should be symmetric about outer_x/2."""
        outer_x = 84.0
        centres = self._call(outer_x=outer_x)
        # bottom-left + bottom-right
        assert centres[0][0] + centres[1][0] == pytest.approx(outer_x)
        # top-left + top-right
        assert centres[2][0] + centres[3][0] == pytest.approx(outer_x)

    def test_symmetry_y(self):
        """Bottom pair and top pair should be symmetric about outer_y/2."""
        outer_y = 84.0
        centres = self._call(outer_y=outer_y)
        assert centres[0][1] + centres[2][1] == pytest.approx(outer_y)
        assert centres[1][1] + centres[3][1] == pytest.approx(outer_y)

    def test_offset_uses_shell_and_pad(self):
        shell, pad = 2.0, 1.0
        expected_offset = (shell + pad) / 2.0
        centres = magnet_corner_centres(84.0, 84.0, shell, pad)
        # bottom-left corner should be at (offset, offset)
        assert centres[0][0] == pytest.approx(expected_offset)
        assert centres[0][1] == pytest.approx(expected_offset)

    def test_zero_pad_uses_half_shell(self):
        shell = 4.0
        centres = magnet_corner_centres(84.0, 84.0, shell_thickness=shell, corner_pad=0.0)
        expected_offset = shell / 2.0
        assert centres[0][0] == pytest.approx(expected_offset)
        assert centres[0][1] == pytest.approx(expected_offset)

    def test_larger_box(self):
        outer_x, outer_y = 168.0, 210.0
        centres = magnet_corner_centres(outer_x, outer_y, shell_thickness=3.0)
        for cx, cy in centres:
            assert 0.0 < cx < outer_x
            assert 0.0 < cy < outer_y


# ===========================================================================
# validate_container
# ===========================================================================

class TestValidateContainer:
    def _outer(self):
        return (84.0, 84.0)

    def test_valid_cylinder(self):
        spec = {"type": "cylinder", "depth": 10.0, "radius": 5.0,
                "x": 21.0, "y": 21.0}
        errors = validate_container(spec, *self._outer())
        assert errors == []

    def test_valid_rectangle(self):
        spec = {"type": "rectangle", "depth": 10.0, "width": 20.0,
                "length": 15.0, "x": 42.0, "y": 42.0}
        errors = validate_container(spec, *self._outer())
        assert errors == []

    def test_unknown_type(self):
        spec = {"type": "triangle", "depth": 5.0}
        errors = validate_container(spec, *self._outer())
        assert any("type" in e.lower() or "unknown" in e.lower() for e in errors)

    def test_zero_depth_invalid(self):
        spec = {"type": "cylinder", "depth": 0.0, "radius": 5.0}
        errors = validate_container(spec, *self._outer())
        assert any("depth" in e.lower() for e in errors)

    def test_negative_depth_invalid(self):
        spec = {"type": "cylinder", "depth": -1.0, "radius": 5.0}
        errors = validate_container(spec, *self._outer())
        assert any("depth" in e.lower() for e in errors)

    def test_zero_radius_invalid(self):
        spec = {"type": "cylinder", "depth": 10.0, "radius": 0.0}
        errors = validate_container(spec, *self._outer())
        assert any("radius" in e.lower() for e in errors)

    def test_zero_width_invalid(self):
        spec = {"type": "rectangle", "depth": 10.0, "width": 0.0, "length": 10.0}
        errors = validate_container(spec, *self._outer())
        assert any("width" in e.lower() for e in errors)

    def test_zero_length_invalid(self):
        spec = {"type": "rectangle", "depth": 10.0, "width": 10.0, "length": 0.0}
        errors = validate_container(spec, *self._outer())
        assert any("length" in e.lower() for e in errors)

    def test_multiple_errors_cylinder(self):
        spec = {"type": "cylinder", "depth": 0.0, "radius": 0.0}
        errors = validate_container(spec, *self._outer())
        assert len(errors) >= 2

    def test_multiple_errors_rectangle(self):
        spec = {"type": "rectangle", "depth": 0.0, "width": 0.0, "length": 0.0}
        errors = validate_container(spec, *self._outer())
        assert len(errors) >= 3

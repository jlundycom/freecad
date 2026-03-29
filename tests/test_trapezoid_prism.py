"""
tests/test_trapezoid_prism.py
-----------------------------
Pure-Python unit tests for the geometry helpers in trapezoid_prism_core.

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

from freecad.HexLatticeMaker.trapezoid_prism_core import (
    DEFAULT_THREAD_PITCH,
    DEFAULT_THREAD_DEPTH_RATIO,
    DEFAULT_SCREW_CLEARANCE,
    validate_trapezoid_prism_params,
    compute_prism_vertices,
    interpolate_width_at_y,
    interpolate_height_at_y,
    compute_thread_params,
    compute_screw_heights,
    compute_screw_center,
    compute_nut_geometry,
    compute_clearance_radius,
)

import pytest


# ===========================================================================
# Constants
# ===========================================================================

class TestConstants:
    def test_default_thread_pitch_positive(self):
        assert DEFAULT_THREAD_PITCH > 0.0

    def test_default_thread_pitch_value(self):
        assert DEFAULT_THREAD_PITCH == pytest.approx(3.0)

    def test_default_thread_depth_ratio_range(self):
        assert 0.0 < DEFAULT_THREAD_DEPTH_RATIO < 1.0

    def test_default_screw_clearance_positive(self):
        assert DEFAULT_SCREW_CLEARANCE > 0.0


# ===========================================================================
# validate_trapezoid_prism_params
# ===========================================================================

class TestValidateTrapezoidPrismParams:
    def _valid(self, **overrides):
        """Return a fully valid parameter set, optionally overriding some values."""
        params = dict(
            front_w=40.0,
            front_h=30.0,
            back_w=30.0,
            back_h=20.0,
            length=50.0,
            split_height=10.0,
            add_screw=True,
            screw_radius=3.0,
            extend_amount=10.0,
            nut_radius=6.0,
            nut_height=5.0,
            thread_pitch=2.0,
        )
        params.update(overrides)
        return params

    def test_valid_params_no_errors(self):
        assert validate_trapezoid_prism_params(**self._valid()) == []

    def test_valid_no_screw(self):
        params = self._valid(add_screw=False)
        assert validate_trapezoid_prism_params(**params) == []

    def test_zero_front_w_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(front_w=0.0))
        assert any("front_w" in e for e in errors)

    def test_negative_front_w_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(front_w=-1.0))
        assert any("front_w" in e for e in errors)

    def test_zero_front_h_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(front_h=0.0))
        assert any("front_h" in e for e in errors)

    def test_zero_back_w_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(back_w=0.0))
        assert any("back_w" in e for e in errors)

    def test_zero_back_h_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(back_h=0.0))
        assert any("back_h" in e for e in errors)

    def test_zero_length_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(length=0.0))
        assert any("length" in e for e in errors)

    def test_zero_split_height_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(split_height=0.0))
        assert any("split_height" in e for e in errors)

    def test_split_height_equals_max_invalid(self):
        # max_h = max(front_h=30, back_h=20) = 30; split_height=30 is invalid
        errors = validate_trapezoid_prism_params(**self._valid(split_height=30.0))
        assert any("split_height" in e for e in errors)

    def test_split_height_exceeds_max_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(split_height=50.0))
        assert any("split_height" in e for e in errors)

    def test_split_height_less_than_max_valid(self):
        errors = validate_trapezoid_prism_params(**self._valid(split_height=29.9))
        assert errors == []

    def test_zero_screw_radius_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(screw_radius=0.0))
        assert any("screw_radius" in e for e in errors)

    def test_extend_amount_ignored_by_validator(self):
        """extend_amount is deprecated; any value (including zero) is accepted."""
        errors = validate_trapezoid_prism_params(**self._valid(extend_amount=0.0))
        assert not any("extend_amount" in e for e in errors)

    def test_nut_radius_less_than_screw_radius_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(screw_radius=5.0, nut_radius=4.0))
        assert any("nut_radius" in e for e in errors)

    def test_nut_radius_equal_screw_radius_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(screw_radius=5.0, nut_radius=5.0))
        assert any("nut_radius" in e for e in errors)

    def test_zero_nut_height_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(nut_height=0.0))
        assert any("nut_height" in e for e in errors)

    def test_zero_thread_pitch_invalid(self):
        errors = validate_trapezoid_prism_params(**self._valid(thread_pitch=0.0))
        assert any("thread_pitch" in e for e in errors)

    def test_multiple_errors(self):
        errors = validate_trapezoid_prism_params(
            front_w=-1.0, front_h=0.0, back_w=0.0, back_h=-5.0,
            length=-10.0, split_height=0.0,
            add_screw=True, screw_radius=0.0, extend_amount=-1.0,
            nut_radius=0.0, nut_height=0.0, thread_pitch=0.0,
        )
        assert len(errors) >= 6

    def test_screw_params_not_checked_when_add_screw_false(self):
        """Screw params with zero/invalid values should not produce errors when add_screw=False."""
        errors = validate_trapezoid_prism_params(
            front_w=40.0, front_h=30.0, back_w=30.0, back_h=20.0,
            length=50.0, split_height=10.0,
            add_screw=False,
            screw_radius=0.0,    # would be invalid if add_screw=True
            extend_amount=0.0,   # deprecated; not validated
            nut_radius=0.0,
            nut_height=0.0,
            thread_pitch=0.0,
        )
        assert errors == []


# ===========================================================================
# compute_prism_vertices
# ===========================================================================

class TestComputePrismVertices:
    def _call(self, front_w=40.0, front_h=30.0, back_w=30.0, back_h=20.0, length=50.0):
        return compute_prism_vertices(front_w, front_h, back_w, back_h, length)

    def test_returns_eight_vertices(self):
        assert len(self._call()) == 8

    def test_all_vertices_are_triples(self):
        for v in self._call():
            assert len(v) == 3

    def test_front_face_at_y_zero(self):
        verts = self._call()
        for v in verts[:4]:
            assert v[1] == pytest.approx(0.0)

    def test_back_face_at_y_length(self):
        length = 50.0
        verts = self._call(length=length)
        for v in verts[4:]:
            assert v[1] == pytest.approx(length)

    def test_bottom_vertices_at_z_zero(self):
        verts = self._call()
        assert verts[0][2] == pytest.approx(0.0)
        assert verts[1][2] == pytest.approx(0.0)
        assert verts[4][2] == pytest.approx(0.0)
        assert verts[5][2] == pytest.approx(0.0)

    def test_front_top_vertices_at_front_h(self):
        verts = self._call(front_h=30.0)
        assert verts[2][2] == pytest.approx(30.0)
        assert verts[3][2] == pytest.approx(30.0)

    def test_back_top_vertices_at_back_h(self):
        verts = self._call(back_h=20.0)
        assert verts[6][2] == pytest.approx(20.0)
        assert verts[7][2] == pytest.approx(20.0)

    def test_front_face_x_symmetric_about_zero(self):
        verts = self._call(front_w=40.0)
        assert verts[0][0] == pytest.approx(-20.0)
        assert verts[1][0] == pytest.approx( 20.0)
        assert verts[2][0] == pytest.approx( 20.0)
        assert verts[3][0] == pytest.approx(-20.0)

    def test_back_face_x_symmetric_about_zero(self):
        verts = self._call(back_w=30.0)
        assert verts[4][0] == pytest.approx(-15.0)
        assert verts[5][0] == pytest.approx( 15.0)
        assert verts[6][0] == pytest.approx( 15.0)
        assert verts[7][0] == pytest.approx(-15.0)

    def test_equal_front_back_gives_rectangular_prism(self):
        """When front and back are equal, all X extents match."""
        verts = compute_prism_vertices(40.0, 30.0, 40.0, 30.0, 50.0)
        # Front and back X widths should be identical
        assert verts[0][0] == pytest.approx(verts[4][0])
        assert verts[1][0] == pytest.approx(verts[5][0])


# ===========================================================================
# interpolate_width_at_y
# ===========================================================================

class TestInterpolateWidthAtY:
    def test_at_front(self):
        assert interpolate_width_at_y(0.0, 40.0, 30.0, 50.0) == pytest.approx(40.0)

    def test_at_back(self):
        assert interpolate_width_at_y(50.0, 40.0, 30.0, 50.0) == pytest.approx(30.0)

    def test_at_midpoint(self):
        assert interpolate_width_at_y(25.0, 40.0, 30.0, 50.0) == pytest.approx(35.0)

    def test_linear_interpolation(self):
        for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
            y = t * 50.0
            expected = 40.0 + t * (30.0 - 40.0)
            assert interpolate_width_at_y(y, 40.0, 30.0, 50.0) == pytest.approx(expected)

    def test_zero_length_returns_front_w(self):
        assert interpolate_width_at_y(0.0, 40.0, 30.0, 0.0) == pytest.approx(40.0)

    def test_clamped_below_zero(self):
        """y < 0 is clamped to front value."""
        assert interpolate_width_at_y(-5.0, 40.0, 30.0, 50.0) == pytest.approx(40.0)

    def test_clamped_above_length(self):
        """y > length is clamped to back value."""
        assert interpolate_width_at_y(60.0, 40.0, 30.0, 50.0) == pytest.approx(30.0)

    def test_equal_widths_constant(self):
        for y in [0.0, 10.0, 25.0, 50.0]:
            assert interpolate_width_at_y(y, 30.0, 30.0, 50.0) == pytest.approx(30.0)


# ===========================================================================
# interpolate_height_at_y
# ===========================================================================

class TestInterpolateHeightAtY:
    def test_at_front(self):
        assert interpolate_height_at_y(0.0, 30.0, 20.0, 50.0) == pytest.approx(30.0)

    def test_at_back(self):
        assert interpolate_height_at_y(50.0, 30.0, 20.0, 50.0) == pytest.approx(20.0)

    def test_at_midpoint(self):
        assert interpolate_height_at_y(25.0, 30.0, 20.0, 50.0) == pytest.approx(25.0)

    def test_linear(self):
        for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
            y = t * 50.0
            expected = 30.0 + t * (20.0 - 30.0)
            assert interpolate_height_at_y(y, 30.0, 20.0, 50.0) == pytest.approx(expected)

    def test_zero_length_returns_front_h(self):
        assert interpolate_height_at_y(0.0, 30.0, 20.0, 0.0) == pytest.approx(30.0)

    def test_increasing_height(self):
        """Height can increase from front to back."""
        assert interpolate_height_at_y(50.0, 20.0, 40.0, 50.0) == pytest.approx(40.0)


# ===========================================================================
# compute_thread_params
# ===========================================================================

class TestComputeThreadParams:
    def test_minor_radius_equals_screw_radius(self):
        p = compute_thread_params(3.0)
        assert p["minor_radius"] == pytest.approx(3.0)

    def test_major_radius_greater_than_minor(self):
        p = compute_thread_params(3.0)
        assert p["major_radius"] > p["minor_radius"]

    def test_major_minus_minor_equals_depth(self):
        p = compute_thread_params(3.0, thread_pitch=2.0, thread_depth_ratio=0.5)
        assert p["major_radius"] - p["minor_radius"] == pytest.approx(p["depth"])

    def test_depth_equals_pitch_times_ratio(self):
        p = compute_thread_params(3.0, thread_pitch=2.0, thread_depth_ratio=0.5)
        assert p["depth"] == pytest.approx(2.0 * 0.5)

    def test_pitch_stored_correctly(self):
        p = compute_thread_params(3.0, thread_pitch=2.5)
        assert p["pitch"] == pytest.approx(2.5)

    def test_default_pitch_used(self):
        p = compute_thread_params(3.0)
        assert p["pitch"] == pytest.approx(DEFAULT_THREAD_PITCH)

    def test_returns_dict_with_required_keys(self):
        p = compute_thread_params(3.0)
        for key in ("minor_radius", "major_radius", "pitch", "depth"):
            assert key in p

    def test_depth_scales_with_pitch(self):
        p1 = compute_thread_params(3.0, thread_pitch=1.0)
        p2 = compute_thread_params(3.0, thread_pitch=2.0)
        assert p2["depth"] == pytest.approx(2.0 * p1["depth"])

    def test_larger_screw_radius(self):
        p = compute_thread_params(10.0, thread_pitch=2.0, thread_depth_ratio=0.5)
        assert p["minor_radius"] == pytest.approx(10.0)
        assert p["major_radius"] == pytest.approx(11.0)


# ===========================================================================
# compute_screw_heights
# ===========================================================================

class TestComputeScrewHeights:
    def _call(self, split_height=10.0, front_h=30.0, back_h=20.0,
              extend_amount=15.0, nut_height=8.0):
        return compute_screw_heights(split_height, front_h, back_h,
                                     extend_amount, nut_height=nut_height)

    def test_max_prism_height_is_max_of_faces(self):
        d = self._call(front_h=30.0, back_h=20.0)
        assert d["max_prism_height"] == pytest.approx(30.0)

    def test_max_prism_height_back_larger(self):
        d = self._call(front_h=20.0, back_h=35.0)
        assert d["max_prism_height"] == pytest.approx(35.0)

    def test_top_piece_height(self):
        d = self._call(split_height=10.0, front_h=30.0, back_h=20.0)
        assert d["top_piece_height"] == pytest.approx(30.0 - 10.0)

    def test_post_total_height_equals_max_h_plus_nut(self):
        """Post extends above prism by nut_height to give the nut threads to engage."""
        d = self._call(front_h=30.0, back_h=20.0, nut_height=8.0)
        assert d["post_total_height"] == pytest.approx(30.0 + 8.0)

    def test_post_total_height_independent_of_extend_amount(self):
        """extend_amount is deprecated; post height is driven by nut_height."""
        d1 = self._call(front_h=30.0, nut_height=8.0, extend_amount=5.0)
        d2 = self._call(front_h=30.0, nut_height=8.0, extend_amount=99.0)
        assert d1["post_total_height"] == pytest.approx(d2["post_total_height"])

    def test_threaded_start_equals_split_height(self):
        """Threads begin at the split plane (bottom of the top piece)."""
        d = self._call(split_height=10.0, front_h=30.0, back_h=20.0)
        assert d["threaded_start_z"] == pytest.approx(10.0)

    def test_threaded_end_equals_max_h_plus_nut(self):
        """Threads extend through the full top piece and the stub above."""
        d = self._call(front_h=30.0, back_h=20.0, nut_height=8.0)
        assert d["threaded_end_z"] == pytest.approx(30.0 + 8.0)

    def test_nut_bottom_z_equals_max_prism_height(self):
        """Nut bottom is flush with the prism top surface."""
        d = self._call(front_h=30.0, back_h=20.0)
        assert d["nut_bottom_z"] == pytest.approx(30.0)

    def test_nut_bottom_z_independent_of_nut_height(self):
        """Nut bottom position doesn't change with nut thickness."""
        d1 = self._call(front_h=30.0, nut_height=5.0)
        d2 = self._call(front_h=30.0, nut_height=12.0)
        assert d1["nut_bottom_z"] == pytest.approx(d2["nut_bottom_z"])

    def test_threaded_end_minus_start_equals_top_piece_plus_nut(self):
        """Total threaded length = top-piece height + nut_height."""
        d = self._call(split_height=10.0, front_h=30.0, back_h=20.0, nut_height=8.0)
        expected = d["top_piece_height"] + 8.0
        assert (d["threaded_end_z"] - d["threaded_start_z"]) == pytest.approx(expected)

    def test_returns_dict(self):
        assert isinstance(self._call(), dict)

    def test_required_keys_present(self):
        d = self._call()
        for key in ("max_prism_height", "top_piece_height", "post_total_height",
                    "threaded_start_z", "threaded_end_z", "nut_bottom_z"):
            assert key in d


# ===========================================================================
# compute_screw_center
# ===========================================================================

class TestComputeScrewCenter:
    def test_x_is_zero(self):
        cx, cy = compute_screw_center(50.0)
        assert cx == pytest.approx(0.0)

    def test_y_is_half_length(self):
        cx, cy = compute_screw_center(50.0)
        assert cy == pytest.approx(25.0)

    def test_various_lengths(self):
        for length in [10.0, 50.0, 100.0, 200.0]:
            cx, cy = compute_screw_center(length)
            assert cx == pytest.approx(0.0)
            assert cy == pytest.approx(length / 2.0)

    def test_returns_tuple(self):
        result = compute_screw_center(50.0)
        assert isinstance(result, tuple)
        assert len(result) == 2


# ===========================================================================
# compute_nut_geometry
# ===========================================================================

class TestComputeNutGeometry:
    def _call(self, screw_r=3.0, flat_r=6.0, height=5.0, clearance=DEFAULT_SCREW_CLEARANCE,
              thread_depth=0.0):
        return compute_nut_geometry(screw_r, flat_r, height, clearance,
                                    thread_depth=thread_depth)

    def test_bore_radius_equals_screw_plus_clearance_no_threads(self):
        """With thread_depth=0 bore = screw_radius + clearance (backward-compatible)."""
        geo = self._call(screw_r=3.0, clearance=0.3, thread_depth=0.0)
        assert geo["bore_radius"] == pytest.approx(3.0 + 0.3)

    def test_bore_radius_equals_screw_plus_clearance(self):
        """Legacy call (no thread_depth kwarg) still works."""
        geo = compute_nut_geometry(3.0, 6.0, 5.0, 0.3)
        assert geo["bore_radius"] == pytest.approx(3.0 + 0.3)

    def test_bore_with_default_thread_depth_matches_no_kwarg(self):
        """Omitting thread_depth entirely gives the same result as thread_depth=0."""
        geo_implicit = compute_nut_geometry(3.0, 6.0, 5.0, 0.3)
        geo_explicit = compute_nut_geometry(3.0, 6.0, 5.0, 0.3, thread_depth=0.0)
        assert geo_implicit["bore_radius"] == pytest.approx(geo_explicit["bore_radius"])

    def test_bore_includes_thread_depth(self):
        """bore_radius = screw_radius + thread_depth + clearance."""
        geo = self._call(screw_r=6.0, clearance=0.3, thread_depth=1.5)
        assert geo["bore_radius"] == pytest.approx(6.0 + 1.5 + 0.3)

    def test_bore_exceeds_shaft_when_threads_present(self):
        """Bore must be larger than just screw_radius when thread_depth > 0."""
        geo_no_thread  = self._call(screw_r=6.0, clearance=0.3, thread_depth=0.0)
        geo_with_thread = self._call(screw_r=6.0, clearance=0.3, thread_depth=1.5)
        assert geo_with_thread["bore_radius"] > geo_no_thread["bore_radius"]

    def test_flat_radius_stored(self):
        geo = self._call(flat_r=7.0)
        assert geo["flat_radius"] == pytest.approx(7.0)

    def test_corner_radius_larger_than_flat_radius(self):
        geo = self._call()
        assert geo["corner_radius"] > geo["flat_radius"]

    def test_corner_radius_formula(self):
        flat_r = 6.0
        geo = self._call(flat_r=flat_r)
        expected = flat_r / math.cos(math.pi / 6.0)
        assert geo["corner_radius"] == pytest.approx(expected)

    def test_height_stored(self):
        geo = self._call(height=8.0)
        assert geo["height"] == pytest.approx(8.0)

    def test_bore_radius_less_than_flat_radius(self):
        """The bore (including thread depth) must still fit inside the nut."""
        geo = self._call(screw_r=3.0, flat_r=10.0, clearance=0.3, thread_depth=1.5)
        assert geo["bore_radius"] < geo["flat_radius"]

    def test_returns_dict_with_required_keys(self):
        geo = self._call()
        for key in ("bore_radius", "flat_radius", "corner_radius", "height"):
            assert key in geo


# ===========================================================================
# compute_clearance_radius
# ===========================================================================

class TestComputeClearanceRadius:
    def test_adds_clearance_to_radius(self):
        assert compute_clearance_radius(3.0, 0.3) == pytest.approx(3.3)

    def test_uses_default_clearance(self):
        expected = 3.0 + DEFAULT_SCREW_CLEARANCE
        assert compute_clearance_radius(3.0) == pytest.approx(expected)

    def test_larger_screw_radius(self):
        assert compute_clearance_radius(6.0, 0.5) == pytest.approx(6.5)

    def test_zero_clearance(self):
        assert compute_clearance_radius(3.0, 0.0) == pytest.approx(3.0)

    def test_returns_float(self):
        result = compute_clearance_radius(3.0)
        assert isinstance(result, float)

    def test_clearance_hole_larger_than_screw(self):
        """Clearance radius is always >= screw_radius."""
        for r in [1.5, 3.0, 5.0, 8.0]:
            for c in [0.0, 0.1, 0.3, 0.5]:
                assert compute_clearance_radius(r, c) >= r

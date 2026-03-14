"""
tests/test_geometry.py
----------------------
Pure-Python unit tests for the geometry helpers in hex_lattice_core.

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

from freecad.HexLatticeMaker.hex_lattice_core import (
    compute_cuts,
    hex_centers,
    is_excluded,
    corner_hole_positions,
    MAX_PIECE_SIZE,
    FIT_CLEARANCE,
    MIN_SEG_RATIO,
)

import pytest


# ===========================================================================
# compute_cuts
# ===========================================================================

class TestComputeCuts:
    def test_no_cut_needed_for_small_part(self):
        assert compute_cuts(200.0) == []
        assert compute_cuts(220.0) == []

    def test_one_cut_for_part_just_over_220(self):
        cuts = compute_cuts(221.0)
        assert cuts == [220.0]

    def test_one_cut_for_part_at_440(self):
        # 440 mm: one cut at 220; piece [0,220] and [220,440]
        cuts = compute_cuts(440.0)
        assert cuts == [220.0]

    def test_two_cuts_for_441_mm(self):
        cuts = compute_cuts(441.0)
        assert cuts == [220.0, 440.0]

    def test_no_duplicate_cuts(self):
        # Exact multiples
        cuts = compute_cuts(440.0)
        assert len(cuts) == len(set(cuts))

    def test_cuts_are_ascending(self):
        cuts = compute_cuts(1000.0)
        assert cuts == sorted(cuts)

    def test_all_spans_within_max(self):
        total = 750.0
        cuts  = compute_cuts(total)
        bounds = [0.0] + cuts + [total]
        spans  = [b - a for a, b in zip(bounds[:-1], bounds[1:])]
        for span in spans:
            assert span <= MAX_PIECE_SIZE + 1e-6, f"Span {span} exceeds MAX_PIECE_SIZE"

    def test_very_large_dimension(self):
        cuts = compute_cuts(5000.0)
        bounds = [0.0] + cuts + [5000.0]
        spans  = [b - a for a, b in zip(bounds[:-1], bounds[1:])]
        for span in spans:
            assert span <= MAX_PIECE_SIZE + 1e-6

    def test_custom_max_piece_size_respected(self):
        """compute_cuts should use a caller-supplied max_piece_size."""
        cuts = compute_cuts(250.0, max_piece_size=100.0)
        assert cuts == [100.0, 200.0]

    def test_custom_max_piece_size_no_cut_when_fits(self):
        cuts = compute_cuts(100.0, max_piece_size=100.0)
        assert cuts == []

    def test_custom_max_piece_size_spans_within_limit(self):
        total = 500.0
        mps   = 150.0
        cuts  = compute_cuts(total, max_piece_size=mps)
        bounds = [0.0] + cuts + [total]
        spans  = [b - a for a, b in zip(bounds[:-1], bounds[1:])]
        for span in spans:
            assert span <= mps + 1e-6


# ===========================================================================
# hex_centers
# ===========================================================================

class TestHexCenters:
    def _default_region(self):
        return dict(gx0=0.0, gx1=100.0, gy0=0.0, gy1=100.0,
                    hex_size=8.0, wall_t=1.2)

    def test_returns_list(self):
        centers = hex_centers(**self._default_region())
        assert isinstance(centers, list)

    def test_all_centers_within_bounds(self):
        params  = self._default_region()
        centers = hex_centers(**params)
        for cx, cy in centers:
            assert params['gx0'] <= cx <= params['gx1'], f"cx={cx} out of range"
            assert params['gy0'] <= cy <= params['gy1'], f"cy={cy} out of range"

    def test_non_empty_for_large_region(self):
        centers = hex_centers(0, 200, 0, 200, 10.0, 1.5)
        assert len(centers) > 0

    def test_empty_for_zero_area_region(self):
        centers = hex_centers(50.0, 50.0, 0.0, 100.0, 8.0, 1.2)
        assert centers == []

    def test_centers_unique(self):
        centers = hex_centers(0, 200, 0, 200, 8.0, 1.2)
        unique  = set(centers)
        assert len(unique) == len(centers)

    def test_horizontal_spacing_approximately_correct(self):
        """Adjacent same-row centers should be ~grid_s * sqrt(3) apart."""
        hex_size = 8.0
        wall_t   = 1.2
        grid_s   = hex_size + wall_t
        h_sp     = grid_s * math.sqrt(3)

        centers = hex_centers(0, 200, 0, 200, hex_size, wall_t)
        if len(centers) < 2:
            pytest.skip("Not enough centers to test spacing")

        # Collect centers on the same approximate y level
        centers_sorted = sorted(centers, key=lambda c: (round(c[1], 3), c[0]))
        # Group by row
        rows = {}
        for cx, cy in centers_sorted:
            key = round(cy, 2)
            rows.setdefault(key, []).append(cx)

        for y_key, xs in rows.items():
            if len(xs) < 2:
                continue
            xs_sorted = sorted(xs)
            for a, b in zip(xs_sorted[:-1], xs_sorted[1:]):
                spacing = b - a
                # Should be close to h_sp (within 5 %)
                assert abs(spacing - h_sp) < h_sp * 0.05, (
                    f"Row y≈{y_key}: spacing {spacing:.3f} ≠ {h_sp:.3f}"
                )


# ===========================================================================
# is_excluded
# ===========================================================================

class TestIsExcluded:
    _base = dict(
        hex_size=8.0,
        perim_w=6.0,
        total_w=200.0,
        total_l=200.0,
        x_cuts=[],
        y_cuts=[],
    )

    def _call(self, cx, cy, **override):
        params = {**self._base, **override}
        return is_excluded(cx, cy,
                           params['hex_size'],
                           params['perim_w'],
                           params['total_w'],
                           params['total_l'],
                           params['x_cuts'],
                           params['y_cuts'])

    # ── perimeter exclusions ──────────────────────────────────────────

    def test_center_of_part_is_not_excluded(self):
        assert not self._call(100.0, 100.0)

    def test_near_left_edge_is_excluded(self):
        # hex_size=8, perim_w=6 → cx-8 < 6 when cx < 14
        assert self._call(10.0, 100.0)

    def test_near_right_edge_is_excluded(self):
        # total_w=200, perim_w=6, hex_size=8 → cx+8 > 194 when cx > 186
        assert self._call(190.0, 100.0)

    def test_near_bottom_edge_is_excluded(self):
        assert self._call(100.0, 10.0)

    def test_near_top_edge_is_excluded(self):
        assert self._call(100.0, 190.0)

    def test_just_inside_perimeter_not_excluded(self):
        # cx=20 → cx-hex_size=12 which is > perim_w=6 → NOT excluded
        assert not self._call(20.0, 100.0)

    # ── cut-bridge exclusions ─────────────────────────────────────────

    def test_center_on_x_cut_is_excluded(self):
        assert self._call(100.0, 100.0, x_cuts=[100.0])

    def test_center_near_x_cut_is_excluded(self):
        # bridge_half = perim_w/2 = 3; hex_size=8
        # excluded when |cx - 100| < 8 + 3 = 11
        assert self._call(108.0, 100.0, x_cuts=[100.0])

    def test_center_far_from_x_cut_not_excluded(self):
        # |cx - 100| = 20 > 8+3=11 → not excluded
        assert not self._call(120.0, 100.0, x_cuts=[100.0])

    def test_center_on_y_cut_is_excluded(self):
        assert self._call(100.0, 100.0, y_cuts=[100.0])

    def test_multiple_cuts_all_checked(self):
        # Two cuts; center is far from both
        assert not self._call(60.0, 60.0, x_cuts=[100.0, 200.0],
                                           y_cuts=[100.0, 200.0])

    def test_multiple_cuts_near_second_cut(self):
        assert self._call(100.0, 101.0, y_cuts=[50.0, 100.0])


# ===========================================================================
# Constants sanity checks
# ===========================================================================

class TestConstants:
    def test_max_piece_size_is_220(self):
        assert MAX_PIECE_SIZE == 220.0

    def test_fit_clearance_is_positive(self):
        assert FIT_CLEARANCE > 0.0

    def test_fit_clearance_is_reasonable(self):
        # Should be between 0.05 mm and 0.5 mm for FDM printing
        assert 0.05 <= FIT_CLEARANCE <= 0.5

    def test_min_seg_ratio_is_positive_fraction(self):
        assert 0.0 < MIN_SEG_RATIO < 1.0


# ===========================================================================
# Integration: cut positions + piece boundaries
# ===========================================================================

class TestPieceBoundaries:
    def test_boundaries_cover_full_dimension(self):
        total = 750.0
        cuts  = compute_cuts(total)
        bounds = [0.0] + cuts + [total]
        assert bounds[0] == 0.0
        assert abs(bounds[-1] - total) < 1e-9

    def test_boundaries_contiguous(self):
        total  = 750.0
        cuts   = compute_cuts(total)
        bounds = [0.0] + cuts + [total]
        for a, b in zip(bounds[:-1], bounds[1:]):
            assert b > a

    def test_single_piece_for_220_or_less(self):
        for total in (100.0, 200.0, 220.0):
            cuts = compute_cuts(total)
            assert cuts == [], f"Expected no cuts for total={total}"


# ===========================================================================
# corner_hole_positions
# ===========================================================================

class TestCornerHolePositions:
    """Tests for the corner leg-hole centre-position helper."""

    def test_returns_four_positions(self):
        positions = corner_hole_positions(200.0, 150.0, 10.0)
        assert len(positions) == 4

    def test_all_positions_within_bounds(self):
        w, l, pw = 200.0, 150.0, 10.0
        for cx, cy in corner_hole_positions(w, l, pw):
            assert 0.0 < cx < w, f"cx={cx} out of (0, {w})"
            assert 0.0 < cy < l, f"cy={cy} out of (0, {l})"

    def test_positions_at_expected_locations(self):
        w, l, pw = 200.0, 150.0, 10.0
        offset = pw / 2.0
        expected = [
            (offset,       offset),
            (w - offset,   offset),
            (offset,       l - offset),
            (w - offset,   l - offset),
        ]
        positions = corner_hole_positions(w, l, pw)
        for pos, exp in zip(positions, expected):
            assert abs(pos[0] - exp[0]) < 1e-9, f"x: {pos[0]} ≠ {exp[0]}"
            assert abs(pos[1] - exp[1]) < 1e-9, f"y: {pos[1]} ≠ {exp[1]}"

    def test_bottom_left_is_nearest_to_origin(self):
        positions = corner_hole_positions(300.0, 200.0, 8.0)
        bl_cx, bl_cy = positions[0]
        dist_bl = math.sqrt(bl_cx ** 2 + bl_cy ** 2)
        for cx, cy in positions[1:]:
            assert dist_bl <= math.sqrt(cx ** 2 + cy ** 2) + 1e-6

    def test_symmetric_for_square_shelf(self):
        """On a square shelf the four hole centres should be symmetric."""
        side = 200.0
        pw   = 12.0
        positions = corner_hole_positions(side, side, pw)
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = positions
        # bottom-left and top-right should sum to (side, side)
        assert abs((x0 + x3) - side) < 1e-9
        assert abs((y0 + y3) - side) < 1e-9
        # bottom-right and top-left should sum to (side, side)
        assert abs((x1 + x2) - side) < 1e-9
        assert abs((y1 + y2) - side) < 1e-9

    def test_holes_fit_within_perimeter_band(self):
        """The hole bounding box must lie entirely within the solid perimeter band."""
        w, l, pw = 300.0, 250.0, 15.0
        leg_width = 12.0
        hole_half = (leg_width + FIT_CLEARANCE) / 2.0
        corner_ctrs = corner_hole_positions(w, l, pw)
        # Expected corner-band intervals along each axis:
        #   bottom-left / top-left  : x band [0, pw]
        #   bottom-right / top-right: x band [w - pw, w]
        #   bottom-left / bottom-right: y band [0, pw]
        #   top-left / top-right      : y band [l - pw, l]
        x_bands = [(0.0, pw), (w - pw, w), (0.0, pw), (w - pw, w)]
        y_bands = [(0.0, pw), (0.0, pw), (l - pw, l), (l - pw, l)]
        for (cx, cy), (xlo, xhi), (ylo, yhi) in zip(corner_ctrs, x_bands, y_bands):
            assert cx - hole_half >= xlo, "hole left edge outside perimeter band"
            assert cx + hole_half <= xhi, "hole right edge outside perimeter band"
            assert cy - hole_half >= ylo, "hole bottom edge outside perimeter band"
            assert cy + hole_half <= yhi, "hole top edge outside perimeter band"

    def test_returns_list_of_tuples(self):
        positions = corner_hole_positions(100.0, 80.0, 6.0)
        assert isinstance(positions, list)
        for item in positions:
            assert isinstance(item, tuple)
            assert len(item) == 2

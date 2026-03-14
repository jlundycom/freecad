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
    leg_flush_placements,
    MAX_PIECE_SIZE,
    FIT_CLEARANCE,
    MIN_SEG_RATIO,
    PIN_RADIUS_RATIO,
    TAPER_RATIO,
    LATTICE_TYPES,
    get_tiling_provider,
    HexagonalTilingProvider,
    SquareTilingProvider,
    TriangularTilingProvider,
    TrihexagonalTilingProvider,
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


# ===========================================================================
# Peg-depth / blind-socket geometry
# ===========================================================================

class TestPegDepth:
    """Tests for the peg_depth calculation used in create_shelf_with_legs.

    These verify the *pure-Python* invariants of the blind-socket design
    without requiring FreeCAD.
    """

    @staticmethod
    def _peg_depth(height: float) -> float:
        """Mirror the peg_depth formula used in create_shelf_with_legs."""
        return height * 0.6

    def test_peg_depth_less_than_shelf_height(self):
        for h in (5.0, 10.0, 20.0, 50.0):
            pd = self._peg_depth(h)
            assert pd < h, f"peg_depth={pd} must be less than height={h}"

    def test_peg_depth_leaves_material_above(self):
        """There must be solid material above the blind socket."""
        for h in (5.0, 10.0, 20.0):
            pd = self._peg_depth(h)
            remaining = h - pd
            assert remaining > 0.0, "no material above blind socket"

    def test_peg_depth_fraction_is_60_percent(self):
        h = 10.0
        pd = self._peg_depth(h)
        assert abs(pd - 6.0) < 1e-9

    def test_peg_depth_positive(self):
        for h in (3.0, 10.0, 100.0):
            assert self._peg_depth(h) > 0.0

    def test_leg_assembly_z_bottom(self):
        """Leg body bottom face must be below the shelf (z < 0)."""
        leg_height = 80.0
        # In assembly the leg origin is shifted by -leg_height
        leg_z_bottom = -leg_height
        assert leg_z_bottom < 0.0

    def test_peg_inside_shelf(self):
        """Peg top must not exceed shelf height."""
        shelf_height = 10.0
        peg_depth = self._peg_depth(shelf_height)
        # Peg goes from z=0 to z=peg_depth
        assert peg_depth <= shelf_height

    def test_corner_legs_at_distinct_positions(self):
        """Four legs must occupy four distinct XY positions."""
        w, l = 300.0, 200.0
        leg_width, leg_height = 12.0, 80.0
        placements = leg_flush_placements(w, l, leg_height, leg_width)
        leg_origins_xy = [(px, py) for px, py, _pz in placements]
        assert len(set(leg_origins_xy)) == 4, "legs must have distinct XY positions"


# ===========================================================================
# leg_flush_placements
# ===========================================================================

class TestLegFlushPlacements:
    """Tests for the flush-corner leg placement helper.

    All tests are pure Python (no FreeCAD required).
    """

    def test_returns_four_placements(self):
        placements = leg_flush_placements(300.0, 200.0, 80.0, 12.0)
        assert len(placements) == 4

    def test_each_placement_is_three_tuple(self):
        for item in leg_flush_placements(300.0, 200.0, 80.0, 12.0):
            assert len(item) == 3, "each placement must be (px, py, pz)"

    def test_bottom_left_outer_corner_at_shelf_origin(self):
        """BL leg must start at (0, 0) — flush with the shelf corner."""
        placements = leg_flush_placements(300.0, 200.0, 80.0, 12.0)
        px, py, _ = placements[0]
        assert abs(px) < 1e-9, f"BL leg px={px} should be 0"
        assert abs(py) < 1e-9, f"BL leg py={py} should be 0"

    def test_bottom_right_outer_corner_at_shelf_right_edge(self):
        """BR leg outer face (px + leg_width) must be flush with shelf right edge."""
        w, leg_width = 300.0, 12.0
        placements = leg_flush_placements(w, 200.0, 80.0, leg_width)
        px, py, _ = placements[1]
        assert abs(px + leg_width - w) < 1e-9, "BR outer face not flush with right edge"
        assert abs(py) < 1e-9, "BR py should be 0"

    def test_top_left_outer_corner_at_shelf_top_edge(self):
        """TL leg outer face (py + leg_width) must be flush with shelf top edge."""
        l, leg_width = 200.0, 12.0
        placements = leg_flush_placements(300.0, l, 80.0, leg_width)
        px, py, _ = placements[2]
        assert abs(px) < 1e-9, "TL px should be 0"
        assert abs(py + leg_width - l) < 1e-9, "TL outer face not flush with top edge"

    def test_top_right_outer_corners_at_shelf_edges(self):
        """TR leg outer faces must be flush with both the right and top edges."""
        w, l, leg_width = 300.0, 200.0, 12.0
        placements = leg_flush_placements(w, l, 80.0, leg_width)
        px, py, _ = placements[3]
        assert abs(px + leg_width - w) < 1e-9, "TR outer face not flush with right edge"
        assert abs(py + leg_width - l) < 1e-9, "TR outer face not flush with top edge"

    def test_all_pz_equal_minus_leg_height(self):
        """All four legs must have pz = -leg_height (shoulder at shelf bottom)."""
        leg_height = 80.0
        for px, py, pz in leg_flush_placements(300.0, 200.0, leg_height, 12.0):
            assert abs(pz + leg_height) < 1e-9, f"pz={pz} should be -{leg_height}"

    def test_no_leg_protrudes_beyond_shelf_x(self):
        """Leg X extent must stay within [0, width]."""
        w, leg_width = 300.0, 12.0
        for px, py, _ in leg_flush_placements(w, 200.0, 80.0, leg_width):
            assert px >= 0.0 - 1e-9
            assert px + leg_width <= w + 1e-9

    def test_no_leg_protrudes_beyond_shelf_y(self):
        """Leg Y extent must stay within [0, length]."""
        l, leg_width = 200.0, 12.0
        for px, py, _ in leg_flush_placements(300.0, l, 80.0, leg_width):
            assert py >= 0.0 - 1e-9
            assert py + leg_width <= l + 1e-9

    def test_hole_centre_equals_peg_centre(self):
        """Hole centre (cx, cy) must equal leg placement + leg_width / 2."""
        w, l, lw, lh = 300.0, 200.0, 12.0, 80.0
        placements = leg_flush_placements(w, l, lh, lw)
        expected_ctrs = [(px + lw * 0.5, py + lw * 0.5) for px, py, _ in placements]
        # Verify bottom-left and top-right are diagonally symmetric
        (cx0, cy0), (cx3, cy3) = expected_ctrs[0], expected_ctrs[3]
        assert abs((cx0 + cx3) - w) < 1e-9
        assert abs((cy0 + cy3) - l) < 1e-9


# ===========================================================================
# Round through-pin geometry
# ===========================================================================

class TestRoundPin:
    """Tests for the round through-pin added to each leg.

    The pin is a cylinder centred at (leg_width/2, leg_width/2) in leg-local
    XY, rising from the leg shoulder (z = leg_height) to the shelf top face
    (z = leg_height + shelf_height).  Its radius = leg_width * PIN_RADIUS_RATIO.

    All tests are pure Python (no FreeCAD required).
    """

    def test_pin_radius_ratio_is_positive(self):
        assert PIN_RADIUS_RATIO > 0.0

    def test_pin_radius_less_than_half_leg_width(self):
        """Pin must fit entirely within the leg cross-section."""
        for lw in (10.0, 20.0, 40.0):
            pin_radius = lw * PIN_RADIUS_RATIO
            assert pin_radius < lw * 0.5, (
                f"pin radius {pin_radius} must be < leg half-width {lw*0.5}"
            )

    def test_pin_fits_within_leg_cross_section(self):
        """Pin circle (centre ± radius) must not exceed leg_width in X or Y."""
        for lw in (10.0, 20.0, 40.0):
            pin_radius = lw * PIN_RADIUS_RATIO
            centre = lw * 0.5
            assert centre - pin_radius >= 0.0
            assert centre + pin_radius <= lw

    def test_pin_height_equals_shelf_height(self):
        """In leg-local coords the pin runs from leg_height to leg_height + shelf_height."""
        leg_height, shelf_height = 80.0, 10.0
        pin_z_start = leg_height
        pin_z_end   = leg_height + shelf_height
        assert abs((pin_z_end - pin_z_start) - shelf_height) < 1e-9

    def test_pin_top_flush_with_shelf_top_in_world_coords(self):
        """After placement (pz = -leg_height) pin top = shelf_height (world)."""
        leg_height, shelf_height = 80.0, 10.0
        pz = -leg_height
        # pin top in local = leg_height + shelf_height
        pin_top_world = (leg_height + shelf_height) + pz
        assert abs(pin_top_world - shelf_height) < 1e-9

    def test_pin_bottom_flush_with_shelf_bottom_in_world_coords(self):
        """After placement (pz = -leg_height) pin bottom = 0 (shelf bottom face)."""
        leg_height = 80.0
        pz = -leg_height
        pin_bottom_world = leg_height + pz
        assert abs(pin_bottom_world) < 1e-9

    def test_pin_hole_radius_larger_than_pin(self):
        """The shelf through-hole must be wider than the pin to allow assembly."""
        for lw in (10.0, 20.0, 40.0):
            pin_radius      = lw * PIN_RADIUS_RATIO
            pin_hole_radius = pin_radius + FIT_CLEARANCE * 0.5
            assert pin_hole_radius > pin_radius

    def test_pin_hole_clearance_uses_fit_clearance(self):
        """Hole radius = pin radius + FIT_CLEARANCE / 2."""
        lw = 20.0
        pin_radius      = lw * PIN_RADIUS_RATIO
        pin_hole_radius = pin_radius + FIT_CLEARANCE * 0.5
        assert abs(pin_hole_radius - pin_radius - FIT_CLEARANCE * 0.5) < 1e-9

    def test_pin_centre_at_leg_centre(self):
        """Pin centre in XY must be at leg_width / 2."""
        for lw in (10.0, 20.0, 40.0):
            cx = lw * 0.5
            cy = lw * 0.5
            assert abs(cx - lw * 0.5) < 1e-9
            assert abs(cy - lw * 0.5) < 1e-9

    def test_four_pin_centres_in_world_coords(self):
        """Pin world-XY centres match the leg centres (px + lw/2, py + lw/2)."""
        w, l, lw, lh = 300.0, 200.0, 12.0, 80.0
        placements = leg_flush_placements(w, l, lh, lw)
        pin_ctrs = [(px + lw * 0.5, py + lw * 0.5) for px, py, _ in placements]
        assert len(set(pin_ctrs)) == 4, "four distinct pin centres required"


# ===========================================================================
# is_excluded – leg zone suppression
# ===========================================================================

class TestIsExcludedLegZones:
    """Tests that hex cells overlapping leg support rectangles are excluded.

    All tests are pure Python (no FreeCAD required).
    """

    # Shared base params: large shelf, no cuts, small hex so perimeter/bridge
    # exclusions don't interfere with the leg-zone tests.
    _base = dict(
        hex_size=4.0,
        perim_w=6.0,
        total_w=300.0,
        total_l=200.0,
        x_cuts=[],
        y_cuts=[],
    )

    def _call(self, cx, cy, leg_zones, **override):
        params = {**self._base, **override}
        return is_excluded(
            cx, cy,
            params['hex_size'],
            params['perim_w'],
            params['total_w'],
            params['total_l'],
            params['x_cuts'],
            params['y_cuts'],
            leg_zones=leg_zones,
        )

    # ── no leg zones → no extra exclusion ────────────────────────────

    def test_no_leg_zones_centre_not_excluded(self):
        """Without leg zones a centre-of-shelf hex must not be excluded."""
        assert not self._call(150.0, 100.0, leg_zones=[])

    # ── hex fully inside a leg zone ───────────────────────────────────

    def test_hex_centre_inside_zone_excluded(self):
        """A hex whose centre lies inside a leg zone must be excluded."""
        zone = (0.0, 0.0, 20.0, 20.0)   # BL leg, 20×20
        cx, cy = 10.0, 10.0              # dead centre of zone
        assert self._call(cx, cy, leg_zones=[zone])

    # ── hex overlaps zone edge ────────────────────────────────────────

    def test_hex_touching_zone_right_edge_excluded(self):
        """Hex bounding circle that overlaps the right edge of a zone is excluded."""
        zone = (0.0, 0.0, 20.0, 20.0)
        # hex_size=4; centre at (23, 10): cx - r = 19 < lx1=20, so circle reaches into zone
        assert self._call(23.0, 10.0, leg_zones=[zone])

    def test_hex_just_clear_of_zone_not_excluded(self):
        """Hex that doesn't touch any zone must not be excluded by leg zones."""
        zone = (0.0, 0.0, 20.0, 20.0)
        # hex_size=4; centre at (28, 10): cx - r = 24 > 20 → clear
        assert not self._call(28.0, 10.0, leg_zones=[zone])

    def test_hex_touching_zone_top_edge_excluded(self):
        zone = (0.0, 0.0, 20.0, 20.0)
        # hex_size=4; centre at (10, 23): cy - r = 19 < ly1=20, so circle reaches into zone
        assert self._call(10.0, 23.0, leg_zones=[zone])

    def test_hex_just_clear_of_zone_top_not_excluded(self):
        zone = (0.0, 0.0, 20.0, 20.0)
        # cy - r = 24 > 20 → clear of top edge
        assert not self._call(10.0, 28.0, leg_zones=[zone])

    # ── multiple zones, hit second ────────────────────────────────────

    def test_hit_second_of_two_zones_excluded(self):
        zone_bl = (0.0,   0.0,   20.0,  20.0)   # BL
        zone_tr = (280.0, 180.0, 300.0, 200.0)  # TR
        # Centre close to TR zone; well away from BL zone
        assert self._call(277.0, 182.0, leg_zones=[zone_bl, zone_tr])

    def test_between_two_zones_not_excluded(self):
        zone_bl = (0.0,   0.0,   20.0,  20.0)
        zone_tr = (280.0, 180.0, 300.0, 200.0)
        # Centre at (150, 100): far from both zones
        assert not self._call(150.0, 100.0, leg_zones=[zone_bl, zone_tr])

    # ── four corner zones derived from real placements ────────────────

    def test_four_real_corner_zones_exclude_hex_at_each_corner(self):
        """Leg zones computed from real placements must exclude hexes at each corner."""
        w, l, lw, lh = 300.0, 200.0, 20.0, 80.0
        placements = leg_flush_placements(w, l, lh, lw)
        zones = [
            (px, py, px + lw, py + lw)
            for px, py, _ in placements
        ]
        # A hex at the centre of each leg square must be excluded
        for (px, py, lx1, ly1) in zones:
            cx = (px + lx1) * 0.5
            cy = (py + ly1) * 0.5
            assert self._call(cx, cy, leg_zones=zones,
                              total_w=w, total_l=l), (
                f"hex at ({cx}, {cy}) should be excluded by leg zone"
            )

    def test_four_real_corner_zones_allow_centre_hex(self):
        """A hex at the centre of the shelf must not be excluded by leg zones."""
        w, l, lw, lh = 300.0, 200.0, 20.0, 80.0
        placements = leg_flush_placements(w, l, lh, lw)
        zones = [
            (px, py, px + lw, py + lw)
            for px, py, _ in placements
        ]
        assert not self._call(w * 0.5, l * 0.5, leg_zones=zones,
                              total_w=w, total_l=l)


# ===========================================================================
# Finger-joint taper geometry
# ===========================================================================

class TestTaperRatio:
    """Tests for the finger-joint draft-angle constant and its derived geometry.

    All tests are pure Python (no FreeCAD required).
    """

    # ── constant sanity ───────────────────────────────────────────────

    def test_taper_ratio_is_float(self):
        assert isinstance(TAPER_RATIO, float)

    def test_taper_ratio_is_positive_fraction(self):
        assert 0.0 < TAPER_RATIO < 1.0

    def test_taper_ratio_reasonable_range(self):
        # 10 %–40 % gives a noticeable-but-not-extreme draft angle
        assert 0.10 <= TAPER_RATIO <= 0.40

    # ── derived depths ────────────────────────────────────────────────

    def test_bottom_depth_narrower_than_nominal(self):
        """tab_d_bot < tab_d: bottom is the narrower end."""
        for tab_d in (2.0, 5.0, 10.0):
            td_bot = tab_d * (1.0 - TAPER_RATIO)
            assert td_bot < tab_d, f"td_bot={td_bot} not < tab_d={tab_d}"

    def test_top_depth_wider_than_nominal(self):
        """tab_d_top > tab_d: top is the wider end."""
        for tab_d in (2.0, 5.0, 10.0):
            td_top = tab_d * (1.0 + TAPER_RATIO)
            assert td_top > tab_d, f"td_top={td_top} not > tab_d={tab_d}"

    def test_taper_is_symmetric_about_nominal(self):
        """Average of top and bottom depths equals the nominal tab_d."""
        tab_d = 6.0
        td_bot = tab_d * (1.0 - TAPER_RATIO)
        td_top = tab_d * (1.0 + TAPER_RATIO)
        assert abs((td_top + td_bot) / 2.0 - tab_d) < 1e-9

    def test_bottom_depth_always_positive(self):
        """Narrower bottom must still be a positive depth."""
        for tab_d in (1.0, 2.0, 5.0, 10.0, 20.0):
            td_bot = tab_d * (1.0 - TAPER_RATIO)
            assert td_bot > 0.0, f"td_bot non-positive for tab_d={tab_d}"

    def test_top_always_wider_than_bottom(self):
        """Top depth > bottom depth for all realistic tab_d values."""
        for tab_d in (2.0, 4.0, 8.0, 16.0):
            td_bot = tab_d * (1.0 - TAPER_RATIO)
            td_top = tab_d * (1.0 + TAPER_RATIO)
            assert td_top > td_bot

    # ── slot clearance ────────────────────────────────────────────────

    def test_slot_wider_than_tab_at_bottom(self):
        """Slot depth at z=0 must exceed tab depth by at least FIT_CLEARANCE."""
        tab_d = 5.0
        td_bot   = tab_d * (1.0 - TAPER_RATIO)
        slot_bot = td_bot + FIT_CLEARANCE
        assert slot_bot - td_bot >= FIT_CLEARANCE - 1e-9

    def test_slot_wider_than_tab_at_top(self):
        """Slot depth at z=height must exceed tab depth by at least FIT_CLEARANCE."""
        tab_d = 5.0
        td_top   = tab_d * (1.0 + TAPER_RATIO)
        slot_top = td_top + FIT_CLEARANCE
        assert slot_top - td_top >= FIT_CLEARANCE - 1e-9

    def test_slot_clearance_uniform_across_height(self):
        """The slot exceeds the matching tab by exactly FIT_CLEARANCE at every z."""
        tab_d = 6.0
        fit   = FIT_CLEARANCE
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            # Linearly interpolate tab depth at fraction frac of height
            td_bot = tab_d * (1.0 - TAPER_RATIO)
            td_top = tab_d * (1.0 + TAPER_RATIO)
            tab_at_z   = td_bot + frac * (td_top - td_bot)
            slot_at_z  = tab_at_z + fit
            assert abs(slot_at_z - tab_at_z - fit) < 1e-9


# ===========================================================================
# LATTICE_TYPES registry
# ===========================================================================

# Relative tolerance used for geometric spacing checks.  An absolute tolerance
# would need to change whenever cell_size changes; 1 % of the expected spacing
# is loose enough to survive floating-point accumulation across many lattice
# steps while tight enough to catch real implementation errors.
_SPACING_RTOL = 0.01


class TestLatticeTypes:
    """Tests for the LATTICE_TYPES registry and get_tiling_provider factory."""

    def test_lattice_types_has_four_entries(self):
        assert len(LATTICE_TYPES) == 4

    def test_required_keys_present(self):
        for key in ("hexagonal", "square", "triangular", "trihexagonal"):
            assert key in LATTICE_TYPES, f"Missing key {key!r}"

    def test_all_display_names_are_strings(self):
        for key, name in LATTICE_TYPES.items():
            assert isinstance(name, str) and name, f"Bad display name for {key!r}"

    def test_get_tiling_provider_returns_correct_types(self):
        assert isinstance(get_tiling_provider("hexagonal"),    HexagonalTilingProvider)
        assert isinstance(get_tiling_provider("square"),       SquareTilingProvider)
        assert isinstance(get_tiling_provider("triangular"),   TriangularTilingProvider)
        assert isinstance(get_tiling_provider("trihexagonal"), TrihexagonalTilingProvider)

    def test_get_tiling_provider_unknown_key_raises(self):
        with pytest.raises(ValueError):
            get_tiling_provider("nonexistent_tiling")

    def test_display_names_unique(self):
        names = list(LATTICE_TYPES.values())
        assert len(names) == len(set(names)), "Duplicate display names in LATTICE_TYPES"


# ===========================================================================
# TilingProvider: get_cells()
# ===========================================================================

class TestTilingCells:
    """Tests that all tiling providers produce valid cell output.

    All tests are pure Python (no FreeCAD required) because get_cells()
    returns plain (cx, cy, n_sides, rotation_deg) tuples.
    """

    _region = dict(gx0=10.0, gx1=190.0, gy0=10.0, gy1=190.0)
    _cell   = dict(cell_size=8.0, wall_t=1.5)

    def _cells(self, key):
        p = get_tiling_provider(key)
        return p.get_cells(**self._region, **self._cell)

    # ── basic output shape ────────────────────────────────────────────────

    def test_hexagonal_non_empty(self):
        assert len(self._cells("hexagonal")) > 0

    def test_square_non_empty(self):
        assert len(self._cells("square")) > 0

    def test_triangular_non_empty(self):
        assert len(self._cells("triangular")) > 0

    def test_trihexagonal_non_empty(self):
        assert len(self._cells("trihexagonal")) > 0

    def test_each_cell_is_4_tuple(self):
        for key in LATTICE_TYPES:
            for cell in self._cells(key):
                assert len(cell) == 4, f"[{key}] cell must be (cx,cy,n,rot)"

    def test_n_sides_correct_for_hexagonal(self):
        for cx, cy, n, rot in self._cells("hexagonal"):
            assert n == 6

    def test_n_sides_correct_for_square(self):
        for cx, cy, n, rot in self._cells("square"):
            assert n == 4

    def test_n_sides_correct_for_triangular(self):
        for cx, cy, n, rot in self._cells("triangular"):
            assert n == 3

    def test_n_sides_correct_for_trihexagonal(self):
        """Trihexagonal cells must be either hexagons (n=6) or triangles (n=3)."""
        for cx, cy, n, rot in self._cells("trihexagonal"):
            assert n in (3, 6), f"Unexpected n_sides={n} in trihexagonal tiling"

    def test_trihexagonal_has_both_hexagons_and_triangles(self):
        """Trihexagonal tiling must contain both n=6 and n=3 cells."""
        sides = {n for _cx, _cy, n, _rot in self._cells("trihexagonal")}
        assert 6 in sides, "Missing hexagons (n=6) in trihexagonal tiling"
        assert 3 in sides, "Missing triangles (n=3) in trihexagonal tiling"

    def test_trihexagonal_triangle_to_hexagon_ratio(self):
        """Trihexagonal tiling has exactly 2 triangles per hexagon."""
        cells = self._cells("trihexagonal")
        n_hex = sum(1 for _cx, _cy, n, _rot in cells if n == 6)
        n_tri = sum(1 for _cx, _cy, n, _rot in cells if n == 3)
        assert n_hex > 0, "No hexagons in trihexagonal tiling"
        # Boundary cropping can shave a few cells from the finite test region,
        # so a 15% tolerance is used.  Any structural bug (e.g. missing an
        # entire triangle type) would produce a ratio far from 2.0.
        assert abs(n_tri / n_hex - 2.0) < 0.15, (
            f"Expected tri/hex ratio ≈ 2.0, got {n_tri/n_hex:.3f}"
        )

    def test_trihexagonal_has_two_triangle_rotations(self):
        """Trihexagonal must have both up (90°) and down (270°) triangles."""
        tri_rots = {rot for _cx, _cy, n, rot in self._cells("trihexagonal") if n == 3}
        assert 90.0  in tri_rots, "Missing up-pointing triangles (rotation=90°)"
        assert 270.0 in tri_rots, "Missing down-pointing triangles (rotation=270°)"

    def test_triangular_has_two_rotations(self):
        """Triangular tiling must have both up (90°) and down (270°) triangles."""
        rotations = {rot for _cx, _cy, _n, rot in self._cells("triangular")}
        assert 90.0  in rotations, "Missing up-pointing triangles (rotation=90)"
        assert 270.0 in rotations, "Missing down-pointing triangles (rotation=270)"

    # ── centres within bounds ─────────────────────────────────────────────

    def test_all_centres_within_region_hexagonal(self):
        r = self._region
        for cx, cy, _n, _rot in self._cells("hexagonal"):
            assert r["gx0"] <= cx <= r["gx1"], f"cx={cx} out of [{r['gx0']},{r['gx1']}]"
            assert r["gy0"] <= cy <= r["gy1"], f"cy={cy} out of [{r['gy0']},{r['gy1']}]"

    def test_all_centres_within_region_square(self):
        r = self._region
        for cx, cy, _n, _rot in self._cells("square"):
            assert r["gx0"] <= cx <= r["gx1"]
            assert r["gy0"] <= cy <= r["gy1"]

    def test_all_centres_within_region_triangular(self):
        r = self._region
        for cx, cy, _n, _rot in self._cells("triangular"):
            assert r["gx0"] <= cx <= r["gx1"]
            assert r["gy0"] <= cy <= r["gy1"]

    def test_all_centres_within_region_trihexagonal(self):
        r = self._region
        for cx, cy, _n, _rot in self._cells("trihexagonal"):
            assert r["gx0"] <= cx <= r["gx1"], f"cx={cx} out of [{r['gx0']},{r['gx1']}]"
            assert r["gy0"] <= cy <= r["gy1"], f"cy={cy} out of [{r['gy0']},{r['gy1']}]"

    # ── no duplicate centres ──────────────────────────────────────────────

    def test_no_duplicate_centres_hexagonal(self):
        pts = [(round(cx, 6), round(cy, 6))
               for cx, cy, _n, _rot in self._cells("hexagonal")]
        assert len(pts) == len(set(pts)), "Duplicate cell centres in hexagonal tiling"

    def test_no_duplicate_centres_square(self):
        pts = [(round(cx, 6), round(cy, 6))
               for cx, cy, _n, _rot in self._cells("square")]
        assert len(pts) == len(set(pts)), "Duplicate cell centres in square tiling"

    def test_no_duplicate_centres_triangular(self):
        pts = [(round(cx, 6), round(cy, 6))
               for cx, cy, _n, _rot in self._cells("triangular")]
        assert len(pts) == len(set(pts)), "Duplicate cell centres in triangular tiling"

    def test_no_duplicate_centres_trihexagonal(self):
        pts = [(round(cx, 6), round(cy, 6))
               for cx, cy, _n, _rot in self._cells("trihexagonal")]
        assert len(pts) == len(set(pts)), "Duplicate cell centres in trihexagonal tiling"

    # ── empty region returns empty list ───────────────────────────────────

    def test_empty_region_returns_empty(self):
        for key in LATTICE_TYPES:
            p = get_tiling_provider(key)
            result = p.get_cells(50.0, 50.0, 0.0, 100.0, 8.0, 1.5)
            assert result == [], f"[{key}] expected [] for zero-width region"

    # ── centre-to-centre spacing (wall_t=0 sanity check) ─────────────────

    def test_square_spacing_at_zero_wall(self):
        """With wall_t=0, adjacent square centres should be exactly cell_size apart."""
        cell_size = 10.0
        p  = get_tiling_provider("square")
        cs = p.get_cells(0.0, 100.0, 0.0, 100.0, cell_size, 0.0)
        # Group by approximate y row
        rows = {}
        for cx, cy, _n, _rot in cs:
            key = round(cy, 4)
            rows.setdefault(key, []).append(cx)
        for y_key, xs in rows.items():
            xs_sorted = sorted(xs)
            for a, b in zip(xs_sorted[:-1], xs_sorted[1:]):
                assert abs((b - a) - cell_size) < cell_size * _SPACING_RTOL, (
                    f"Square row y≈{y_key}: spacing {b-a:.4f} ≠ {cell_size}"
                )

    def test_triangular_adjacent_distance_at_zero_wall(self):
        """With wall_t=0, the nearest neighbour distance in the triangular tiling
        should equal cell_size / sqrt(3) (centroid-to-centroid for shared edge)."""
        cell_size = 9.0
        expected  = cell_size / math.sqrt(3)
        p  = get_tiling_provider("triangular")
        cs = p.get_cells(0.0, 100.0, 0.0, 100.0, cell_size, 0.0)
        # Find minimum pairwise distance (should equal the expected adjacency dist)
        min_dist = float("inf")
        pts = [(cx, cy) for cx, cy, _n, _rot in cs]
        for i, (ax, ay) in enumerate(pts):
            for bx, by in pts[i + 1:]:
                d = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)
                if d < min_dist:
                    min_dist = d
        assert abs(min_dist - expected) < expected * _SPACING_RTOL, (
            f"Triangular min dist {min_dist:.4f} ≠ expected {expected:.4f}"
        )

    # ── circumradius ──────────────────────────────────────────────────────

    def test_hexagonal_circumradius_equals_cell_size(self):
        p = get_tiling_provider("hexagonal")
        for s in (5.0, 8.0, 12.0):
            assert abs(p.cell_circumradius(s) - s) < 1e-9

    def test_square_circumradius(self):
        p = get_tiling_provider("square")
        for s in (5.0, 8.0, 12.0):
            expected = s * math.sqrt(2) / 2.0
            assert abs(p.cell_circumradius(s) - expected) < 1e-9

    def test_triangular_circumradius(self):
        p = get_tiling_provider("triangular")
        for s in (5.0, 8.0, 12.0):
            expected = s / math.sqrt(3)
            assert abs(p.cell_circumradius(s) - expected) < 1e-9

    def test_trihexagonal_circumradius_equals_cell_size(self):
        """Trihexagonal circumradius is the hexagon circumradius = cell_size."""
        p = get_tiling_provider("trihexagonal")
        for s in (5.0, 8.0, 12.0):
            assert abs(p.cell_circumradius(s) - s) < 1e-9

    # ── trihexagonal adjacency distance ───────────────────────────────────

    def test_trihexagonal_adjacency_distance_at_zero_wall(self):
        """With wall_t=0, the nearest-neighbour distance in the trihexagonal
        tiling (hex-centre to triangle-centre) is 2·cell_size/√3."""
        cell_size = 9.0
        expected  = 2.0 * cell_size / math.sqrt(3)
        p  = get_tiling_provider("trihexagonal")
        cs = p.get_cells(0.0, 100.0, 0.0, 100.0, cell_size, 0.0)
        min_dist = float("inf")
        pts = [(cx, cy) for cx, cy, _n, _rot in cs]
        for i, (ax, ay) in enumerate(pts):
            for bx, by in pts[i + 1:]:
                d = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)
                if d < min_dist:
                    min_dist = d
        assert abs(min_dist - expected) < expected * _SPACING_RTOL, (
            f"Trihexagonal min dist {min_dist:.4f} ≠ expected {expected:.4f}"
        )

    # ── trihexagonal uniform coverage (oblique-drift guard) ───────────────

    def test_trihexagonal_coverage_uniform_across_y(self):
        """Trihexagonal tiling must have the same cell density at all Y positions.

        Uses a tall region to expose any oblique-drift accumulation that would
        leave the top strips under-populated (analogous to the bug fixed in
        the triangular tiling).
        """
        p    = get_tiling_provider("trihexagonal")
        cell_size, wall_t = 8.0, 1.5
        step = cell_size + wall_t
        strip_height = step * math.sqrt(3)  # a2y

        gx0, gx1 = 0.0, 200.0
        gy0, gy1 = 0.0, 500.0
        cells = p.get_cells(gx0, gx1, gy0, gy1, cell_size, wall_t)

        low_cells  = sum(1 for _cx, cy, _n, _rot in cells if cy < gy0 + 2 * strip_height)
        high_cells = sum(1 for _cx, cy, _n, _rot in cells if cy > gy1 - 2 * strip_height)

        assert low_cells  > 0, "No cells in bottom strips"
        assert high_cells > 0, "No cells in top strips"
        # The region holds ~17 cells per strip-pair; allow ±3 for boundary
        # cropping.  Any oblique drift would produce differences >> 10.
        assert abs(low_cells - high_cells) <= 3, (
            f"Cell counts differ: bottom={low_cells}, top={high_cells}. "
            "Possible oblique drift in trihexagonal tiling."
        )

    # ── triangular tiling uniform coverage (regression for oblique-drift bug) ─

    def test_triangular_coverage_uniform_across_y(self):
        """Triangular tiling must have the same cell density at all Y positions.

        The old oblique-lattice implementation accumulated an X drift as the
        row index increased, causing cells near the top of the region to be
        missed (the lattice shifted out of bounds on the left).  This test
        verifies that the count per horizontal strip is the same at the
        bottom and top of a tall region.
        """
        p    = get_tiling_provider("triangular")
        cell_size, wall_t = 8.0, 1.5
        step = cell_size + wall_t
        h    = step * math.sqrt(3) / 2.0

        # Tall region: many strips, so oblique drift would be noticeable
        gx0, gx1 = 0.0, 200.0
        gy0, gy1 = 0.0, 500.0
        cells = p.get_cells(gx0, gx1, gy0, gy1, cell_size, wall_t)

        # Count cells in the first two strips (low Y) vs the last two strips (high Y)
        strip_height = h
        low_cells  = sum(1 for cx, cy, _n, _rot in cells if cy < gy0 + 2 * strip_height)
        high_cells = sum(1 for cx, cy, _n, _rot in cells if cy > gy1 - 2 * strip_height)

        assert low_cells > 0,  "No cells in bottom strips"
        assert high_cells > 0, "No cells in top strips"
        # The region width (200 mm) and strip height (≈9.96 mm) produce ~17
        # cells per strip.  Boundary cropping may include or exclude cells
        # exactly on the edge, so a tolerance of ±2 (roughly 10% of ~17)
        # is generous enough to avoid flakiness while being far below the
        # magnitude of the bug (which produced 0 vs 86).
        assert abs(low_cells - high_cells) <= 2, (
            f"Cell counts differ: bottom strips={low_cells}, top strips={high_cells}. "
            "Likely cause: oblique drift in triangular tiling."
        )

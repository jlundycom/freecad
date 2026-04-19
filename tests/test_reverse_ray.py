"""
tests/test_reverse_ray.py
-------------------------
Pure-Python unit tests for helpers in reverse_ray_core.
"""

import os
import sys

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import pytest

from freecad.HexLatticeMaker.reverse_ray_core import (
    line_cylinder_intersection_2d,
    dedupe_angles,
    validate_reverse_ray_params,
)


class TestLineCylinderIntersection2D:
    def test_intersects_positive_x(self):
        p = line_cylinder_intersection_2d((0.0, 0.0), (10.0, 0.0), 5.0)
        assert p == pytest.approx((5.0, 0.0))

    def test_intersects_negative_x(self):
        p = line_cylinder_intersection_2d((0.0, 0.0), (-1.0, 0.0), 5.0)
        assert p == pytest.approx((-5.0, 0.0))

    def test_no_intersection_for_zero_direction(self):
        assert line_cylinder_intersection_2d((1.0, 2.0), (1.0, 2.0), 5.0) is None

    def test_no_forward_intersection_when_pointing_away(self):
        assert line_cylinder_intersection_2d((10.0, 0.0), (20.0, 0.0), 5.0) is None


class TestDedupeAngles:
    def test_dedupes_same_angular_bucket(self):
        pts = [(5.0, 0.0), (4.9, 0.05), (0.0, 5.0)]
        unique = dedupe_angles(pts, (0.0, 0.0), min_step_rad=0.2)
        assert len(unique) == 2

    def test_empty_input(self):
        assert dedupe_angles([], (0.0, 0.0), min_step_rad=0.1) == []


class TestValidateReverseRayParams:
    def test_valid_params(self):
        errs = validate_reverse_ray_params(40.0, 120.0, 2.0, 0.75, 8)
        assert errs == []

    def test_invalid_params(self):
        errs = validate_reverse_ray_params(-1.0, 0.0, 2.0, 0.0, 0)
        assert any("cylinder_radius" in e for e in errs)
        assert any("cylinder_height" in e for e in errs)
        assert any("slot_radius" in e for e in errs)
        assert any("samples_per_edge" in e for e in errs)

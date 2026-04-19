"""
reverse_ray_core.py
-------------------
Reverse ray-tracing helper for cylindrical shadow models.

Given edge points from a 2D source shape (Sketch/SVG) and a light point,
this module computes where rays intersect a vertical cylinder and can build
a printable cylindrical shell with ray tunnels cut through the wall.
"""

import math


def line_cylinder_intersection_2d(
    light_xy: tuple,
    target_xy: tuple,
    radius: float,
    center_xy: tuple = (0.0, 0.0),
):
    """Return the first forward intersection of a 2D line ray with a circle.

    Parameters
    ----------
    light_xy : (x, y)
        Ray origin in XY.
    target_xy : (x, y)
        A point defining the ray direction (ray is light -> target).
    radius : float
        Circle radius.
    center_xy : (x, y)
        Circle center in XY.

    Returns
    -------
    (x, y) tuple or None
        First intersection for t > 0 on ``light + t*(target-light)``.
        Returns None when no forward intersection exists.
    """
    lx, ly = float(light_xy[0]), float(light_xy[1])
    tx, ty = float(target_xy[0]), float(target_xy[1])
    cx, cy = float(center_xy[0]), float(center_xy[1])

    dx = tx - lx
    dy = ty - ly
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return None

    ox = lx - cx
    oy = ly - cy
    a = dx * dx + dy * dy
    b = 2.0 * (ox * dx + oy * dy)
    c = ox * ox + oy * oy - float(radius) * float(radius)

    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None

    sqrt_disc = math.sqrt(max(0.0, disc))
    t1 = (-b - sqrt_disc) / (2.0 * a)
    t2 = (-b + sqrt_disc) / (2.0 * a)
    ts = [t for t in (t1, t2) if t > 1e-9]
    if not ts:
        return None
    t = min(ts)
    return (lx + t * dx, ly + t * dy)


def dedupe_angles(points_xy: list, center_xy: tuple, min_step_rad: float) -> list:
    """Deduplicate XY points by polar angle around ``center_xy``.

    Keeps one representative point per angular bucket.
    """
    if not points_xy:
        return []
    step = max(float(min_step_rad), 1e-6)
    cx, cy = float(center_xy[0]), float(center_xy[1])
    buckets = {}
    for x, y in points_xy:
        a = math.atan2(y - cy, x - cx)
        key = int(round(a / step))
        if key not in buckets:
            buckets[key] = (x, y)
    return list(buckets.values())


def validate_reverse_ray_params(
    cylinder_radius: float,
    cylinder_height: float,
    wall_thickness: float,
    slot_radius: float,
    samples_per_edge: int,
) -> list:
    """Validate reverse-ray model parameters."""
    errors = []
    if cylinder_radius <= 0.0:
        errors.append("cylinder_radius must be positive")
    if cylinder_height <= 0.0:
        errors.append("cylinder_height must be positive")
    if wall_thickness <= 0.0:
        errors.append("wall_thickness must be positive")
    if cylinder_radius > 0.0 and wall_thickness >= cylinder_radius:
        errors.append("wall_thickness must be less than cylinder_radius")
    if slot_radius <= 0.0:
        errors.append("slot_radius must be positive")
    if samples_per_edge < 1:
        errors.append("samples_per_edge must be >= 1")
    return errors


def create_reverse_ray_cylinder(
    image_shape,
    light_point,
    cylinder_radius: float = 40.0,
    cylinder_height: float = 120.0,
    wall_thickness: float = 2.0,
    slot_radius: float = 0.75,
    samples_per_edge: int = 8,
    cylinder_center_xy: tuple = None,
    cylinder_base_z: float = 0.0,
):
    """Build a cylindrical shell cut by reverse ray tunnels.

    Parameters
    ----------
    image_shape
        FreeCAD shape containing source edges (Sketch/SVG).
    light_point
        FreeCAD vector-like object with x/y/z.
    """
    import Part
    import FreeCAD as App

    errs = validate_reverse_ray_params(
        cylinder_radius, cylinder_height, wall_thickness, slot_radius, samples_per_edge
    )
    if errs:
        raise ValueError("; ".join(errs))

    if image_shape is None or not hasattr(image_shape, "Edges") or not image_shape.Edges:
        raise ValueError("image_shape must provide at least one edge")

    cx, cy = (0.0, 0.0) if cylinder_center_xy is None else cylinder_center_xy
    base = App.Vector(float(cx), float(cy), float(cylinder_base_z))
    axis = App.Vector(0.0, 0.0, 1.0)

    outer = Part.makeCylinder(float(cylinder_radius), float(cylinder_height), base, axis)
    inner_r = float(cylinder_radius) - float(wall_thickness)
    inner = Part.makeCylinder(inner_r, float(cylinder_height) + 1e-3, base, axis)
    shell = outer.cut(inner)

    lx, ly = float(light_point.x), float(light_point.y)
    hit_points = []
    for edge in image_shape.Edges:
        try:
            pts = edge.discretize(Number=int(samples_per_edge) + 1)
        except Exception:
            continue
        for p in pts:
            hit = line_cylinder_intersection_2d(
                (lx, ly),
                (float(p.x), float(p.y)),
                float(cylinder_radius),
                (float(cx), float(cy)),
            )
            if hit is not None:
                hit_points.append(hit)

    min_angle = float(slot_radius) / max(float(cylinder_radius), 1e-9)
    hit_points = dedupe_angles(hit_points, (float(cx), float(cy)), min_angle)
    if not hit_points:
        return shell

    cutters = []
    for hx, hy in hit_points:
        cutter = Part.makeCylinder(
            float(slot_radius),
            float(cylinder_height) + 0.5,
            App.Vector(float(hx), float(hy), float(cylinder_base_z) - 0.25),
            axis,
        )
        cutters.append(cutter)

    if not cutters:
        return shell

    cut_union = cutters[0]
    for c in cutters[1:]:
        cut_union = cut_union.fuse(c)
    return shell.cut(cut_union)

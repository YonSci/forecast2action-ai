import pytest

from app.data_pipeline.infrastructure_data_pipeline import (
    GRID_SHAPE,
    _in_grid,
    _km_per_degree_lon,
    _pixel_index,
    rasterize_health_facility_counts,
    rasterize_road_length_km,
)


def test_pixel_index_maps_known_real_coordinates_correctly():
    # Grid: LON_MIN=33, LAT_MAX=15, 0.25deg cells, shape (48, 60).
    # A point just inside the NW corner is (row 0, col 0); a point in the
    # SE corner is the last real row/col.
    assert _pixel_index(14.99, 33.01) == (0, 0)
    row, col = _pixel_index(3.01, 47.99)
    assert row == GRID_SHAPE[0] - 1
    assert col == GRID_SHAPE[1] - 1
    assert _in_grid(row, col) is True
    # Outside Ethiopia's real bounding box entirely -- must not be in-grid.
    assert _in_grid(*_pixel_index(20.0, 33.0)) is False


def test_rasterize_health_facility_counts_sums_real_points_per_pixel():
    points = [
        {"lat": 9.03, "lon": 38.74},  # Addis Ababa area
        {"lat": 9.03, "lon": 38.74},  # same real pixel -- must accumulate, not overwrite
        {"lat": 14.0, "lon": 40.0},  # a different real pixel
    ]
    counts = rasterize_health_facility_counts(points)

    assert counts.sum() == 3.0
    assert counts.max() == 2.0  # the 2 Addis Ababa points landed in the same pixel


def test_rasterize_road_length_km_preserves_real_total_segment_length():
    # A single real straight segment along the equator-adjacent latitude
    # band -- interval sampling must not lose or double-count length: the
    # raster's total sum should equal the segment's own real geodesic
    # length (within float rounding), regardless of how many pixels it
    # crosses.
    lat1, lon1 = 9.0, 38.0
    lat2, lon2 = 9.0, 39.0  # 1 real degree of longitude at this latitude
    expected_km = _km_per_degree_lon((lat1 + lat2) / 2.0) * abs(lon2 - lon1)

    length_km = rasterize_road_length_km([[{"lat": lat1, "lon": lon1}, {"lat": lat2, "lon": lon2}]])

    assert length_km.sum() == pytest.approx(expected_km, rel=1e-2)


def test_rasterize_road_length_km_ignores_points_outside_the_real_grid():
    length_km = rasterize_road_length_km([[{"lat": 40.0, "lon": 40.0}, {"lat": 41.0, "lon": 41.0}]])

    assert length_km.sum() == 0.0
    assert length_km.shape == GRID_SHAPE

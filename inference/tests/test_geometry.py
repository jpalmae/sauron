import numpy as np

from sauron_inference.rules.geometry import (
    bbox_area,
    cosine_similarity,
    point_in_polygon,
    polygon_area,
    segment_crosses_line,
)

SQUARE = np.array([[0, 0], [100, 0], [100, 100], [0, 100]], dtype=np.float32)


def test_point_in_polygon():
    assert point_in_polygon((50, 50), SQUARE)
    assert not point_in_polygon((150, 50), SQUARE)
    assert point_in_polygon((0, 50), SQUARE)  # edge counts as inside


def test_segment_crosses_line():
    a, b = (0, 0), (100, 0)
    assert segment_crosses_line((50, -10), (50, 10), a, b)
    assert segment_crosses_line((50, 10), (50, -10), a, b)
    assert not segment_crosses_line((50, 5), (50, 10), a, b)
    assert not segment_crosses_line((50, 0), (60, 5), a, b)  # on the line: no crossing


def test_cosine_similarity():
    assert cosine_similarity(np.array([1, 0]), np.array([1, 0])) == 1.0
    assert cosine_similarity(np.array([1, 0]), np.array([-1, 0])) == -1.0
    assert abs(cosine_similarity(np.array([1, 0]), np.array([0, 1]))) < 1e-9
    assert cosine_similarity(np.array([0, 0]), np.array([1, 0])) == 0.0


def test_polygon_and_bbox_area():
    assert polygon_area(SQUARE) == 10000
    assert bbox_area((0, 0, 10, 20)) == 200
    assert bbox_area((10, 10, 5, 5)) == 0

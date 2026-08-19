from sauron_deepstream.calibration import calibration_report, validate_calibration
from sauron_deepstream.domain import ROIConfig


def test_valid_calibration_has_no_errors():
    roi = ROIConfig.model_validate(
        {
            "lines": [
                {
                    "id": "L1",
                    "points": [[100, 300], [1100, 300]],
                    "direction": [0, 1],
                }
            ],
            "polygons": [
                {
                    "id": "lane",
                    "points": [[100, 100], [1100, 100], [1100, 650], [100, 650]],
                    "rules": ["stopped", "congestion"],
                }
            ],
            "homography": {
                "src_points": [[200, 200], [1000, 200], [1100, 600], [100, 600]],
                "dst_points": [[0, 0], [12, 0], [12, 40], [0, 40]],
            },
        }
    )
    report = calibration_report(roi, 1280, 720)
    assert report["passed"] is True
    assert report["errors"] == 0


def test_flags_wrong_way_without_direction_and_outside_points():
    roi = ROIConfig.model_validate(
        {
            "lines": [{"id": "same", "points": [[-1, 2], [2, 2]]}],
            "polygons": [
                {
                    "id": "same",
                    "points": [[1, 1], [30, 1], [30, 20]],
                    "rules": ["wrong_way"],
                }
            ],
        }
    )
    codes = {issue.code for issue in validate_calibration(roi, 100, 100)}
    assert "point_outside_frame" in codes
    assert "duplicate_id" in codes
    assert "missing_direction" in codes
    assert "missing_homography" in codes


def test_flags_line_parallel_to_flow():
    roi = ROIConfig.model_validate(
        {
            "lines": [
                {"id": "L1", "points": [[10, 10], [90, 10]], "direction": [1, 0]}
            ]
        }
    )
    codes = {issue.code for issue in validate_calibration(roi, 100, 100)}
    assert "line_parallel_to_flow" in codes

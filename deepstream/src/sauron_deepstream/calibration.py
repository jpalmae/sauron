from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np

from .domain import ROIConfig


@dataclass(frozen=True, slots=True)
class CalibrationIssue:
    severity: Literal["error", "warning"]
    code: str
    target: str
    message: str


def _inside_frame(point: tuple[float, float], width: int, height: int) -> bool:
    return 0 <= point[0] <= width and 0 <= point[1] <= height


def _polygon_area(points: list[tuple[float, float]]) -> float:
    polygon = np.asarray(points, dtype=np.float64)
    x = polygon[:, 0]
    y = polygon[:, 1]
    return abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))) / 2


def _direction_issues(
    target: str,
    direction: tuple[float, float] | None,
    *,
    line_vector: tuple[float, float] | None = None,
) -> list[CalibrationIssue]:
    if direction is None:
        return []
    magnitude = math.hypot(*direction)
    if magnitude < 0.5:
        return [
            CalibrationIssue(
                "error", "direction_too_small", target, "Direction vector is near zero."
            )
        ]
    if line_vector is None:
        return []
    line_magnitude = math.hypot(*line_vector)
    if line_magnitude == 0:
        return []
    cosine = abs(
        (direction[0] * line_vector[0] + direction[1] * line_vector[1])
        / (magnitude * line_magnitude)
    )
    if cosine > 0.7:
        return [
            CalibrationIssue(
                "warning",
                "line_parallel_to_flow",
                target,
                "Counting line is nearly parallel to the configured flow direction.",
            )
        ]
    return []


def validate_calibration(roi: ROIConfig, width: int, height: int) -> list[CalibrationIssue]:
    if width <= 0 or height <= 0:
        raise ValueError("frame width and height must be positive")
    issues: list[CalibrationIssue] = []
    frame_area = width * height
    diagonal = math.hypot(width, height)

    identifiers: set[str] = set()
    for line in roi.lines:
        target = f"line:{line.id}"
        if line.id in identifiers:
            issues.append(CalibrationIssue("error", "duplicate_id", target, "ROI id is duplicated."))
        identifiers.add(line.id)
        if any(not _inside_frame(point, width, height) for point in line.points):
            issues.append(
                CalibrationIssue(
                    "error", "point_outside_frame", target, "Line contains a point outside the frame."
                )
            )
        vector = (
            line.points[1][0] - line.points[0][0],
            line.points[1][1] - line.points[0][1],
        )
        if math.hypot(*vector) < diagonal * 0.05:
            issues.append(
                CalibrationIssue(
                    "warning",
                    "line_too_short",
                    target,
                    "Counting line covers less than 5% of the frame diagonal.",
                )
            )
        issues.extend(_direction_issues(target, line.direction, line_vector=vector))

    for polygon in roi.polygons:
        target = f"polygon:{polygon.id}"
        if polygon.id in identifiers:
            issues.append(CalibrationIssue("error", "duplicate_id", target, "ROI id is duplicated."))
        identifiers.add(polygon.id)
        if any(not _inside_frame(point, width, height) for point in polygon.points):
            issues.append(
                CalibrationIssue(
                    "error",
                    "point_outside_frame",
                    target,
                    "Polygon contains a point outside the frame.",
                )
            )
        area = _polygon_area(polygon.points)
        if area < frame_area * 0.01:
            issues.append(
                CalibrationIssue(
                    "warning",
                    "polygon_too_small",
                    target,
                    "Polygon covers less than 1% of the frame.",
                )
            )
        if "wrong_way" in polygon.rules and polygon.direction is None:
            issues.append(
                CalibrationIssue(
                    "error",
                    "missing_direction",
                    target,
                    "Wrong-way analytics requires a permitted flow direction.",
                )
            )
        issues.extend(_direction_issues(target, polygon.direction))

    if roi.homography:
        target = "homography"
        source_area = _polygon_area(roi.homography.src_points)
        destination_area = _polygon_area(roi.homography.dst_points)
        if any(
            not _inside_frame(point, width, height) for point in roi.homography.src_points
        ):
            issues.append(
                CalibrationIssue(
                    "error",
                    "point_outside_frame",
                    target,
                    "Homography source contains a point outside the frame.",
                )
            )
        if source_area < frame_area * 0.005 or destination_area <= 0:
            issues.append(
                CalibrationIssue(
                    "error",
                    "degenerate_homography",
                    target,
                    "Homography points do not define a usable calibration surface.",
                )
            )
    else:
        issues.append(
            CalibrationIssue(
                "warning",
                "missing_homography",
                "homography",
                "Speed metrics are unavailable until real-world calibration is defined.",
            )
        )
    if not roi.lines and not roi.polygons:
        issues.append(
            CalibrationIssue(
                "error", "empty_roi", "roi", "At least one line or polygon is required."
            )
        )
    return issues


def calibration_report(roi: ROIConfig, width: int, height: int) -> dict[str, object]:
    issues = validate_calibration(roi, width, height)
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    return {
        "schema_version": 1,
        "passed": errors == 0,
        "frame": {"width": width, "height": height},
        "errors": errors,
        "warnings": warnings,
        "issues": [asdict(issue) for issue in issues],
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Sauron calibration report",
        "",
        f"**Result: {'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"Errors: {report['errors']} · Warnings: {report['warnings']}",
        "",
        "| Severity | Target | Code | Detail |",
        "| --- | --- | --- | --- |",
    ]
    issues = cast(list[dict[str, Any]], report["issues"])
    for issue in issues:
        lines.append(
            "| {severity} | {target} | {code} | {message} |".format(**issue)
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a Sauron camera calibration")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.config.read_text(encoding="utf-8"))
    roi = ROIConfig.model_validate(payload.get("roi_config", payload))
    report = calibration_report(roi, args.width, args.height)
    markdown = render_markdown(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 2)


if __name__ == "__main__":
    main()

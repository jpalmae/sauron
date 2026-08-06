import { describe, expect, it } from "vitest";
import {
  centroid,
  directionFromClick,
  distToSegment,
  hitTestLine,
  homographyDst,
  pointInPolygon,
} from "./roi";

const SQUARE: [number, number][] = [
  [0, 0],
  [100, 0],
  [100, 100],
  [0, 100],
];

describe("geometry", () => {
  it("centroid", () => {
    expect(centroid(SQUARE)).toEqual([50, 50]);
  });

  it("pointInPolygon", () => {
    expect(pointInPolygon([50, 50], SQUARE)).toBe(true);
    expect(pointInPolygon([150, 50], SQUARE)).toBe(false);
  });

  it("distToSegment", () => {
    expect(distToSegment([50, 10], [0, 0], [100, 0])).toBe(10);
    expect(distToSegment([-10, 0], [0, 0], [100, 0])).toBe(10); // clamps to endpoint
  });

  it("hitTestLine with tolerance", () => {
    const line = { id: "L1", points: [[0, 0], [100, 0]] as [number, number][] };
    expect(hitTestLine([50, 5], line, 8)).toBe(true);
    expect(hitTestLine([50, 20], line, 8)).toBe(false);
  });

  it("directionFromClick returns unit vector", () => {
    const d = directionFromClick([0, 0], [10, 0]);
    expect(d[0]).toBeCloseTo(1);
    expect(d[1]).toBeCloseTo(0);
    const diag = directionFromClick([0, 0], [10, 10]);
    expect(Math.hypot(...diag)).toBeCloseTo(1, 1);
  });

  it("directionFromClick degenerate defaults to +x", () => {
    expect(directionFromClick([5, 5], [5, 5])).toEqual([1, 0]);
  });

  it("homographyDst builds a rectangle in meters", () => {
    expect(homographyDst(25, 10)).toEqual([
      [0, 0],
      [25, 0],
      [25, 10],
      [0, 10],
    ]);
  });
});

import type { RoiLine, RoiPolygon } from "./api";

export type Pt = [number, number];

export function centroid(points: Pt[]): Pt {
  const n = Math.max(points.length, 1);
  return [
    points.reduce((s, p) => s + p[0], 0) / n,
    points.reduce((s, p) => s + p[1], 0) / n,
  ];
}

export function lineMid(line: RoiLine): Pt {
  const [a, b] = line.points;
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
}

export function pointInPolygon(p: Pt, polygon: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    const intersect =
      yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export function distToSegment(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.hypot(p[0] - a[0], p[1] - a[1]);
  let t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

/** Unit-ish direction vector from an anchor point toward a clicked point. */
export function directionFromClick(anchor: Pt, click: Pt): Pt {
  const dx = click[0] - anchor[0];
  const dy = click[1] - anchor[1];
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) return [1, 0];
  return [Math.round((dx / len) * 100) / 100, Math.round((dy / len) * 100) / 100];
}

export function hitTestPolygon(p: Pt, poly: RoiPolygon): boolean {
  return pointInPolygon(p, poly.points as Pt[]);
}

export function hitTestLine(p: Pt, line: RoiLine, tolerance = 8): boolean {
  if (line.points.length < 2) return false;
  return distToSegment(p, line.points[0] as Pt, line.points[1] as Pt) <= tolerance;
}

/** Rectangle dst_points (meters) for a homography given real-world w x h. */
export function homographyDst(widthM: number, heightM: number): Pt[] {
  return [
    [0, 0],
    [widthM, 0],
    [widthM, heightM],
    [0, heightM],
  ];
}

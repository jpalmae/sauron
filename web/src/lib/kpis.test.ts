import { describe, expect, it } from "vitest";
import type { KpiRow } from "./api";
import { congestionSeries, pivotCounts, speedSeries } from "./kpis";

const row = (
  bucket: string,
  cls: string | null,
  count: number,
  speed: number | null = null,
  congestion = 0,
): KpiRow => ({
  bucket,
  camera_id: "cam-1",
  vehicle_class: cls,
  total_count: count,
  avg_speed_kmh: speed,
  congestion_minutes: congestion,
});

describe("pivotCounts", () => {
  it("pivots class rows into per-bucket columns", () => {
    const rows = [
      row("2026-08-06T10:00:00Z", "car", 10),
      row("2026-08-06T10:00:00Z", "truck", 3),
      row("2026-08-06T11:00:00Z", "car", 7),
      row("2026-08-06T11:00:00Z", null, 0, null, 5), // congestion row: ignored
    ];
    const out = pivotCounts(rows, "hour");
    expect(out).toHaveLength(2);
    expect(out[0].car).toBe(10);
    expect(out[0].truck).toBe(3);
    expect(out[0].total).toBe(13);
    expect(out[1].car).toBe(7);
    expect(out[0].label).toMatch(/:00$/);
  });

  it("ignores unknown classes", () => {
    const out = pivotCounts([row("2026-08-06T10:00:00Z", "spaceship", 9)], "hour");
    expect(out[0].total).toBe(0);
  });
});

describe("speedSeries", () => {
  it("computes count-weighted average speed", () => {
    const rows = [
      row("2026-08-06T10:00:00Z", "car", 3, 60),
      row("2026-08-06T10:00:00Z", "truck", 1, 40),
    ];
    const out = speedSeries(rows, "hour");
    expect(out[0].avg_speed_kmh).toBeCloseTo(55); // (3*60 + 1*40)/4
  });

  it("skips buckets with no counted vehicles", () => {
    const out = speedSeries([row("2026-08-06T10:00:00Z", "car", 0, 60)], "hour");
    expect(out).toHaveLength(0);
  });
});

describe("congestionSeries", () => {
  it("sums congestion minutes from null-class rows only", () => {
    const rows = [
      row("2026-08-06T10:00:00Z", null, 0, null, 12),
      row("2026-08-06T10:00:00Z", "car", 50, 60, 0),
      row("2026-08-06T11:00:00Z", null, 0, null, 8.456),
    ];
    const out = congestionSeries(rows, "hour");
    expect(out).toHaveLength(2);
    expect(out[0].minutes).toBe(12);
    expect(out[1].minutes).toBe(8.5);
  });
});

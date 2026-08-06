import type { KpiRow } from "./api";

export interface BucketCount {
  bucket: string;
  label: string;
  car: number;
  bus: number;
  truck: number;
  motorcycle: number;
  total: number;
}

export interface SpeedPoint {
  bucket: string;
  label: string;
  avg_speed_kmh: number;
}

export interface CongestionPoint {
  bucket: string;
  label: string;
  minutes: number;
}

const VEHICLE_CLASSES = ["car", "bus", "truck", "motorcycle"] as const;

export function bucketLabel(iso: string, bucket: string): string {
  const d = new Date(iso);
  if (bucket === "hour") {
    return `${d.getHours().toString().padStart(2, "0")}:00`;
  }
  return d.toLocaleDateString("es-CL", { day: "2-digit", month: "2-digit" });
}

/** Pivot KPI rows (LINE_CROSSING counts) into per-bucket class columns. */
export function pivotCounts(rows: KpiRow[], bucket: string): BucketCount[] {
  const byBucket = new Map<string, BucketCount>();
  for (const row of rows) {
    if (row.vehicle_class === null) continue;
    let entry = byBucket.get(row.bucket);
    if (!entry) {
      entry = {
        bucket: row.bucket,
        label: bucketLabel(row.bucket, bucket),
        car: 0,
        bus: 0,
        truck: 0,
        motorcycle: 0,
        total: 0,
      };
      byBucket.set(row.bucket, entry);
    }
    const cls = row.vehicle_class as (typeof VEHICLE_CLASSES)[number];
    if (VEHICLE_CLASSES.includes(cls)) {
      entry[cls] += row.total_count;
      entry.total += row.total_count;
    }
  }
  return [...byBucket.values()].sort((a, b) => a.bucket.localeCompare(b.bucket));
}

/** Weighted mean speed per bucket across classes (weighted by count). */
export function speedSeries(rows: KpiRow[], bucket: string): SpeedPoint[] {
  const acc = new Map<string, { num: number; den: number }>();
  for (const row of rows) {
    if (row.avg_speed_kmh === null || row.vehicle_class === null) continue;
    const entry = acc.get(row.bucket) ?? { num: 0, den: 0 };
    entry.num += row.avg_speed_kmh * row.total_count;
    entry.den += row.total_count;
    acc.set(row.bucket, entry);
  }
  return [...acc.entries()]
    .filter(([, v]) => v.den > 0)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([b, v]) => ({
      bucket: b,
      label: bucketLabel(b, bucket),
      avg_speed_kmh: Math.round((v.num / v.den) * 10) / 10,
    }));
}

export function congestionSeries(rows: KpiRow[], bucket: string): CongestionPoint[] {
  const acc = new Map<string, number>();
  for (const row of rows) {
    if (row.vehicle_class !== null) continue; // congestion rows carry null class
    acc.set(row.bucket, (acc.get(row.bucket) ?? 0) + row.congestion_minutes);
  }
  return [...acc.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([b, minutes]) => ({
      bucket: b,
      label: bucketLabel(b, bucket),
      minutes: Math.round(minutes * 10) / 10,
    }));
}

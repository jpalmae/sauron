import { Bike, Bus, Car, Truck, type LucideIcon } from "lucide-react";

export const CLASS_ICONS: Record<string, LucideIcon> = {
  car: Car,
  bus: Bus,
  truck: Truck,
  motorcycle: Bike,
};

export const CLASS_LABELS: Record<string, string> = {
  car: "Liviano",
  bus: "Bus",
  truck: "Camión",
  motorcycle: "Moto",
};

export const EVENT_LABELS: Record<string, string> = {
  LINE_CROSSING: "Cruce de línea",
  STOPPED_VEHICLE: "Vehículo detenido",
  OBSTRUCTION: "Obstrucción",
  WRONG_WAY: "Sentido contrario",
  CONGESTION: "Congestión",
};

export const SEVERITY_CLASSES = {
  info: "text-info border-info/40 bg-info/10",
  warning: "text-warn border-warn/40 bg-warn/10",
  critical: "text-crit border-crit/40 bg-crit/10",
} as const;

export const SEVERITY_DOT = {
  info: "bg-info",
  warning: "bg-warn",
  critical: "bg-crit",
} as const;

export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("es-CL", { hour12: false });
}

export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString("es-CL")} ${d.toLocaleTimeString("es-CL", { hour12: false })}`;
}

export function relTime(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `hace ${s}s`;
  if (s < 3600) return `hace ${Math.floor(s / 60)}m`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)}h`;
  return `hace ${Math.floor(s / 86400)}d`;
}

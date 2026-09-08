import type { Camera, EventItem } from "./api";

export type Domain = "traffic" | "people" | "matriculas" | "streaming";

export const TRAFFIC_EVENTS = new Set([
  "LINE_CROSSING",
  "CONGESTION",
  "STOPPED_VEHICLE",
  "OBSTRUCTION",
  "WRONG_WAY",
  "ALPR",
  "ALPR_WATCHLIST",
  "TRAVEL_TIME",
]);

export const PEOPLE_EVENTS = new Set([
  "OCCUPANCY",
  "CHAIR_OCCUPANCY",
  "GROUPING",
  "FALL",
]);

export const MATRICULAS_EVENTS = new Set(["ALPR", "ALPR_WATCHLIST"]);

export function isTrafficEvent(e: EventItem | { event_type: string }): boolean {
  return TRAFFIC_EVENTS.has(e.event_type);
}

export function isPeopleEvent(e: EventItem | { event_type: string }): boolean {
  return PEOPLE_EVENTS.has(e.event_type);
}

export function isMatriculasEvent(e: EventItem | { event_type: string }): boolean {
  return MATRICULAS_EVENTS.has(e.event_type);
}

export function getCameraDomain(camera: Camera): Domain {
  return camera.analytics_profile;
}

export function filterCamerasByDomain(cameras: Camera[], domain: Domain): Camera[] {
  return cameras.filter((c) => getCameraDomain(c) === domain);
}

export function filterEventsByDomain(events: EventItem[], domain: Domain): EventItem[] {
  return events.filter((e) =>
    domain === "traffic" ? isTrafficEvent(e) : domain === "people" ? isPeopleEvent(e) : isMatriculasEvent(e),
  );
}

export const DOMAIN_LABEL: Record<Domain, string> = {
  traffic: "Tráfico",
  people: "Personas",
  matriculas: "Matrículas",
  streaming: "Streaming",
};

export const DOMAIN_COLOR: Record<Domain, string> = {
  traffic: "text-info border-info/40 bg-info/10",
  people: "text-warn border-warn/40 bg-warn/10",
  matriculas: "text-violet-300 border-violet-300/40 bg-violet-300/10",
  streaming: "text-amber-300 border-amber-300/40 bg-amber-300/10",
};

export const DOMAIN_DOT: Record<Domain, string> = {
  traffic: "bg-info",
  people: "bg-warn",
  matriculas: "bg-violet-300",
  streaming: "bg-amber-300",
};

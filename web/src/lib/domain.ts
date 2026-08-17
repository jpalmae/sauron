import type { Camera, EventItem } from "./api";

export type Domain = "traffic" | "people";

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

export function isTrafficEvent(e: EventItem | { event_type: string }): boolean {
  return TRAFFIC_EVENTS.has(e.event_type);
}

export function isPeopleEvent(e: EventItem | { event_type: string }): boolean {
  return PEOPLE_EVENTS.has(e.event_type);
}

export function getCameraDomain(camera: Camera): Domain {
  return camera.analytics_profile;
}

export function filterCamerasByDomain(cameras: Camera[], domain: Domain): Camera[] {
  return cameras.filter((c) => getCameraDomain(c) === domain);
}

export function filterEventsByDomain(events: EventItem[], domain: Domain): EventItem[] {
  return events.filter((e) => (domain === "traffic" ? isTrafficEvent(e) : isPeopleEvent(e)));
}

export const DOMAIN_LABEL: Record<Domain, string> = {
  traffic: "Tráfico",
  people: "Personas",
};

export const DOMAIN_COLOR: Record<Domain, string> = {
  traffic: "text-info border-info/40 bg-info/10",
  people: "text-warn border-warn/40 bg-warn/10",
};

export const DOMAIN_DOT: Record<Domain, string> = {
  traffic: "bg-info",
  people: "bg-warn",
};

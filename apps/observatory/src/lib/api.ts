import { invoke } from "@tauri-apps/api/core";
import type { AutopsyPayload } from "./types";

export function autopsyHealth(): Promise<AutopsyPayload> {
  return invoke("autopsy_health");
}

export function autopsyStatus(limit = 8, sectionLimit = 4): Promise<AutopsyPayload> {
  return invoke("autopsy_status", { limit, sectionLimit });
}

export function autopsyConsult(query: string, limit = 6, inspectLimit = 0, route = "lexical"): Promise<AutopsyPayload> {
  return invoke("autopsy_consult", { query, limit, inspectLimit, route });
}

export function autopsyItem(stableKey: string): Promise<AutopsyPayload> {
  return invoke("autopsy_item", { stableKey });
}

export function autopsyNeighbors(stableKey: string, limit = 18): Promise<AutopsyPayload> {
  return invoke("autopsy_neighbors", { stableKey, limit });
}

export function autopsyTimeline(stableKey: string): Promise<AutopsyPayload> {
  return invoke("autopsy_timeline", { stableKey });
}

export function autopsyBackup(): Promise<AutopsyPayload> {
  return invoke("autopsy_backup");
}

export type AutopsyPayload = Record<string, any>;

export type MemorySummary = {
  stable_key?: string;
  stableKey?: string;
  kind?: string;
  title?: string;
  label?: string;
  summary?: string;
  preview?: string;
  content?: string;
  updated_at?: string;
  activity_at?: string;
  source_kind?: string;
};

export type UiEvent = {
  at: string;
  kind: "info" | "success" | "error";
  message: string;
};

export function stableKeyOf(value: AutopsyPayload | MemorySummary | null | undefined): string {
  if (!value) return "";
  return String(value.stable_key ?? value.stableKey ?? "");
}

export function titleOf(value: AutopsyPayload | MemorySummary | null | undefined): string {
  if (!value) return "";
  return String(value.title ?? value.label ?? stableKeyOf(value));
}

export function previewOf(value: AutopsyPayload | MemorySummary | null | undefined): string {
  if (!value) return "";
  return String(value.summary ?? value.preview ?? value.content ?? "");
}

import Graph from "graphology";
import type { AutopsyPayload } from "./types";
import { previewOf, stableKeyOf, titleOf } from "./types";

const KIND_COLOR: Record<string, string> = {
  decision: "#e2e2e2",
  attempt: "#58c7aa",
  plan: "#9adfd2",
  preference: "#b8b8b8",
  open_question: "#d26a6a",
  question: "#d26a6a",
  memory_note: "#8f8f8f",
  repository: "#7d948f",
  workspace: "#6f7775",
  thread: "#a4a4a4",
  episode: "#5f6765"
};

function colorFor(kind: string | undefined): string {
  return KIND_COLOR[String(kind ?? "").toLowerCase()] ?? "#a9a7a0";
}

function graphLabel(attrs: AutopsyPayload, center: boolean): string {
  if (center) return "";
  const title = titleOf(attrs);
  return title.length > 42 ? `${title.slice(0, 39)}...` : title;
}

function addNode(graph: Graph, key: string, attrs: AutopsyPayload, index: number, total: number, center = false) {
  if (!key || graph.hasNode(key)) return;
  const angle = center ? 0 : (Math.PI * 2 * Math.max(index, 0)) / Math.max(total, 1);
  const radius = center ? 0 : 3.4 + (index % 3) * 0.9;
  graph.addNode(key, {
    x: center ? 0 : Math.cos(angle) * radius,
    y: center ? 0 : Math.sin(angle) * radius,
    size: center ? 18 : 9,
    label: graphLabel(attrs, center),
    color: colorFor(attrs.kind ?? attrs.entity_kind),
    borderColor: center ? "#ffffff" : "#2a2a2a",
    highlighted: false,
    kind: attrs.kind ?? attrs.entity_kind ?? "memory",
    preview: previewOf(attrs)
  });
}

function addEdge(graph: Graph, source: string, target: string, label: string, index: number) {
  if (!source || !target || source === target) return;
  const edgeKey = `${source}->${target}:${label}:${index}`;
  if (graph.hasEdge(edgeKey)) return;
  graph.addDirectedEdgeWithKey(edgeKey, source, target, {
    label,
    color: label === "supersedes" || label === "reverts" ? "#d26a6a" : "rgba(255,255,255,0.34)",
    size: 1.1
  });
}

export function buildNeighborhoodGraph(itemPayload: AutopsyPayload | null, neighborsPayload: AutopsyPayload | null, timelinePayload: AutopsyPayload | null): Graph {
  const graph = new Graph({ type: "directed", multi: true });
  const item = itemPayload?.item ?? timelinePayload?.timeline?.item ?? null;
  const centerKey = stableKeyOf(item);
  if (!item || !centerKey) return graph;

  addNode(graph, centerKey, item, 0, 1, true);

  const links = Array.isArray(item.links) ? item.links : [];
  links.forEach((link: AutopsyPayload, index: number) => {
    const key = String(link.entity_stable_key ?? link.stable_key ?? "");
    addNode(graph, key, { ...link, title: link.entity_label, kind: link.entity_kind }, index, links.length);
    addEdge(graph, centerKey, key, String(link.relation ?? "linked"), index);
  });

  const relations = Array.isArray(item.relations) ? item.relations : [];
  relations.forEach((relation: AutopsyPayload, index: number) => {
    const key = String(relation.entity_stable_key ?? "");
    addNode(graph, key, { ...relation, title: relation.entity_label, kind: relation.entity_kind, summary: relation.fact_text }, index + links.length, relations.length + links.length);
    if (relation.direction === "incoming") {
      addEdge(graph, key, centerKey, String(relation.relation ?? "related"), index);
    } else {
      addEdge(graph, centerKey, key, String(relation.relation ?? "related"), index);
    }
  });

  const neighbors = Array.isArray(neighborsPayload?.neighbors) ? neighborsPayload?.neighbors : [];
  neighbors.forEach((neighbor: AutopsyPayload, index: number) => {
    const key = String(neighbor.stable_key ?? neighbor.entity_stable_key ?? "");
    addNode(graph, key, neighbor, index + links.length + relations.length, neighbors.length + links.length + relations.length);
    addEdge(graph, centerKey, key, String(neighbor.relation ?? neighbor.edge_relation ?? "neighbor"), index);
  });

  const events = Array.isArray(timelinePayload?.timeline?.events) ? timelinePayload?.timeline?.events : [];
  events.forEach((event: AutopsyPayload, index: number) => {
    const key = String(event.entity_stable_key ?? "");
    addNode(graph, key, { ...event, title: event.entity_label, kind: event.entity_kind, summary: event.fact_text }, index + 20, events.length + 20);
    if (event.direction === "incoming") {
      addEdge(graph, key, centerKey, String(event.relation ?? "timeline"), index + 100);
    } else {
      addEdge(graph, centerKey, key, String(event.relation ?? "timeline"), index + 100);
    }
  });

  return graph;
}

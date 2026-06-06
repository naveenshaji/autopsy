import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Brain,
  CheckCircle2,
  Clock3,
  FileSearch,
  FileText,
  GitBranch,
  Hammer,
  HelpCircle,
  Image as ImageIcon,
  Link2,
  MessageSquareText,
  Pencil,
  Search,
  Settings2,
  Sparkles,
  Terminal,
  Wrench,
  LayoutGrid,
  type LucideIcon,
} from "lucide-react";
import "./styles.css";

type Point = { x: number; y: number };
type Size = { width: number; height: number };

type GraphNode = {
  id: string | number;
  stableKey?: string;
  kind: string;
  label: string;
  summary?: string | null;
  visualKind?: string;
  detailChips?: string[];
  sourceKind?: string;
  updatedAt?: string;
  stateFlags?: string[];
  provenance?: Record<string, unknown>;
  sourceRef?: string;
  isFocus?: boolean;
};

type GraphConnection = {
  id?: string | number;
  relation: string;
  predicate?: string;
  factText?: string | null;
  fromNodeID?: string | number;
  fromNodeId?: string | number;
  sourceID?: string | number;
  sourceId?: string | number;
  toNodeID?: string | number;
  toNodeId?: string | number;
  targetID?: string | number;
  targetId?: string | number;
  subjectLabel?: string | null;
  subjectKind?: string | null;
  objectLabel?: string | null;
  objectKind?: string | null;
  explanation?: string | null;
  overlapTerms?: string[];
  isExplicit?: boolean;
};

type GraphThread = {
  thread_id?: string;
  threadId?: string;
  event_count?: number;
  revision?: number;
  started_at?: string;
  updated_at?: string;
};

type GraphEvent = {
  id: string;
  event_type?: string;
  title?: string;
  timestamp?: string;
  status?: string;
  content?: string;
  run_id?: string;
  runId?: string;
  metadata?: Record<string, unknown>;
};

type GraphSnapshot = {
  scopeTitle?: string;
  focusNodeID?: string | number;
  focusNodeId?: string | number;
  nodes: GraphNode[];
  connections: GraphConnection[];
  thread?: GraphThread;
  events?: GraphEvent[];
  allEventCount?: number;
};

type ThreadSummary = {
  thread_id: string;
  event_count: number;
  revision: number;
  updated_at?: string;
};

type Prominence = "focus" | "primary" | "secondary" | "supporting";

type Descriptor = {
  icon: LucideIcon;
  category: string;
  prominence: Prominence;
  metricText?: string;
  tone: string;
};

type LayoutCache = {
  positions: Record<string, Point>;
  signatures: Record<string, string>;
  focusId: string;
  canvasSize: Size;
  compact: boolean;
};

type LayoutResult = {
  basePositions: Record<string, Point>;
  renderedPositions: Record<string, Point>;
  entryPositions?: Record<string, Point>;
  canvasSize: Size;
};

type GraphCanvasMode = "full" | "compact";
type CameraTarget = {
  nodeId: string;
  revision: string;
  fraction: Point;
};

type PopoverPlacement = {
  className: string;
  left: number;
  top: number;
  width: number;
  maxHeight: number;
};

type NodeConnectionDetail = {
  key: string;
  relation: string;
  direction: "incoming" | "outgoing";
  otherLabel: string;
  otherKind: string;
  explanation?: string | null;
};

type DragState =
  | { type: "pan"; start: Point; base: Point; moved: boolean }
  | { type: "node"; id: string; start: Point; base: Point; moved: boolean };

const BASE_CANVAS_SIZE: Record<GraphCanvasMode, Size> = {
  full: { width: 1500, height: 980 },
  compact: { width: 920, height: 560 },
};
const DRAG_CLICK_SUPPRESSION_DISTANCE = 3;

const PROMINENCE_WIDTH: Record<GraphCanvasMode, Record<Prominence, number>> = {
  full: {
    focus: 210,
    primary: 182,
    secondary: 164,
    supporting: 146,
  },
  compact: {
    focus: 148,
    primary: 136,
    secondary: 122,
    supporting: 108,
  },
};

const PROMINENCE_HEIGHT: Record<GraphCanvasMode, Record<Prominence, number>> = {
  full: {
    focus: 118,
    primary: 102,
    secondary: 92,
    supporting: 78,
  },
  compact: {
    focus: 92,
    primary: 82,
    secondary: 72,
    supporting: 62,
  },
};

function getThreadIdFromPath(): string {
  const match = window.location.pathname.match(/\/context-graph\/threads\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function getToken(): string {
  return new URLSearchParams(window.location.search).get("token") ?? "";
}

function getThemeOverride(): "light" | "dark" | "" {
  const value = new URLSearchParams(window.location.search).get("theme");
  return value === "light" || value === "dark" ? value : "";
}

function getCanvasModeOverride(): GraphCanvasMode | "" {
  const value = new URLSearchParams(window.location.search).get("mode") ?? new URLSearchParams(window.location.search).get("compact");
  if (value === "full" || value === "0" || value === "false") return "full";
  if (value === "compact" || value === "1" || value === "true") return "compact";
  return "";
}

function queryParam(...names: string[]): string {
  const params = new URLSearchParams(window.location.search);
  for (const name of names) {
    const value = params.get(name);
    if (value !== null && value.trim()) return value.trim();
  }
  return "";
}

function canvasModeForViewport(viewportSize: Size): GraphCanvasMode {
  const override = getCanvasModeOverride();
  if (override) return override;
  return viewportSize.width <= 1320 || viewportSize.height <= 840 ? "compact" : "full";
}

function normalizeId(value: string | number | undefined | null): string {
  return String(value ?? "");
}

function focusNodeId(snapshot: GraphSnapshot | null): string {
  return normalizeId(snapshot?.focusNodeID ?? snapshot?.focusNodeId ?? "turn:root");
}

function cameraFractionParam(...names: string[]): number | null {
  const raw = queryParam(...names);
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? clamp(value, 0, 1) : null;
}

function cameraTargetForSnapshot(snapshot: GraphSnapshot | null, compact: boolean): CameraTarget | null {
  if (!snapshot) return null;
  const cameraMode = queryParam("camera", "cameraTarget").toLowerCase();
  if (["0", "false", "off", "no"].includes(cameraMode)) return null;

  const explicitNodeId = queryParam("cameraTargetNodeID", "cameraTargetNodeId", "targetNodeID", "targetNodeId");
  const nodeId = explicitNodeId ? normalizeId(explicitNodeId) : (!compact ? focusNodeId(snapshot) : "");
  if (!nodeId || !snapshot.nodes.some((node) => normalizeId(node.id) === nodeId)) return null;

  const revision = queryParam("cameraTargetRevision", "targetRevision", "cameraRevision") || nodeId;
  return {
    nodeId,
    revision,
    fraction: {
      x: cameraFractionParam("cameraTargetX", "targetX") ?? 0.5,
      y: cameraFractionParam("cameraTargetY", "targetY") ?? 0.5,
    },
  };
}

function sourceId(connection: GraphConnection): string {
  return normalizeId(connection.fromNodeID ?? connection.fromNodeId ?? connection.sourceID ?? connection.sourceId);
}

function targetId(connection: GraphConnection): string {
  return normalizeId(connection.toNodeID ?? connection.toNodeId ?? connection.targetID ?? connection.targetId);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function positiveModulo(value: number, divisor: number): number {
  if (!Number.isFinite(divisor) || divisor === 0) return 0;
  return ((value % divisor) + divisor) % divisor;
}

function distance(a: Point, b: Point): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

function stableUnit(id: string, salt: number): number {
  let numericId: bigint;
  try {
    numericId = BigInt(String(id).replace(/[^\d-]/g, "") || "0");
  } catch {
    numericId = 0n;
    for (const character of String(id)) {
      numericId = BigInt.asUintN(64, numericId * 131n + BigInt(character.charCodeAt(0)));
    }
  }
  let value = BigInt.asUintN(64, numericId * 1103515245n + BigInt(salt) * 12345n);
  value = BigInt.asUintN(64, value ^ (value >> 33n));
  value = BigInt.asUintN(64, value * 0xff51afd7ed558ccdn);
  value = BigInt.asUintN(64, value ^ (value >> 33n));
  return Number(value % 10000n) / 9999;
}

function blendAngle(primary: number, secondary: number | null, secondaryWeight: number): number {
  if (secondary === null) return primary;
  const x = Math.cos(primary) * (1 - secondaryWeight) + Math.cos(secondary) * secondaryWeight;
  const y = Math.sin(primary) * (1 - secondaryWeight) + Math.sin(secondary) * secondaryWeight;
  return x === 0 && y === 0 ? primary : Math.atan2(y, x);
}

function descriptorForNode(node: GraphNode): Descriptor {
  const kind = node.visualKind || node.kind;
  const summary = (node.summary ?? "").trim();
  switch (kind) {
    case "turn_context":
      return { icon: Search, category: "Current Context", prominence: "focus", tone: "blue" };
    case "user_message":
      return { icon: MessageSquareText, category: "Prompt", prominence: "primary", tone: "cyan" };
    case "memory_context":
    case "graph_memory":
      if (summary === "decision") return { icon: CheckCircle2, category: "Decision", prominence: "primary", tone: "indigo" };
      if (summary === "attempt") return { icon: Hammer, category: "Attempt", prominence: "primary", tone: "orange" };
      if (summary === "observation") return { icon: Brain, category: "Observation", prominence: "primary", tone: "blue" };
      if (summary === "open_question") return { icon: HelpCircle, category: "Open Question", prominence: "primary", tone: "yellow" };
      if (summary === "resolved_question") return { icon: CheckCircle2, category: "Resolved Question", prominence: "primary", tone: "green" };
      if (summary === "question") return { icon: HelpCircle, category: "Question", prominence: "primary", tone: "yellow" };
      if (summary === "preference") return { icon: Settings2, category: "Preference", prominence: "primary", tone: "pink" };
      if (summary === "procedure") return { icon: Settings2, category: "Procedure", prominence: "primary", tone: "teal" };
      if (summary === "plan") return { icon: GitBranch, category: "Plan", prominence: "primary", tone: "teal" };
      if (summary === "timeline" || summary === "timeline_event") {
        return { icon: Clock3, category: "Timeline", prominence: "primary", tone: "brown" };
      }
      return { icon: Brain, category: "Note", prominence: "primary", tone: "gray" };
    case "file_excerpt":
      return { icon: FileText, category: "File Read", prominence: "primary", tone: "purple" };
    case "file_reads":
      return { icon: FileText, category: "Files Read", prominence: "primary", metricText: leadingCount(node.label), tone: "purple" };
    case "file_searches":
      return { icon: FileSearch, category: "File Search", prominence: "primary", metricText: leadingCount(node.label), tone: "mint" };
    case "changed_file":
      return { icon: FileText, category: "Changed File", prominence: "primary", tone: "purple" };
    case "web_result":
      return { icon: Link2, category: "Web Result", prominence: "primary", tone: "brown" };
    case "tool_result":
      return { icon: Wrench, category: "Tool Output", prominence: "secondary", tone: "green" };
    case "plan_context":
      return { icon: GitBranch, category: "Plan", prominence: "secondary", tone: "teal" };
    case "reasoning_context":
      return { icon: Brain, category: "Reasoning", prominence: "secondary", metricText: leadingCount(node.label), tone: "orange" };
    case "memory_status_context":
      return { icon: Brain, category: "Memory Status", prominence: "secondary", tone: "gray" };
    case "memory_query_context":
      return { icon: Brain, category: "Memory Consult", prominence: "secondary", tone: "indigo" };
    case "memory_search_context":
      return { icon: Search, category: "Memory Search", prominence: "secondary", tone: "teal" };
    case "memory_item_context":
      return { icon: Brain, category: "Memory Item", prominence: "secondary", tone: "indigo" };
    case "memory_timeline_context":
      return { icon: Clock3, category: "Memory Timeline", prominence: "secondary", tone: "brown" };
    case "memory_history_context":
      return { icon: Clock3, category: "Memory History", prominence: "secondary", tone: "brown" };
    case "memory_neighbors_context":
      return { icon: Link2, category: "Memory Relations", prominence: "secondary", tone: "teal" };
    case "file_search_context":
      return { icon: FileSearch, category: "File Search", prominence: "secondary", tone: "mint" };
    case "file_read_context":
      return { icon: FileText, category: "File Read", prominence: "secondary", tone: "purple" };
    case "git_status_context":
      return { icon: GitBranch, category: "Git Status", prominence: "secondary", tone: "gray" };
    case "git_diff_context":
      return { icon: GitBranch, category: "Git Diff", prominence: "secondary", tone: "orange" };
    case "git_show_context":
      return { icon: GitBranch, category: "Git Object", prominence: "secondary", tone: "orange" };
    case "git_log_context":
      return { icon: GitBranch, category: "Git History", prominence: "secondary", tone: "brown" };
    case "git_context":
      return { icon: GitBranch, category: "Git", prominence: "secondary", tone: "gray" };
    case "command_context":
      return { icon: Terminal, category: "Command", prominence: "secondary", tone: "mint" };
    case "command_batch":
      return { icon: Terminal, category: "Commands", prominence: "secondary", metricText: leadingCount(node.label), tone: "mint" };
    case "web_search":
      return { icon: Search, category: "Search", prominence: "secondary", tone: "yellow" };
    case "file_changes":
      return { icon: Pencil, category: "File Changes", prominence: "secondary", metricText: leadingCount(node.label), tone: "red" };
    case "image_context":
      return { icon: ImageIcon, category: "Image", prominence: "secondary", tone: "pink" };
    case "image_generation":
      return { icon: Sparkles, category: "Image Generation", prominence: "secondary", tone: "pink" };
    case "review_context":
      return { icon: CheckCircle2, category: "Review", prominence: "secondary", tone: "orange" };
    case "turn_group_context":
      return { icon: Clock3, category: "Turn", prominence: "secondary", tone: "gray" };
    case "history_context":
      return { icon: Clock3, category: "History", prominence: "supporting", tone: "gray" };
    case "instruction_source":
      return { icon: Settings2, category: "Instructions", prominence: "supporting", tone: "gray" };
    case "assistant_response":
      return { icon: MessageSquareText, category: "Assistant", prominence: "primary", tone: "indigo" };
    case "context_artifact":
      return { icon: LayoutGrid, category: "Context", prominence: "supporting", tone: "gray" };
    default:
      return {
        icon: LayoutGrid,
        category: kind.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()),
        prominence: "supporting",
        tone: "gray",
      };
  }
}

function leadingCount(label: string): string | undefined {
  const match = String(label).match(/^\d+/);
  return match?.[0];
}

function nodeSignature(node: GraphNode): string {
  return [node.kind, node.visualKind ?? "", node.label, node.summary ?? "", [...(node.detailChips ?? [])].join(","), [...(node.stateFlags ?? [])].sort().join(",")].join("::");
}

function emphasisSignature(node: GraphNode): string {
  return [node.visualKind ?? "", node.label, node.summary ?? "", [...(node.detailChips ?? [])].join(","), [...(node.stateFlags ?? [])].sort().join(",")].join("::");
}

function animationSignature(snapshot: GraphSnapshot | null): string {
  if (!snapshot) return "";
  const nodes = [...snapshot.nodes]
    .sort((a, b) => normalizeId(a.id).localeCompare(normalizeId(b.id)))
    .map((node) => `${normalizeId(node.id)}:${emphasisSignature(node)}`)
    .join("|");
  const edges = [...snapshot.connections]
    .map((edge) => `${sourceId(edge)}->${targetId(edge)}:${edge.relation}`)
    .sort()
    .join("|");
  return `${focusNodeId(snapshot)}||${nodes}||${edges}`;
}

function layoutNodeSize(node: GraphNode, compact: boolean): Size {
  const descriptor = descriptorForNode(node);
  const mode = compact ? "compact" : "full";
  const horizontalChrome = compact ? 24 : 30;
  const verticalChrome = compact ? 22 : 28;
  const width = PROMINENCE_WIDTH[mode][descriptor.prominence] + horizontalChrome;
  const baseHeight = PROMINENCE_HEIGHT[mode][descriptor.prominence];
  const chips = detailChips(node);
  const summary = node.summary ?? "";
  const contentBonus = chips.length
    ? Math.min(
      (compact ? 6 : 8) + chips.length * (compact ? 18 : 22) + Math.max(0, chips.length - 1) * 4,
      compact ? 62 : 86,
    )
    : Math.min(summary.length / 20, compact ? 28 : 42);
  return { width, height: baseHeight + contentBonus + verticalChrome };
}

type FirstHopRing = {
  nodes: GraphNode[];
  radiusX: number;
  radiusY: number;
};

function ellipseCircumference(radiusX: number, radiusY: number): number {
  if (radiusX <= 0 || radiusY <= 0) return 0;
  const h = Math.pow(radiusX - radiusY, 2) / Math.pow(radiusX + radiusY, 2);
  return Math.PI * (radiusX + radiusY) * (1 + (3 * h) / (10 + Math.sqrt(4 - 3 * h)));
}

function firstHopRings(nodes: GraphNode[], compact: boolean, expandDense = false): FirstHopRing[] {
  const ordered = [...nodes];
  const dense = ordered.length > (compact ? 8 : 10);
  const averageSpan = Math.max(
    compact ? 132 : 164,
    ordered.reduce((sum, node) => sum + layoutNodeSize(node, compact).width, 0) / Math.max(ordered.length, 1),
  ) + (compact ? (dense ? (expandDense ? 76 : 38) : 20) : (dense ? (expandDense ? 88 : 44) : 28));
  const baseRadius = compact ? (dense ? (expandDense ? 210 : 150) : 118) : (dense ? (expandDense ? 304 : 220) : 176);
  const ringGap = compact ? (dense ? (expandDense ? 116 : 64) : 82) : (dense ? (expandDense ? 156 : 96) : 132);
  const rings: FirstHopRing[] = [];
  let index = 0;
  let ringIndex = 0;

  while (index < ordered.length) {
    const rawRadius = baseRadius + ringIndex * ringGap;
    const radiusY = compact && dense && !expandDense ? Math.min(rawRadius, 286) : rawRadius;
    const radiusX = compact && dense
      ? radiusY * (ringIndex === 0 ? 1.2 : 1.55) + ringIndex * 36
      : radiusY * (compact ? (ringIndex === 0 ? 1.18 : 1.6) : (ringIndex === 0 ? 1.12 : 1.34));
    const circumference = ellipseCircumference(radiusX, radiusY);
    const capacity = Math.max(1, Math.floor(circumference / averageSpan));
    const ringNodes = ordered.slice(index, index + capacity);
    rings.push({ nodes: ringNodes, radiusX, radiusY });
    index += ringNodes.length;
    ringIndex += 1;
  }

  return rings;
}

function clampedPosition(point: Point, canvasSize: Size, compact: boolean): Point {
  const margin = compact ? 72 : 98;
  return {
    x: clamp(point.x, margin, canvasSize.width - margin),
    y: clamp(point.y, margin, canvasSize.height - margin),
  };
}

function graphAdjacency(snapshot: GraphSnapshot): Record<string, Set<string>> {
  const adjacency: Record<string, Set<string>> = {};
  for (const connection of snapshot.connections) {
    const from = sourceId(connection);
    const to = targetId(connection);
    if (!from || !to) continue;
    adjacency[from] ??= new Set();
    adjacency[to] ??= new Set();
    adjacency[from].add(to);
    adjacency[to].add(from);
  }
  return adjacency;
}

function breadthFirstDistances(snapshot: GraphSnapshot, focusId: string): Record<string, number> {
  const adjacency = graphAdjacency(snapshot);
  const distances: Record<string, number> = { [focusId]: 0 };
  const queue = [focusId];
  let index = 0;
  while (index < queue.length) {
    const current = queue[index++];
    const nextDistance = (distances[current] ?? 0) + 1;
    if (nextDistance > 3) continue;
    for (const neighbor of adjacency[current] ?? []) {
      if (distances[neighbor] !== undefined) continue;
      distances[neighbor] = nextDistance;
      queue.push(neighbor);
    }
  }
  return distances;
}

function isTurnClusterNode(node?: GraphNode): boolean {
  return node?.kind === "turn_context" || node?.kind === "history_context";
}

function isGraphMemoryNode(node?: GraphNode): boolean {
  if (!node) return false;
  return nodeVisualKind(node) === "graph_memory" || node.kind === "graph_memory";
}

function isMemoryCommandNode(node?: GraphNode): boolean {
  return Boolean(node && nodeVisualKind(node).startsWith("memory_"));
}

function usesDenseCommandLayout(snapshot: GraphSnapshot): boolean {
  const commandNodeCount = snapshot.nodes.filter((node) => node.kind === "command_context").length;
  return commandNodeCount >= 18 && commandNodeCount / Math.max(snapshot.nodes.length, 1) > 0.68;
}

function labelCompare(a?: GraphNode, b?: GraphNode): number {
  return (a?.label ?? "").localeCompare(b?.label ?? "", undefined, { numeric: true, sensitivity: "base" });
}

function avoidanceAngle(origin: Point, existingPositions: Record<string, Point>, candidateId: string): number | null {
  let x = 0;
  let y = 0;
  for (const [nodeId, point] of Object.entries(existingPositions)) {
    if (nodeId === candidateId) continue;
    const dx = origin.x - point.x;
    const dy = origin.y - point.y;
    const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
    const influence = 1 / dist;
    x += (dx / dist) * influence;
    y += (dy / dist) * influence;
  }
  return x === 0 && y === 0 ? null : Math.atan2(y, x);
}

function relaxPositions(
  snapshot: GraphSnapshot,
  initialPositions: Record<string, Point>,
  idealPositions: Record<string, Point>,
  canvasSize: Size,
  adjacency: Record<string, Set<string>>,
  fixedIds: Set<string>,
  nodesById: Record<string, GraphNode>,
  maxIterations: number,
  compact: boolean,
  denseCommandLayout = false,
): Record<string, Point> {
  const positions: Record<string, Point> = { ...initialPositions };
  const nodeIds = snapshot.nodes.map((node) => normalizeId(node.id));
  const margin = compact ? 72 : 98;

  for (let iteration = 0; iteration < maxIterations; iteration += 1) {
    const forces: Record<string, Point> = Object.fromEntries(nodeIds.map((id) => [id, { x: 0, y: 0 }]));

    for (let leftIndex = 0; leftIndex < nodeIds.length; leftIndex += 1) {
      const leftId = nodeIds[leftIndex];
      const left = positions[leftId];
      const leftNode = nodesById[leftId];
      if (!left || !leftNode) continue;
      const leftSize = layoutNodeSize(leftNode, compact);
      for (const rightId of nodeIds.slice(leftIndex + 1)) {
        const right = positions[rightId];
        const rightNode = nodesById[rightId];
        if (!right || !rightNode) continue;
        const rightSize = layoutNodeSize(rightNode, compact);
        const dx = right.x - left.x;
        const dy = right.y - left.y;
        const centerDistance = Math.max(Math.sqrt(dx * dx + dy * dy), 0.01);
        const targetDistance = Math.max(
          (leftSize.width + rightSize.width) * (denseCommandLayout ? 0.58 : 0.43),
          (leftSize.height + rightSize.height) * (denseCommandLayout ? 0.82 : 0.72),
        ) + (compact ? 12 : 18);
        if (centerDistance < targetDistance) {
          const overlap = targetDistance - centerDistance;
          const direction = { x: dx / centerDistance, y: dy / centerDistance };
          const push = overlap * 0.48;
          forces[leftId].x -= direction.x * push;
          forces[leftId].y -= direction.y * push;
          forces[rightId].x += direction.x * push;
          forces[rightId].y += direction.y * push;
        }
        if (denseCommandLayout) {
          const overlapX = (leftSize.width + rightSize.width) * 0.58 + (compact ? 16 : 22) - Math.abs(dx);
          const overlapY = (leftSize.height + rightSize.height) * 0.62 + (compact ? 12 : 16) - Math.abs(dy);
          if (overlapX > 0 && overlapY > 0) {
            if (overlapX < overlapY) {
              const directionX = Math.sign(dx) || (stableUnit(`${leftId}:${rightId}`, 211) < 0.5 ? -1 : 1);
              const rectangularPush = overlapX * 0.62;
              forces[leftId].x -= directionX * rectangularPush;
              forces[rightId].x += directionX * rectangularPush;
            } else {
              const directionY = Math.sign(dy) || (stableUnit(`${leftId}:${rightId}`, 223) < 0.5 ? -1 : 1);
              const rectangularPush = overlapY * 0.62;
              forces[leftId].y -= directionY * rectangularPush;
              forces[rightId].y += directionY * rectangularPush;
            }
          }
        }
      }
    }

    for (const nodeId of nodeIds) {
      if (fixedIds.has(nodeId)) continue;
      const current = positions[nodeId];
      const ideal = idealPositions[nodeId];
      if (!current || !ideal) continue;
      forces[nodeId].x += (ideal.x - current.x) * 0.09;
      forces[nodeId].y += (ideal.y - current.y) * 0.09;

      const neighbors = adjacency[nodeId];
      if (neighbors?.size) {
        let ax = 0;
        let ay = 0;
        let count = 0;
        for (const neighborId of neighbors) {
          const neighbor = positions[neighborId];
          if (!neighbor) continue;
          ax += neighbor.x - current.x;
          ay += neighbor.y - current.y;
          count += 1;
        }
        if (count > 0) {
          forces[nodeId].x += (ax / count) * 0.028;
          forces[nodeId].y += (ay / count) * 0.028;
        }
      }
    }

    for (const nodeId of nodeIds) {
      if (fixedIds.has(nodeId)) continue;
      const current = positions[nodeId];
      const force = forces[nodeId];
      if (!current || !force) continue;
      const maxStep = denseCommandLayout ? (compact ? 20 : 28) : (compact ? 16 : 24);
      const magnitude = Math.sqrt(force.x * force.x + force.y * force.y);
      const scale = magnitude > maxStep && magnitude > 0 ? maxStep / magnitude : 1;
      const next = { x: current.x + force.x * scale, y: current.y + force.y * scale };
      positions[nodeId] = {
        x: clamp(next.x, margin, canvasSize.width - margin),
        y: clamp(next.y, margin, canvasSize.height - margin),
      };
    }
  }

  return positions;
}

function relaxedFocusedLayout(snapshot: GraphSnapshot, focusId: string, center: Point, canvasSize: Size, compact: boolean): Record<string, Point> {
  const adjacency = graphAdjacency(snapshot);
  const distances = breadthFirstDistances(snapshot, focusId);
  const nodesById = Object.fromEntries(snapshot.nodes.map((node) => [normalizeId(node.id), node]));
  const orderedNodes = [...snapshot.nodes].sort((a, b) => {
    const leftDistance = Math.min(distances[normalizeId(a.id)] ?? 3, 3);
    const rightDistance = Math.min(distances[normalizeId(b.id)] ?? 3, 3);
    return leftDistance === rightDistance ? labelCompare(a, b) : leftDistance - rightDistance;
  });
  const targetRadii: Record<number, number> = compact
    ? { 0: 0, 1: 118, 2: 214, 3: 310 }
    : { 0: 0, 1: 176, 2: 318, 3: 452 };
  const radialBand = compact ? 34 : 54;
  const tangentialBand = compact ? 42 : 66;
  const denseCommandLayout = usesDenseCommandLayout(snapshot);
  let positions: Record<string, Point> = { [focusId]: center };
  const idealPositions: Record<string, Point> = { [focusId]: center };
  const orderedByDistance: Record<number, GraphNode[]> = {};
  for (const node of orderedNodes) {
    const id = normalizeId(node.id);
    if (id === focusId) continue;
    const distanceKey = Math.min(distances[id] ?? 3, 3);
    orderedByDistance[distanceKey] ??= [];
    orderedByDistance[distanceKey].push(node);
  }
  const firstHop = [...(orderedByDistance[1] ?? [])].sort((a, b) => {
    const priority = Number(isTurnClusterNode(a)) - Number(isTurnClusterNode(b));
    return priority === 0 ? labelCompare(a, b) : priority;
  });
  const anchorAngles: Record<string, number> = {};
  const rings = firstHopRings(firstHop, compact, denseCommandLayout);
  const outerFirstHopRadius = rings.reduce((radius, ring) => Math.max(radius, ring.radiusY), targetRadii[1] ?? 0);
  targetRadii[2] = Math.max(targetRadii[2] ?? 0, outerFirstHopRadius + (compact ? 96 : 142));
  targetRadii[3] = Math.max(targetRadii[3] ?? 0, outerFirstHopRadius + (compact ? 184 : 268));

  rings.forEach((ring, ringIndex) => {
    const totalWeight = Math.max(ring.nodes.reduce((sum, node) => sum + (isTurnClusterNode(node) ? 1.75 : 1), 0), 1);
    let accumulatedWeight = 0;
    const ringPhase = ringIndex === 0 ? 0 : (ringIndex % 2 === 0 ? 0.22 : -0.34);
    for (const node of ring.nodes) {
      const id = normalizeId(node.id);
      const weight = isTurnClusterNode(node) ? 1.75 : 1;
      const angle = -Math.PI / 2 + ringPhase + 2 * Math.PI * ((accumulatedWeight + weight / 2) / totalWeight);
      accumulatedWeight += weight;
      anchorAngles[id] = angle;
      const radialJitter = (stableUnit(id, 17) - 0.5) * radialBand;
      const tangentJitter = (stableUnit(id, 29) - 0.5) * tangentialBand * 0.55;
      const kindBonus = isTurnClusterNode(node) ? (compact ? 22 : 34) : 0;
      const radiusX = ring.radiusX + radialJitter + kindBonus;
      const radiusY = ring.radiusY + radialJitter + kindBonus;
      const point = {
        x: center.x + Math.cos(angle) * radiusX + -Math.sin(angle) * tangentJitter,
        y: center.y + Math.sin(angle) * radiusY + Math.cos(angle) * tangentJitter,
      };
      positions[id] = point;
      idealPositions[id] = point;
    }
  });

  const parentByNodeId: Record<string, string> = {};
  for (const distanceKey of [2, 3]) {
    const group = [...(orderedByDistance[distanceKey] ?? [])].sort(labelCompare);
    for (const node of group) {
      const id = normalizeId(node.id);
      const candidates = [...(adjacency[id] ?? [])]
        .map((neighborId) => ({ distance: distances[neighborId] ?? Number.MAX_SAFE_INTEGER, node: nodesById[neighborId] }))
        .filter((candidate) => candidate.node && candidate.distance < distanceKey)
        .sort((a, b) => {
          if (a.distance !== b.distance) return a.distance - b.distance;
          const turnPriority = Number(isTurnClusterNode(a.node)) - Number(isTurnClusterNode(b.node));
          return turnPriority === 0 ? labelCompare(a.node, b.node) : turnPriority;
        });
      if (candidates[0]?.node) {
        parentByNodeId[id] = normalizeId(candidates[0].node.id);
      }
    }
  }

  const childrenByParent: Record<string, string[]> = {};
  for (const [childId, parentId] of Object.entries(parentByNodeId)) {
    childrenByParent[parentId] ??= [];
    childrenByParent[parentId].push(childId);
  }

  for (const distanceKey of [2, 3]) {
    const group = [...(orderedByDistance[distanceKey] ?? [])].sort(labelCompare);
    for (const node of group) {
      const id = normalizeId(node.id);
      const parentId = parentByNodeId[id];
      const siblings = parentId
        ? [...(childrenByParent[parentId] ?? [])].sort((a, b) => labelCompare(nodesById[a], nodesById[b]))
        : group.map((item) => normalizeId(item.id));
      const index = Math.max(siblings.indexOf(id), 0);
      const siblingCount = Math.max(siblings.length, 1);
      const parentPosition = parentId ? positions[parentId] ?? center : center;
      const parentNode = parentId ? nodesById[parentId] : undefined;
      const parentAngle = parentId && anchorAngles[parentId] !== undefined
        ? anchorAngles[parentId]
        : Math.atan2(parentPosition.y - center.y, parentPosition.x - center.x);
      const siblingStep = (compact ? Math.PI / 7.2 : Math.PI / 8.8) * (isTurnClusterNode(parentNode) ? 1.2 : 1);
      const fanOffset = (index - (siblingCount - 1) / 2) * siblingStep;
      const memoryRelationChild = isGraphMemoryNode(node) && isMemoryCommandNode(parentNode);
      const seededAngle = memoryRelationChild ? parentAngle + Math.PI + fanOffset * 0.78 : parentAngle + fanOffset;
      const outwardStep = memoryRelationChild
        ? (compact ? 72 : 112)
        : (compact ? 90 : 138) + (distanceKey === 3 ? (compact ? 20 : 28) : 0);
      const layer = Math.floor(index / 3);
      const radialDistance = outwardStep + layer * (memoryRelationChild ? (compact ? 22 : 32) : (compact ? 32 : 46));
      const tangentialDistance = ((index % 3) - 1) * (memoryRelationChild ? (compact ? 34 : 52) : (compact ? 22 : 34));
      const avoid = avoidanceAngle(parentPosition, positions, id);
      const angle = blendAngle(seededAngle, avoid, memoryRelationChild ? 0.18 : 0.35);
      const radialJitter = (stableUnit(id, 17) - 0.5) * radialBand * 0.42;
      const tangentJitter = (stableUnit(id, 29) - 0.5) * tangentialBand * 0.32;
      positions[id] = {
        x: parentPosition.x + Math.cos(angle) * (radialDistance + radialJitter) + -Math.sin(angle) * (tangentialDistance + tangentJitter),
        y: parentPosition.y + Math.sin(angle) * (radialDistance + radialJitter) + Math.cos(angle) * (tangentialDistance + tangentJitter),
      };
      const targetRadius = (targetRadii[distanceKey] ?? targetRadii[3]) + radialJitter;
      idealPositions[id] = {
        x: memoryRelationChild ? positions[id].x : center.x + Math.cos(angle) * targetRadius + -Math.sin(angle) * (tangentialDistance * 0.65),
        y: memoryRelationChild ? positions[id].y : center.y + Math.sin(angle) * targetRadius + Math.cos(angle) * (tangentialDistance * 0.65),
      };
    }
  }

  positions = relaxPositions(
    snapshot,
    positions,
    idealPositions,
    canvasSize,
    adjacency,
    new Set([focusId]),
    nodesById,
    denseCommandLayout ? (compact ? 44 : 56) : (compact ? 26 : 34),
    compact,
    denseCommandLayout,
  );
  return Object.fromEntries(Object.entries(positions).map(([id, point]) => [id, clampedPosition(point, canvasSize, compact)]));
}

function relaxedClusteredLayout(snapshot: GraphSnapshot, center: Point, canvasSize: Size, compact: boolean): Record<string, Point> {
  const adjacency = graphAdjacency(snapshot);
  const groups: Record<string, GraphNode[]> = {};
  for (const node of snapshot.nodes) {
    groups[node.kind] ??= [];
    groups[node.kind].push(node);
  }
  const orderedKinds = Object.keys(groups).sort();
  const outerRadius = compact ? 156 : 248;
  const clusterRadius = compact ? 78 : 124;
  const positions: Record<string, Point> = {};
  const idealPositions: Record<string, Point> = {};
  const nodesById = Object.fromEntries(snapshot.nodes.map((node) => [normalizeId(node.id), node]));
  const denseCommandLayout = usesDenseCommandLayout(snapshot);

  orderedKinds.forEach((kind, kindIndex) => {
    const nodes = [...(groups[kind] ?? [])].sort(labelCompare);
    if (!nodes.length) return;
    const clusterAngle = -Math.PI / 2 + (2 * Math.PI * kindIndex) / Math.max(orderedKinds.length, 1);
    const clusterCenter = {
      x: center.x + Math.cos(clusterAngle) * outerRadius,
      y: center.y + Math.sin(clusterAngle) * outerRadius,
    };
    nodes.forEach((node, index) => {
      const id = normalizeId(node.id);
      const angle = clusterAngle + (2 * Math.PI * index) / Math.max(nodes.length, 1);
      const radialJitter = (stableUnit(id, 31) - 0.5) * clusterRadius * 0.42;
      const tangentJitter = (stableUnit(id, 43) - 0.5) * clusterRadius * 0.64;
      const point = {
        x: clusterCenter.x + Math.cos(angle) * (clusterRadius * 0.38 + radialJitter) + -Math.sin(angle) * tangentJitter,
        y: clusterCenter.y + Math.sin(angle) * (clusterRadius * 0.38 + radialJitter) + Math.cos(angle) * tangentJitter,
      };
      positions[id] = point;
      idealPositions[id] = point;
    });
  });

  return relaxPositions(
    snapshot,
    positions,
    idealPositions,
    canvasSize,
    adjacency,
    new Set(),
    nodesById,
    denseCommandLayout ? (compact ? 38 : 48) : (compact ? 24 : 30),
    compact,
    denseCommandLayout,
  );
}

function fallbackGridLayout(snapshot: GraphSnapshot, center: Point, compact: boolean): Record<string, Point> {
  return Object.fromEntries(snapshot.nodes.map((node, index) => [
    normalizeId(node.id),
    {
      x: center.x + (index % 6) * (compact ? 110 : 150) - (compact ? 220 : 360),
      y: center.y + Math.floor(index / 6) * (compact ? 90 : 120) - (compact ? 120 : 240),
    },
  ]));
}

function shouldUseFullRelayout(snapshot: GraphSnapshot, cache: LayoutCache | null, canvasSize: Size, compact: boolean): boolean {
  if (!cache || !Object.keys(cache.positions).length) return true;
  if (cache.focusId !== focusNodeId(snapshot)) return true;
  if (cache.compact !== compact) return true;
  const currentIds = new Set(snapshot.nodes.map((node) => normalizeId(node.id)));
  const retained = [...currentIds].filter((id) => cache.positions[id]).length;
  if (retained < Math.max(2, Math.floor(snapshot.nodes.length / 3))) return true;
  const canvasDelta = Math.abs(cache.canvasSize.width - canvasSize.width) + Math.abs(cache.canvasSize.height - canvasSize.height);
  return canvasDelta > (compact ? 420 : 640);
}

function incrementalLayout(snapshot: GraphSnapshot, cache: LayoutCache, center: Point, canvasSize: Size, compact: boolean): Record<string, Point> {
  const adjacency = graphAdjacency(snapshot);
  const focusId = focusNodeId(snapshot);
  const nodesById = Object.fromEntries(snapshot.nodes.map((node) => [normalizeId(node.id), node]));
  const denseCommandLayout = usesDenseCommandLayout(snapshot);
  const currentIds = new Set(snapshot.nodes.map((node) => normalizeId(node.id)));
  const currentSignatures = Object.fromEntries(snapshot.nodes.map((node) => [normalizeId(node.id), nodeSignature(node)]));
  const distances = focusId ? breadthFirstDistances(snapshot, focusId) : {};
  let positions: Record<string, Point> = {};
  let idealPositions: Record<string, Point> = {};
  const changedIds = new Set<string>();
  const addedIds = new Set<string>();

  for (const node of snapshot.nodes) {
    const id = normalizeId(node.id);
    if (cache.positions[id]) {
      const clamped = clampedPosition(cache.positions[id], canvasSize, compact);
      positions[id] = clamped;
      idealPositions[id] = clamped;
      if (cache.signatures[id] !== currentSignatures[id]) changedIds.add(id);
    } else {
      changedIds.add(id);
      addedIds.add(id);
    }
  }

  if (!changedIds.size) return positions;
  const movableIds = new Set(changedIds);
  for (const id of changedIds) {
    for (const neighbor of adjacency[id] ?? []) {
      if (currentIds.has(neighbor) && neighbor !== focusId) movableIds.add(neighbor);
    }
  }

  if (focusId && currentIds.has(focusId)) {
    positions[focusId] = center;
    idealPositions[focusId] = center;
    movableIds.delete(focusId);
  }

  const orderedMovable = [...movableIds].sort((a, b) => {
    const da = Math.min(distances[a] ?? 3, 3);
    const db = Math.min(distances[b] ?? 3, 3);
    return da === db ? labelCompare(nodesById[a], nodesById[b]) : da - db;
  });

  for (const id of orderedMovable) {
    const node = nodesById[id];
    if (!node || (positions[id] && !changedIds.has(id))) continue;
    if (!positions[id] && isTurnClusterNode(node) && Object.keys(positions).length) {
      const sparse = sparseTurnClusterPosition(node, center, canvasSize, positions, adjacency, nodesById, compact);
      positions[id] = sparse;
      idealPositions[id] = sparse;
      continue;
    }
    const parentPosition = [...(adjacency[id] ?? [])]
      .map((neighborId) => ({ id: neighborId, position: positions[neighborId], distance: distances[neighborId] ?? Number.MAX_SAFE_INTEGER }))
      .filter((item): item is { id: string; position: Point; distance: number } => Boolean(item.position))
      .sort((a, b) => (a.distance === b.distance ? labelCompare(nodesById[a.id], nodesById[b.id]) : a.distance - b.distance))[0]?.position ?? center;
    const parentId = [...(adjacency[id] ?? [])]
      .filter((neighborId) => positions[neighborId])
      .sort((a, b) => ((distances[a] ?? Number.MAX_SAFE_INTEGER) - (distances[b] ?? Number.MAX_SAFE_INTEGER)) || labelCompare(nodesById[a], nodesById[b]))[0];
    const parentNode = parentId ? nodesById[parentId] : undefined;
    const nodeDistance = Math.min(distances[id] ?? 3, 3);
    const parentAngle = Math.atan2(parentPosition.y - center.y, parentPosition.x - center.x);
    const stableAngle = -Math.PI / 2 + 2 * Math.PI * stableUnit(id, 67);
    const avoid = avoidanceAngle(parentPosition, positions, id);
    const memoryRelationChild = isGraphMemoryNode(node) && isMemoryCommandNode(parentNode);
    const memoryFan = (stableUnit(id, 89) - 0.5) * (compact ? Math.PI / 4.8 : Math.PI / 5.8);
    const angle = memoryRelationChild
      ? blendAngle(parentAngle + Math.PI + memoryFan, avoid, 0.18)
      : blendAngle(blendAngle(parentAngle, stableAngle, 0.35), avoid, 0.58);
    const baseDistance = memoryRelationChild
      ? (compact ? 84 : 126)
      : nodeDistance === 1 ? (compact ? 132 : 188) : nodeDistance === 2 ? (compact ? 102 : 148) : (compact ? 118 : 170);
    const kindBonus = isTurnClusterNode(node) ? (compact ? 28 : 40) : 0;
    const radialJitter = (stableUnit(id, 17) - 0.5) * (compact ? 26 : 36);
    const tangentJitter = (stableUnit(id, 29) - 0.5) * (memoryRelationChild ? (compact ? 76 : 104) : (compact ? 42 : 60));
    const seeded = clampedPosition({
      x: parentPosition.x + Math.cos(angle) * (baseDistance + kindBonus + radialJitter) + -Math.sin(angle) * tangentJitter,
      y: parentPosition.y + Math.sin(angle) * (baseDistance + kindBonus + radialJitter) + Math.cos(angle) * tangentJitter,
    }, canvasSize, compact);
    positions[id] = seeded;
    idealPositions[id] = seeded;
  }

  if (addedIds.size) {
    const influenceFloor = compact ? 190 : 270;
    const minPush = compact ? 8 : 12;
    const maxPush = compact ? 42 : 62;

    for (const id of currentIds) {
      if (addedIds.has(id) || id === focusId) continue;
      const current = positions[id];
      const node = nodesById[id];
      if (!current || !node) continue;

      let pushX = 0;
      let pushY = 0;
      const nodeSize = layoutNodeSize(node, compact);
      for (const addedId of addedIds) {
        const arrival = positions[addedId];
        const arrivalNode = nodesById[addedId];
        if (!arrival || !arrivalNode) continue;

        const dx = current.x - arrival.x;
        const dy = current.y - arrival.y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const arrivalSize = layoutNodeSize(arrivalNode, compact);
        const clearance = Math.max(
          (nodeSize.width + arrivalSize.width) * 0.58,
          (nodeSize.height + arrivalSize.height) * 0.86,
        ) + (compact ? 34 : 48);
        const influence = Math.max(influenceFloor, clearance);
        if (dist > influence) continue;

        const stableAngle = 2 * Math.PI * stableUnit(`${id}:${addedId}`, 307);
        const directionX = dist <= 1.01 ? Math.cos(stableAngle) : dx / dist;
        const directionY = dist <= 1.01 ? Math.sin(stableAngle) : dy / dist;
        const push = clamp((influence - dist) * 0.22, minPush, maxPush);
        pushX += directionX * push;
        pushY += directionY * push;
      }

      if (Math.abs(pushX) + Math.abs(pushY) > 0.5) {
        movableIds.add(id);
        idealPositions[id] = clampedPosition({ x: current.x + pushX, y: current.y + pushY }, canvasSize, compact);
      }
    }
  }

  const fixedIds = new Set([...currentIds].filter((id) => !movableIds.has(id) && id !== focusId));
  return relaxPositions(
    snapshot,
    positions,
    idealPositions,
    canvasSize,
    adjacency,
    fixedIds,
    nodesById,
    denseCommandLayout ? (compact ? 24 : 32) : (compact ? 12 : 16),
    compact,
    denseCommandLayout,
  );
}

function renderedPositionFromBase(
  point: Point,
  id: string,
  center: Point,
  nodeOffsets: Record<string, Point>,
  pan: Point,
  zoom: number,
): Point {
  const offset = nodeOffsets[id] ?? { x: 0, y: 0 };
  const translated = {
    x: point.x + offset.x + pan.x,
    y: point.y + offset.y + pan.y,
  };
  return {
    x: center.x + (translated.x - center.x) * zoom,
    y: center.y + (translated.y - center.y) * zoom,
  };
}

function entryPositionsForNewNodes(
  snapshot: GraphSnapshot,
  basePositions: Record<string, Point>,
  cache: LayoutCache | null,
  center: Point,
  canvasSize: Size,
  nodeOffsets: Record<string, Point>,
  pan: Point,
  zoom: number,
  compact: boolean,
): Record<string, Point> {
  if (!cache || !Object.keys(cache.positions).length) return {};
  const adjacency = graphAdjacency(snapshot);
  const entryPositions: Record<string, Point> = {};
  const entryDistance = compact ? 42 : 58;

  for (const node of snapshot.nodes) {
    const id = normalizeId(node.id);
    if (cache.positions[id] || !basePositions[id]) continue;
    const target = basePositions[id];
    const anchor = [...(adjacency[id] ?? [])]
      .map((neighborId) => ({ id: neighborId, position: cache.positions[neighborId] }))
      .filter((item): item is { id: string; position: Point } => Boolean(item.position))
      .sort((left, right) => distance(target, left.position) - distance(target, right.position))[0];
    const origin = anchor?.position ?? center;
    let dx = target.x - origin.x;
    let dy = target.y - origin.y;
    let magnitude = Math.sqrt(dx * dx + dy * dy);
    if (magnitude < 1) {
      const angle = 2 * Math.PI * stableUnit(id, 331);
      dx = Math.cos(angle);
      dy = Math.sin(angle);
      magnitude = 1;
    }

    const entryBase = clampedPosition({
      x: origin.x + (dx / magnitude) * entryDistance,
      y: origin.y + (dy / magnitude) * entryDistance,
    }, canvasSize, compact);
    entryPositions[id] = renderedPositionFromBase(entryBase, id, center, nodeOffsets, pan, zoom);
  }

  return entryPositions;
}

function sparseTurnClusterPosition(
  node: GraphNode,
  center: Point,
  canvasSize: Size,
  positions: Record<string, Point>,
  adjacency: Record<string, Set<string>>,
  nodesById: Record<string, GraphNode>,
  compact: boolean,
): Point {
  const id = normalizeId(node.id);
  const connected = [...(adjacency[id] ?? [])].map((neighborId) => positions[neighborId]).filter((point): point is Point => Boolean(point));
  const parentPosition = connected[0];
  const canvasRadius = Math.min(canvasSize.width, canvasSize.height) / 2;
  const radiusFractions = compact ? [0.34, 0.48, 0.62, 0.76] : [0.32, 0.47, 0.62, 0.77];
  const angleCount = compact ? 12 : 16;
  const stableAngleOffset = 2 * Math.PI * stableUnit(id, 113);
  const existing = Object.values(positions);
  let bestPoint: Point | null = null;
  let bestScore = -Number.MAX_VALUE;

  for (const radiusFraction of radiusFractions) {
    const radius = canvasRadius * radiusFraction;
    for (let angleIndex = 0; angleIndex < angleCount; angleIndex += 1) {
      const angle = stableAngleOffset + (2 * Math.PI * angleIndex) / angleCount;
      const candidate = clampedPosition({
        x: center.x + Math.cos(angle) * radius,
        y: center.y + Math.sin(angle) * radius,
      }, canvasSize, compact);
      const nearest = existing.map((point) => distance(candidate, point)).sort((a, b) => a - b)[0] ?? radius;
      const edgeDistance = Math.min(candidate.x, canvasSize.width - candidate.x, candidate.y, canvasSize.height - candidate.y);
      const edgePenalty = Math.max(0, (compact ? 80 : 110) - edgeDistance) * 1.35;
      const linkPenalty = parentPosition ? Math.max(0, distance(candidate, parentPosition) - (compact ? 260 : 380)) * 0.14 : 0;
      const centerPenalty = Math.max(0, (compact ? 118 : 176) - distance(candidate, center)) * 0.28;
      const stableTieBreaker = stableUnit(id, angleIndex + 191) * 3;
      const neighborBonus = [...(adjacency[id] ?? [])].filter((neighborId) => nodesById[neighborId]).length * 0.01;
      const score = nearest - edgePenalty - linkPenalty - centerPenalty + stableTieBreaker + neighborBonus;
      if (score > bestScore) {
        bestScore = score;
        bestPoint = candidate;
      }
    }
  }
  return bestPoint ?? center;
}

function computeLayout(
  snapshot: GraphSnapshot,
  viewportSize: Size,
  cache: LayoutCache | null,
  nodeOffsets: Record<string, Point>,
  pan: Point,
  zoom: number,
  compact: boolean,
): LayoutResult {
  const mode = compact ? "compact" : "full";
  const baseCanvasSize = {
    width: Math.max(BASE_CANVAS_SIZE[mode].width, viewportSize.width),
    height: Math.max(BASE_CANVAS_SIZE[mode].height, viewportSize.height),
  };
  const denseCanvasScale = usesDenseCommandLayout(snapshot)
    ? clamp(Math.sqrt(snapshot.nodes.length / (compact ? 28 : 36)), compact ? 2.05 : 1.58, compact ? 2.8 : 2.2)
    : 1;
  const canvasSize = {
    width: Math.round(baseCanvasSize.width * denseCanvasScale),
    height: Math.round(baseCanvasSize.height * denseCanvasScale),
  };
  const center = { x: canvasSize.width / 2, y: canvasSize.height / 2 };
  const focusId = focusNodeId(snapshot);
  const shouldFull = shouldUseFullRelayout(snapshot, cache, canvasSize, compact);
  let basePositions = shouldFull
    ? snapshot.nodes.some((node) => normalizeId(node.id) === focusId)
      ? relaxedFocusedLayout(snapshot, focusId, center, canvasSize, compact)
      : relaxedClusteredLayout(snapshot, center, canvasSize, compact)
    : incrementalLayout(snapshot, cache as LayoutCache, center, canvasSize, compact);

  if (!Object.keys(basePositions).length) basePositions = fallbackGridLayout(snapshot, center, compact);

  const renderedPositions = Object.fromEntries(Object.entries(basePositions).map(([id, point]) => [
    id,
    renderedPositionFromBase(point, id, center, nodeOffsets, pan, zoom),
  ]));
  const entryPositions = entryPositionsForNewNodes(
    snapshot,
    basePositions,
    shouldFull ? null : cache,
    center,
    canvasSize,
    nodeOffsets,
    pan,
    zoom,
    compact,
  );

  return { basePositions, renderedPositions, entryPositions, canvasSize };
}

function useElementSize<T extends HTMLElement>(): [React.RefObject<T>, Size] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState<Size>({ width: 1200, height: 800 });
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, size];
}

function useReducedMotion(): boolean {
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return reducedMotion;
}

function snappyProgress(progress: number): number {
  const t = clamp(progress, 0, 1);
  const c1 = 0.08;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
}

function smoothProgress(progress: number): number {
  const t = clamp(progress, 0, 1);
  return t * t * (3 - 2 * t);
}

function interpolatePoint(from: Point | undefined, to: Point, progress: number): Point {
  if (!from) return to;
  return {
    x: from.x + (to.x - from.x) * progress,
    y: from.y + (to.y - from.y) * progress,
  };
}

function useAnimatedLayout(
  targetLayout: LayoutResult | null,
  animationKey: string,
  reducedMotion: boolean,
): LayoutResult | null {
  const [animatedLayout, setAnimatedLayout] = useState<LayoutResult | null>(targetLayout);
  const renderedPositionsRef = useRef<Record<string, Point>>({});
  const animationKeyRef = useRef(animationKey);

  useEffect(() => {
    if (!targetLayout) {
      renderedPositionsRef.current = {};
      setAnimatedLayout(null);
      animationKeyRef.current = animationKey;
      return;
    }

    const previousPositions = renderedPositionsRef.current;
    const shouldAnimate = Boolean(animationKeyRef.current && animationKeyRef.current !== animationKey && !reducedMotion);
    animationKeyRef.current = animationKey;

    if (!shouldAnimate) {
      renderedPositionsRef.current = targetLayout.renderedPositions;
      setAnimatedLayout(targetLayout);
      return;
    }

    let frame = 0;
    const start = window.performance.now();
    const duration = 340;
    const targetPositions = targetLayout.renderedPositions;

    const tick = (now: number) => {
      const progress = snappyProgress((now - start) / duration);
      const entryPositions = targetLayout.entryPositions ?? {};
      const renderedPositions = Object.fromEntries(Object.entries(targetPositions).map(([id, point]) => [
        id,
        interpolatePoint(previousPositions[id] ?? entryPositions[id], point, progress),
      ]));

      renderedPositionsRef.current = renderedPositions;
      setAnimatedLayout({
        ...targetLayout,
        renderedPositions,
      });

      if (now - start < duration) {
        frame = window.requestAnimationFrame(tick);
      } else {
        renderedPositionsRef.current = targetPositions;
        setAnimatedLayout(targetLayout);
      }
    };

    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [animationKey, reducedMotion, targetLayout]);

  return animatedLayout;
}

function dotPatternStyle(zoom: number, pan: Point, canvasSize: Size, compact: boolean): React.CSSProperties & Record<string, string | number> {
  const clampedZoom = Math.max(zoom, 0.01);
  const spacingScale = clampedZoom < 0.75 ? 2 : clampedZoom < 1.45 ? 1 : 0.5;
  const spacing = (compact ? 20 : 26) * spacingScale;
  const screenSpacing = spacing * clampedZoom;
  const radiusScale = clampedZoom < 0.75 ? 0.9 : clampedZoom < 1.45 ? 1 : 0.75;
  const radius = Math.min(compact ? 1.8 : 2.1, Math.max(0.75, (compact ? 1.3 : 1.5) * Math.sqrt(clampedZoom) * radiusScale));
  const center = { x: canvasSize.width / 2, y: canvasSize.height / 2 };
  const backgroundX = positiveModulo(center.x * (1 - clampedZoom) + pan.x * clampedZoom, screenSpacing);
  const backgroundY = positiveModulo(center.y * (1 - clampedZoom) + pan.y * clampedZoom, screenSpacing);

  return {
    width: canvasSize.width,
    height: canvasSize.height,
    "--dot-radius": `${radius}px`,
    "--dot-fade-radius": `${radius + 0.1}px`,
    backgroundSize: `${screenSpacing}px ${screenSpacing}px`,
    backgroundPosition: `${backgroundX}px ${backgroundY}px`,
  };
}

function pathForEdge(from: Point, to: Point, compact: boolean): string {
  const deltaX = to.x - from.x;
  const controlOffset = Math.max(Math.abs(deltaX) * 0.35, compact ? 28 : 44);
  const c1 = { x: from.x + controlOffset, y: from.y };
  const c2 = { x: to.x - controlOffset, y: to.y };
  return `M ${from.x} ${from.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${to.x} ${to.y}`;
}

function stateLabel(flag: string): string {
  const labels: Record<string, string> = {
    current: "Current",
    in_progress: "In Progress",
    in_context: "In Context",
    consulted: "Consulted",
    complete: "Complete",
    follow_up: "Follow-Up",
    superseded: "Superseded",
    answered: "Answered",
    reverted: "Reverted",
    blocked: "Blocked",
  };
  return labels[flag] ?? flag.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function isLiveNode(node: GraphNode): boolean {
  const flags = new Set(node.stateFlags ?? []);
  return (node.kind === "turn_context" || nodeVisualKind(node) === "turn_group_context") && (flags.has("in_progress") || flags.has("streaming") || flags.has("live"));
}

function nodeVisualKind(node: GraphNode): string {
  return node.visualKind || node.kind;
}

function detailChips(node: GraphNode): string[] {
  if (node.detailChips?.length) return node.detailChips.map((item) => String(item).trim()).filter(Boolean).slice(0, 4);
  const summary = (node.summary ?? "").trim();
  if (!summary) return [];
  if (node.kind === "file_reads") return summary.split(",").map((item) => item.trim()).filter(Boolean).slice(0, 4);
  if (["file_searches", "reasoning_context", "command_batch", "file_changes"].includes(node.kind)) {
    return summary.split("\n").map((item) => item.trim()).filter(Boolean).slice(0, 4);
  }
  if ([
    "memory_status_context",
    "memory_query_context",
    "memory_search_context",
    "memory_item_context",
    "memory_timeline_context",
    "memory_history_context",
    "memory_neighbors_context",
    "file_search_context",
    "file_read_context",
    "git_status_context",
    "git_diff_context",
    "git_show_context",
    "git_log_context",
    "git_context",
  ].includes(nodeVisualKind(node))) {
    return summary.split("\n").map((item) => item.trim()).filter(Boolean).slice(0, 4);
  }
  return [];
}

function allDetailChips(node: GraphNode): string[] {
  if (node.detailChips?.length) return node.detailChips.map((item) => String(item).trim()).filter(Boolean);
  return detailChips(node);
}

function formatFieldLabel(value: string): string {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function primitiveValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function eventCommand(event: GraphEvent): string {
  const metadataCommand = isPlainObject(event.metadata) ? event.metadata.command : "";
  return String(metadataCommand || event.content || event.title || "").trim();
}

function eventRunId(event: GraphEvent): string {
  return String(event.run_id ?? event.runId ?? (isPlainObject(event.metadata) ? event.metadata.run_id ?? event.metadata.runId : "") ?? "").trim();
}

function matchingEventsForNode(node: GraphNode, events: GraphEvent[]): GraphEvent[] {
  const sourceRef = String(node.sourceRef ?? "").trim();
  const provenanceCommand = String(node.provenance?.command ?? "").trim();
  const provenanceCommands = Array.isArray(node.provenance?.commands)
    ? node.provenance.commands.map((command) => String(command).trim()).filter(Boolean)
    : [];
  const runId = String(node.provenance?.run_id ?? sourceRef).trim();
  const commands = new Set([provenanceCommand, ...provenanceCommands].filter(Boolean));
  return events.filter((event) => {
    const id = String(event.id ?? "").trim();
    if (sourceRef && id === sourceRef) return true;
    const command = eventCommand(event);
    if (command && commands.has(command)) return true;
    if ((node.kind === "turn_context" || nodeVisualKind(node) === "turn_group_context") && runId && eventRunId(event) === runId) return true;
    return false;
  });
}

function relatedConnectionsForNode(
  node: GraphNode,
  connections: GraphConnection[],
  nodesById: Record<string, GraphNode>,
): NodeConnectionDetail[] {
  const nodeId = normalizeId(node.id);
  return connections.flatMap((connection, index) => {
    const from = sourceId(connection);
    const to = targetId(connection);
    if (from !== nodeId && to !== nodeId) return [];
    const outgoing = from === nodeId;
    const other = nodesById[outgoing ? to : from];
    return [{
      key: edgeKey(connection, index),
      relation: connection.predicate || connection.relation,
      direction: outgoing ? "outgoing" : "incoming",
      otherLabel: connection[outgoing ? "objectLabel" : "subjectLabel"] || other?.label || (outgoing ? to : from),
      otherKind: (connection[outgoing ? "objectKind" : "subjectKind"] || other?.visualKind || other?.kind || "node").replaceAll("_", " "),
      explanation: connection.explanation || connection.factText || null,
    }];
  });
}

function nodePopoverPlacement(node: GraphNode, position: Point, canvasSize: Size, compact: boolean): PopoverPlacement {
  const padding = compact ? 12 : 18;
  const gap = compact ? 12 : 14;
  const nodeSize = layoutNodeSize(node, compact);
  const width = Math.min(compact ? 340 : 408, Math.max(280, canvasSize.width - padding * 2));
  const halfWidth = width / 2;
  const minReadableHeight = compact ? 180 : 220;
  const topAnchor = position.y - nodeSize.height / 2 - gap;
  const bottomAnchor = position.y + nodeSize.height / 2 + gap;
  const topSpace = topAnchor - padding;
  const bottomSpace = canvasSize.height - padding - bottomAnchor;
  const leftSpace = position.x - nodeSize.width / 2 - gap - padding;
  const rightSpace = canvasSize.width - padding - (position.x + nodeSize.width / 2 + gap);
  const verticalMax = Math.max(128, canvasSize.height - padding * 2);
  const clampLeft = (x: number) => clamp(x, padding + halfWidth, canvasSize.width - padding - halfWidth);
  const centeredTop = clamp(position.y, padding + minReadableHeight / 2, canvasSize.height - padding - minReadableHeight / 2);

  if (topSpace >= minReadableHeight || (topSpace > bottomSpace && topSpace >= 144)) {
    return {
      className: "placement-top",
      left: clampLeft(position.x),
      top: topAnchor,
      width,
      maxHeight: clamp(topSpace, 128, verticalMax),
    };
  }

  if (bottomSpace >= minReadableHeight || bottomSpace >= topSpace) {
    return {
      className: "placement-bottom",
      left: clampLeft(position.x),
      top: bottomAnchor,
      width,
      maxHeight: clamp(bottomSpace, 128, verticalMax),
    };
  }

  if (rightSpace >= width || rightSpace >= leftSpace) {
    return {
      className: "placement-right",
      left: clamp(position.x + nodeSize.width / 2 + gap, padding, canvasSize.width - padding),
      top: centeredTop,
      width: Math.min(width, Math.max(260, rightSpace)),
      maxHeight: verticalMax,
    };
  }

  return {
    className: "placement-left",
    left: clamp(position.x - nodeSize.width / 2 - gap, padding, canvasSize.width - padding),
    top: centeredTop,
    width: Math.min(width, Math.max(260, leftSpace)),
    maxHeight: verticalMax,
  };
}

function displaySummary(node: GraphNode): string | null {
  const summary = (node.summary ?? "").trim();
  if (!summary || summary === node.label || detailChips(node).length) return null;
  return summary;
}

function NodeCard({
  node,
  position,
  selected,
  hovered,
  emphasized,
  settlingEmphasis,
  appearing,
  appearingSettling,
  appearedSnap,
  compact,
  onPointerDown,
  onClick,
  onHover,
}: {
  node: GraphNode;
  position: Point;
  selected: boolean;
  hovered: boolean;
  emphasized: boolean;
  settlingEmphasis: boolean;
  appearing: boolean;
  appearingSettling: boolean;
  appearedSnap: boolean;
  compact: boolean;
  onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => void;
  onClick: () => void;
  onHover: (hovered: boolean) => void;
}) {
  const descriptor = descriptorForNode(node);
  const Icon = descriptor.icon;
  const chips = detailChips(node);
  const summary = displaySummary(node);
  const mode = compact ? "compact" : "full";
  return (
    <div
      className={[
        "graph-node",
        `tone-${descriptor.tone}`,
        `prominence-${descriptor.prominence}`,
        selected ? "selected" : "",
        hovered ? "hovered" : "",
        emphasized ? "emphasized" : "",
        settlingEmphasis ? "settling-emphasis" : "",
        appearing ? "appearing" : "",
        appearingSettling ? "appearing-settling" : "",
        appearedSnap ? "appeared-snap" : "",
        isLiveNode(node) ? "live-active" : "",
      ].filter(Boolean).join(" ")}
      data-node-id={normalizeId(node.id)}
      data-node-kind={nodeVisualKind(node)}
      style={{ left: position.x, top: position.y, width: PROMINENCE_WIDTH[mode][descriptor.prominence] }}
      onPointerDown={onPointerDown}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      onPointerEnter={() => onHover(true)}
      onPointerLeave={() => onHover(false)}
    >
      <div className="node-head">
        <span className="node-icon">
          <Icon size={compact ? 11 : 12} strokeWidth={2.25} />
        </span>
        <span className="node-title-wrap">
          <span className="node-label">{node.label}</span>
          <span className="node-category-row">
            <span className="node-category">{descriptor.category}</span>
            {descriptor.metricText ? <span className="node-metric">{descriptor.metricText}</span> : null}
          </span>
        </span>
      </div>
      {chips.length ? (
        <div className="node-chip-stack">
          {chips.map((chip) => <span key={chip} className="detail-chip">{chip}</span>)}
        </div>
      ) : summary ? (
        <div className="node-summary">{summary}</div>
      ) : null}
      {node.stateFlags?.length ? (
        <div className="state-row">
          {node.stateFlags.slice(0, compact ? 1 : 2).map((flag) => (
            <span key={flag} className={`state-badge state-${flag.replaceAll("_", "-")}`}>{stateLabel(flag)}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function NodePopover({
  node,
  position,
  canvasSize,
  compact,
  snapshot,
  nodesById,
  onClose,
}: {
  node: GraphNode;
  position: Point;
  canvasSize: Size;
  compact: boolean;
  snapshot: GraphSnapshot;
  nodesById: Record<string, GraphNode>;
  onClose: () => void;
}) {
  const descriptor = descriptorForNode(node);
  const Icon = descriptor.icon;
  const chips = allDetailChips(node);
  const summary = (node.summary ?? "").trim();
  const provenanceEntries = Object.entries(node.provenance ?? {})
    .filter(([, value]) => value !== null && value !== undefined && value !== "");
  const relatedConnections = relatedConnectionsForNode(node, snapshot.connections, nodesById);
  const matchingEvents = matchingEventsForNode(node, snapshot.events ?? []);
  const placement = nodePopoverPlacement(node, position, canvasSize, compact);
  const style = {
    left: placement.left,
    top: placement.top,
    width: placement.width,
    "--popover-max-height": `${placement.maxHeight}px`,
  } as React.CSSProperties & Record<string, string | number>;

  return (
	    <div
	      className={`graph-popover node-inspector ${placement.className} tone-${descriptor.tone}`}
	      style={style}
	      onClick={(event) => event.stopPropagation()}
	      onPointerDown={(event) => event.stopPropagation()}
	      onWheel={(event) => event.stopPropagation()}
	    >
      <div className="popover-header">
        <span className="popover-icon">
          <Icon size={13} strokeWidth={2.25} />
        </span>
        <span className="popover-title-wrap">
          <span className="popover-title">{node.label}</span>
          <span className="popover-subtitle">
            <span>{descriptor.category}</span>
            <span>{nodeVisualKind(node).replaceAll("_", " ")}</span>
          </span>
        </span>
      </div>
      <div className="popover-scroll">
        {(node.stateFlags ?? []).length ? (
          <section className="inspector-section">
            <div className="inspector-section-title">State</div>
            <div className="popover-meta">
              {(node.stateFlags ?? []).map((flag) => <span key={flag} className="popover-state">{stateLabel(flag)}</span>)}
            </div>
          </section>
        ) : null}
        {summary ? (
          <section className="inspector-section">
            <div className="inspector-section-title">Summary</div>
            <div className="popover-summary">{summary}</div>
          </section>
        ) : null}
        {chips.length ? (
          <section className="inspector-section">
            <div className="inspector-section-title">Details</div>
            <div className="popover-meta popover-command-chips">
              {chips.map((chip) => <span key={chip}>{chip}</span>)}
            </div>
          </section>
        ) : null}
        <section className="inspector-section">
          <div className="inspector-section-title">Source</div>
          <div className="inspector-grid">
            <span>Kind</span>
            <strong>{node.sourceKind || node.kind}</strong>
            <span>Node ID</span>
            <strong>{normalizeId(node.id)}</strong>
            {node.stableKey ? (
              <>
                <span>Stable Key</span>
                <strong>{node.stableKey}</strong>
              </>
            ) : null}
            {node.sourceRef ? (
              <>
                <span>Source Ref</span>
                <strong>{node.sourceRef}</strong>
              </>
            ) : null}
            {node.updatedAt ? (
              <>
                <span>Updated</span>
                <strong>{formatTimestamp(node.updatedAt)}</strong>
              </>
            ) : null}
          </div>
        </section>
        {provenanceEntries.length ? (
          <section className="inspector-section">
            <div className="inspector-section-title">Provenance</div>
            <div className="inspector-grid">
              {provenanceEntries.map(([key, value]) => (
                <React.Fragment key={key}>
                  <span>{formatFieldLabel(key)}</span>
                  {Array.isArray(value) ? (
                    <strong className="inspector-code-list">
                      {value.length ? value.map((item, index) => <code key={`${key}-${index}`}>{primitiveValue(item)}</code>) : "[]"}
                    </strong>
                  ) : isPlainObject(value) ? (
                    <strong><code>{primitiveValue(value)}</code></strong>
                  ) : (
                    <strong>{primitiveValue(value)}</strong>
                  )}
                </React.Fragment>
              ))}
            </div>
          </section>
        ) : null}
        {matchingEvents.length ? (
          <section className="inspector-section">
            <div className="inspector-section-title">Captured Events</div>
            <div className="event-list">
              {matchingEvents.map((event) => (
                <div key={event.id} className="event-card">
                  <div className="event-card-head">
                    <strong>{event.title || event.event_type || "Event"}</strong>
                    {event.timestamp ? <span>{formatTimestamp(event.timestamp)}</span> : null}
                  </div>
                  {eventCommand(event) ? <code>{eventCommand(event)}</code> : null}
                  <div className="popover-meta">
                    {event.status ? <span>{stateLabel(event.status)}</span> : null}
                    {eventRunId(event) ? <span>run: {eventRunId(event)}</span> : null}
                    {event.event_type ? <span>{event.event_type.replaceAll("_", " ")}</span> : null}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}
        {relatedConnections.length ? (
          <section className="inspector-section">
            <div className="inspector-section-title">Relationships</div>
            <div className="relationship-list">
              {relatedConnections.map((connection) => (
                <div key={connection.key} className="relationship-row">
                  <span>{connection.direction === "outgoing" ? "To" : "From"}</span>
                  <div>
                    <strong>{connection.relation.replaceAll("_", " ")}</strong>
                    <small>{connection.otherLabel} · {connection.otherKind}</small>
                    {connection.explanation ? <p>{connection.explanation}</p> : null}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}
        <section className="inspector-section">
          <div className="inspector-section-title">Graph</div>
          <div className="inspector-grid">
            <span>Thread Events</span>
            <strong>{snapshot.thread?.event_count ?? snapshot.events?.length ?? 0}</strong>
            <span>Total Rendered</span>
            <strong>{snapshot.allEventCount ?? snapshot.nodes.length}</strong>
            <span>Connections</span>
            <strong>{relatedConnections.length}</strong>
          </div>
        </section>
      </div>
    </div>
  );
}

function EdgePopover({
  connection,
  fromNode,
  toNode,
  position,
  canvasSize,
  compact,
  onClose,
}: {
  connection: GraphConnection;
  fromNode: GraphNode;
  toNode: GraphNode;
  position: Point;
  canvasSize: Size;
  compact: boolean;
  onClose: () => void;
}) {
  const padding = compact ? 12 : 18;
  const top = clamp(position.y + (compact ? 26 : 34), padding, canvasSize.height - padding);
  const left = clamp(position.x, padding, canvasSize.width - padding);
  return (
    <div
      className="graph-popover edge-inspector placement-bottom"
      style={{ left, top }}
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
      onWheel={(event) => event.stopPropagation()}
    >
      <div className="edge-popover-head">
        <Link2 size={16} />
        <div>
          <div className="popover-title">{connection.predicate || connection.relation}</div>
          <div className="popover-subtitle">{connection.isExplicit === false ? "Inferred from shared content" : "Explicit relationship"}</div>
        </div>
      </div>
      <div className="triple-box">
        <div className="triple-row">
          <span>Subject</span>
          <strong>{connection.subjectLabel || fromNode.label}</strong>
          <small>{(connection.subjectKind || fromNode.kind).replaceAll("_", " ")}</small>
        </div>
        <div className="triple-row">
          <span>Predicate</span>
          <strong>{connection.predicate || connection.relation}</strong>
        </div>
        <div className="triple-row">
          <span>Object</span>
          <strong>{connection.objectLabel || toNode.label}</strong>
          <small>{(connection.objectKind || toNode.kind).replaceAll("_", " ")}</small>
        </div>
      </div>
      {connection.explanation ? <div className="popover-summary">{connection.explanation}</div> : null}
      {connection.overlapTerms?.length ? (
        <div className="popover-meta">{connection.overlapTerms.map((term) => <span key={term}>{term}</span>)}</div>
      ) : null}
    </div>
  );
}

function EmptyState({ token }: { token: string }) {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    fetch(`/context-graph/api/threads?token=${encodeURIComponent(token)}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload) => {
        if (!cancelled) setThreads(Array.isArray(payload.threads) ? payload.threads : []);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <main className="shell center-shell">
      <section className="empty-panel">
        <h1>Autopsy Context Graph</h1>
        {!token ? <p>Missing worker token.</p> : null}
        {error ? <p>{error}</p> : null}
        {threads.length ? (
          <div className="thread-list">
            {threads.map((thread) => (
              <a
                key={thread.thread_id}
                href={`/context-graph/threads/${encodeURIComponent(thread.thread_id)}?token=${encodeURIComponent(token)}`}
              >
                <span>{thread.thread_id}</span>
                <small>{thread.event_count} events</small>
              </a>
            ))}
          </div>
        ) : (
          <p>No active thread graph has events yet.</p>
        )}
      </section>
    </main>
  );
}

function GraphApp({ threadId, token }: { threadId: string; token: string }) {
  const [viewportRef, viewportSize] = useElementSize<HTMLDivElement>();
  const [snapshot, setSnapshot] = useState<GraphSnapshot | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [selectedEdgeId, setSelectedEdgeId] = useState("");
  const [hoveredId, setHoveredId] = useState("");
  const [nodeOffsets, setNodeOffsets] = useState<Record<string, Point>>({});
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadedStorageKey, setLoadedStorageKey] = useState("");
  const [emphasizedIds, setEmphasizedIds] = useState<Set<string>>(new Set());
  const [settlingEmphasisIds, setSettlingEmphasisIds] = useState<Set<string>>(new Set());
  const [appearingIds, setAppearingIds] = useState<Set<string>>(new Set());
  const [appearingSettlingIds, setAppearingSettlingIds] = useState<Set<string>>(new Set());
  const [appearedSnapIds, setAppearedSnapIds] = useState<Set<string>>(new Set());
  const dragRef = useRef<DragState | null>(null);
  const suppressNextClickRef = useRef(false);
  const suppressClickClearTimeoutRef = useRef<number | null>(null);
  const layoutCacheRef = useRef<LayoutCache | null>(null);
  const priorSignatureRef = useRef<Record<string, string>>({});
  const knownNodeIdsRef = useRef<Set<string>>(new Set());
  const appearStartTimeoutRef = useRef<number | null>(null);
  const appearSettleTimeoutRef = useRef<number | null>(null);
  const appearSnapTimeoutRef = useRef<number | null>(null);
  const lastAppliedCameraTargetRef = useRef("");
  const cameraAnimationRef = useRef<number | null>(null);
  const canvasMode = canvasModeForViewport(viewportSize);
  const compact = canvasMode === "compact";
  const reducedMotion = useReducedMotion();

  const storageKey = `autopsy.memory-graph-canvas.${canvasMode}.${threadId.replace(/[^A-Za-z0-9._-]/g, "-")}`;

  useEffect(() => {
    setLoadedStorageKey("");
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        setZoom(clamp(Number(parsed.zoom) || 1, 0.55, 2.2));
        setPan({ x: Number(parsed.panX) || 0, y: Number(parsed.panY) || 0 });
        setNodeOffsets(parsed.nodeOffsets && typeof parsed.nodeOffsets === "object" ? parsed.nodeOffsets : {});
      } else {
        setZoom(1);
        setPan({ x: 0, y: 0 });
        setNodeOffsets({});
      }
    } catch {
      setZoom(1);
      setPan({ x: 0, y: 0 });
      setNodeOffsets({});
    } finally {
      setLoadedStorageKey(storageKey);
    }
  }, [storageKey]);

  useEffect(() => {
    if (loadedStorageKey !== storageKey) return;
    window.localStorage.setItem(storageKey, JSON.stringify({
      zoom,
      panX: pan.x,
      panY: pan.y,
      nodeOffsets,
    }));
  }, [loadedStorageKey, nodeOffsets, pan.x, pan.y, storageKey, zoom]);

  useEffect(() => () => {
    if (cameraAnimationRef.current !== null) {
      window.cancelAnimationFrame(cameraAnimationRef.current);
      cameraAnimationRef.current = null;
    }
    if (suppressClickClearTimeoutRef.current !== null) {
      window.clearTimeout(suppressClickClearTimeoutRef.current);
      suppressClickClearTimeoutRef.current = null;
    }
    if (appearStartTimeoutRef.current !== null) {
      window.clearTimeout(appearStartTimeoutRef.current);
      appearStartTimeoutRef.current = null;
    }
    if (appearSettleTimeoutRef.current !== null) {
      window.clearTimeout(appearSettleTimeoutRef.current);
      appearSettleTimeoutRef.current = null;
    }
    if (appearSnapTimeoutRef.current !== null) {
      window.clearTimeout(appearSnapTimeoutRef.current);
      appearSnapTimeoutRef.current = null;
    }
  }, []);

  const loadSnapshot = useCallback(async () => {
    const response = await fetch(
      `/context-graph/api/threads/${encodeURIComponent(threadId)}/snapshot?token=${encodeURIComponent(token)}`,
      { cache: "no-store" },
    );
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = (await response.json()) as GraphSnapshot;
    const nextNodeIds = new Set(payload.nodes.map((node) => normalizeId(node.id)));
    const newNodeIds = [...nextNodeIds].filter((id) => !knownNodeIdsRef.current.has(id));
    knownNodeIdsRef.current = nextNodeIds;
    if (newNodeIds.length && !reducedMotion) {
      if (appearStartTimeoutRef.current !== null) {
        window.clearTimeout(appearStartTimeoutRef.current);
        appearStartTimeoutRef.current = null;
      }
      if (appearSettleTimeoutRef.current !== null) {
        window.clearTimeout(appearSettleTimeoutRef.current);
        appearSettleTimeoutRef.current = null;
      }
      if (appearSnapTimeoutRef.current !== null) {
        window.clearTimeout(appearSnapTimeoutRef.current);
        appearSnapTimeoutRef.current = null;
      }
      const newNodeIdSet = new Set(newNodeIds);
      setAppearingIds(newNodeIdSet);
      setAppearingSettlingIds(new Set());
      setAppearedSnapIds(new Set());
      appearStartTimeoutRef.current = window.setTimeout(() => {
        appearStartTimeoutRef.current = null;
        setAppearingIds(new Set());
        setAppearingSettlingIds(newNodeIdSet);
      }, 34);
      appearSettleTimeoutRef.current = window.setTimeout(() => {
        appearSettleTimeoutRef.current = null;
        setAppearingSettlingIds((current) => {
          const next = new Set(current);
          for (const id of newNodeIds) next.delete(id);
          return next;
        });
        setAppearedSnapIds(newNodeIdSet);
      }, 520);
      appearSnapTimeoutRef.current = window.setTimeout(() => {
        appearSnapTimeoutRef.current = null;
        setAppearedSnapIds((current) => {
          const next = new Set(current);
          for (const id of newNodeIds) next.delete(id);
          return next;
        });
      }, 680);
    } else if (reducedMotion) {
      if (appearStartTimeoutRef.current !== null) {
        window.clearTimeout(appearStartTimeoutRef.current);
        appearStartTimeoutRef.current = null;
      }
      if (appearSettleTimeoutRef.current !== null) {
        window.clearTimeout(appearSettleTimeoutRef.current);
        appearSettleTimeoutRef.current = null;
      }
      if (appearSnapTimeoutRef.current !== null) {
        window.clearTimeout(appearSnapTimeoutRef.current);
        appearSnapTimeoutRef.current = null;
      }
      setAppearingIds(new Set());
      setAppearingSettlingIds(new Set());
      setAppearedSnapIds(new Set());
    }
    setSnapshot(payload);
    setError("");
    setLoading(false);
  }, [reducedMotion, threadId, token]);

  useEffect(() => {
    let cancelled = false;
    const run = () => {
      loadSnapshot().catch((err) => {
        if (!cancelled) {
          setError(String(err));
          setLoading(false);
        }
      });
    };
    run();
    const interval = window.setInterval(run, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [loadSnapshot]);

  const signature = useMemo(() => animationSignature(snapshot), [snapshot]);

  useEffect(() => {
    if (!snapshot) return;
    const currentSignatures = Object.fromEntries(snapshot.nodes.map((node) => [normalizeId(node.id), emphasisSignature(node)]));
    if (!Object.keys(priorSignatureRef.current).length) {
      priorSignatureRef.current = currentSignatures;
      setEmphasizedIds(new Set());
      setSettlingEmphasisIds(new Set());
      return;
    }
    const changed = Object.entries(currentSignatures)
      .filter(([id, value]) => priorSignatureRef.current[id] !== value)
      .map(([id]) => id);
    priorSignatureRef.current = currentSignatures;
    if (!changed.length) return;
    if (reducedMotion) {
      setEmphasizedIds(new Set());
      setSettlingEmphasisIds(new Set());
      return;
    }
    setEmphasizedIds((current) => new Set([...current, ...changed]));
    setSettlingEmphasisIds((current) => {
      const next = new Set(current);
      for (const id of changed) next.delete(id);
      return next;
    });
    const releaseTimeout = window.setTimeout(() => {
      setEmphasizedIds((current) => {
        const next = new Set(current);
        for (const id of changed) next.delete(id);
        return next;
      });
      setSettlingEmphasisIds((current) => new Set([...current, ...changed]));
    }, 650);
    const settleTimeout = window.setTimeout(() => {
      setSettlingEmphasisIds((current) => {
        const next = new Set(current);
        for (const id of changed) next.delete(id);
        return next;
      });
    }, 930);
    return () => {
      window.clearTimeout(releaseTimeout);
      window.clearTimeout(settleTimeout);
    };
  }, [reducedMotion, signature, snapshot]);

  const layout = useMemo<LayoutResult | null>(() => {
    if (!snapshot) return null;
    return computeLayout(snapshot, viewportSize, layoutCacheRef.current, nodeOffsets, pan, zoom, compact);
  }, [compact, nodeOffsets, pan, snapshot, viewportSize, zoom]);
  const renderedLayout = useAnimatedLayout(layout, signature, reducedMotion);

  useEffect(() => {
    if (!snapshot || !layout || loadedStorageKey !== storageKey) return;
    const cameraTarget = cameraTargetForSnapshot(snapshot, compact);
    if (!cameraTarget) return;
    const renderedPosition = layout.renderedPositions[cameraTarget.nodeId];
    if (!renderedPosition || viewportSize.width <= 0 || viewportSize.height <= 0) return;

    const targetKey = `${cameraTarget.nodeId}:${cameraTarget.revision}`;
    if (lastAppliedCameraTargetRef.current === targetKey) return;
    lastAppliedCameraTargetRef.current = targetKey;

    const stageOffset = {
      x: (viewportSize.width - layout.canvasSize.width) / 2,
      y: (viewportSize.height - layout.canvasSize.height) / 2,
    };
    const nodeViewportPoint = {
      x: stageOffset.x + renderedPosition.x,
      y: stageOffset.y + renderedPosition.y,
    };
    const desiredPoint = {
      x: viewportSize.width * cameraTarget.fraction.x,
      y: viewportSize.height * cameraTarget.fraction.y,
    };
    const delta = {
      x: (desiredPoint.x - nodeViewportPoint.x) / Math.max(zoom, 0.01),
      y: (desiredPoint.y - nodeViewportPoint.y) / Math.max(zoom, 0.01),
    };
    if (Math.abs(delta.x) <= 1 && Math.abs(delta.y) <= 1) return;

    if (cameraAnimationRef.current !== null) {
      window.cancelAnimationFrame(cameraAnimationRef.current);
      cameraAnimationRef.current = null;
    }

    const startPan = pan;
    const targetPan = { x: startPan.x + delta.x, y: startPan.y + delta.y };
    if (reducedMotion) {
      setPan(targetPan);
      return;
    }

    const start = window.performance.now();
    const duration = 420;
    const tick = (now: number) => {
      const progress = smoothProgress((now - start) / duration);
      setPan({
        x: startPan.x + (targetPan.x - startPan.x) * progress,
        y: startPan.y + (targetPan.y - startPan.y) * progress,
      });
      if (now - start < duration) {
        cameraAnimationRef.current = window.requestAnimationFrame(tick);
      } else {
        cameraAnimationRef.current = null;
        setPan(targetPan);
      }
    };
    cameraAnimationRef.current = window.requestAnimationFrame(tick);
  }, [compact, layout, loadedStorageKey, pan, reducedMotion, snapshot, storageKey, viewportSize, zoom]);

  useEffect(() => {
    if (!snapshot || !layout) return;
    layoutCacheRef.current = {
      positions: layout.basePositions,
      signatures: Object.fromEntries(snapshot.nodes.map((node) => [normalizeId(node.id), nodeSignature(node)])),
      focusId: focusNodeId(snapshot),
      canvasSize: layout.canvasSize,
      compact,
    };
  }, [compact, layout, snapshot]);

  useEffect(() => {
    if (!snapshot) return;
    const focusId = focusNodeId(snapshot);
    setSelectedId((current) => (current && snapshot.nodes.some((node) => normalizeId(node.id) === current) ? current : ""));
    setSelectedEdgeId((current) => (current && snapshot.connections.some((edge, index) => edgeKey(edge, index) === current) ? current : ""));
  }, [snapshot]);

  useEffect(() => {
    const onPointerMove = (event: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const dx = event.clientX - drag.start.x;
      const dy = event.clientY - drag.start.y;
      if (!drag.moved && Math.sqrt(dx * dx + dy * dy) > DRAG_CLICK_SUPPRESSION_DISTANCE) {
        drag.moved = true;
      }
      if (drag.type === "pan") {
        setPan({ x: drag.base.x + dx, y: drag.base.y + dy });
      } else {
        setNodeOffsets((current) => ({
          ...current,
          [drag.id]: { x: drag.base.x + dx / Math.max(zoom, 0.01), y: drag.base.y + dy / Math.max(zoom, 0.01) },
        }));
      }
    };
    const onPointerUp = () => {
      const drag = dragRef.current;
      if (drag?.moved) {
        suppressNextClickRef.current = true;
        if (suppressClickClearTimeoutRef.current !== null) {
          window.clearTimeout(suppressClickClearTimeoutRef.current);
        }
        suppressClickClearTimeoutRef.current = window.setTimeout(() => {
          suppressNextClickRef.current = false;
          suppressClickClearTimeoutRef.current = null;
        }, 0);
      }
      dragRef.current = null;
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
  }, [zoom]);

  const nodesById = useMemo(() => Object.fromEntries((snapshot?.nodes ?? []).map((node) => [normalizeId(node.id), node])), [snapshot]);
  const selectedNode = snapshot?.nodes.find((node) => normalizeId(node.id) === selectedId);
  const selectedNodePosition = selectedNode && renderedLayout ? renderedLayout.renderedPositions[normalizeId(selectedNode.id)] : undefined;
  const selectedEdge = snapshot?.connections.find((edge, index) => edgeKey(edge, index) === selectedEdgeId);
  const selectedEdgeFrom = selectedEdge ? nodesById[sourceId(selectedEdge)] : undefined;
  const selectedEdgeTo = selectedEdge ? nodesById[targetId(selectedEdge)] : undefined;
  const selectedEdgePosition = selectedEdge && renderedLayout
    ? midpoint(renderedLayout.renderedPositions[sourceId(selectedEdge)], renderedLayout.renderedPositions[targetId(selectedEdge)])
    : undefined;
  const isLive = !error;

  const onWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) {
      const nextZoom = clamp(zoom * (event.deltaY < 0 ? 1.08 : 0.92), 0.55, 2.2);
      setZoom(nextZoom);
      return;
    }
    setPan((current) => ({
      x: current.x - event.deltaX,
      y: current.y - event.deltaY,
    }));
  };

  return (
    <main className={`shell ${compact ? "compact" : "full"}`}>
      <div className={`status-dot ${isLive ? "live" : "error"}`} aria-label={isLive ? "Graph live" : "Graph offline"} />
      <section className="workspace" aria-label={`Context graph for ${threadId}`}>
        <div
          ref={viewportRef}
	          className="canvas-viewport"
	          onWheel={onWheel}
	          onPointerDown={(event) => {
	            if (event.button !== 0) return;
	            dragRef.current = { type: "pan", start: { x: event.clientX, y: event.clientY }, base: pan, moved: false };
	          }}
	          onClick={() => {
	            if (suppressNextClickRef.current) {
	              suppressNextClickRef.current = false;
	              return;
	            }
	            setSelectedId("");
	            setSelectedEdgeId("");
	          }}
        >
          {loading ? <div className="canvas-state">Loading graph</div> : null}
          {error && !snapshot?.nodes.length ? <div className="canvas-state">Graph offline</div> : null}
          {!loading && !error && !snapshot?.nodes.length ? <div className="canvas-state">No context events</div> : null}
          {snapshot && renderedLayout ? (
            <div
              className="canvas-stage"
              style={dotPatternStyle(zoom, pan, renderedLayout.canvasSize, compact)}
            >
              <svg className="edge-layer" width={renderedLayout.canvasSize.width} height={renderedLayout.canvasSize.height}>
                {snapshot.connections.map((connection, index) => {
                  const fromId = sourceId(connection);
                  const toId = targetId(connection);
                  const from = renderedLayout.renderedPositions[fromId];
                  const to = renderedLayout.renderedPositions[toId];
                  if (!from || !to) return null;
                  const id = edgeKey(connection, index);
                  const primary = fromId === focusNodeId(snapshot) || toId === focusNodeId(snapshot);
                  const hovered = fromId === hoveredId || toId === hoveredId;
                  const selected = selectedEdgeId === id;
                  return (
                    <g
                      key={id}
                      className={[
                        "edge-group",
                        primary ? "primary" : "",
                        hovered ? "hovered" : "",
                        selected ? "selected" : "",
                      ].filter(Boolean).join(" ")}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelectedId("");
                        setSelectedEdgeId(id);
                      }}
                      onPointerDown={(event) => event.stopPropagation()}
                    >
                      <path className="edge-hit" d={pathForEdge(from, to, compact)} />
                      <path className="graph-edge" d={pathForEdge(from, to, compact)} pathLength={1} />
                    </g>
                  );
                })}
              </svg>
              {snapshot.nodes.map((node) => {
                const id = normalizeId(node.id);
                const position = renderedLayout.renderedPositions[id];
                if (!position) return null;
                return (
                  <NodeCard
                    key={id}
                    node={node}
                    position={position}
	                    selected={(selectedId || focusNodeId(snapshot)) === id}
	                    hovered={hoveredId === id}
	                    emphasized={emphasizedIds.has(id)}
	                    settlingEmphasis={settlingEmphasisIds.has(id)}
	                    appearing={appearingIds.has(id)}
	                    appearingSettling={appearingSettlingIds.has(id)}
	                    appearedSnap={appearedSnapIds.has(id)}
	                    compact={compact}
	                    onPointerDown={(event) => {
	                      event.stopPropagation();
	                      if (event.button !== 0) return;
	                      dragRef.current = {
	                        type: "node",
	                        id,
	                        start: { x: event.clientX, y: event.clientY },
	                        base: nodeOffsets[id] ?? { x: 0, y: 0 },
	                        moved: false,
	                      };
	                    }}
	                    onClick={() => {
	                      if (suppressNextClickRef.current) {
	                        suppressNextClickRef.current = false;
	                        return;
	                      }
	                      setSelectedEdgeId("");
	                      setSelectedId(id);
	                    }}
                    onHover={(isHovered) => setHoveredId(isHovered ? id : (hoveredId === id ? "" : hoveredId))}
                  />
                );
              })}
              {selectedNode && selectedNodePosition ? (
                <NodePopover
                  node={selectedNode}
                  position={selectedNodePosition}
                  canvasSize={renderedLayout.canvasSize}
                  compact={compact}
                  snapshot={snapshot}
                  nodesById={nodesById}
                  onClose={() => setSelectedId("")}
                />
              ) : null}
              {selectedEdge && selectedEdgeFrom && selectedEdgeTo && selectedEdgePosition ? (
                <EdgePopover
                  connection={selectedEdge}
                  fromNode={selectedEdgeFrom}
                  toNode={selectedEdgeTo}
                  position={selectedEdgePosition}
                  canvasSize={renderedLayout.canvasSize}
                  compact={compact}
                  onClose={() => setSelectedEdgeId("")}
                />
              ) : null}
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}

function edgeKey(edge: GraphConnection, index: number): string {
  return normalizeId(edge.id || `${sourceId(edge)}-${targetId(edge)}-${edge.relation}-${index}`);
}

function midpoint(a?: Point, b?: Point): Point | undefined {
  if (!a || !b) return undefined;
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

function Root() {
  const token = getToken();
  const threadId = getThreadIdFromPath();
  const theme = getThemeOverride();
  useEffect(() => {
    if (theme) {
      document.documentElement.dataset.theme = theme;
    } else {
      delete document.documentElement.dataset.theme;
    }
  }, [theme]);

  if (!threadId) {
    return <EmptyState token={token} />;
  }
  if (!token) {
    return (
      <main className="shell center-shell">
        <section className="empty-panel">
          <h1>Autopsy Context Graph</h1>
          <p>Missing worker token.</p>
        </section>
      </main>
    );
  }
  return <GraphApp threadId={threadId} token={token} />;
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);

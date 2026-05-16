<script lang="ts">
  import { afterUpdate, onDestroy } from "svelte";
  import Sigma from "sigma";
  import { animateNodes } from "sigma/utils";
  import type Graph from "graphology";
  import { buildNeighborhoodGraph } from "../lib/graph";
  import type { AutopsyPayload } from "../lib/types";

  type OverlayEdge = {
    key: string;
    path: string;
    color: string;
    label: string;
  };

  type OverlayNode = {
    key: string;
    x: number;
    y: number;
    r: number;
    color: string;
    label: string;
    selected: boolean;
  };

  type NodePopover = {
    key: string;
    title: string;
    kind: string;
    preview: string;
    x: number;
    y: number;
  };

  export let itemPayload: AutopsyPayload | null = null;
  export let neighborsPayload: AutopsyPayload | null = null;
  export let timelinePayload: AutopsyPayload | null = null;
  export let selectedStableKey = "";
  export let showLabels = true;
  export let panEnabled = true;
  export let graphBusy = false;
  export let onSelectNode: (stableKey: string) => void = () => {};

  let container: HTMLDivElement;
  let renderer: Sigma | null = null;
  let graph: Graph | null = null;
  let renderSignature = "";
  let settingsSignature = "";
  let overlayEdges: OverlayEdge[] = [];
  let overlayNodes: OverlayNode[] = [];
  let popover: NodePopover | null = null;
  let hasGraph = false;
  let cancelNodeAnimation: (() => void) | null = null;
  let overlayFrame = 0;
  let resizeObserver: ResizeObserver | null = null;

  function currentSignature() {
    return JSON.stringify({
      item: itemPayload?.item?.stable_key,
      links: itemPayload?.item?.links?.length ?? 0,
      relations: itemPayload?.item?.relations?.length ?? 0,
      neighbors: neighborsPayload?.neighbors?.length ?? 0,
      events: timelinePayload?.timeline?.events?.length ?? 0
    });
  }

  function edgeCurve(source: { x: number; y: number }, target: { x: number; y: number }, index: number) {
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const distance = Math.max(1, Math.hypot(dx, dy));
    const bend = Math.min(160, Math.max(44, distance * 0.34));
    const normalX = (-dy / distance) * (index % 2 === 0 ? 18 : -18);
    const normalY = (dx / distance) * (index % 2 === 0 ? 18 : -18);
    const c1 = { x: source.x + dx * 0.35 + normalX + bend * 0.12, y: source.y + dy * 0.18 + normalY };
    const c2 = { x: target.x - dx * 0.35 + normalX - bend * 0.12, y: target.y - dy * 0.18 + normalY };
    return `M ${source.x.toFixed(1)} ${source.y.toFixed(1)} C ${c1.x.toFixed(1)} ${c1.y.toFixed(1)} ${c2.x.toFixed(1)} ${c2.y.toFixed(1)} ${target.x.toFixed(1)} ${target.y.toFixed(1)}`;
  }

  function shortLabel(value: unknown) {
    const label = String(value ?? "");
    return label.length > 34 ? `${label.slice(0, 31)}...` : label;
  }

  function updatePopoverPosition() {
    if (!popover || !renderer || !graph || !graph.hasNode(popover.key)) return;
    const attrs = graph.getNodeAttributes(popover.key);
    const point = renderer.graphToViewport({ x: Number(attrs.x ?? 0), y: Number(attrs.y ?? 0) });
    popover = { ...popover, x: point.x, y: point.y };
  }

  function updateOverlay() {
    if (!renderer || !graph) {
      overlayEdges = [];
      overlayNodes = [];
      return;
    }

    const nextEdges: OverlayEdge[] = [];
    const nextNodes: OverlayNode[] = [];
    let index = 0;
    graph.forEachNode((node, attributes) => {
      if (!renderer) return;
      const point = renderer.graphToViewport({ x: Number(attributes.x ?? 0), y: Number(attributes.y ?? 0) });
      nextNodes.push({
        key: String(node),
        x: point.x,
        y: point.y,
        r: node === selectedStableKey ? 8 : 5.5,
        color: String(attributes.color ?? "#9adfd2"),
        label: shortLabel(attributes.title ?? attributes.label ?? node),
        selected: node === selectedStableKey
      });
    });

    graph.forEachEdge((edge, attributes, source, target) => {
      if (!graph || !renderer || !graph.hasNode(source) || !graph.hasNode(target)) return;
      const sourceAttrs = graph.getNodeAttributes(source);
      const targetAttrs = graph.getNodeAttributes(target);
      const sourcePoint = renderer.graphToViewport({ x: Number(sourceAttrs.x ?? 0), y: Number(sourceAttrs.y ?? 0) });
      const targetPoint = renderer.graphToViewport({ x: Number(targetAttrs.x ?? 0), y: Number(targetAttrs.y ?? 0) });
      nextEdges.push({
        key: String(edge),
        path: edgeCurve(sourcePoint, targetPoint, index),
        color: String(attributes.color ?? "rgba(255,255,255,0.38)"),
        label: String(attributes.label ?? "")
      });
      index += 1;
    });

    overlayEdges = nextEdges;
    overlayNodes = nextNodes;
    updatePopoverPosition();
  }

  function startOverlayLoop(duration = 520) {
    cancelAnimationFrame(overlayFrame);
    const started = performance.now();
    const frame = () => {
      updateOverlay();
      if (performance.now() - started < duration) {
        overlayFrame = requestAnimationFrame(frame);
      }
    };
    overlayFrame = requestAnimationFrame(frame);
  }

  function applySettings() {
    if (!renderer) return;
    const nextSettings = JSON.stringify({ showLabels, panEnabled, selectedStableKey, popover: popover?.key ?? "" });
    if (nextSettings === settingsSignature) return;
    settingsSignature = nextSettings;
    renderer.setSettings({
      renderLabels: showLabels,
      enableCameraPanning: panEnabled,
      nodeReducer: (node, data) => {
        if (node === selectedStableKey || node === popover?.key) {
          return {
            ...data,
            color: "#9adfd2",
            size: data.size * 1.18,
            zIndex: 10
          };
        }
        return data;
      }
    });
    renderer.refresh({ schedule: true });
  }

  function openNodePopover(key: string) {
    if (!renderer || !graph || !graph.hasNode(key)) return;
    const attrs = graph.getNodeAttributes(key);
    const point = renderer.graphToViewport({ x: Number(attrs.x ?? 0), y: Number(attrs.y ?? 0) });
    popover = {
      key,
      title: String(attrs.title ?? attrs.label ?? key),
      kind: String(attrs.kind ?? "memory"),
      preview: String(attrs.preview ?? ""),
      x: point.x,
      y: point.y
    };
    applySettings();
  }

  function installRenderer(nextGraph: Graph) {
    graph = nextGraph;
    renderer?.kill();
    renderer = new Sigma(graph, container, {
      allowInvalidContainer: true,
      autoCenter: true,
      autoRescale: true,
      enableCameraPanning: panEnabled,
      enableCameraZooming: true,
      hideEdgesOnMove: false,
      hideLabelsOnMove: true,
      itemSizesReference: "screen",
      labelColor: { color: "rgba(255,255,255,0.58)" },
      labelDensity: 0.52,
      labelGridCellSize: 84,
      labelRenderedSizeThreshold: 9,
      labelSize: 11,
      maxCameraRatio: 2.4,
      minCameraRatio: 0.34,
      renderEdgeLabels: false,
      renderLabels: showLabels,
      stagePadding: 28,
      zIndex: true,
      edgeReducer: () => ({ hidden: true }),
      nodeReducer: (node, data) => {
        if (node === selectedStableKey) {
          return { ...data, color: "#9adfd2", size: data.size * 1.18, zIndex: 10 };
        }
        return data;
      }
    });

    renderer.on("clickNode", ({ node }) => {
      openNodePopover(String(node));
    });
    renderer.on("clickStage", () => {
      popover = null;
      applySettings();
    });
    renderer.getCamera().on("updated", updateOverlay);

    resizeObserver?.disconnect();
    resizeObserver = new ResizeObserver(() => {
      renderer?.resize();
      updateOverlay();
    });
    resizeObserver.observe(container);
    startOverlayLoop();
  }

  function syncEdges(targetGraph: Graph) {
    if (!graph) return;

    graph.edges().forEach((edge) => {
      if (!targetGraph.hasEdge(edge)) graph?.dropEdge(edge);
    });

    targetGraph.forEachEdge((edge, attributes, source, target) => {
      if (!graph) return;
      if (graph.hasEdge(edge)) {
        graph.mergeEdgeAttributes(edge, attributes);
      } else if (graph.hasNode(source) && graph.hasNode(target)) {
        graph.addDirectedEdgeWithKey(edge, source, target, attributes);
      }
    });
  }

  function syncGraph() {
    if (!container) return;
    const signature = currentSignature();
    if (signature === renderSignature) return;
    renderSignature = signature;

    const targetGraph = buildNeighborhoodGraph(itemPayload, neighborsPayload, timelinePayload);
    hasGraph = targetGraph.order > 0;
    popover = null;

    if (!graph || !renderer) {
      installRenderer(targetGraph);
      return;
    }

    cancelNodeAnimation?.();
    const targets: Record<string, Record<string, number>> = {};
    const targetNodes = new Set(targetGraph.nodes());
    const currentNodes = new Set(graph.nodes());
    const focusKey = selectedStableKey && graph.hasNode(selectedStableKey) ? selectedStableKey : graph.nodes()[0];
    const focusAttrs = focusKey ? graph.getNodeAttributes(focusKey) : { x: 0, y: 0 };

    targetGraph.forEachNode((node, targetAttrs) => {
      if (graph?.hasNode(node)) {
        const currentAttrs = graph.getNodeAttributes(node);
        graph.mergeNodeAttributes(node, {
          ...targetAttrs,
          x: currentAttrs.x,
          y: currentAttrs.y,
          size: currentAttrs.size
        });
      } else {
        graph?.addNode(node, {
          ...targetAttrs,
          x: Number(focusAttrs.x ?? 0),
          y: Number(focusAttrs.y ?? 0),
          size: 1
        });
      }
      targets[node] = {
        x: Number(targetAttrs.x ?? 0),
        y: Number(targetAttrs.y ?? 0),
        size: Number(targetAttrs.size ?? 8)
      };
    });

    currentNodes.forEach((node) => {
      if (!targetNodes.has(node)) {
        const attrs = graph?.getNodeAttributes(node) ?? { x: 0, y: 0 };
        targets[node] = {
          x: Number(attrs.x ?? 0) * 0.62,
          y: Number(attrs.y ?? 0) * 0.62,
          size: 0.2
        };
      }
    });

    syncEdges(targetGraph);
    cancelNodeAnimation = animateNodes(
      graph,
      targets,
      { duration: 460, easing: "cubicInOut" },
      () => {
        if (!graph) return;
        currentNodes.forEach((node) => {
          if (!targetNodes.has(node) && graph?.hasNode(node)) graph.dropNode(node);
        });
        cancelNodeAnimation = null;
        updateOverlay();
      }
    );
    renderer.refresh({ schedule: true });
    startOverlayLoop(560);
  }

  export function fit() {
    void renderer?.getCamera().animatedReset({ duration: 320, easing: "cubicInOut" });
    startOverlayLoop(360);
  }

  export function zoomIn() {
    void renderer?.getCamera().animatedZoom({ duration: 220, easing: "cubicOut", factor: 1.35 });
    startOverlayLoop(260);
  }

  export function zoomOut() {
    void renderer?.getCamera().animatedUnzoom({ duration: 220, easing: "cubicOut", factor: 1.35 });
    startOverlayLoop(260);
  }

  function focusNode(key: string) {
    if (!renderer || !graph || !key || !graph.hasNode(key)) {
      fit();
      return;
    }
    const attrs = graph.getNodeAttributes(key);
    const viewportPoint = renderer.graphToViewport({ x: Number(attrs.x ?? 0), y: Number(attrs.y ?? 0) });
    const framedPoint = renderer.viewportToFramedGraph(viewportPoint);
    void renderer.getCamera().animate({ x: framedPoint.x, y: framedPoint.y, ratio: 0.72 }, { duration: 320, easing: "cubicInOut" });
    startOverlayLoop(360);
  }

  export function focusSelected() {
    focusNode(selectedStableKey);
  }

  afterUpdate(() => {
    syncGraph();
    applySettings();
  });

  onDestroy(() => {
    cancelNodeAnimation?.();
    cancelAnimationFrame(overlayFrame);
    resizeObserver?.disconnect();
    renderer?.kill();
  });
</script>

<div class="graph-shell">
  <div bind:this={container} class="graph-canvas"></div>

  <svg class="graph-edge-layer">
    {#each overlayEdges as edge}
      <path d={edge.path} stroke={edge.color} />
    {/each}
    {#each overlayNodes as node}
      <g
        class="graph-node"
        class:selected={node.selected}
        role="button"
        tabindex="0"
        aria-label={`Inspect ${node.label}`}
        transform={`translate(${node.x.toFixed(1)} ${node.y.toFixed(1)})`}
        on:click|stopPropagation={() => openNodePopover(node.key)}
        on:keydown={(event) => {
          if (event.key === "Enter" || event.key === " ") openNodePopover(node.key);
        }}
      >
        <title>{node.label}</title>
        <circle r={node.r} fill={node.color} />
        {#if showLabels}
          <text x="10" y="4">{node.label}</text>
        {/if}
      </g>
    {/each}
  </svg>

  {#if graphBusy}
    <div class="graph-loading">
      <span></span>
      <strong>Fetching graph context</strong>
    </div>
  {/if}

  {#if !hasGraph}
    <div class="graph-empty">
      <span>Choose a memory result to render its local graph.</span>
    </div>
  {/if}

  {#if popover}
    <div class="node-popover" style={`left:${popover.x}px;top:${popover.y}px;`}>
      <div>
        <span>{popover.kind}</span>
        <strong>{popover.title}</strong>
        <p>{popover.preview || popover.key}</p>
      </div>
      <footer>
        <button type="button" on:click={() => onSelectNode(popover?.key ?? "")}>Inspect</button>
        <button type="button" on:click={() => focusNode(popover?.key ?? "")}>Focus</button>
        <button type="button" on:click={() => (popover = null)}>Close</button>
      </footer>
    </div>
  {/if}
</div>

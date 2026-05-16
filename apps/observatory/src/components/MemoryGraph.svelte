<script lang="ts">
  import { afterUpdate, onDestroy } from "svelte";
  import Sigma from "sigma";
  import { buildNeighborhoodGraph } from "../lib/graph";
  import type { AutopsyPayload } from "../lib/types";

  export let itemPayload: AutopsyPayload | null = null;
  export let neighborsPayload: AutopsyPayload | null = null;
  export let timelinePayload: AutopsyPayload | null = null;
  export let showLabels = true;

  let container: HTMLDivElement;
  let renderer: Sigma | null = null;
  let renderSignature = "";

  function render() {
    if (!container) return;
    const nextSignature = JSON.stringify({
      item: itemPayload?.item?.stable_key,
      links: itemPayload?.item?.links?.length ?? 0,
      relations: itemPayload?.item?.relations?.length ?? 0,
      neighbors: neighborsPayload?.neighbors?.length ?? 0,
      events: timelinePayload?.timeline?.events?.length ?? 0,
      showLabels
    });
    if (nextSignature === renderSignature) return;
    renderSignature = nextSignature;
    renderer?.kill();
    const graph = buildNeighborhoodGraph(itemPayload, neighborsPayload, timelinePayload);
    renderer = new Sigma(graph, container, {
      allowInvalidContainer: true,
      renderLabels: showLabels,
      renderEdgeLabels: false,
      labelColor: { color: "rgba(255,255,255,0.56)" },
      edgeLabelColor: { color: "rgba(255,255,255,0.32)" },
      defaultEdgeType: "arrow",
      defaultNodeType: "circle",
      labelSize: 11,
      edgeLabelSize: 10,
      labelDensity: 0.55,
      labelGridCellSize: 80,
      labelRenderedSizeThreshold: 9,
      minCameraRatio: 0.42,
      maxCameraRatio: 2.4
    });
  }

  afterUpdate(render);

  onDestroy(() => {
    renderer?.kill();
  });
</script>

<div class="graph-shell">
  <div bind:this={container} class="graph-canvas"></div>
  {#if !itemPayload?.item}
    <div class="graph-empty">
      <span>Choose a memory result to render its local graph.</span>
    </div>
  {/if}
</div>

<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import MemoryGraph from "./components/MemoryGraph.svelte";
  import {
    autopsyBackup,
    autopsyConsult,
    autopsyHealth,
    autopsyItem,
    autopsyNeighbors,
    autopsyStatus,
    autopsyTimeline
  } from "./lib/api";
  import type { AutopsyPayload, MemorySummary, UiEvent } from "./lib/types";
  import { previewOf, stableKeyOf, titleOf } from "./lib/types";

  type RouteId = "lexical" | "hybrid" | "auto";
  type ModeId = "consult" | "inspect" | "trace";
  type ViewId = "overview" | "graph" | "items" | "timeline" | "trace" | "falkor";
  type TimelineFilter = "all" | "activity" | "decision" | "attempt" | "commit" | "thread";
  type TimelineRange = "7d" | "30d" | "all";

  type DetailBundle = {
    item: AutopsyPayload | null;
    neighbors: AutopsyPayload | null;
    timeline: AutopsyPayload | null;
  };

  const routeOptions: Array<{ id: RouteId; label: string; hint: string }> = [
    { id: "lexical", label: "Fast", hint: "Lexical route, no inspection fan-out" },
    { id: "hybrid", label: "Deep", hint: "Hybrid retrieval with inspected top hits" },
    { id: "auto", label: "Auto", hint: "Let Autopsy select the route" }
  ];

  const modeOptions: Array<{ id: ModeId; label: string }> = [
    { id: "consult", label: "Consult" },
    { id: "inspect", label: "Inspect" },
    { id: "trace", label: "Trace" }
  ];

  const viewOptions: Array<{ id: ViewId; label: string; title: string }> = [
    { id: "overview", label: "O", title: "Refresh overview" },
    { id: "graph", label: "G", title: "Graph workspace" },
    { id: "items", label: "I", title: "Expand active items" },
    { id: "timeline", label: "T", title: "Timeline focus" },
    { id: "trace", label: "C", title: "Command trace" },
    { id: "falkor", label: "F", title: "Refresh Falkor health" }
  ];

  const timelineFilters: Array<{ id: TimelineFilter; label: string }> = [
    { id: "all", label: "Timeline" },
    { id: "activity", label: "Activity" },
    { id: "decision", label: "Decisions" },
    { id: "attempt", label: "Attempts" },
    { id: "commit", label: "Commits" },
    { id: "thread", label: "Threads" }
  ];

  let query = "Autopsy Observatory";
  let queryInput: HTMLInputElement;
  let graphControl: {
    fit?: () => void;
    zoomIn?: () => void;
    zoomOut?: () => void;
    focusSelected?: () => void;
  } | null = null;
  let route: RouteId = "lexical";
  let mode: ModeId = "consult";
  let activeView: ViewId = "graph";
  let timelineFilter: TimelineFilter = "all";
  let timelineRange: TimelineRange = "7d";
  let showGraphLabels = true;
  let panEnabled = true;
  let showSuperseded = true;
  let timelinePlaying = false;
  let activeTimelineIndex = 0;
  let expandedQueries = false;
  let expandedActive = false;
  let expandedTrace = false;
  let savedQueries = ["CLI launcher history", "Observatory redesign", "Graph popover anchoring", "Memory health checks"];
  let health: AutopsyPayload | null = null;
  let status: AutopsyPayload | null = null;
  let consult: AutopsyPayload | null = null;
  let itemPayload: AutopsyPayload | null = null;
  let neighborsPayload: AutopsyPayload | null = null;
  let timelinePayload: AutopsyPayload | null = null;
  let selectedStableKey = "";
  let detailLoadingKey = "";
  let loadingState: Record<string, boolean> = {};
  let error = "";
  let events: UiEvent[] = [];
  let detailCache = new Map<string, DetailBundle>();
  let consultCache = new Map<string, AutopsyPayload>();
  let timelineTimer: number | null = null;
  let disposers: Array<() => void> = [];

  $: counts = health?.counts ?? {};
  $: checks = health?.checks ?? {};
  $: runningLabels = Object.entries(loadingState)
    .filter(([, running]) => running)
    .map(([label]) => label);
  $: anyLoading = runningLabels.length > 0;
  $: activeItems = (status?.status?.active_now ?? []) as MemorySummary[];
  $: hits = (consult?.hits ?? []) as MemorySummary[];
  $: workflow = consult?.workflow ?? null;
  $: timings = consult?.timings ?? {};
  $: selectedItem = itemPayload?.item ?? null;
  $: selectedHit = hits.find((hit) => stableKeyOf(hit) === selectedStableKey) ?? null;
  $: selectedMemory = selectedItem ?? selectedHit ?? activeItems.find((item) => stableKeyOf(item) === selectedStableKey) ?? null;
  $: selectedKind = String(selectedMemory?.kind ?? selectedItem?.kind ?? "memory");
  $: selectedTitle = titleOf(selectedMemory) || "No memory selected";
  $: selectedPreview = previewOf(selectedMemory);
  $: selectedContent = String(selectedItem?.content ?? selectedPreview ?? "Select a memory to inspect its exact evidence.");
  $: relationRows = (selectedItem?.relations ?? []) as AutopsyPayload[];
  $: linkRows = (selectedItem?.links ?? []) as AutopsyPayload[];
  $: timelineEvents = (timelinePayload?.timeline?.events ?? []) as AutopsyPayload[];
  $: retrievalReasons = (selectedHit?.retrieval_reasons ?? []) as string[];
  $: statusSummary = status?.status?.summary ?? "No status loaded yet.";
  $: commandState = anyLoading ? `${runningLabels.length} running` : "ready";
  $: visibleSavedQueries = expandedQueries ? savedQueries : savedQueries.slice(0, 4);
  $: visibleActiveItems = expandedActive ? activeItems : activeItems.slice(0, 5);
  $: visibleEvents = expandedTrace ? events : events.slice(0, 5);
  $: rawTimelineMarkers = buildTimelineMarkers(timelineEvents, hits, activeItems);
  $: filteredTimelineMarkers = filterTimelineMarkers(rawTimelineMarkers, timelineFilter, showSuperseded, timelineRange);
  $: timelinePath = buildTimelinePath(filteredTimelineMarkers);
  $: clampedTimelineIndex = Math.min(activeTimelineIndex, Math.max(0, filteredTimelineMarkers.length - 1));

  function setLoading(label: string, running: boolean) {
    loadingState = { ...loadingState, [label]: running };
  }

  function isRunning(labelPrefix: string) {
    return runningLabels.some((label) => label.startsWith(labelPrefix));
  }

  function pushEvent(kind: UiEvent["kind"], message: string) {
    events = [{ at: new Date().toLocaleTimeString(), kind, message }, ...events].slice(0, 24);
  }

  async function guarded<T>(label: string, action: () => Promise<T>): Promise<T | null> {
    setLoading(label, true);
    error = "";
    const started = performance.now();
    try {
      const result = await action();
      const elapsed = Math.round(performance.now() - started);
      const cacheHit = Boolean((result as AutopsyPayload)?.observatory?.cache_hit);
      pushEvent("success", `${label} ${cacheHit ? "cache" : "completed"} in ${elapsed}ms`);
      return result;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught);
      error = message;
      pushEvent("error", `${label} failed`);
      return null;
    } finally {
      setLoading(label, false);
    }
  }

  async function refreshOverview() {
    const healthPromise = guarded("health", autopsyHealth);
    const statusPromise = guarded("status", () => autopsyStatus(8, 5));
    const [nextHealth, nextStatus] = await Promise.all([healthPromise, statusPromise]);

    if (nextHealth) health = nextHealth;
    if (nextStatus) {
      status = nextStatus;
      const firstKey = stableKeyOf((nextStatus.status?.active_now ?? [])[0]);
      if (!selectedStableKey && firstKey) {
        selectMemory(firstKey, false);
        void loadMemoryDetails(firstKey);
      }
    }
  }

  function inspectLimitForRoute(value: RouteId) {
    if (value === "hybrid") return 2;
    if (value === "auto") return 1;
    return 0;
  }

  async function runConsult() {
    const cleanQuery = query.trim();
    if (!cleanQuery) {
      error = "Enter a query before consulting memory.";
      return;
    }

    const cacheKey = `${route}:${cleanQuery}`;
    const cached = consultCache.get(cacheKey);
    if (cached) {
      consult = cached;
      pushEvent("info", "consult cache rendered instantly");
      selectFirstHit(cached);
      mode = "consult";
      activeView = "graph";
      return;
    }

    const result = await guarded(`consult:${route}`, () => autopsyConsult(cleanQuery, 8, inspectLimitForRoute(route), route));
    if (!result) return;
    consult = result;
    consultCache.set(cacheKey, result);
    consultCache = new Map(consultCache);
    if (result.status) status = result;
    selectFirstHit(result);
    mode = "consult";
    activeView = "graph";
  }

  function selectFirstHit(payload: AutopsyPayload) {
    const firstKey = stableKeyOf((payload.hits ?? [])[0]);
    if (firstKey) {
      selectMemory(firstKey, false);
      void loadMemoryDetails(firstKey);
    }
  }

  function selectMemory(stableKey: string, load = true) {
    if (!stableKey) return;
    selectedStableKey = stableKey;
    const cached = detailCache.get(stableKey);
    if (cached) {
      itemPayload = cached.item;
      neighborsPayload = cached.neighbors;
      timelinePayload = cached.timeline;
    } else {
      itemPayload = null;
      neighborsPayload = null;
      timelinePayload = null;
    }
    if (load) void loadMemoryDetails(stableKey);
  }

  async function loadMemoryDetails(stableKey: string, force = false) {
    if (!stableKey) return;
    const cached = detailCache.get(stableKey);
    if (cached && !force) {
      itemPayload = cached.item;
      neighborsPayload = cached.neighbors;
      timelinePayload = cached.timeline;
      pushEvent("info", `detail cache loaded for ${compactKey(stableKey)}`);
      return;
    }

    detailLoadingKey = stableKey;
    const bundle: DetailBundle = { item: null, neighbors: null, timeline: null };
    const itemPromise = guarded(`item:${compactKey(stableKey)}`, () => autopsyItem(stableKey)).then((nextItem) => {
      bundle.item = nextItem;
      if (selectedStableKey === stableKey) itemPayload = nextItem;
      return nextItem;
    });
    const neighborsPromise = guarded(`neighbors:${compactKey(stableKey)}`, () => autopsyNeighbors(stableKey, 18)).then((nextNeighbors) => {
      bundle.neighbors = nextNeighbors;
      if (selectedStableKey === stableKey) neighborsPayload = nextNeighbors;
      return nextNeighbors;
    });
    const timelinePromise = guarded(`timeline:${compactKey(stableKey)}`, () => autopsyTimeline(stableKey)).then((nextTimeline) => {
      bundle.timeline = nextTimeline;
      if (selectedStableKey === stableKey) timelinePayload = nextTimeline;
      return nextTimeline;
    });
    const [nextItem, nextNeighbors, nextTimeline] = await Promise.all([itemPromise, neighborsPromise, timelinePromise]);
    bundle.item = nextItem;
    bundle.neighbors = nextNeighbors;
    bundle.timeline = nextTimeline;
    detailCache.set(stableKey, bundle);
    detailCache = new Map(detailCache);

    if (selectedStableKey === stableKey) {
      itemPayload = nextItem;
      neighborsPayload = nextNeighbors;
      timelinePayload = nextTimeline;
    }
    if (detailLoadingKey === stableKey) detailLoadingKey = "";
  }

  async function runBackup() {
    const result = await guarded("backup", autopsyBackup);
    if (result?.written) pushEvent("info", `backup written to ${result.written}`);
  }

  function runSavedQuery(value: string) {
    query = value;
    void runConsult();
  }

  function saveCurrentQuery() {
    const cleanQuery = query.trim();
    if (!cleanQuery || savedQueries.includes(cleanQuery)) return;
    savedQueries = [cleanQuery, ...savedQueries].slice(0, 12);
    expandedQueries = true;
    pushEvent("info", "saved current query");
  }

  function selectView(view: ViewId) {
    activeView = view;
    if (view === "overview") void refreshOverview();
    if (view === "items") expandedActive = true;
    if (view === "trace") {
      mode = "trace";
      expandedTrace = true;
    }
    if (view === "timeline") mode = "inspect";
    if (view === "falkor") void guarded("health", autopsyHealth).then((nextHealth) => {
      if (nextHealth) health = nextHealth;
    });
  }

  function handleGraphNodeSelect(stableKey: string) {
    selectMemory(stableKey);
    mode = "inspect";
    activeView = "graph";
  }

  function runGraphAction(action: "pan" | "focus" | "fit" | "zoom-in" | "zoom-out" | "labels") {
    if (action === "pan") panEnabled = !panEnabled;
    if (action === "focus") graphControl?.focusSelected?.();
    if (action === "fit") graphControl?.fit?.();
    if (action === "zoom-in") graphControl?.zoomIn?.();
    if (action === "zoom-out") graphControl?.zoomOut?.();
    if (action === "labels") showGraphLabels = !showGraphLabels;
  }

  function formatMs(value: unknown): string {
    if (value === undefined || value === null || value === "") return "--";
    return `${value} ms`;
  }

  function compactKey(value: string): string {
    if (!value) return "--";
    return value.length > 22 ? `${value.slice(0, 10)}...${value.slice(-8)}` : value;
  }

  function relationCount(name: string): number {
    return relationRows.filter((relationItem) => String(relationItem.relation ?? "").replace("-", "_") === name).length;
  }

  function markerKey(marker: AutopsyPayload | null | undefined): string {
    if (!marker) return "";
    return String(marker.stable_key ?? marker.stableKey ?? marker.entity_stable_key ?? "");
  }

  function markerKind(marker: AutopsyPayload | null | undefined): string {
    if (!marker) return "activity";
    return String(marker.kind ?? marker.entity_kind ?? marker.relation ?? "activity").toLowerCase();
  }

  function markerLabel(marker: AutopsyPayload | null | undefined): string {
    if (!marker) return "";
    return String(marker.entity_label ?? marker.title ?? marker.label ?? marker.relation ?? "Memory event");
  }

  function markerSummary(marker: AutopsyPayload | null | undefined): string {
    if (!marker) return "";
    return String(marker.fact_text ?? marker.summary ?? marker.preview ?? marker.content ?? markerLabel(marker));
  }

  function markerDate(marker: AutopsyPayload | null | undefined): Date | null {
    if (!marker) return null;
    const raw = marker.updated_at ?? marker.activity_at ?? marker.valid_at ?? marker.created_at;
    if (!raw) return null;
    const date = new Date(String(raw));
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function buildTimelineMarkers(events: AutopsyPayload[], consultHits: MemorySummary[], active: MemorySummary[]): AutopsyPayload[] {
    if (events.length > 0) return events.slice(0, 18);
    const merged = [...consultHits, ...active];
    const seen = new Set<string>();
    return merged
      .filter((item) => {
        const key = stableKeyOf(item);
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 18)
      .map((item) => ({
        ...item,
        relation: item.kind,
        entity_label: titleOf(item),
        fact_text: previewOf(item)
      }));
  }

  function filterTimelineMarkers(markers: AutopsyPayload[], filter: TimelineFilter, superseded: boolean, range: TimelineRange): AutopsyPayload[] {
    const now = Date.now();
    const days = range === "7d" ? 7 : range === "30d" ? 30 : null;
    return markers.filter((marker) => {
      const kind = markerKind(marker);
      const summary = markerSummary(marker).toLowerCase();
      const relation = String(marker.relation ?? "").toLowerCase();
      if (!superseded && (relation.includes("supersedes") || relation.includes("reverts"))) return false;
      if (filter !== "all" && filter !== "activity") {
        if (filter === "commit" && !summary.includes("commit")) return false;
        if (filter !== "commit" && !kind.includes(filter)) return false;
      }
      if (days) {
        const date = markerDate(marker);
        if (date && now - date.getTime() > days * 24 * 60 * 60 * 1000) return false;
      }
      return true;
    });
  }

  function markerX(index: number, total: number): number {
    if (total <= 1) return 50;
    return 8 + (index / (total - 1)) * 84;
  }

  function markerY(index: number): number {
    return index % 2 === 0 ? 52 : 38;
  }

  function buildTimelinePath(markers: AutopsyPayload[]): string {
    if (markers.length < 2) return "";
    const points = markers.map((_, index) => ({ x: markerX(index, markers.length), y: markerY(index) }));
    return points.slice(1).reduce((path, point, index) => {
      const previous = points[index];
      const mid = (previous.x + point.x) / 2;
      return `${path} C ${mid.toFixed(1)} ${previous.y.toFixed(1)} ${mid.toFixed(1)} ${point.y.toFixed(1)} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
    }, `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`);
  }

  function selectTimelineMarker(index: number) {
    activeTimelineIndex = index;
    const key = markerKey(filteredTimelineMarkers[index]);
    if (key) selectMemory(key);
  }

  function stepTimeline(direction: -1 | 1) {
    if (filteredTimelineMarkers.length === 0) return;
    const nextIndex = (activeTimelineIndex + direction + filteredTimelineMarkers.length) % filteredTimelineMarkers.length;
    selectTimelineMarker(nextIndex);
  }

  function stopTimelinePlayback() {
    if (timelineTimer !== null) {
      window.clearInterval(timelineTimer);
      timelineTimer = null;
    }
    timelinePlaying = false;
  }

  function toggleTimelinePlayback() {
    if (timelinePlaying) {
      stopTimelinePlayback();
      return;
    }
    timelinePlaying = true;
    timelineTimer = window.setInterval(() => stepTimeline(1), 1400);
  }

  function cycleTimelineRange() {
    timelineRange = timelineRange === "7d" ? "30d" : timelineRange === "30d" ? "all" : "7d";
  }

  function handleShortcut(event: KeyboardEvent) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      queryInput?.focus();
      queryInput?.select();
    }
  }

  onMount(() => {
    window.addEventListener("keydown", handleShortcut);
    void refreshOverview();
    listen("observatory://run-health", () => void refreshOverview()).then((dispose) => disposers.push(dispose));
    listen("observatory://run-backup", () => void runBackup()).then((dispose) => disposers.push(dispose));
  });

  onDestroy(() => {
    window.removeEventListener("keydown", handleShortcut);
    disposers.forEach((dispose) => dispose());
    stopTimelinePlayback();
  });
</script>

<main
  class="observatory-shell"
  class:timeline-focus={activeView === "timeline"}
  class:trace-focus={activeView === "trace"}
>
  <aside class="tool-rail" aria-label="Observatory tools">
    <div class="window-dots" aria-hidden="true">
      <span></span>
      <span></span>
      <span></span>
    </div>

    {#each viewOptions as view}
      <button
        class="rail-button"
        class:active={activeView === view.id}
        type="button"
        aria-label={view.title}
        title={view.title}
        on:click={() => selectView(view.id)}
      >
        {view.label}
      </button>
    {/each}

    <div class="rail-spacer"></div>

    <div class="mini-health" class:healthy={health?.ok}>
      <span></span>
      <strong>Falkor</strong>
      <small>{health?.ok ? "Operational" : isRunning("health") ? "Checking" : "Needs check"}</small>
    </div>
  </aside>

  <aside class="memory-panel panel-shell">
    <header class="brand-stack">
      <p>Autopsy</p>
      <h1>Observatory</h1>
      <span>{statusSummary}</span>
    </header>

    <section class="panel-section health-section">
      <div class="section-heading">
        <span>System</span>
        <button type="button" on:click={refreshOverview} disabled={isRunning("health") || isRunning("status")}>
          {isRunning("health") || isRunning("status") ? "Syncing" : "Refresh"}
        </button>
      </div>
      <div class="health-grid">
        <span>Items <strong>{counts.items ?? "--"}</strong></span>
        <span>Edges <strong>{counts.edges ?? "--"}</strong></span>
        <span>Vectors <strong>{counts.vectors ?? "--"}</strong></span>
        <span>Targets <strong>{checks.init_managed_targets ?? "--"}</strong></span>
      </div>
    </section>

    <section class="panel-section saved-section">
      <div class="section-heading">
        <span>Saved queries</span>
        <button type="button" aria-label="Save current query" on:click={saveCurrentQuery}>Save</button>
      </div>
      {#each visibleSavedQueries as savedQuery, index}
        <button class="saved-query" type="button" on:click={() => runSavedQuery(savedQuery)}>
          <span>{savedQuery}</span>
          <small>#{index + 1}</small>
        </button>
      {/each}
      {#if savedQueries.length > 4}
        <button class="view-all" type="button" on:click={() => (expandedQueries = !expandedQueries)}>
          {expandedQueries ? "Show fewer queries" : "View all queries"}
          <span>{expandedQueries ? "less" : "more"}</span>
        </button>
      {/if}
    </section>

    <section class="panel-section active-section">
      <div class="section-heading">
        <span>Active memories</span>
        <strong>{activeItems.length}</strong>
      </div>
      {#if isRunning("status") && activeItems.length === 0}
        <div class="skeleton-list">
          <span></span>
          <span></span>
          <span></span>
        </div>
      {:else}
        <div class="active-list">
          {#each visibleActiveItems as memory}
            <button
              type="button"
              class:selected={stableKeyOf(memory) === selectedStableKey}
              class="active-memory"
              on:click={() => selectMemory(stableKeyOf(memory))}
            >
              <span>{titleOf(memory)}</span>
              <small>{memory.kind}</small>
              <i></i>
            </button>
          {/each}
        </div>
      {/if}
      {#if activeItems.length > 5}
        <button class="view-all" type="button" on:click={() => (expandedActive = !expandedActive)}>
          {expandedActive ? "Show fewer active" : "View all active"}
          <span>{expandedActive ? "less" : "more"}</span>
        </button>
      {/if}
    </section>

    <section class="panel-section trace-section">
      <div class="section-heading">
        <span>Command trace</span>
        <strong class:live={anyLoading}>{anyLoading ? "Busy" : "Live"}</strong>
      </div>
      {#if visibleEvents.length === 0}
        <p class="muted">No local UI commands yet.</p>
      {:else}
        {#each visibleEvents as event}
          <div class="trace-line" class:bad={event.kind === "error"}>
            <time>{event.at}</time>
            <span>{event.message}</span>
          </div>
        {/each}
      {/if}
      {#if events.length > 5}
        <button class="view-all" type="button" on:click={() => (expandedTrace = !expandedTrace)}>
          {expandedTrace ? "Collapse trace" : "View full trace"}
          <span>{expandedTrace ? "less" : "more"}</span>
        </button>
      {/if}
    </section>
  </aside>

  <section class="workspace-shell">
    <header class="command-deck panel-shell">
      <div class="query-row">
        <input
          bind:this={queryInput}
          bind:value={query}
          aria-label="Memory query"
          placeholder="Ask your memory anything..."
          on:keydown={(event) => event.key === "Enter" && runConsult()}
        />
        <kbd>Command-K</kbd>
        <button class="primary-action" type="button" on:click={runConsult} disabled={isRunning("consult")}>
          {isRunning("consult") ? "Consulting" : "Consult"}
        </button>
      </div>

      <div class="command-meta">
        <div class="segmented-row">
          <span>Route</span>
          {#each routeOptions as option}
            <button class:active={route === option.id} type="button" title={option.hint} on:click={() => (route = option.id)}>
              {option.label}
            </button>
          {/each}
        </div>
        <div class="segmented-row mode-row">
          <span>Mode</span>
          {#each modeOptions as option}
            <button class:active={mode === option.id} type="button" on:click={() => (mode = option.id)}>{option.label}</button>
          {/each}
        </div>
      </div>
    </header>

    {#if error}
      <div class="error-banner">
        <span>{error}</span>
        <button type="button" on:click={() => (error = "")}>Dismiss</button>
      </div>
    {/if}

    <section class="graph-stage panel-shell">
      <div class="canvas-tools" aria-label="Graph controls">
        <button type="button" class:active={panEnabled} on:click={() => runGraphAction("pan")}>{panEnabled ? "Pan" : "Lock"}</button>
        <button type="button" on:click={() => runGraphAction("focus")}>Focus</button>
        <button type="button" on:click={() => runGraphAction("fit")}>Fit</button>
        <button type="button" on:click={() => runGraphAction("zoom-in")}>+</button>
        <button type="button" on:click={() => runGraphAction("zoom-out")}>-</button>
        <button type="button" class:active={showGraphLabels} on:click={() => runGraphAction("labels")}>
          {showGraphLabels ? "Labels" : "No labels"}
        </button>
      </div>

      <div class="graph-top-actions">
        <span>{commandState}</span>
        <button type="button" on:click={() => selectedStableKey && loadMemoryDetails(selectedStableKey, true)} disabled={!selectedStableKey || !!detailLoadingKey}>
          {detailLoadingKey ? "Loading" : "Reload node"}
        </button>
      </div>

      <MemoryGraph
        bind:this={graphControl}
        {itemPayload}
        {neighborsPayload}
        {timelinePayload}
        {selectedStableKey}
        showLabels={showGraphLabels}
        {panEnabled}
        graphBusy={!!detailLoadingKey && !itemPayload}
        onSelectNode={handleGraphNodeSelect}
      />

      <div class="relation-legend">
        <span><i></i> implements</span>
        <span><i></i> supersedes</span>
        <span><i></i> informed-by</span>
        <span><i></i> refines</span>
      </div>
    </section>

    <section class="timeline-dock panel-shell">
      <header class="dock-header">
        <nav>
          {#each timelineFilters as filter}
            <button class:active={timelineFilter === filter.id} type="button" on:click={() => (timelineFilter = filter.id)}>
              {filter.label}
            </button>
          {/each}
        </nav>
        <div>
          <label><input type="checkbox" bind:checked={showSuperseded} /> Show superseded</label>
          <button type="button" on:click={cycleTimelineRange}>{timelineRange}</button>
        </div>
      </header>

      <div class="timeline-track">
        <svg class="timeline-curve" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {#if timelinePath}
            <path d={timelinePath} />
          {/if}
        </svg>
        {#each filteredTimelineMarkers as marker, index}
          <button
            type="button"
            class="timeline-marker"
            class:active={index === activeTimelineIndex}
            style={`--x:${markerX(index, filteredTimelineMarkers.length)}%;--y:${markerY(index)}%`}
            title={markerSummary(marker)}
            on:click={() => selectTimelineMarker(index)}
          >
            <span>{markerKind(marker).slice(0, 1).toUpperCase()}</span>
          </button>
        {/each}
        <div class="timeline-playhead" style={`--x:${markerX(clampedTimelineIndex, filteredTimelineMarkers.length || 1)}%;`}>
          <strong>{timelineRange}</strong>
          <span>{markerLabel(filteredTimelineMarkers[clampedTimelineIndex]) || selectedTitle}</span>
        </div>
      </div>

      <footer class="timeline-footer">
        <div>
          <span><i class="commit"></i> Commit</span>
          <span><i class="decision"></i> Decision</span>
          <span><i class="attempt"></i> Attempt</span>
          <span><i class="thread"></i> Thread</span>
        </div>
        <div class="transport">
          <button type="button" on:click={() => selectTimelineMarker(0)} disabled={filteredTimelineMarkers.length === 0}>Start</button>
          <button type="button" on:click={() => stepTimeline(-1)} disabled={filteredTimelineMarkers.length === 0}>Prev</button>
          <button type="button" on:click={toggleTimelinePlayback} disabled={filteredTimelineMarkers.length === 0}>
            {timelinePlaying ? "Pause" : "Play"}
          </button>
          <button type="button" on:click={() => stepTimeline(1)} disabled={filteredTimelineMarkers.length === 0}>Next</button>
          <button type="button" on:click={() => (timelineRange = "all")}>Fit</button>
        </div>
      </footer>
    </section>
  </section>

  <aside class="inspector-panel panel-shell">
    <header class="inspector-header">
      <span>{mode === "trace" ? "Command trace" : "Selected memory"}</span>
      <button type="button" aria-label="Refresh selected memory" on:click={() => selectedStableKey && loadMemoryDetails(selectedStableKey, true)} disabled={!selectedStableKey || !!detailLoadingKey}>
        R
      </button>
    </header>

    <section class="selected-summary">
      <div>
        <h2>{selectedTitle}</h2>
        <p>{selectedStableKey ? compactKey(selectedStableKey) : "Select a result or active memory."}</p>
      </div>
      <span class="kind-pill">{selectedKind}</span>
    </section>

    {#if mode === "trace"}
      <section class="inspector-section trace-detail">
        <div class="section-label">Operations</div>
        {#if events.length === 0}
          <p class="muted">No commands have run in this session.</p>
        {:else}
          {#each events as event}
            <div class="trace-line" class:bad={event.kind === "error"}>
              <time>{event.at}</time>
              <span>{event.message}</span>
            </div>
          {/each}
        {/if}
      </section>
    {:else}
      <section class="inspector-section">
        <div class="section-label">Content excerpt</div>
        {#if detailLoadingKey && !selectedItem}
          <div class="skeleton-copy">
            <span></span>
            <span></span>
            <span></span>
          </div>
        {:else}
          <p>{selectedContent}</p>
        {/if}
      </section>

      <section class="inspector-grid">
        <div>
          <span>Kind</span>
          <strong>{selectedKind}</strong>
        </div>
        <div>
          <span>Confidence</span>
          <strong>{selectedItem?.confidence ?? "--"}</strong>
        </div>
        <div>
          <span>Status</span>
          <strong>{workflow?.complete === false ? "needs follow-up" : workflow ? "workflow.complete" : "--"}</strong>
        </div>
        <div>
          <span>Stable key</span>
          <strong>{selectedStableKey ? compactKey(selectedStableKey) : "--"}</strong>
        </div>
        <div>
          <span>Source</span>
          <strong>{selectedItem?.source_kind ?? selectedMemory?.source_kind ?? "--"}</strong>
        </div>
        <div>
          <span>Repository</span>
          <strong>{selectedItem?.repository_name ?? selectedMemory?.repository_name ?? "system"}</strong>
        </div>
      </section>

      {#if mode === "consult"}
        <section class="inspector-section">
          <div class="section-label">Retrieval reasons</div>
          {#if retrievalReasons.length > 0}
            <ul class="reason-list">
              {#each retrievalReasons as reason}
                <li>{reason}</li>
              {/each}
            </ul>
          {:else}
            <p class="muted">Run a consult and select a result to see retrieval reasons.</p>
          {/if}
        </section>

        <section class="timing-strip">
          <div>
            <span>Retrieved in</span>
            <strong>{formatMs(consult?.observatory?.elapsed_ms)}</strong>
          </div>
          <div>
            <span>Lexical</span>
            <strong>{formatMs(timings.lexical_s ? Number(timings.lexical_s * 1000).toFixed(0) : null)}</strong>
          </div>
          <div>
            <span>Rerank</span>
            <strong>{formatMs(timings.rerank_s ? Number(timings.rerank_s * 1000).toFixed(0) : null)}</strong>
          </div>
        </section>
      {:else}
        <section class="timing-strip">
          <div>
            <span>Graph hop</span>
            <strong>{linkRows.length + relationRows.length}</strong>
          </div>
          <div>
            <span>Neighbors</span>
            <strong>{(neighborsPayload?.neighbors ?? []).length}</strong>
          </div>
          <div>
            <span>Timeline</span>
            <strong>{timelineEvents.length}</strong>
          </div>
        </section>
      {/if}

      <section class="inspector-section">
        <div class="section-heading">
          <span>Relations ({relationRows.length})</span>
        </div>
        <div class="relation-chips">
          <span>implements <strong>{relationCount("implements")}</strong></span>
          <span>supersedes <strong>{relationCount("supersedes")}</strong></span>
          <span>informed-by <strong>{relationCount("informed_by")}</strong></span>
          <span>refines <strong>{relationCount("refines")}</strong></span>
        </div>
      </section>
    {/if}
  </aside>
</main>

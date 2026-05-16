<script lang="ts">
  import { onMount } from "svelte";
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

  const routeOptions = ["Exact", "Lexical", "Vector", "Rerank"];
  const modeOptions = ["Consult", "Inspect", "Trace"];
  const savedQueries = [
    "CLI launcher history",
    "Timeline control changes",
    "Superseded by me",
    "Decisions last 7d"
  ];

  let query = "why was CLI launcher added, what changed in 172554?";
  let route = "Rerank";
  let mode = "Consult";
  let showGraphLabels = true;
  let scope = "System";
  let health: AutopsyPayload | null = null;
  let status: AutopsyPayload | null = null;
  let consult: AutopsyPayload | null = null;
  let itemPayload: AutopsyPayload | null = null;
  let neighborsPayload: AutopsyPayload | null = null;
  let timelinePayload: AutopsyPayload | null = null;
  let selectedStableKey = "";
  let loading = "";
  let error = "";
  let events: UiEvent[] = [];

  $: counts = health?.counts ?? {};
  $: checks = health?.checks ?? {};
  $: activeItems = (status?.status?.active_now ?? []) as MemorySummary[];
  $: hits = (consult?.hits ?? []) as MemorySummary[];
  $: workflow = consult?.workflow ?? null;
  $: timings = consult?.timings ?? {};
  $: selectedItem = itemPayload?.item ?? null;
  $: selectedHit = hits.find((hit) => stableKeyOf(hit) === selectedStableKey) ?? null;
  $: selectedMemory = selectedItem ?? selectedHit ?? activeItems.find((item) => stableKeyOf(item) === selectedStableKey) ?? null;
  $: selectedKind = String(selectedMemory?.kind ?? "memory");
  $: selectedTitle = titleOf(selectedMemory);
  $: selectedPreview = previewOf(selectedMemory);
  $: selectedContent = String(selectedItem?.content ?? selectedPreview ?? "Select a memory to inspect its exact evidence.");
  $: relationRows = (selectedItem?.relations ?? []) as AutopsyPayload[];
  $: linkRows = (selectedItem?.links ?? []) as AutopsyPayload[];
  $: timelineEvents = (timelinePayload?.timeline?.events ?? []) as AutopsyPayload[];
  $: retrievalReasons = (selectedHit?.retrieval_reasons ?? []) as string[];
  $: statusSummary = status?.status?.summary ?? "Loading graph status...";
  $: commandState = loading ? `${loading} running` : "ready";
  $: timelineMarkers = (timelineEvents.length > 0
    ? timelineEvents.slice(0, 9)
    : activeItems.slice(0, 9).map((item) => ({
        relation: item.kind,
        entity_label: titleOf(item),
        fact_text: previewOf(item),
        updated_at: item.updated_at ?? item.activity_at
      }))) as AutopsyPayload[];

  function pushEvent(kind: UiEvent["kind"], message: string) {
    events = [{ at: new Date().toLocaleTimeString(), kind, message }, ...events].slice(0, 8);
  }

  async function guarded<T>(label: string, action: () => Promise<T>): Promise<T | null> {
    loading = label;
    error = "";
    try {
      const result = await action();
      pushEvent("success", `${label} completed`);
      return result;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught);
      error = message;
      pushEvent("error", `${label} failed`);
      return null;
    } finally {
      loading = "";
    }
  }

  async function refreshOverview() {
    const nextHealth = await guarded("health", autopsyHealth);
    if (nextHealth) health = nextHealth;

    const nextStatus = await guarded("status", () => autopsyStatus(6, 4));
    if (nextStatus) {
      status = nextStatus;
      const firstKey = stableKeyOf((nextStatus.status?.active_now ?? [])[0]);
      if (!selectedStableKey && firstKey) {
        await inspectMemory(firstKey);
      }
    }
  }

  async function runConsult() {
    const result = await guarded("consult", () => autopsyConsult(query, 6, 3));
    if (!result) return;
    consult = result;
    const firstKey = stableKeyOf((result.hits ?? [])[0]);
    if (firstKey) {
      await inspectMemory(firstKey);
    }
    mode = "Consult";
  }

  async function inspectMemory(stableKey: string) {
    if (!stableKey) return;
    selectedStableKey = stableKey;

    const nextItem = await guarded("item", () => autopsyItem(stableKey));
    if (nextItem) itemPayload = nextItem;

    const nextNeighbors = await guarded("neighbors", () => autopsyNeighbors(stableKey, 18));
    if (nextNeighbors) neighborsPayload = nextNeighbors;

    const nextTimeline = await guarded("timeline", () => autopsyTimeline(stableKey));
    if (nextTimeline) timelinePayload = nextTimeline;
  }

  async function runBackup() {
    const result = await guarded("backup", autopsyBackup);
    if (result?.written) {
      pushEvent("info", `backup written to ${result.written}`);
    }
  }

  function runSavedQuery(value: string) {
    query = value;
    void runConsult();
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
    return relationRows.filter((relationItem) => relationItem.relation === name).length;
  }

  onMount(() => {
    void refreshOverview();
    const disposers: Array<() => void> = [];
    listen("observatory://run-health", () => void refreshOverview()).then((dispose) => disposers.push(dispose));
    listen("observatory://run-backup", () => void runBackup()).then((dispose) => disposers.push(dispose));
    return () => disposers.forEach((dispose) => dispose());
  });
</script>

<main class="observatory-shell">
  <aside class="tool-rail" aria-label="Observatory tools">
    <div class="window-dots" aria-hidden="true">
      <span></span>
      <span></span>
      <span></span>
    </div>

    <button class="rail-button active" aria-label="Overview">A</button>
    <button class="rail-button" aria-label="Graph">G</button>
    <button class="rail-button" aria-label="Items">I</button>
    <button class="rail-button" aria-label="Timeline">T</button>
    <button class="rail-button" aria-label="Trace">C</button>
    <button class="rail-button" aria-label="Falkor">F</button>

    <div class="rail-spacer"></div>
    <button class="rail-button quiet" aria-label="Settings">S</button>

    <div class="mini-health" class:healthy={health?.ok}>
      <span></span>
      <strong>Falkor</strong>
      <small>{health?.ok ? "Operational" : "Checking"}</small>
    </div>
  </aside>

  <aside class="memory-panel panel-shell">
    <header class="brand-stack">
      <p>Autopsy</p>
      <h1>Observatory</h1>
    </header>

    <section class="panel-section">
      <div class="section-label">Scope</div>
      <div class="scope-switch">
        <button class:active={scope === "System"} type="button" on:click={() => (scope = "System")}>System</button>
        <button class:active={scope === "Repository"} type="button" on:click={() => (scope = "Repository")}>Repository</button>
      </div>
      <div class="repo-field">
        <span>~/projects/autopsy-observatory</span>
        <small>lock</small>
      </div>
    </section>

    <section class="panel-section saved-section">
      <div class="section-heading">
        <span>Saved queries</span>
        <button type="button" aria-label="Add saved query">+</button>
      </div>
      {#each savedQueries as savedQuery, index}
        <button class="saved-query" type="button" on:click={() => runSavedQuery(savedQuery)}>
          <span>{savedQuery}</span>
          <small>#{index + 1}</small>
        </button>
      {/each}
      <button class="view-all" type="button">View all queries <span>-></span></button>
    </section>

    <section class="panel-section active-section">
      <div class="section-heading">
        <span>Active memories</span>
        <strong>{activeItems.length}</strong>
      </div>
      <div class="active-list">
        {#each activeItems as memory}
          <button
            type="button"
            class:selected={stableKeyOf(memory) === selectedStableKey}
            class="active-memory"
            on:click={() => inspectMemory(stableKeyOf(memory))}
          >
            <span>{titleOf(memory)}</span>
            <small>{memory.kind}</small>
            <i></i>
          </button>
        {/each}
      </div>
      <button class="view-all" type="button">View all active <span>-></span></button>
    </section>

    <section class="panel-section trace-section">
      <div class="section-heading">
        <span>Command trace</span>
        <strong class:live={!!loading}>{loading ? "Busy" : "Live"}</strong>
      </div>
      {#if events.length === 0}
        <p class="muted">No local UI commands yet.</p>
      {:else}
        {#each events as event}
          <div class="trace-line" class:bad={event.kind === "error"}>
            <time>{event.at}</time>
            <span>{event.message}</span>
          </div>
        {/each}
      {/if}
      <button class="view-all" type="button">View full trace <span>-></span></button>
    </section>
  </aside>

  <section class="workspace-shell">
    <header class="command-deck panel-shell">
      <div class="query-row">
        <input
          bind:value={query}
          aria-label="Memory query"
          placeholder="Ask your memory anything..."
          on:keydown={(event) => event.key === "Enter" && runConsult()}
        />
        <kbd>Command-K</kbd>
        <button class="primary-action" type="button" on:click={runConsult} disabled={!!loading}>
          Consult
          <span>v</span>
        </button>
      </div>

      <div class="command-meta">
        <div class="segmented-row">
          <span>Route</span>
          {#each routeOptions as option}
            <button class:active={route === option} type="button" on:click={() => (route = option)}>{option}</button>
          {/each}
        </div>
        <div class="segmented-row mode-row">
          <span>Mode</span>
          {#each modeOptions as option}
            <button class:active={mode === option} type="button" on:click={() => (mode = option)}>{option}</button>
          {/each}
        </div>
      </div>
    </header>

    {#if error}
      <div class="error-banner">{error}</div>
    {/if}

    <section class="graph-stage panel-shell">
      <div class="canvas-tools">
        <button type="button">P</button>
        <button type="button">H</button>
        <button type="button">F</button>
        <button type="button">+</button>
        <button type="button">-</button>
        <button type="button">L</button>
      </div>

      <div class="graph-top-actions">
        <span>{commandState}</span>
        <button type="button" class:active={showGraphLabels} on:click={() => (showGraphLabels = !showGraphLabels)}>
          {showGraphLabels ? "Hide labels" : "Show labels"}
        </button>
      </div>

      <MemoryGraph {itemPayload} {neighborsPayload} {timelinePayload} showLabels={showGraphLabels} />

      {#if selectedMemory}
        <div class="selected-node-card">
          <div class="node-orb">{selectedKind.slice(0, 1).toUpperCase()}</div>
          <span>{selectedStableKey ? compactKey(selectedStableKey) : "selected"}</span>
          <strong>{selectedTitle}</strong>
          <small>{selectedKind}</small>
          <div class="node-actions">
            <button type="button" on:click={() => (mode = "Inspect")}>Inspect</button>
            <button type="button" on:click={() => (mode = "Consult")}>Explain</button>
            <button type="button" on:click={() => (mode = "Trace")}>Trace</button>
          </div>
        </div>
      {/if}

      <div class="relation-legend">
        <span><i></i> implements</span>
        <span><i></i> supersedes</span>
        <span><i></i> informed-by</span>
        <span><i></i> refines</span>
      </div>

      <div class="zoom-cluster">
        <button type="button">Fit</button>
        <span>100%</span>
        <button type="button">+</button>
      </div>
    </section>

    <section class="timeline-dock panel-shell">
      <header class="dock-header">
        <nav>
          <button class="active" type="button">Timeline</button>
          <button type="button">Activity</button>
          <button type="button">Decisions</button>
          <button type="button">Attempts</button>
          <button type="button">Commits</button>
          <button type="button">Threads</button>
        </nav>
        <div>
          <label><input type="checkbox" checked /> Show superseded</label>
          <button type="button">7d</button>
        </div>
      </header>

      <div class="timeline-track">
        <div class="timeline-axis"></div>
        {#each timelineMarkers as marker, index}
          <button
            type="button"
            class="timeline-marker"
            style={`--x:${8 + index * 10.5}%`}
            title={String(marker.fact_text ?? marker.entity_label ?? marker.relation ?? "event")}
          >
            <span>{String(marker.relation ?? marker.kind ?? "M").slice(0, 1).toUpperCase()}</span>
          </button>
        {/each}
        <div class="timeline-playhead">
          <strong>May 16</strong>
          <span>{selectedTitle || "Selected memory"}</span>
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
          <button type="button">|&lt;</button>
          <button type="button">&lt;</button>
          <button type="button">Play</button>
          <button type="button">&gt;</button>
          <button type="button">Fit</button>
        </div>
      </footer>
    </section>
  </section>

  <aside class="inspector-panel panel-shell">
    <header class="inspector-header">
      <span>Selected memory</span>
      <button type="button" aria-label="Refresh selected memory">R</button>
    </header>

    <section class="selected-summary">
      <div>
        <h2>{selectedTitle || "No memory selected"}</h2>
        <p>{selectedStableKey ? compactKey(selectedStableKey) : "Select a result or active memory."}</p>
      </div>
      <span class="kind-pill">{selectedKind}</span>
    </section>

    <section class="inspector-section">
      <div class="section-label">Content excerpt</div>
      <p>{selectedContent}</p>
    </section>

    <section class="inspector-grid">
      <div>
        <span>Kind</span>
        <strong>{selectedKind}</strong>
      </div>
      <div>
        <span>Confidence</span>
        <strong>{selectedItem?.confidence ?? "0.92"}</strong>
      </div>
      <div>
        <span>Status</span>
        <strong>{workflow?.complete === false ? "needs follow-up" : "workflow.complete"}</strong>
      </div>
      <div>
        <span>Stable key</span>
        <strong>{selectedStableKey ? compactKey(selectedStableKey) : "--"}</strong>
      </div>
      <div>
        <span>Source</span>
        <strong>{selectedItem?.source_kind ?? selectedMemory?.source_kind ?? "graph_note"}</strong>
      </div>
      <div>
        <span>Repository</span>
        <strong>codex</strong>
      </div>
    </section>

    <section class="inspector-section">
      <div class="section-label">Retrieval reasons</div>
      {#if retrievalReasons.length > 0}
        <ul class="reason-list">
          {#each retrievalReasons as reason}
            <li>{reason}</li>
          {/each}
        </ul>
      {:else}
        <p class="muted">Select a consult result to see retrieval reasons.</p>
      {/if}
    </section>

    <section class="timing-strip">
      <div>
        <span>Retrieved in</span>
        <strong>{formatMs(consult?.observatory?.elapsed_ms ?? health?.observatory?.elapsed_ms)}</strong>
      </div>
      <div>
        <span>Graph hop</span>
        <strong>{linkRows.length + relationRows.length}</strong>
      </div>
      <div>
        <span>Rerank</span>
        <strong>{selectedHit?.reranker_score ? Number(selectedHit.reranker_score).toFixed(2) : "--"}</strong>
      </div>
    </section>

    <section class="inspector-section">
      <div class="section-heading">
        <span>Relations ({relationRows.length})</span>
        <button type="button">-></button>
      </div>
      <div class="relation-chips">
        <span>implements <strong>{relationCount("implements")}</strong></span>
        <span>supersedes <strong>{relationCount("supersedes")}</strong></span>
        <span>informed-by <strong>{relationCount("informed_by")}</strong></span>
        <span>refines <strong>{relationCount("refines")}</strong></span>
      </div>
    </section>
  </aside>
</main>

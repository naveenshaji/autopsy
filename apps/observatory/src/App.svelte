<script lang="ts">
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { Tabs } from "bits-ui";
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

  let activeTab = "overview";
  let query = "Autopsy v0.1.2 restore health hardening";
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
  $: recentActivity = (status?.status?.recent_activity ?? []) as MemorySummary[];
  $: hits = (consult?.hits ?? []) as MemorySummary[];
  $: workflow = consult?.workflow ?? null;
  $: timings = consult?.timings ?? {};
  $: selectedItem = itemPayload?.item ?? null;
  $: timelineEvents = (timelinePayload?.timeline?.events ?? []) as AutopsyPayload[];

  function pushEvent(kind: UiEvent["kind"], message: string) {
    events = [{ at: new Date().toLocaleTimeString(), kind, message }, ...events].slice(0, 10);
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
    const nextStatus = await guarded("status", () => autopsyStatus(8, 4));
    if (nextStatus) status = nextStatus;
  }

  async function runConsult() {
    const result = await guarded("consult", () => autopsyConsult(query, 6, 3));
    if (!result) return;
    consult = result;
    const firstKey = stableKeyOf((result.hits ?? [])[0]);
    if (firstKey) {
      await inspectMemory(firstKey);
    }
    activeTab = "recall";
  }

  async function inspectMemory(stableKey: string) {
    selectedStableKey = stableKey;
    const nextItem = await guarded("item", () => autopsyItem(stableKey));
    if (nextItem) itemPayload = nextItem;
    const nextNeighbors = await guarded("neighbors", () => autopsyNeighbors(stableKey, 18));
    if (nextNeighbors) neighborsPayload = nextNeighbors;
    const nextTimeline = await guarded("timeline", () => autopsyTimeline(stableKey));
    if (nextTimeline) timelinePayload = nextTimeline;
    activeTab = "map";
  }

  async function runBackup() {
    const result = await guarded("backup", autopsyBackup);
    if (result?.written) {
      pushEvent("info", `backup written to ${result.written}`);
    }
  }

  onMount(() => {
    void refreshOverview();
    const disposers: Array<() => void> = [];
    listen("observatory://run-health", () => void refreshOverview()).then((dispose) => disposers.push(dispose));
    listen("observatory://run-backup", () => void runBackup()).then((dispose) => disposers.push(dispose));
    return () => disposers.forEach((dispose) => dispose());
  });
</script>

<main class="app-shell">
  <aside class="side-rail">
    <div class="brand">
      <div class="brand-mark">A</div>
      <div>
        <p class="eyebrow">Local memory layer</p>
        <h1>Autopsy Observatory</h1>
      </div>
    </div>

    <section class="status-panel" class:healthy={health?.ok}>
      <span class="pulse"></span>
      <div>
        <p class="label">System Health</p>
        <strong>{health?.ok ? "Operational" : "Needs inspection"}</strong>
      </div>
    </section>

    <section class="metric-stack">
      <div>
        <span>Items</span>
        <strong>{counts.items ?? "..."}</strong>
      </div>
      <div>
        <span>Edges</span>
        <strong>{counts.edges ?? "..."}</strong>
      </div>
      <div>
        <span>Vectors</span>
        <strong>{counts.vectors ?? "..."}</strong>
      </div>
      <div>
        <span>Managed Targets</span>
        <strong>{checks.init_managed_targets ?? "..."}</strong>
      </div>
    </section>

    <section class="quick-actions">
      <button type="button" on:click={refreshOverview} disabled={!!loading}>Run Health</button>
      <button type="button" on:click={runBackup} disabled={!!loading}>Backup</button>
    </section>

    <section class="event-log">
      <p class="section-title">Command Trace</p>
      {#if events.length === 0}
        <p class="muted">No local UI commands yet.</p>
      {:else}
        {#each events as event}
          <div class:bad={event.kind === "error"} class:good={event.kind === "success"} class="event-row">
            <span>{event.at}</span>
            <p>{event.message}</p>
          </div>
        {/each}
      {/if}
    </section>
  </aside>

  <section class="workspace">
    <header class="top-bar">
      <div>
        <p class="eyebrow">Read-only graph observability</p>
        <h2>Evidence, recall, timeline, neighborhood.</h2>
      </div>
      <div class="query-bar">
        <input bind:value={query} aria-label="Memory query" placeholder="Ask Autopsy memory..." on:keydown={(event) => event.key === "Enter" && runConsult()} />
        <button type="button" on:click={runConsult} disabled={!!loading}>Consult</button>
      </div>
    </header>

    {#if error}
      <div class="error-banner">{error}</div>
    {/if}

    <Tabs.Root bind:value={activeTab} class="tabs-root">
      <Tabs.List class="tabs-list" aria-label="Observatory views">
        <Tabs.Trigger value="overview">Overview</Tabs.Trigger>
        <Tabs.Trigger value="recall">Recall Explain</Tabs.Trigger>
        <Tabs.Trigger value="map">Memory Map</Tabs.Trigger>
        <Tabs.Trigger value="timeline">Timeline</Tabs.Trigger>
      </Tabs.List>

      <Tabs.Content value="overview" class="tab-panel">
        <div class="overview-grid">
          <section class="large-panel">
            <div class="panel-heading">
              <span>Active Now</span>
              <strong>{status?.status?.summary ?? "Loading graph status..."}</strong>
            </div>
            <div class="memory-list">
              {#each activeItems as memory}
                <button type="button" class="memory-row" on:click={() => inspectMemory(stableKeyOf(memory))}>
                  <span>{memory.kind}</span>
                  <strong>{titleOf(memory)}</strong>
                  <p>{previewOf(memory)}</p>
                </button>
              {/each}
            </div>
          </section>

          <section class="side-panel">
            <div class="panel-heading compact">
              <span>Runtime</span>
              <strong>{health?.backend ?? "falkor"} / {health?.mode ?? "native"}</strong>
            </div>
            <dl class="health-list">
              <div><dt>Indexes</dt><dd>{checks.indexes_ready ? "ready" : "unknown"}</dd></div>
              <div><dt>Backup</dt><dd>{checks.backup_fresh ? "fresh" : "stale/missing"}</dd></div>
              <div><dt>Graph</dt><dd>{checks.graph_ready ? "ready" : "pending"}</dd></div>
              <div><dt>Elapsed</dt><dd>{health?.observatory?.elapsed_ms ?? "..."} ms</dd></div>
            </dl>
          </section>
        </div>
      </Tabs.Content>

      <Tabs.Content value="recall" class="tab-panel">
        <div class="recall-grid">
          <section class="large-panel">
            <div class="panel-heading">
              <span>Ranked Results</span>
              <strong>{workflow?.status ?? "Run a query"}</strong>
            </div>
            <div class="result-list">
              {#each hits as hit}
                <button type="button" class:selected={stableKeyOf(hit) === selectedStableKey} class="result-row" on:click={() => inspectMemory(stableKeyOf(hit))}>
                  <span>{hit.kind}</span>
                  <strong>{titleOf(hit)}</strong>
                  <p>{previewOf(hit)}</p>
                </button>
              {/each}
              {#if consult && hits.length === 0}
                <p class="empty-copy">No reliable hits. Workflow: {workflow?.status}</p>
              {/if}
            </div>
          </section>

          <section class="side-panel">
            <div class="panel-heading compact">
              <span>Retrieval Timings</span>
              <strong>{consult?.observatory?.elapsed_ms ?? "..."} ms wall</strong>
            </div>
            <dl class="health-list">
              <div><dt>Exact</dt><dd>{timings.exact_s ?? 0}s</dd></div>
              <div><dt>Lexical</dt><dd>{timings.lexical_s ?? 0}s</dd></div>
              <div><dt>Vector</dt><dd>{timings.vector_s ?? 0}s</dd></div>
              <div><dt>Rerank</dt><dd>{timings.rerank_s ?? 0}s</dd></div>
            </dl>
            <p class="muted">{workflow?.message ?? "Run consult to see why memory was retrieved."}</p>
          </section>
        </div>
      </Tabs.Content>

      <Tabs.Content value="map" class="tab-panel">
        <div class="map-grid">
          <MemoryGraph {itemPayload} {neighborsPayload} {timelinePayload} />
          <aside class="inspector">
            <p class="eyebrow">Inspector</p>
            <h3>{selectedItem ? titleOf(selectedItem) : "No memory selected"}</h3>
            <p class="inspector-key">{selectedStableKey}</p>
            <p>{selectedItem?.content ?? "Select a result or active memory to inspect its evidence graph."}</p>
          </aside>
        </div>
      </Tabs.Content>

      <Tabs.Content value="timeline" class="tab-panel">
        <section class="large-panel timeline-panel">
          <div class="panel-heading">
            <span>Lineage</span>
            <strong>{timelineEvents.length} relation events</strong>
          </div>
          {#each timelineEvents as event}
            <div class="timeline-row">
              <span>{event.relation}</span>
              <strong>{event.entity_label}</strong>
              <p>{event.fact_text}</p>
            </div>
          {/each}
          {#if selectedItem && timelineEvents.length === 0}
            <p class="empty-copy">No timeline relation events for this memory yet.</p>
          {/if}
        </section>
      </Tabs.Content>
    </Tabs.Root>
  </section>
</main>

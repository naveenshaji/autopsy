import Image from "next/image";

const featureGroups = [
  {
    label: "Context",
    title: "Compact memory packs with provenance built in",
    text: "Autopsy context combines current state, retrieved facts, bounded graph neighbors, lineage warnings, relation hints, and a ready-to-insert text block.",
  },
  {
    label: "Recall",
    title: "Consults that know when evidence is weak",
    text: "Consult returns workflow completeness metadata, suggested follow-ups, and inspected items so agents can stop guessing when retrieval is thin.",
  },
  {
    label: "Writes",
    title: "Typed outcomes with ontology-checked relations",
    text: "Decisions, attempts, procedures, plans, preferences, and open questions are stored with durable semantic edges such as answers, supersedes, refines, and depends-on.",
  },
];

const proofPoints = [
  "Falkor-backed local graph storage",
  "Repo, namespace, entity, metadata, tag, and temporal filters",
  "Evidence-backed derived observations",
  "Memory governance audit with poisoning and sensitive-data guards",
  "MCP bridge for coding agents",
  "Native macOS menu bar activity companion",
];

const commands = [
  "brew tap naveenshaji/autopsy https://github.com/naveenshaji/autopsy",
  "brew install autopsy-memory",
  "autopsy install",
  "autopsy context --current-only --query \"release decisions\"",
];

export default function Home() {
  return (
    <main>
      <section className="hero" id="top">
        <Image
          className="hero-image"
          src="/autopsy-memory-console.png"
          alt="A dark developer workspace showing Autopsy graph memory, terminal activity, and a compact macOS-style popover."
          fill
          priority
          unoptimized
          sizes="100vw"
        />
        <div className="hero-scrim" />

        <header className="site-nav">
          <a className="brand" href="#top" aria-label="Autopsy Memory home">
            <span className="brand-mark" aria-hidden="true" />
            <span>Autopsy Memory</span>
          </a>
          <nav aria-label="Primary navigation">
            <a href="#memory">Memory</a>
            <a href="#trust">Trust</a>
            <a href="#install">Install</a>
          </nav>
        </header>

        <div className="hero-content">
          <p className="eyebrow">Local-first agent memory</p>
          <h1>Autopsy Memory</h1>
          <p className="hero-copy">
            A governed graph memory layer for coding agents. Store durable
            decisions, recover context across repos, inspect relation lineage,
            and keep recall grounded in evidence.
          </p>
          <div className="hero-actions">
            <a className="button primary" href="#install">
              Install with Homebrew
            </a>
            <a className="button secondary" href="#memory">
              Explore the memory model
            </a>
          </div>
        </div>
      </section>

      <section className="section intro-band" aria-label="Product summary">
        <dl className="metric-strip" aria-label="Autopsy product highlights">
          <div>
            <dt>Current release</dt>
            <dd>v0.1.19</dd>
          </div>
          <div>
            <dt>Backend</dt>
            <dd>Falkor graph</dd>
          </div>
          <div>
            <dt>Surface</dt>
            <dd>CLI, MCP, macOS</dd>
          </div>
        </dl>
        <div className="section-grid">
          <p className="section-kicker">What it does</p>
          <div>
            <h2>Memory that behaves like infrastructure, not a scratchpad.</h2>
            <p>
              Autopsy stores semantic items and typed fact edges in a local
              graph. Agents can ask for compact context packs, inspect exact
              facts, review timelines, and write new outcomes with relation
              coverage that future work can trust.
            </p>
          </div>
        </div>
      </section>

      <section className="section" id="memory">
        <div className="section-heading">
          <p className="section-kicker">Memory contract</p>
          <h2>Readable by agents. Verifiable by engineers.</h2>
        </div>

        <div className="feature-row">
          {featureGroups.map((feature) => (
            <article className="feature-card" key={feature.label}>
              <p>{feature.label}</p>
              <h3>{feature.title}</h3>
              <span>{feature.text}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="section trust-band" id="trust">
        <div className="trust-layout">
          <div>
            <p className="section-kicker">Governed local recall</p>
            <h2>Built for memory that survives real debugging.</h2>
            <p>
              Autopsy fails loudly when Falkor is unavailable, keeps secrets out
              of durable memory, and exposes audit signals for stale lineage,
              duplicate facts, low-signal writes, poisoning risk, and sensitive
              data.
            </p>
          </div>
          <div className="proof-grid">
            {proofPoints.map((point) => (
              <div className="proof-item" key={point}>
                <span aria-hidden="true" />
                <p>{point}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section utility-section">
        <div className="utility-copy">
          <p className="section-kicker">Native companion</p>
          <h2>Quiet visibility from the macOS menu bar.</h2>
          <p>
            The companion app is not a graph browser. It stays compact, shows
            recent writes and consults, surfaces attention items, and gives
            developers quick health, backup, restart, and instruction-status
            controls.
          </p>
        </div>
        <div className="utility-panel" aria-label="Menu bar feature summary">
          <div>
            <strong>Activity</strong>
            <span>Recent writes and consults</span>
          </div>
          <div>
            <strong>Attention</strong>
            <span>Inline health and setup signals</span>
          </div>
          <div>
            <strong>Recovery</strong>
            <span>Manual health, backup, restart, quit</span>
          </div>
        </div>
      </section>

      <section className="section install-band" id="install">
        <div className="install-grid">
          <div>
            <p className="section-kicker">Install</p>
            <h2>Start local, then let agents remember the work.</h2>
            <p>
              Homebrew is the preferred macOS path. It installs the CLI, stages
              the menu bar utility, and keeps the local runtime pointed at the
              stable package path.
            </p>
          </div>
          <div className="terminal" aria-label="Install commands">
            {commands.map((command) => (
              <code key={command}>
                <span>$</span> {command}
              </code>
            ))}
          </div>
        </div>
      </section>

      <footer className="footer">
        <p>Autopsy Memory</p>
        <a href="#top">Back to top</a>
      </footer>
    </main>
  );
}

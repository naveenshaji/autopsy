# Codex answerer diagnostic

`codex_diagnostic.py` is a standalone, resumable follow-up to the aggregate
raw-evidence retrieval study. It uses the existing frozen Autopsy retrieval
predictions and ChatGPT-authenticated `codex exec`; it never uses an OpenAI API
key. The result is deliberately labeled an **exploratory 110-case stratified
diagnostic**, not official LoCoMo or LongMemEval accuracy and not a number that
can be compared directly with Mem0's managed-platform scores.

The frozen sample contains ten cases from each of LoCoMo's five categories,
all 30 LongMemEval-S abstention cases, and five answerable cases from each of
LongMemEval-S's six categories. It intentionally oversamples categories and
abstentions. Combined metrics are therefore unweighted diagnostics.

## Leakage boundary

`prepare` is the only phase that reads both dataset gold and retrieval output.
It writes separate artifacts:

- `answer-inputs/` contains only an opaque case handle, question, question
  date, and ranked text under per-case `C001`-style handles.
- `private-gold.json` contains source IDs, categories, abstention labels, and
  reference answers used only after answer generation.
- `manifest.json` seals both sides with SHA-256 hashes.

The answerer never sees original case IDs (`_abs` would reveal LongMemEval
abstentions), source/session IDs (`answer_`/`noans_` can reveal evidence),
categories, gold answers, relevance labels, or retrieval diagnostics. Every
resume verifies the seal. Answer and judge runs use separate ephemeral Codex
sessions in blank directories with tools, apps, shell, browser, web search,
memory, hooks, and multi-agent features disabled.

The launcher copies only the cached ChatGPT login into a temporary mode-0600
`CODEX_HOME`, removes API-key/token environment variables, enforces
`forced_login_method="chatgpt"`, and requires `codex login status` to report
`Logged in using ChatGPT`. ChatGPT plan quota may be consumed and is not
measured; the report says zero API-key dollar spend, not "free" or "offline".

## Phases

```bash
TOOL=evaluation/publication/raw-retrieval-v1/codex_diagnostic.py
RUN=/private/tmp/autopsy-codex-diagnostic

python "$TOOL" prepare \
  --run-dir "$RUN" \
  --locomo-data /path/to/locomo10.json \
  --locomo-predictions /path/to/locomo-autopsy.predictions.jsonl \
  --longmemeval-data /path/to/longmemeval_s_cleaned.json \
  --longmemeval-predictions /path/to/longmemeval-autopsy.predictions.jsonl

# These phases make remote Codex calls through the cached ChatGPT login.
python "$TOOL" answer --run-dir "$RUN"
python "$TOOL" judge --run-dir "$RUN"

# This phase is local and aggregate-only.
python "$TOOL" score --run-dir "$RUN"

# Resume only missing answer/judge batches and then rescore.
python "$TOOL" resume --run-dir "$RUN"

# Read-only seal/completion check; never calls a model.
python "$TOOL" status --run-dir "$RUN"
```

The defaults pin answer routing to `gpt-5.4-mini` at `xhigh` reasoning and the
judge to `gpt-5.4` at `medium` reasoning, with two independent judge passes.
The manifest also pins the exact prompt, selection-policy, output-schema,
dataset, and retrieval-artifact hashes. Model IDs pin routing names, not
immutable server-side weights; Codex CLI does not expose a temperature or seed
for these runs, so judge agreement and the per-pass score range are reported.

Keep the run directory private. It contains benchmark questions, contexts,
answers, gold labels, and source identifiers and must not be placed in the
aggregate-only publication archive. Only the sanitized `aggregate-score.json`
is suitable for consideration, subject to the dataset attribution and claim
limits in the publication bundle.

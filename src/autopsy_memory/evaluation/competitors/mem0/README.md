# Pinned Mem0 OSS raw-retrieval adapter

These assets ship inside the `autopsy-memory` wheel so the installed CLI can
bootstrap its optional competitor environment without a source checkout. The
environment is deliberately separate from Autopsy's runtime dependencies. It
pins:

- Mem0 OSS `2.0.11`, source commit
  `f2532f072fdefa4c90264acc80af0984309f8b06` (`v2.0.11`);
- `sentence-transformers==5.1.2` and its complete Python 3.12 dependency lock;
- `sentence-transformers/multi-qa-MiniLM-L6-cos-v1`, model revision
  `b207367332321f8e44f96e224ef15bc607f4dbf0`.

When the environment is absent, `autopsy evaluate run --adapter mem0-oss-raw`
prints the absolute path to this packaged `setup.sh`. Run that path directly.
In a source checkout, the convenience wrapper remains:

```bash
evaluation/competitors/mem0/setup.sh
```

The default environment is
`~/.cache/autopsy/evaluation/mem0-oss-2.0.11`. Pass a different directory as
the first argument for CI or a disposable run, then point the adapter at it:

```bash
/absolute/path/printed/by/autopsy/setup.sh /tmp/autopsy-mem0-venv
export AUTOPSY_MEM0_PYTHON=/tmp/autopsy-mem0-venv/bin/python
```

The adapter runs that interpreter as an NDJSON subprocess with
`MEM0_TELEMETRY=false`, `infer=False`, and embedded on-disk Qdrant. Corpus
preparation receives no query or judgment fields. Mem0 UUIDs are mapped to
opaque evaluation document handles out-of-band, and those handles are never
embedded.

Repository scope uses Mem0/Qdrant metadata filtering and a result-boundary
verification. Expiration uses Mem0's native current-date behavior plus an exact
UTC result check. Mem0 OSS 2.0.11 rejects `reference_date`; native historical
`as-of` retrieval is therefore reported as unsupported and is not emulated.
Empty documents in an upstream representation have no embedding semantics and
are reported as `skipped_empty_items`; they are never replaced with searchable
placeholder text. Vector coverage is computed over non-empty eligible items.

After bootstrap, evaluation is local and requires no API key or paid service.
The first bootstrap/model download uses the network; measured runs use local
CPU, the cached model, and embedded Qdrant. The subprocess strips inherited API
credentials and forces Hugging Face/Transformers offline mode. External API
cost is reported as USD 0.

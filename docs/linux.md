# Autopsy on Linux

Autopsy runs natively on Linux: the CLI, the memory worker, the MCP bridge and
the embedded FalkorDB graph. The macOS menu bar app is the only part that is
macOS-only.

## Requirements

- x86_64 or arm64 Linux with glibc 2.39 or newer (Ubuntu 24.04+, Debian 13+,
  Fedora 40+). The embedded FalkorDB package ships prebuilt binaries only for
  these systems.
- Python 3.12, 3.13 or 3.14 with the `venv` module. On Debian and Ubuntu,
  install it with `sudo apt install python3-venv` (or `python3.12-venv`).
- About 2 GB of disk for the runtime and the default local models.

If your system `python3` is newer than 3.14, install Python 3.13 next to it
(for example `sudo dnf install python3.13`) and pass it to the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/naveenshaji/autopsy/main/scripts/install-release.sh | PYTHON=python3.13 sh
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/naveenshaji/autopsy/main/scripts/install-release.sh | sh
autopsy install
```

The first command downloads the latest tagged release, builds it into its own
virtual environment and puts the `autopsy`, `autopsy-memory-worker` and
`autopsy-memory-mcp` commands in `~/.local/bin`. If `~/.local/bin` is not on your
`PATH`, the installer prints the line to add.

`autopsy install` then installs the agent instructions (Claude Code, Codex,
Gemini CLI, OpenCode), runs `autopsy doctor` and starts a background warmup that
downloads the local embedding and reranking models. Add `--smoke-test` to also
run a read, an abstention check and a temporary write and delete.

Check the result:

```bash
autopsy version --json
autopsy doctor
autopsy status --current-only
```

To install from a checkout instead of a release:

```bash
git clone https://github.com/naveenshaji/autopsy.git
cd autopsy
./scripts/install-global.sh
autopsy install
```

### Installer options

| Variable | Default | Meaning |
| --- | --- | --- |
| `AUTOPSY_VERSION` | latest release | Release to install, for example `0.1.34`. |
| `AUTOPSY_INSTALL_PREFIX` | `~/.local` | Where the runtime and the `bin/` commands go. |
| `PYTHON` | first of `python3.12`, `python3.13`, `python3.14`, `python3` | Interpreter for the virtual environment. |
| `AUTOPSY_TORCH_INDEX_URL` | `https://download.pytorch.org/whl/cpu` | Where torch comes from. Set to `pypi` for PyPI's default build. |

Autopsy's local models run on the CPU. PyPI's Linux torch wheels bundle several
GB of CUDA libraries, so the installer uses the CPU-only build by default. The
install is about 1.5 GB instead of over 5 GB.

## Where things live

| What | Path |
| --- | --- |
| Runtime | `~/.local/Cellar/autopsy-memory/<version>/` (`~/.local/opt/autopsy-memory` points at the current one) |
| Commands | `~/.local/bin/autopsy`, `autopsy-memory-worker`, `autopsy-memory-mcp` |
| Memory graph, settings, logs, backups | `$XDG_DATA_HOME/autopsy` (`~/.local/share/autopsy`) |
| Model weights | the Hugging Face cache (`~/.cache/huggingface`) |

Set `AUTOPSY_APP_SUPPORT_DIR` to keep the data somewhere else. The CLI, the worker
and the MCP bridge all respect it.

Each memory write also writes a verified local snapshot to
`~/.local/share/autopsy/Backups`. The iCloud Drive copy described in
[backups](backups.md) is macOS-only. On Linux, point your own backup or sync tool
at that folder.

## Using it from Claude Code

The instructions that `autopsy install` writes to `~/.claude/CLAUDE.md` tell
Claude Code to use the CLI. To also give it the MCP tools (including
`autopsy_memory_remember` for recall by meaning), register the bridge:

```bash
claude mcp add --scope user autopsy -- autopsy-memory-mcp
```

The bridge speaks MCP's newline-delimited stdio framing, which Claude Code uses,
as well as Content-Length framing. It starts the memory worker on demand.

Import past Claude Code sessions so they can be recalled:

```bash
autopsy import-session ~/.claude/projects/<project>/<session>.jsonl --source claude-code
autopsy remember "what did we decide about the release process"
```

Re-importing a growing transcript only rewrites the exchanges that changed.

## The memory worker

The CLI and the MCP bridge start `autopsy-memory-worker` when they need it. The
worker keeps the models loaded and exits after an hour idle
(`AUTOPSY_WORKER_IDLE_TIMEOUT_SECONDS`; `0` keeps it running). It listens on
a random localhost port recorded in `~/.local/share/autopsy/CLI/ml-worker.json`.
No systemd unit is needed. If you want one to stay up, run
`autopsy-memory-worker` from a user service with
`AUTOPSY_WORKER_IDLE_TIMEOUT_SECONDS=0`.

Vectors for meaning-based recall are computed after imports and on
`autopsy sync`. Run `autopsy sync` after writing many notes by hand.

## Lighter models with ONNX Runtime

The default models run through sentence-transformers and torch. The `onnx`
provider runs the same models through ONNX Runtime instead, with the same vectors
and scores and much less memory in a resident worker. Install ONNX Runtime into
Autopsy's environment (from a checkout, `pip install -e ".[onnx]"` does the same):

```bash
~/.local/opt/autopsy-memory/venv/bin/python -m pip install onnxruntime tokenizers
```

Then set the provider in `~/.local/share/autopsy/MemoryRoot/memory/config/autopsy_embeddings.json`:

```json
{
  "provider": "onnx",
  "model": "BAAI/bge-base-en-v1.5",
  "reranker": {
    "enabled": true,
    "provider": "onnx",
    "model": "BAAI/bge-reranker-base"
  }
}
```

The model must publish an ONNX export: `onnx/model.onnx`, or the file named by
`"onnx_file"`. Autopsy downloads it on first use, even when sentence-transformers
already cached the model. Keep the same embedding model when you switch
providers. Vectors from a different model don't match, and Autopsy doesn't
recompute stored vectors when the model changes.

## Upgrade and uninstall

Upgrade by running the installer again, then `autopsy install`. The previous
version stays in `~/.local/Cellar/autopsy-memory/` until you delete it.

Uninstall:

```bash
rm -rf ~/.local/Cellar/autopsy-memory ~/.local/opt/autopsy-memory
rm -f ~/.local/bin/autopsy ~/.local/bin/autopsy-memory-worker ~/.local/bin/autopsy-memory-mcp
```

Your memory stays in `~/.local/share/autopsy` until you remove it yourself.

## Troubleshooting

- `Autopsy supports Python 3.12 to 3.14`: install Python 3.13 and rerun the
  installer with `PYTHON=python3.13`.
- `could not create a virtual environment`: install your distribution's venv
  package (`python3-venv` on Debian and Ubuntu).
- `autopsy: command not found`: add `~/.local/bin` to `PATH` and open a new
  terminal.
- Memory reads fail: run `autopsy doctor` and read the FalkorDB runtime
  diagnostics and the Redis log path it prints.

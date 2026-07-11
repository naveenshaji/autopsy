# Mem0 source-checkout convenience wrapper

The canonical bootstrap script, complete Python 3.12 lock, and documentation
live under
[`src/autopsy_memory/evaluation/competitors/mem0/`](../../../src/autopsy_memory/evaluation/competitors/mem0/)
so they ship inside the wheel. This directory retains the short source-checkout
command:

```bash
evaluation/competitors/mem0/setup.sh
```

The wrapper delegates directly to the packaged script; no lock is duplicated
here.

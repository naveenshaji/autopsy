# Homebrew Distribution

Autopsy ships a Homebrew formula at [Formula/autopsy-memory.rb](../Formula/autopsy-memory.rb).

## Install

Use the public tap:

```bash
brew tap naveenshaji/autopsy
brew install autopsy-memory
autopsy install
autopsy doctor
```

Requirements: macOS 14 Sonoma or newer on Apple Silicon with Homebrew.

`autopsy install` writes global agent instructions and, on macOS, installs and
starts the menu bar LaunchAgent. Add repo-local instructions from a repository
with:

```bash
autopsy install --repo
```

On a new machine or after a repair, run the deeper smoke check:

```bash
autopsy install --smoke-test
```

It verifies doctor, current-state reads, consult abstention, and temporary
write/delete behavior.

That writes `~/Library/LaunchAgents/com.naveenshaji.autopsy.menubar.plist`
pointing at the stable Homebrew `opt` path:

```text
<brew-prefix>/opt/autopsy-memory/menubar/.build/release/AutopsyMenuBar.app/Contents/MacOS/AutopsyMenuBar
```

The Homebrew formula is the preferred self-contained macOS distribution because
it pins the Python dependencies, includes the local semantic retrieval/reranker
runtime, and vendors the native Apple Silicon FalkorDB module used by the
embedded graph backend.

Stop and remove the menu bar LaunchAgent with:

```bash
autopsy menubar --uninstall-launch-agent
```

## macOS Prerelease Recovery

On macOS prereleases such as macOS 27, Homebrew may be Tier 2 until upstream CI
and bottle coverage catch up. Homebrew may also require explicit trust for
formulae from third-party taps.

If Homebrew still runs but refuses the Autopsy tap or formula, trust the formula
and build from source:

```bash
brew trust --formula naveenshaji/autopsy/autopsy-memory
brew update
brew reinstall --build-from-source naveenshaji/autopsy/autopsy-memory
autopsy install --smoke-test
```

If Homebrew itself cannot update, upgrade, or reinstall on that macOS release,
run the release bootstrap script instead:

```bash
curl -fsSL https://raw.githubusercontent.com/naveenshaji/autopsy/HEAD/scripts/install-release.sh | sh
autopsy install --smoke-test
```

Pass the tag to pin a specific release and avoid any latest-release lookup:

```bash
curl -fsSL https://raw.githubusercontent.com/naveenshaji/autopsy/HEAD/scripts/install-release.sh | sh -s -- v0.1.30
autopsy install --smoke-test
```

Pass `AUTOPSY_INSTALL_PREFIX=$HOME/.local` when piping to `sh` if
`/opt/homebrew` is not writable or when you want a user-local recovery install:

```bash
curl -fsSL https://raw.githubusercontent.com/naveenshaji/autopsy/HEAD/scripts/install-release.sh | AUTOPSY_INSTALL_PREFIX="$HOME/.local" sh -s -- v0.1.30
```

## Python/Pip Installs

`pip install autopsy-memory` is useful for development, but on macOS it is not
currently the preferred full distribution path because the PyPI `falkordblite`
package does not bundle the native Darwin FalkorDB module. Homebrew supplies
that module as a pinned resource and sets `AUTOPSY_FALKORDB_MODULE_PATH` in the
installed wrappers.

Keep the operational split clear: `autopsy` is the release CLI and should be the
only command pointed at `~/Library/Application Support/Autopsy` during normal
work. Development and source-checkout experiments should use `autopsy-dev`,
which defaults to `~/Library/Application Support/AutopsyDev` and refuses the
production support tree unless `AUTOPSY_DEV_ALLOW_PRODUCTION_MEMORY=1` is set
intentionally. In a source checkout, `./scripts/autopsy-dev ...` is the stable
wrapper for the same dev CLI even if the local virtualenv entry points have not
been regenerated.

## Plain `brew install autopsy-memory`

Plain `brew install autopsy-memory` without a tap requires acceptance into
`homebrew/core`. The formula name is currently available, but core acceptance is
a separate upstream review. Before submitting to core:

- Keep the formula license as `Apache-2.0`.
- Expect Homebrew core review to evaluate notability and formula acceptability.
- Consider whether the menu bar app should stay in the formula or move to a
  separate cask; the owned tap is the most flexible path for shipping CLI plus
  source-built macOS menu bar app together.

## Updating The Formula

After tagging and publishing a release:

```bash
/opt/homebrew/opt/python@3.12/libexec/bin/python scripts/update-homebrew-formula.py --version <version> --python /opt/homebrew/opt/python@3.12/libexec/bin/python
```

The script:

- downloads the public GitHub tag archive and writes its SHA-256,
- derives Python dependency versions from a dry-run install report constrained by
  `scripts/homebrew-constraints.txt`,
- resolves PyPI source distributions and hashes,
- rewrites `Formula/autopsy-memory.rb`.

Formula generation intentionally requires macOS 14 Sonoma or newer on Apple
Silicon with Python 3.12. The formula vendors macOS arm64 wheels and the native
FalkorDB module, and the formula itself depends on Homebrew `python@3.12`. Review
`scripts/homebrew-constraints.txt` intentionally when upgrading the packaged
local ML/runtime dependency set; otherwise formula regeneration should stay
stable for a given release.

Validate the formula from a local tap:

```bash
brew tap-new naveenshaji/autopsy
cp Formula/autopsy-memory.rb "$(brew --repository)/Library/Taps/naveenshaji/homebrew-autopsy/Formula/autopsy-memory.rb"
brew style naveenshaji/autopsy/autopsy-memory
brew audit --formula --strict naveenshaji/autopsy/autopsy-memory
brew fetch --formula --deps naveenshaji/autopsy/autopsy-memory
```

Use a clean Homebrew prefix or disposable machine for full install testing so it
does not collide with a manually installed `/opt/homebrew/Cellar/autopsy-memory`
tree.

To validate the formula against the current checkout before tagging:

```bash
./scripts/homebrew-current-check.sh
```

That styles a generated formula whose source archive is built from the current
checkout. Full install testing is intentionally guarded because it temporarily
uses a local Homebrew tap:

```bash
AUTOPSY_HOMEBREW_CURRENT_INSTALL=1 ./scripts/homebrew-current-check.sh
```

Outside CI, add `AUTOPSY_HOMEBREW_CURRENT_ALLOW_LOCAL=1` when you intentionally
want to run the install locally. If `autopsy-memory` is already installed, the
script refuses to replace it unless `AUTOPSY_HOMEBREW_CURRENT_REPLACE_LOCAL=1`
is also set. By default, local replacement checks reinstall the previously
installed formula during cleanup; set `AUTOPSY_HOMEBREW_CURRENT_KEEP_LOCAL=1`
only when you intentionally want to keep the generated current-checkout formula
installed.

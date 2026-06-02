# Homebrew Distribution

Autopsy ships a Homebrew formula at [Formula/autopsy-memory.rb](../Formula/autopsy-memory.rb).

## Install From This Repository As A Tap

Because this repository is named `autopsy` rather than `homebrew-autopsy`, users
must provide the repository URL when tapping it directly:

```bash
brew tap naveenshaji/autopsy https://github.com/naveenshaji/autopsy
brew install autopsy-memory
autopsy version --json
autopsy doctor
```

Start the macOS menu bar utility after install:

```bash
autopsy menubar --install-launch-agent
```

That writes `~/Library/LaunchAgents/com.naveenshaji.autopsy.menubar.plist`
pointing at the stable Homebrew `opt` path:

```text
<brew-prefix>/opt/autopsy-memory/menubar/.build/release/AutopsyMenuBar.app/Contents/MacOS/AutopsyMenuBar
```

Stop and remove the menu bar LaunchAgent with:

```bash
autopsy menubar --uninstall-launch-agent
```

## Preferred Public Tap

For a cleaner user command, publish the same formula to a dedicated tap repo:

```text
https://github.com/naveenshaji/homebrew-autopsy
```

with this layout:

```text
Formula/autopsy-memory.rb
```

Then users can install with:

```bash
brew tap naveenshaji/autopsy
brew install autopsy-memory
autopsy menubar --install-launch-agent
```

After a tap is installed, `brew install autopsy-memory` works because Homebrew
searches tapped formulae.

## Plain `brew install autopsy-memory`

Plain `brew install autopsy-memory` without a tap requires acceptance into
`homebrew/core`. The formula name is currently available, but core acceptance is
a separate upstream review. Before submitting to core:

- Replace the current all-rights-reserved license with a real open-source
  license.
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
- derives Python dependency versions from a dry-run install report,
- resolves PyPI source distributions and hashes,
- rewrites `Formula/autopsy-memory.rb`.

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

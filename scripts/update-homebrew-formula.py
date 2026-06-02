#!/usr/bin/env python3
"""Regenerate the Homebrew tap formula for the current release tag."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "Formula" / "autopsy-memory.rb"
PACKAGE_NAME = "autopsy-memory"
FORMULA_CLASS = "AutopsyMemory"


def read_project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "autopsy-homebrew-formula-generator"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def public_tag_sha256(version: str) -> tuple[str, str]:
    url = f"https://github.com/naveenshaji/autopsy/archive/refs/tags/v{version}.tar.gz"
    payload = fetch_bytes(url)
    return url, hashlib.sha256(payload).hexdigest()


def pip_dependency_report(python: str) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="autopsy-homebrew-report-") as tmp:
        report_path = Path(tmp) / "pip-report.json"
        subprocess.run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--ignore-installed",
                "--report",
                str(report_path),
                str(ROOT),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return json.loads(report_path.read_text())["install"]


def pypi_release_file(name: str, version: str) -> tuple[str, str]:
    data = json.loads(fetch_bytes(f"https://pypi.org/pypi/{name}/{version}/json"))
    urls = data["urls"]
    for item in urls:
        if item["packagetype"] == "sdist":
            return item["url"], item["digests"]["sha256"]
    for item in urls:
        if item["packagetype"] == "bdist_wheel":
            return item["url"], item["digests"]["sha256"]
    raise RuntimeError(f"No source or wheel distribution found for {name}=={version}")


def resource_blocks(python: str) -> str:
    resources: list[tuple[str, str, str]] = []
    for item in pip_dependency_report(python):
        metadata = item.get("metadata") or {}
        name = metadata.get("name")
        version = metadata.get("version")
        if not name or not version or name.lower().replace("_", "-") == PACKAGE_NAME:
            continue
        url, sha = pypi_release_file(name, version)
        resources.append((name.lower().replace("_", "-"), url, sha))

    blocks = []
    for name, url, sha in sorted(resources):
        blocks.append(
            textwrap.dedent(
                f"""\
                resource "{name}" do
                  url "{url}"
                  sha256 "{sha}"
                end
                """
            )
        )
    return "\n".join(blocks)


def render_formula(version: str, source_url: str, source_sha: str, resources: str) -> str:
    resource_text = textwrap.indent(resources.rstrip(), "  ")
    return f'''require "json"

class {FORMULA_CLASS} < Formula
  include Language::Python::Virtualenv

  desc "Local-first Falkor-backed memory layer and CLI for coding agents"
  homepage "https://github.com/naveenshaji/autopsy"
  url "{source_url}"
  sha256 "{source_sha}"
  license :cannot_represent

  depends_on :macos
  depends_on "python@3.12"

{resource_text}

  def install
    virtualenv_install_with_resources

    menubar = prefix/"menubar"
    menubar.install Dir["apps/menubar/*"]

    with_env(PATH: "#{{libexec}}/bin:#{{ENV.fetch("PATH", "")}}") do
      system libexec/"bin/python", "-m", "autopsy_memory.cli", "menubar", "--dir", menubar, "--build", "--release"
    end

    bin.env_script_all_files libexec/"bin", AUTOPSY_UNIFIED_MEMORY: "1"
  end

  def caveats
    <<~EOS
      To install agent instructions and start the macOS menu bar utility:
        autopsy install

      To stop only the menu bar utility:
        autopsy menubar --uninstall-launch-agent
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{{bin}}/autopsy version")
    system bin/"autopsy", "version", "--json"
    system bin/"autopsy", "doctor"

    menubar_paths = JSON.parse(shell_output("#{{bin}}/autopsy menubar --print-path"))
    assert menubar_paths["app_bundle_exists"], "expected prebuilt menu bar app bundle"
    assert menubar_paths["app_bundle_current"], "expected current menu bar app bundle"
  end
end
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=read_project_version())
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source_url, source_sha = public_tag_sha256(args.version)
    resources = resource_blocks(args.python)
    formula = render_formula(args.version, source_url, source_sha, resources)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(formula)
    print(f"updated {args.output} for v{args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

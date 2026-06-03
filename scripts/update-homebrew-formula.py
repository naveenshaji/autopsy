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
FALKORDB_NATIVE_VERSION = "v4.18.3"
FALKORDB_MACOS_ARM64_URL = (
    f"https://github.com/FalkorDB/FalkorDB/releases/download/{FALKORDB_NATIVE_VERSION}/falkordb-macos-arm64v8.so"
)
FALKORDB_MACOS_ARM64_SHA256 = "53aa98e66dc52cf4d95628d1144ab4f3233cadf951faf81e76d5a7c44483541a"


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


def report_distribution(item: dict[str, Any]) -> tuple[str, str]:
    download_info = item.get("download_info") or {}
    url = str(download_info.get("url") or "")
    archive_info = download_info.get("archive_info") or {}
    hashes = archive_info.get("hashes") or {}
    sha = str(hashes.get("sha256") or "")
    if url and sha:
        return url, sha

    metadata = item.get("metadata") or {}
    name = metadata.get("name")
    version = metadata.get("version")
    if not name or not version:
        raise RuntimeError(f"Cannot resolve distribution for install report item: {item!r}")

    data = json.loads(fetch_bytes(f"https://pypi.org/pypi/{name}/{version}/json"))
    urls = data["urls"]
    for release_file in urls:
        if release_file["packagetype"] == "bdist_wheel":
            return release_file["url"], release_file["digests"]["sha256"]
    for release_file in urls:
        if release_file["packagetype"] == "sdist":
            return release_file["url"], release_file["digests"]["sha256"]
    raise RuntimeError(f"No source or wheel distribution found for {name}=={version}")


def resource_blocks(python: str) -> str:
    resources: list[tuple[str, str, str, bool]] = []
    for item in pip_dependency_report(python):
        metadata = item.get("metadata") or {}
        name = metadata.get("name")
        version = metadata.get("version")
        if not name or not version or name.lower().replace("_", "-") == PACKAGE_NAME:
            continue
        url, sha = report_distribution(item)
        resources.append((name.lower().replace("_", "-"), url, sha, url.endswith(".whl")))

    blocks = []
    for name, url, sha, is_wheel in sorted(resources):
        url_suffix = ", using: :nounzip" if is_wheel else ""
        blocks.append(
            textwrap.dedent(
                f"""\
                resource "{name}" do
                  url "{url}"{url_suffix}
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

  depends_on arch: :arm64
  depends_on :macos
  depends_on "openssl@3"
  depends_on "python@3.12"

{resource_text}

  resource "falkordb-macos-arm64v8" do
    url "{FALKORDB_MACOS_ARM64_URL}", using: :nounzip
    sha256 "{FALKORDB_MACOS_ARM64_SHA256}"
  end

  def autopsy_pip_install(target)
    system Formula["python@3.12"].opt_bin/"python3.12", "-m", "pip",
           "--python=#{{libexec}}/bin/python", "install",
           "--verbose", "--no-deps", "--ignore-installed", "--no-compile",
           target
  end

  def autopsy_resource_target
    wheel = Dir["*.whl"].first
    return Pathname.pwd/wheel if wheel

    Pathname.pwd
  end

  def install
    venv = virtualenv_create(libexec, "python3.12", system_site_packages: true, without_pip: true)
    resources.each do |resource|
      next if resource.name == "falkordb-macos-arm64v8"

      resource.stage do
        autopsy_pip_install autopsy_resource_target
      end
    end
    venv.pip_install_and_link buildpath

    native_module = libexec/"share/autopsy/falkordb.so"
    native_module.dirname.mkpath
    resource("falkordb-macos-arm64v8").stage do
      cp "falkordb-macos-arm64v8.so", native_module
    end
    chmod 0755, native_module

    menubar = prefix/"menubar"
    menubar.install Dir["apps/menubar/*"]

    with_env(PATH: "#{{libexec}}/bin:#{{ENV.fetch("PATH", "")}}") do
      system libexec/"bin/python", "-m", "autopsy_memory.cli", "menubar", "--dir", menubar, "--build", "--release"
    end

    wrapper_env = {{
      AUTOPSY_UNIFIED_MEMORY:       "1",
      AUTOPSY_FALKORDB_MODULE_PATH: native_module.to_s,
    }}
    %w[autopsy autopsy-memory-mcp autopsy-memory-worker].each do |script|
      rm bin/script if (bin/script).exist?
      (bin/script).write_env_script libexec/"bin/#{{script}}", wrapper_env
    end
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

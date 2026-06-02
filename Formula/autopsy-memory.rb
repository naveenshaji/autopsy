require "json"

class AutopsyMemory < Formula
  include Language::Python::Virtualenv

  desc "Local-first Falkor-backed memory layer and CLI for coding agents"
  homepage "https://github.com/naveenshaji/autopsy"
  url "https://github.com/naveenshaji/autopsy/archive/refs/tags/v0.1.15.tar.gz"
  sha256 "ccff952cb0c952cc67110efb024cd7990af238dfff2c80a1ebd0145fe48d4a4d"
  license :cannot_represent

  depends_on :macos
  depends_on "python@3.12"

  resource "falkordb" do
    url "https://files.pythonhosted.org/packages/c8/3a/58da510e5800a5cdbf9591111e4287cbf68b475bf074db12a94e5db8bcea/falkordb-1.6.1.tar.gz"
    sha256 "bbef448a0b43e00ff3062bd6201368618d7b36e969d16ba71e8b8e3fa90873d4"
  end

  resource "falkordblite" do
    url "https://files.pythonhosted.org/packages/70/03/afbb6e0f03c302aa9b64a38e1a2c43664f86921f0dcbf03ec9e31da06ac6/falkordblite-0.10.0.tar.gz"
    sha256 "65a72abafd30711f699c15571df6959edb8901605053ce940ccdd837832e709b"
  end

  resource "psutil" do
    url "https://files.pythonhosted.org/packages/aa/c6/d1ddf4abb55e93cebc4f2ed8b5d6dbad109ecb8d63748dd2b20ab5e57ebe/psutil-7.2.2.tar.gz"
    sha256 "0746f5f8d406af344fd547f1c8daa5f5c33dbc293bb8d6a16d80b4bb88f59372"
  end

  resource "python-dateutil" do
    url "https://files.pythonhosted.org/packages/66/c0/0c8b6ad9f17a802ee498c46e004a0eb49bc148f2fd230864601a86dcf6db/python-dateutil-2.9.0.post0.tar.gz"
    sha256 "37dd54208da7e1cd875388217d5e00ebd4179249f90fb72437e91a35459a0ad3"
  end

  resource "redis" do
    url "https://files.pythonhosted.org/packages/7b/7f/3759b1d0d72b7c92f0d70ffd9dc962b7b7b5ee74e135f9d7d8ab06b8a318/redis-7.4.0.tar.gz"
    sha256 "64a6ea7bf567ad43c964d2c30d82853f8df927c5c9017766c55a1d1ed95d18ad"
  end

  resource "setuptools" do
    url "https://files.pythonhosted.org/packages/4f/db/cfac1baf10650ab4d1c111714410d2fbb77ac5a616db26775db562c8fab2/setuptools-82.0.1.tar.gz"
    sha256 "7d872682c5d01cfde07da7bccc7b65469d3dca203318515ada1de5eda35efbf9"
  end

  resource "six" do
    url "https://files.pythonhosted.org/packages/94/e7/b2c673351809dca68a0e064b6af791aa332cf192da575fd474ed7d6f16a2/six-1.17.0.tar.gz"
    sha256 "ff70335d468e7eb6ec65b95b99d3a2836546063f63acc5171de367e834932a81"
  end

  def install
    virtualenv_install_with_resources

    menubar = prefix/"menubar"
    menubar.install Dir["apps/menubar/*"]

    with_env(PATH: "#{libexec}/bin:#{ENV.fetch("PATH", "")}") do
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
    assert_match version.to_s, shell_output("#{bin}/autopsy version")
    system bin/"autopsy", "version", "--json"
    system bin/"autopsy", "doctor"

    menubar_paths = JSON.parse(shell_output("#{bin}/autopsy menubar --print-path"))
    assert menubar_paths["app_bundle_exists"], "expected prebuilt menu bar app bundle"
    assert menubar_paths["app_bundle_current"], "expected current menu bar app bundle"
  end
end

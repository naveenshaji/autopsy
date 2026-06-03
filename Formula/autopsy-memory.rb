require "json"

class AutopsyMemory < Formula
  include Language::Python::Virtualenv

  desc "Local-first Falkor-backed memory layer and CLI for coding agents"
  homepage "https://github.com/naveenshaji/autopsy"
  url "https://github.com/naveenshaji/autopsy/archive/refs/tags/v0.1.22.tar.gz"
  sha256 "ee1423729f987b42714fafa9aa0414cc8569e78150db2aab3f00ce3d03594155"
  license :cannot_represent

  depends_on arch: :arm64
  depends_on "libyaml"
  depends_on :macos
  depends_on "openssl@3"
  depends_on "python@3.12"

  resource "annotated-doc" do
    url "https://files.pythonhosted.org/packages/1e/d3/26bf1008eb3d2daa8ef4cacc7f3bfdc11818d111f7e2d0201bc6e3b49d45/annotated_doc-0.0.4-py3-none-any.whl", using: :nounzip
    sha256 "571ac1dc6991c450b25a9c2d84a3705e2ae7a53467b5d111c24fa8baabbed320"
  end

  resource "anyio" do
    url "https://files.pythonhosted.org/packages/da/42/e921fccf5015463e32a3cf6ee7f980a6ed0f395ceeaa45060b61d86486c2/anyio-4.13.0-py3-none-any.whl", using: :nounzip
    sha256 "08b310f9e24a9594186fd75b4f73f4a4152069e3853f1ed8bfbf58369f4ad708"
  end

  resource "certifi" do
    url "https://files.pythonhosted.org/packages/59/8c/57e832b7af6d7c5abe66eb3fbe3a3a32f4d11ea23a1aa7131371035be991/certifi-2026.5.20-py3-none-any.whl", using: :nounzip
    sha256 "3c52e209ba0a4ad7aebe60436a4ab349c39e1e602e8c134221e546902ad25897"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/c7/0d/67e5b4109ea4a837e80daa87c2c696711955e40449a97e8926672534def2/click-8.4.1-py3-none-any.whl", using: :nounzip
    sha256 "482be17c6991b8c19c5429a1e995d9b0efdbb63172824c41f99965dc0ade8ec2"
  end

  resource "falkordb" do
    url "https://files.pythonhosted.org/packages/90/02/1cf9cef72228ca2b2776b4ed0cb2645298ddcc57c1fe2c545cd46bc11eae/falkordb-1.6.1-py3-none-any.whl", using: :nounzip
    sha256 "cf51caeb433c04db303de5967a0c2590675fcc0354e80997870b1e0497d30c34"
  end

  resource "falkordblite" do
    url "https://files.pythonhosted.org/packages/0e/43/39d8cf13964784447676d24f0cefa3bdc99c10e647c71e6a4172d302dcac/falkordblite-0.10.0-cp312-cp312-macosx_10_13_x86_64.macosx_15_0_arm64.whl", using: :nounzip
    sha256 "741fda166170513db1815d5369870e47d44da2e9b85320fddbc50c88a7338d51"
  end

  resource "filelock" do
    url "https://files.pythonhosted.org/packages/81/47/dd9a212ef6e343a6857485ffe25bba537304f1913bdbed446a23f7f592e1/filelock-3.29.0-py3-none-any.whl", using: :nounzip
    sha256 "96f5f6344709aa1572bbf631c640e4ebeeb519e08da902c39a001882f30ac258"
  end

  resource "fsspec" do
    url "https://files.pythonhosted.org/packages/d5/0c/043d5e551459da400957a1395e0febbf771446ff34291afcbe3d8be2a279/fsspec-2026.4.0-py3-none-any.whl", using: :nounzip
    sha256 "11ef7bb35dab8a394fde6e608221d5cf3e8499401c249bebaeaad760a1a8dec2"
  end

  resource "h11" do
    url "https://files.pythonhosted.org/packages/04/4b/29cac41a4d98d144bf5f6d33995617b185d14b22401f75ca86f384e87ff1/h11-0.16.0-py3-none-any.whl", using: :nounzip
    sha256 "63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86"
  end

  resource "hf-xet" do
    url "https://files.pythonhosted.org/packages/9b/ff/edcc2b40162bef3ff78e14ab637e5f3b89243d6aee72f5949d3bb6a5af83/hf_xet-1.5.0-cp37-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "fd6e5a9b0fdac4ed03ed45ef79254a655b1aaab514a02202617fbf643f5fdf7a"
  end

  resource "httpcore" do
    url "https://files.pythonhosted.org/packages/7e/f5/f66802a942d491edb555dd61e3a9961140fd64c90bce1eafd741609d334d/httpcore-1.0.9-py3-none-any.whl", using: :nounzip
    sha256 "2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55"
  end

  resource "httpx" do
    url "https://files.pythonhosted.org/packages/2a/39/e50c7c3a983047577ee07d2a9e53faf5a69493943ec3f6a384bdc792deb2/httpx-0.28.1-py3-none-any.whl", using: :nounzip
    sha256 "d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad"
  end

  resource "huggingface-hub" do
    url "https://files.pythonhosted.org/packages/02/28/d7cef5e477b855c25d415b8f57e5bc7347c7a90cad3acf1725d0c92ca294/huggingface_hub-1.17.0-py3-none-any.whl", using: :nounzip
    sha256 "3b8156d23118e87f6a587648bfbc04f04a12a757ccb4ed298b35c4ae638bf24c"
  end

  resource "idna" do
    url "https://files.pythonhosted.org/packages/1e/5e/d4e9f1a599fb8e573b7b87160658329fbf28d19eac2718f51fc3def3aa5a/idna-3.18-py3-none-any.whl", using: :nounzip
    sha256 "7f952cbe720b688055e3f87de14f5c3e5fdaa8bc3928985c4077ca689de849a2"
  end

  resource "jinja2" do
    url "https://files.pythonhosted.org/packages/62/a1/3d680cbfd5f4b8f15abc1d571870c5fc3e594bb582bc3b64ea099db13e56/jinja2-3.1.6-py3-none-any.whl", using: :nounzip
    sha256 "85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67"
  end

  resource "joblib" do
    url "https://files.pythonhosted.org/packages/7b/91/984aca2ec129e2757d1e4e3c81c3fcda9d0f85b74670a094cc443d9ee949/joblib-1.5.3-py3-none-any.whl", using: :nounzip
    sha256 "5fc3c5039fc5ca8c0276333a188bbd59d6b7ab37fe6632daa76bc7f9ec18e713"
  end

  resource "markdown-it-py" do
    url "https://files.pythonhosted.org/packages/b3/81/4da04ced5a082363ecfa159c010d200ecbd959ae410c10c0264a38cac0f5/markdown_it_py-4.2.0-py3-none-any.whl", using: :nounzip
    sha256 "9f7ebbcd14fe59494226453aed97c1070d83f8d24b6fc3a3bcf9a38092641c4a"
  end

  resource "markupsafe" do
    url "https://files.pythonhosted.org/packages/9a/81/7e4e08678a1f98521201c3079f77db69fb552acd56067661f8c2f534a718/markupsafe-3.0.3-cp312-cp312-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "1872df69a4de6aead3491198eaf13810b565bdbeec3ae2dc8780f14458ec73ce"
  end

  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/b3/38/89ba8ad64ae25be8de66a6d463314cf1eb366222074cfda9ee839c56a4b4/mdurl-0.1.2-py3-none-any.whl", using: :nounzip
    sha256 "84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8"
  end

  resource "mpmath" do
    url "https://files.pythonhosted.org/packages/43/e3/7d92a15f894aa0c9c4b49b8ee9ac9850d6e63b03c9c32c0367a13ae62209/mpmath-1.3.0-py3-none-any.whl", using: :nounzip
    sha256 "a0b2b9fe80bbcd81a6647ff13108738cfb482d481d826cc0e02f5b35e5c88d2c"
  end

  resource "narwhals" do
    url "https://files.pythonhosted.org/packages/1f/b6/e7cdde7b8e90d5dff25b622f95833ef26567ad184c977278b93a1cbd5717/narwhals-2.22.0-py3-none-any.whl", using: :nounzip
    sha256 "1421797ede01789cc1537619dbc3f36f840737240f748fdb24a60a0225fc80be"
  end

  resource "networkx" do
    url "https://files.pythonhosted.org/packages/9e/c9/b2622292ea83fbb4ec318f5b9ab867d0a28ab43c5717bb85b0a5f6b3b0a4/networkx-3.6.1-py3-none-any.whl", using: :nounzip
    sha256 "d47fbf302e7d9cbbb9e2555a0d267983d2aa476bac30e90dfbe5669bd57f3762"
  end

  resource "numpy" do
    url "https://files.pythonhosted.org/packages/ad/fe/c0a6b7b2ca128a8fb228575147073b660656734b8ebe4d76c8fd748dcc79/numpy-2.4.6-cp312-cp312-macosx_14_0_arm64.whl", using: :nounzip
    sha256 "3213d622a0283a39a93d188f3cf72b26862df52fbb4ca3697f51705016523d41"
  end

  resource "packaging" do
    url "https://files.pythonhosted.org/packages/df/b2/87e62e8c3e2f4b32e5fe99e0b86d576da1312593b39f47d8ceef365e95ed/packaging-26.2-py3-none-any.whl", using: :nounzip
    sha256 "5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e"
  end

  resource "psutil" do
    url "https://files.pythonhosted.org/packages/80/c4/f5af4c1ca8c1eeb2e92ccca14ce8effdeec651d5ab6053c589b074eda6e1/psutil-7.2.2-cp36-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "1a7b04c10f32cc88ab39cbf606e117fd74721c831c98a27dc04578deb0c16979"
  end

  resource "pygments" do
    url "https://files.pythonhosted.org/packages/f4/7e/a72dd26f3b0f4f2bf1dd8923c85f7ceb43172af56d63c7383eb62b332364/pygments-2.20.0-py3-none-any.whl", using: :nounzip
    sha256 "81a9e26dd42fd28a23a2d169d86d7ac03b46e2f8b59ed4698fb4785f946d0176"
  end

  resource "python-dateutil" do
    url "https://files.pythonhosted.org/packages/ec/57/56b9bcc3c9c6a792fcbaf139543cee77261f3651ca9da0c93f5c1221264b/python_dateutil-2.9.0.post0-py2.py3-none-any.whl", using: :nounzip
    sha256 "a8b2bc7bffae282281c8140a97d3aa9c14da0b136dfe83f850eea9a5f7470427"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/89/a0/6cf41a19a1f2f3feab0e9c0b74134aa2ce6849093d5517a0c550fe37a648/pyyaml-6.0.3-cp312-cp312-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "fc09d0aa354569bc501d4e787133afc08552722d3ab34836a80547331bb5d4a0"
  end

  resource "redis" do
    url "https://files.pythonhosted.org/packages/74/3a/95deec7db1eb53979973ebd156f3369a72732208d1391cd2e5d127062a32/redis-7.4.0-py3-none-any.whl", using: :nounzip
    sha256 "a9c74a5c893a5ef8455a5adb793a31bb70feb821c86eccb62eebef5a19c429ec"
  end

  resource "regex" do
    url "https://files.pythonhosted.org/packages/54/4b/ee27938d1b2c443e89a9a10e00d2d19aa5ee300cd3d61140644e93bb083e/regex-2026.5.9-cp312-cp312-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "f7a7c26137296beba7784de6eba69c6a93a63ccebc385e4962fe67e267a91225"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/82/3b/64d4899d73f91ba49a8c18a8ff3f0ea8f1c1d75481760df8c68ef5235bf5/rich-15.0.0-py3-none-any.whl", using: :nounzip
    sha256 "33bd4ef74232fb73fe9279a257718407f169c09b78a87ad3d296f548e27de0bb"
  end

  resource "safetensors" do
    url "https://files.pythonhosted.org/packages/e8/00/374c0c068e30cd31f1e1b46b4b5738168ec79e7689ca82ee93ddfea05109/safetensors-0.7.0-cp38-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "94fd4858284736bb67a897a41608b5b0c2496c9bdb3bf2af1fa3409127f20d57"
  end

  resource "scikit-learn" do
    url "https://files.pythonhosted.org/packages/cc/d5/2b5148f2279196775e1db2aeb85d14b70ac80e7e32b3b28e7ebeafb0901d/scikit_learn-1.9.0-cp312-cp312-macosx_12_0_arm64.whl", using: :nounzip
    sha256 "5be45aa4a42a68a533913a6ed736cf309de2226411c79ef8d609a5456f1939b1"
  end

  resource "scipy" do
    url "https://files.pythonhosted.org/packages/cf/a9/599c28631bad314d219cf9ffd40e985b24d603fc8a2f4ccc5ae8419a535b/scipy-1.17.1-cp312-cp312-macosx_14_0_arm64.whl", using: :nounzip
    sha256 "cc90d2e9c7e5c7f1a482c9875007c095c3194b1cfedca3c2f3291cdc2bc7c086"
  end

  resource "sentence-transformers" do
    url "https://files.pythonhosted.org/packages/bf/03/ee99a6b030e7a2e056547729f8a4709dd93e13d9c6f07590f74c395c4017/sentence_transformers-5.5.1-py3-none-any.whl", using: :nounzip
    sha256 "4fe11d433badc5282d32f7fc08bc714216b7a5aca426f9df77a45a554756deb7"
  end

  resource "setuptools" do
    url "https://files.pythonhosted.org/packages/e1/e3/c164c88b2e5ce7b24d667b9bd83589cf4f3520d97cad01534cd3c4f55fdb/setuptools-81.0.0-py3-none-any.whl", using: :nounzip
    sha256 "fdd925d5c5d9f62e4b74b30d6dd7828ce236fd6ed998a08d81de62ce5a6310d6"
  end

  resource "shellingham" do
    url "https://files.pythonhosted.org/packages/e0/f9/0595336914c5619e5f28a1fb793285925a8cd4b432c9da0a987836c7f822/shellingham-1.5.4-py2.py3-none-any.whl", using: :nounzip
    sha256 "7ecfff8f2fd72616f7481040475a65b2bf8af90a56c89140852d1120324e8686"
  end

  resource "six" do
    url "https://files.pythonhosted.org/packages/b7/ce/149a00dd41f10bc29e5921b496af8b574d8413afcd5e30dfa0ed46c2cc5e/six-1.17.0-py2.py3-none-any.whl", using: :nounzip
    sha256 "4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274"
  end

  resource "sympy" do
    url "https://files.pythonhosted.org/packages/a2/09/77d55d46fd61b4a135c444fc97158ef34a095e5681d0a6c10b75bf356191/sympy-1.14.0-py3-none-any.whl", using: :nounzip
    sha256 "e091cc3e99d2141a0ba2847328f5479b05d94a6635cb96148ccb3f34671bd8f5"
  end

  resource "threadpoolctl" do
    url "https://files.pythonhosted.org/packages/32/d5/f9a850d79b0851d1d4ef6456097579a9005b31fea68726a4ae5f2d82ddd9/threadpoolctl-3.6.0-py3-none-any.whl", using: :nounzip
    sha256 "43a0b8fd5a2928500110039e43a5eed8480b918967083ea48dc3ab9f13c4a7fb"
  end

  resource "tokenizers" do
    url "https://files.pythonhosted.org/packages/2e/47/174dca0502ef88b28f1c9e06b73ce33500eedfac7a7692108aec220464e7/tokenizers-0.22.2-cp39-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "1e418a55456beedca4621dbab65a318981467a2b188e982a23e117f115ce5001"
  end

  resource "torch" do
    url "https://files.pythonhosted.org/packages/ef/bb/285d643f254731294c9b595a007eac39db4600a98682d7bca688f42ca164/torch-2.12.0-cp312-cp312-macosx_14_0_arm64.whl", using: :nounzip
    sha256 "b41339df93d491435e790ff8bcbae1c0ce777175889bfd1281d119862793e6a2"
  end

  resource "tqdm" do
    url "https://files.pythonhosted.org/packages/16/e1/3079a9ff9b8e11b846c6ac5c8b5bfb7ff225eee721825310c91b3b50304f/tqdm-4.67.3-py3-none-any.whl", using: :nounzip
    sha256 "ee1e4c0e59148062281c49d80b25b67771a127c85fc9676d3be5f243206826bf"
  end

  resource "transformers" do
    url "https://files.pythonhosted.org/packages/02/ca/2eaa5359f2ccb8c2e1656bc26305ad0cf438aa392ce4b29ae67a315c186e/transformers-5.9.0-py3-none-any.whl", using: :nounzip
    sha256 "1d19509bcff7028ebc6b277d71caa712e8353778463d38764237d14b42b52788"
  end

  resource "typer" do
    url "https://files.pythonhosted.org/packages/3f/f9/2b3ff4e56e5fa7debfaf9eb135d0da96f3e9a1d5b27222223c7296336e5f/typer-0.25.1-py3-none-any.whl", using: :nounzip
    sha256 "75caa44ed46a03fb2dab8808753ffacdbfea88495e74c85a28c5eefcf5f39c89"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/18/67/36e9267722cc04a6b9f15c7f3441c2363321a3ea07da7ae0c0707beb2a9c/typing_extensions-4.15.0-py3-none-any.whl", using: :nounzip
    sha256 "f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548"
  end

  resource "falkordb-macos-arm64v8" do
    url "https://github.com/FalkorDB/FalkorDB/releases/download/v4.18.3/falkordb-macos-arm64v8.so", using: :nounzip
    sha256 "53aa98e66dc52cf4d95628d1144ab4f3233cadf951faf81e76d5a7c44483541a"
  end

  def autopsy_pip_install(target)
    system Formula["python@3.12"].opt_bin/"python3.12", "-m", "pip",
           "--python=#{libexec}/bin/python", "install",
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

    with_env(PATH: "#{libexec}/bin:#{ENV.fetch("PATH", "")}") do
      system libexec/"bin/python", "-m", "autopsy_memory.cli", "menubar", "--dir", menubar, "--build", "--release"
    end

    wrapper_env = {
      AUTOPSY_UNIFIED_MEMORY:       "1",
      AUTOPSY_FALKORDB_MODULE_PATH: native_module.to_s,
    }
    %w[autopsy autopsy-memory-mcp autopsy-memory-worker].each do |script|
      rm bin/script if (bin/script).exist?
      (bin/script).write_env_script libexec/"bin/#{script}", wrapper_env
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
    assert_match version.to_s, shell_output("#{bin}/autopsy version")
    system bin/"autopsy", "version", "--json"
    system bin/"autopsy", "doctor"

    menubar_paths = JSON.parse(shell_output("#{bin}/autopsy menubar --print-path"))
    assert menubar_paths["app_bundle_exists"], "expected prebuilt menu bar app bundle"
    assert menubar_paths["app_bundle_current"], "expected current menu bar app bundle"
  end
end

import io
import zipfile
from pathlib import Path

import pytest

from app import toolchain_specs as specs
from app import toolchains
from app.config import settings
from app.errors import WorkflowError

SHA = "a" * 64
GITHUB = "https://api.github.com/repos"


def fetchers(json: dict | None = None, text: dict | None = None) -> specs.Fetchers:
    """Fake network: answers by URL, fails on any other."""
    async def get_json(url: str):
        return (json or {})[url]

    async def get_text(url: str) -> str:
        return (text or {})[url]

    return specs.Fetchers(json=get_json, text=get_text)


def release(repo: str, tag: str) -> dict:
    return {f"{GITHUB}/{repo}/releases/latest": {"tag_name": tag}}


def test_pick_version_exact_prefix_and_latest():
    versions = ["3.8.8", "3.9.0", "3.9.10", "3.9.9", "4.0.1"]
    assert specs.pick_version(versions, "3.9.0", "Maven") == "3.9.0"
    assert specs.pick_version(versions, "3.9", "Maven") == "3.9.10"
    assert specs.pick_version(versions, "3", "Maven") == "3.9.10"
    assert specs.pick_version(versions, "latest", "Maven") == "4.0.1"
    with pytest.raises(WorkflowError, match="No Maven release matches '5'"):
        specs.pick_version(versions, "5", "Maven")


def test_checksum_in_sums_file_and_single_hash():
    assert specs.checksum_in(f"{SHA}  other.zip\n{'b' * 64} *want.zip\n", "want.zip") == "b" * 64
    assert specs.checksum_in(f"{SHA}  file\n") == SHA
    with pytest.raises(WorkflowError, match="No checksum"):
        specs.checksum_in(f"{SHA}  other.zip\n", "want.zip")


async def test_rust_default_and_exact():
    toml = 'date = "x"\n[pkg.cargo]\nversion = "0.1.0"\n[pkg.rust]\nversion = "1.82.0 (f6e511eec 2024-10-15)"\n'
    url = "https://static.rust-lang.org/dist/rust-1.82.0-x86_64-unknown-linux-gnu.tar.xz"
    fetch = fetchers(text={
        "https://static.rust-lang.org/dist/channel-rust-stable.toml": toml,
        url + ".sha256": f"{SHA}  rust-1.82.0-x86_64-unknown-linux-gnu.tar.xz\n",
    })
    got = await specs.resolve_rust("stable", "x86_64", fetch)
    assert (got.version, got.url, got.checksum) == ("1.82.0", url, SHA)
    assert got.components == ("rustc", "cargo", "rust-std-x86_64-unknown-linux-gnu")
    assert (await specs.resolve_rust("1.82.0", "x86_64", fetch)).url == url
    with pytest.raises(WorkflowError, match="exact version"):
        await specs.resolve_rust("1.82", "x86_64", fetch)


async def test_java_lts_and_major():
    asset = [{"version": {"openjdk_version": "21.0.5+11-LTS"}, "binary": {"package": {"link": "https://x/jdk.tar.gz", "checksum": SHA}}}]
    query = "architecture=x64&image_type=jdk&os=linux"
    fetch = fetchers(json={
        "https://api.adoptium.net/v3/info/available_releases": {"most_recent_lts": 21},
        f"https://api.adoptium.net/v3/assets/latest/21/hotspot?{query}": asset,
    })
    got = await specs.resolve_java("lts", "x64", fetch)
    assert (got.version, got.url, got.checksum) == ("21.0.5_11-LTS", "https://x/jdk.tar.gz", SHA)
    assert (await specs.resolve_java("21", "x64", fetch)).checksum == SHA
    with pytest.raises(WorkflowError, match="major version"):
        await specs.resolve_java("21.0.5", "x64", fetch)


async def test_maven_ignores_prereleases_and_uses_sha512():
    metadata = "<versions><version>3.9.9</version><version>4.0.0-rc-1</version><version>3.9.10</version></versions>"
    url = "https://archive.apache.org/dist/maven/maven-3/3.9.10/binaries/apache-maven-3.9.10-bin.tar.gz"
    fetch = fetchers(text={
        "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/maven-metadata.xml": metadata,
        url + ".sha512": "c" * 128,
    })
    got = await specs.resolve_maven("latest", "x86_64", fetch)
    assert (got.version, got.url, got.algo) == ("3.9.10", url, "sha512")
    with pytest.raises(WorkflowError, match="No Maven release"):
        await specs.resolve_maven("4", "x86_64", fetch)


async def test_gradle_default_and_exact():
    url = "https://services.gradle.org/distributions/gradle-8.10.2-bin.zip"
    fetch = fetchers(
        json={"https://services.gradle.org/versions/current": {"version": "8.10.2"}},
        text={url + ".sha256": SHA},
    )
    assert (await specs.resolve_gradle("latest", "x86_64", fetch)).url == url
    assert (await specs.resolve_gradle("v8.10.2", "x86_64", fetch)).checksum == SHA


async def test_kotlin_deno_uv_use_the_latest_github_tag():
    kotlin = "https://github.com/JetBrains/kotlin/releases/download/v2.0.21/kotlin-compiler-2.0.21.zip"
    got = await specs.resolve_kotlin("latest", "x86_64", fetchers(json=release("JetBrains/kotlin", "v2.0.21"), text={kotlin + ".sha256": SHA}))
    assert (got.version, got.url) == ("2.0.21", kotlin)
    deno = "https://github.com/denoland/deno/releases/download/v2.1.4/deno-aarch64-unknown-linux-gnu.zip"
    got = await specs.resolve_deno("2.1.4", "aarch64", fetchers(text={deno + ".sha256sum": f"{SHA}  deno.zip"}))
    assert (got.version, got.url, got.checksum) == ("2.1.4", deno, SHA)
    uv = "https://github.com/astral-sh/uv/releases/download/0.5.4/uv-x86_64-unknown-linux-gnu.tar.gz"
    got = await specs.resolve_uv("latest", "x86_64", fetchers(json=release("astral-sh/uv", "0.5.4"), text={uv + ".sha256": f"{SHA} *uv.tar.gz"}))
    assert (got.version, got.url) == ("0.5.4", uv)


async def test_bun_takes_its_checksum_from_shasums():
    base = "https://github.com/oven-sh/bun/releases/download/bun-v1.1.38"
    fetch = fetchers(
        json=release("oven-sh/bun", "bun-v1.1.38"),
        text={f"{base}/SHASUMS256.txt": f"{'d' * 64}  bun-linux-aarch64.zip\n{SHA}  bun-linux-x64.zip\n"},
    )
    got = await specs.resolve_bun("latest", "x64", fetch)
    assert (got.version, got.url, got.checksum) == ("1.1.38", f"{base}/bun-linux-x64.zip", SHA)


def dotnet_fetch() -> specs.Fetchers:
    sdk = {"version": "9.0.100", "files": [
        {"name": "dotnet-sdk-linux-x64.tar.gz", "rid": "linux-x64", "url": "https://x/sdk.tar.gz", "hash": "e" * 128},
        {"name": "dotnet-sdk-linux-x64.zip", "rid": "linux-x64", "url": "https://x/sdk.zip", "hash": "f" * 128},
    ]}
    return fetchers(json={
        "https://builds.dotnet.microsoft.com/dotnet/release-metadata/releases-index.json": {"releases-index": [
            {"channel-version": "10.0", "latest-sdk": "10.0.1", "support-phase": "preview", "release-type": "sts", "releases.json": "https://x/10"},
            {"channel-version": "9.0", "latest-sdk": "9.0.100", "support-phase": "active", "release-type": "lts", "releases.json": "https://x/9"},
        ]},
        "https://x/9": {"releases": [{"sdk": sdk}]},
    })


async def test_dotnet_default_channel_and_exact_sdk():
    got = await specs.resolve_dotnet("lts", "x64", dotnet_fetch())
    assert (got.version, got.url, got.algo) == ("9.0.100", "https://x/sdk.tar.gz", "sha512")
    assert (await specs.resolve_dotnet("9.0.100", "x64", dotnet_fetch())).version == "9.0.100"
    assert (await specs.resolve_dotnet("9", "x64", dotnet_fetch())).version == "9.0.100"
    with pytest.raises(WorkflowError, match="No .NET"):
        await specs.resolve_dotnet("9.0.999", "x64", dotnet_fetch())
    with pytest.raises(WorkflowError, match="No .NET release matches"):
        await specs.resolve_dotnet("7.0", "x64", dotnet_fetch())


async def test_zig_skips_master_and_other_machines():
    entry = lambda v: {"x86_64-linux": {"tarball": f"https://ziglang.org/download/{v}/zig.tar.xz", "shasum": SHA}}
    fetch = fetchers(json={"https://ziglang.org/download/index.json": {
        "master": entry("master"), "0.12.1": entry("0.12.1"), "0.13.0": entry("0.13.0"),
        "0.14.0": {"aarch64-linux": {"tarball": "x", "shasum": SHA}},
    }})
    assert (await specs.resolve_zig("latest", "x86_64", fetch)).version == "0.13.0"
    assert (await specs.resolve_zig("0.12", "x86_64", fetch)).version == "0.12.1"
    with pytest.raises(WorkflowError, match="No Zig release"):
        await specs.resolve_zig("0.14", "x86_64", fetch)


async def test_terraform_helm_kubectl():
    base = "https://releases.hashicorp.com/terraform/1.9.8"
    name = "terraform_1.9.8_linux_amd64.zip"
    got = await specs.resolve_terraform("latest", "amd64", fetchers(
        json={"https://checkpoint-api.hashicorp.com/v1/check/terraform": {"current_version": "1.9.8"}},
        text={f"{base}/terraform_1.9.8_SHA256SUMS": f"{SHA}  {name}\n"},
    ))
    assert (got.version, got.url, got.checksum) == ("1.9.8", f"{base}/{name}", SHA)

    helm = "https://get.helm.sh/helm-v3.16.2-linux-arm64.tar.gz"
    got = await specs.resolve_helm("latest", "arm64", fetchers(json=release("helm/helm", "v3.16.2"), text={helm + ".sha256sum": f"{SHA}  helm.tar.gz"}))
    assert (got.version, got.url) == ("3.16.2", helm)

    kubectl = "https://dl.k8s.io/release/v1.30.2/bin/linux/amd64/kubectl"
    fetch = fetchers(text={
        "https://dl.k8s.io/release/stable.txt": "v1.31.0\n",
        "https://dl.k8s.io/release/stable-1.30.txt": "v1.30.2\n",
        kubectl + ".sha256": SHA,
    })
    assert (await specs.resolve_kubectl("1.30", "amd64", fetch)).url == kubectl
    assert (await specs.resolve_kubectl("1.30.2", "amd64", fetch)).single_file == "kubectl"
    assert (await specs.resolve_kubectl("stable", "amd64", fetchers(text={
        "https://dl.k8s.io/release/stable.txt": "v1.30.2\n", kubectl + ".sha256": SHA}))).version == "1.30.2"


def test_at_least_ten_new_toolchains_are_listed():
    assert len(specs.ARCHIVES) >= 10
    assert set(specs.ARCHIVES) <= set(toolchains.TOOLCHAINS)
    for archive in specs.ARCHIVES.values():
        assert archive.commands and archive.default and archive.description


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o775 << 16
            zf.writestr(info, content)
    return buffer.getvalue()


def test_extract_zip_keeps_exec_bit_and_refuses_escapes(tmp_path: Path):
    archive = tmp_path / "a.zip"
    archive.write_bytes(zip_bytes({"tool/bin/run": b"x"}))
    toolchains._extract(archive, tmp_path / "out")
    mode = (tmp_path / "out" / "tool" / "bin" / "run").stat().st_mode
    assert mode & 0o111 and not mode & 0o022
    archive.write_bytes(zip_bytes({"../evil": b"x"}))
    with pytest.raises(WorkflowError, match="Unsafe path"):
        toolchains._extract(archive, tmp_path / "out2")


async def test_install_archive_end_to_end_without_network(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "toolchains_dir", tmp_path / "tc")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    calls = []

    async def resolve(selector: str, arch: str, fetch: specs.Fetchers) -> specs.Download:
        return specs.Download(selector, "https://example.test/fake.zip", SHA)

    async def fake_download(url, checksum, into, algo="sha256", single_file=""):
        calls.append((url, checksum, algo))
        (into / "fake-1" / "bin").mkdir(parents=True)
        (into / "fake-1" / "bin" / "fake").write_text("#!/bin/sh\n")

    monkeypatch.setitem(specs.ARCHIVES, "fake", specs.Archive("Fake", ("bin/fake",), "9.9", resolve, specs.X86_ARM))
    monkeypatch.setattr(toolchains, "_download_and_extract", fake_download)
    monkeypatch.setitem(toolchains.TOOLCHAINS, "fake", "Fake")

    message = await toolchains.install("fake")
    assert "fake 9.9 installed" in message
    assert (settings.toolchains_dir / "bin" / "fake").resolve() == settings.toolchains_dir / "fake-9.9" / "fake-1" / "bin" / "fake"
    assert not list(settings.toolchains_dir.glob("*.partial"))
    await toolchains.install("fake", "9.9")
    assert len(calls) == 1  # already there: nothing downloaded again


async def test_unknown_toolchain_lists_the_available_ones():
    with pytest.raises(WorkflowError, match="rust"):
        await toolchains.install("cobol")


def fake_rust_tarball(root: Path, manifest_line: str = "file:bin/rustc") -> None:
    (root / "rustc" / "bin").mkdir(parents=True)
    (root / "rustc" / "bin" / "rustc").write_text("bin")
    (root / "rustc" / "manifest.in").write_text(f"{manifest_line}\ndir:lib/rustlib\n")
    (root / "rustc" / "lib" / "rustlib").mkdir(parents=True)
    (root / "rustc" / "lib" / "rustlib" / "x").write_text("lib")
    (root / "rustc" / "install.sh").write_text("exit 1")


def test_copy_components_copies_the_manifest_without_running_anything(tmp_path: Path):
    fake_rust_tarball(tmp_path / "src")
    toolchains._copy_components(tmp_path / "src", tmp_path / "out", ("rustc",))
    assert (tmp_path / "out" / "bin" / "rustc").read_text() == "bin"
    assert (tmp_path / "out" / "lib" / "rustlib" / "x").read_text() == "lib"
    assert not (tmp_path / "out" / "install.sh").exists()


def test_copy_components_refuses_escapes_and_missing_components(tmp_path: Path):
    fake_rust_tarball(tmp_path / "src", "file:../../evil")
    with pytest.raises(WorkflowError, match="Unsafe path"):
        toolchains._copy_components(tmp_path / "src", tmp_path / "out", ("rustc",))
    with pytest.raises(WorkflowError, match="no component"):
        toolchains._copy_components(tmp_path / "src", tmp_path / "out", ("cargo",))


async def test_install_archive_refuses_a_version_that_escapes_the_directory(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "toolchains_dir", tmp_path / "tc")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")

    async def resolve(selector: str, arch: str, fetch: specs.Fetchers) -> specs.Download:
        return specs.Download("../../evil", "https://example.test/fake.zip", SHA)

    monkeypatch.setitem(specs.ARCHIVES, "fake", specs.Archive("Fake", ("bin/fake",), "9.9", resolve, specs.X86_ARM))
    monkeypatch.setitem(toolchains.TOOLCHAINS, "fake", "Fake")
    with pytest.raises(WorkflowError, match="unexpected fake version"):
        await toolchains.install("fake")


def test_drop_write_bits_ignores_links_to_outside_folders(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("x")
    outside.chmod(0o777)
    (outside / "secret").chmod(0o666)
    prefix = tmp_path / "prefix"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "tool").write_text("x")
    (prefix / "bin" / "tool").chmod(0o777)
    (prefix / "link").symlink_to(outside, target_is_directory=True)

    toolchains._drop_write_bits(prefix)

    assert (prefix / "bin" / "tool").stat().st_mode & 0o777 == 0o755
    assert outside.stat().st_mode & 0o777 == 0o777
    assert (outside / "secret").stat().st_mode & 0o777 == 0o666

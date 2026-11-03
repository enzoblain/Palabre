"""Where to download each archive toolchain from, and how its version selector is resolved.

Every entry only turns a selector ("latest", "21", "1.22.3"...) into one official download
(URL + published checksum) for the machine's architecture. Downloading, checking, extracting
and linking are done by `toolchains`. The resolvers do no I/O but the two fetchers they get.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.errors import WorkflowError

GITHUB_API = "https://api.github.com/repos"
DEFAULT_SELECTORS = ("", "latest")


@dataclass(frozen=True)
class Fetchers:
    """What the resolvers use to read indexes and checksum files."""

    json: Callable[[str], Awaitable[Any]]
    text: Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class Download:
    version: str
    url: str
    checksum: str
    algo: str = "sha256"
    # The download is one executable (not an archive), saved under this name
    single_file: str = ""
    # Rust-style archive of components (one directory each, listed in a manifest.in): the ones to copy
    components: tuple[str, ...] = ()


Resolver = Callable[[str, str, Fetchers], Awaitable[Download]]


@dataclass(frozen=True)
class Archive:
    description: str
    # Commands to link for the team, relative to the extracted root (e.g. "bin/java")
    commands: tuple[str, ...]
    default: str
    resolve: Resolver
    # platform.machine() → the architecture word of this tool's download names
    arches: dict[str, str]


X86_ARM = {"x86_64": "x86_64", "aarch64": "aarch64"}
AMD_ARM = {"x86_64": "amd64", "aarch64": "arm64"}
X64_ARM = {"x86_64": "x64", "aarch64": "arm64"}


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def pick_version(versions: list[str], selector: str, what: str) -> str:
    """The exact version, else the highest one of that major / minor ("1.22" → 1.22.x), else the highest."""
    wanted = selector.removeprefix("v")
    if wanted in DEFAULT_SELECTORS:
        matches = versions
    elif wanted in versions:
        return wanted
    else:
        matches = [v for v in versions if v.startswith(wanted + ".")]
    if not matches:
        raise WorkflowError(f"No {what} release matches {selector!r}")
    return max(matches, key=version_key)


def checksum_in(text: str, filename: str = "") -> str:
    """The hash of `filename` in a SHA*SUMS file, or the first word of a one-hash file."""
    for line in text.splitlines():
        words = line.split()
        if words and (not filename or (len(words) > 1 and words[-1].lstrip("*") == filename)):
            return words[0]
    raise WorkflowError(f"No checksum published for {filename or 'this download'}")


async def github_latest(fetch: Fetchers, repo: str) -> str:
    """The tag of the latest release of a GitHub repository."""
    return (await fetch.json(f"{GITHUB_API}/{repo}/releases/latest"))["tag_name"]


async def _github_version(fetch: Fetchers, repo: str, selector: str, prefix: str = "v") -> str:
    """The version without its tag prefix: the selector itself unless it asks for the latest."""
    if selector.removeprefix("v") in DEFAULT_SELECTORS:
        return (await github_latest(fetch, repo)).removeprefix(prefix)
    return selector.removeprefix("v")


# --- Rust ----------------------------------------------------------------------------


async def resolve_rust(selector: str, arch: str, fetch: Fetchers) -> Download:
    triple = f"{arch}-unknown-linux-gnu"
    if selector in (*DEFAULT_SELECTORS, "stable"):
        channel = await fetch.text("https://static.rust-lang.org/dist/channel-rust-stable.toml")
        found = re.search(r'\[pkg\.rust\]\s+version = "(\d+\.\d+\.\d+)', channel)
        if found is None:
            raise WorkflowError("Cannot read the stable Rust version")
        version = found.group(1)
    elif re.fullmatch(r"\d+\.\d+\.\d+", selector):
        version = selector
    else:
        raise WorkflowError(f"Rust takes 'stable' or an exact version such as 1.80.0, not {selector!r}")
    url = f"https://static.rust-lang.org/dist/rust-{version}-{triple}.tar.xz"
    sha = checksum_in(await fetch.text(url + ".sha256"))
    # rustc and cargo with the standard library; no docs, no linker (the image has no C compiler)
    return Download(version, url, sha, components=("rustc", "cargo", f"rust-std-{triple}"))


# --- JVM -----------------------------------------------------------------------------


async def resolve_java(selector: str, arch: str, fetch: Fetchers) -> Download:
    if selector in (*DEFAULT_SELECTORS, "lts"):
        major = str((await fetch.json("https://api.adoptium.net/v3/info/available_releases"))["most_recent_lts"])
    elif selector.isdigit():
        major = selector
    else:
        raise WorkflowError(f"Java takes 'lts' or a major version such as 21, not {selector!r}")
    query = f"architecture={arch}&image_type=jdk&os=linux"
    assets = await fetch.json(f"https://api.adoptium.net/v3/assets/latest/{major}/hotspot?{query}")
    if not assets:
        raise WorkflowError(f"No Temurin JDK {major} for this machine")
    package = assets[0]["binary"]["package"]
    version = assets[0]["version"]["openjdk_version"].replace("+", "_")  # 21.0.5_11, safe in a path
    return Download(version, package["link"], package["checksum"])


async def _maven_versions(fetch: Fetchers) -> list[str]:
    metadata = await fetch.text("https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/maven-metadata.xml")
    return [v for v in re.findall(r"<version>([^<]+)</version>", metadata) if re.fullmatch(r"\d+(\.\d+)*", v)]


async def resolve_maven(selector: str, arch: str, fetch: Fetchers) -> Download:
    version = pick_version(await _maven_versions(fetch), selector, "Maven")
    url = f"https://archive.apache.org/dist/maven/maven-{version.split('.')[0]}/{version}/binaries/apache-maven-{version}-bin.tar.gz"
    return Download(version, url, checksum_in(await fetch.text(url + ".sha512")), algo="sha512")


async def resolve_gradle(selector: str, arch: str, fetch: Fetchers) -> Download:
    wanted = selector.removeprefix("v")
    if wanted in DEFAULT_SELECTORS:
        wanted = (await fetch.json("https://services.gradle.org/versions/current"))["version"]
    url = f"https://services.gradle.org/distributions/gradle-{wanted}-bin.zip"
    return Download(wanted, url, checksum_in(await fetch.text(url + ".sha256")))


async def resolve_kotlin(selector: str, arch: str, fetch: Fetchers) -> Download:
    version = await _github_version(fetch, "JetBrains/kotlin", selector)
    url = f"https://github.com/JetBrains/kotlin/releases/download/v{version}/kotlin-compiler-{version}.zip"
    return Download(version, url, checksum_in(await fetch.text(url + ".sha256")))


# --- JavaScript runtimes -------------------------------------------------------------


async def resolve_deno(selector: str, arch: str, fetch: Fetchers) -> Download:
    version = await _github_version(fetch, "denoland/deno", selector)
    url = f"https://github.com/denoland/deno/releases/download/v{version}/deno-{arch}-unknown-linux-gnu.zip"
    return Download(version, url, checksum_in(await fetch.text(url + ".sha256sum")))


async def resolve_bun(selector: str, arch: str, fetch: Fetchers) -> Download:
    version = await _github_version(fetch, "oven-sh/bun", selector, prefix="bun-v")
    base = f"https://github.com/oven-sh/bun/releases/download/bun-v{version}"
    name = f"bun-linux-{arch}.zip"
    return Download(version, f"{base}/{name}", checksum_in(await fetch.text(f"{base}/SHASUMS256.txt"), name))


# --- .NET, Zig -----------------------------------------------------------------------


def _dotnet_channel(index: list[dict], selector: str) -> dict:
    if selector in (*DEFAULT_SELECTORS, "lts"):
        active = [c for c in index if c.get("support-phase") == "active"]
        lts = [c for c in active if c.get("release-type") == "lts"]
        if selector != "latest" and (lts or active):
            return (lts or active)[0]
        return index[0]
    prefix = ".".join(selector.split(".")[:2])
    channel = next((c for c in index if c["channel-version"] == prefix or c["channel-version"].split(".")[0] == prefix), None)
    if channel is None:
        raise WorkflowError(f"No .NET release matches {selector!r}")
    return channel


async def resolve_dotnet(selector: str, arch: str, fetch: Fetchers) -> Download:
    index = (await fetch.json("https://builds.dotnet.microsoft.com/dotnet/release-metadata/releases-index.json"))["releases-index"]
    channel = _dotnet_channel(index, selector)
    exact = selector if len(selector.split(".")) >= 3 else channel["latest-sdk"]
    rid = f"linux-{arch}"
    for release in (await fetch.json(channel["releases.json"]))["releases"]:
        for sdk in [release.get("sdk") or {}, *release.get("sdks", [])]:
            if sdk.get("version") != exact:
                continue
            found = next((f for f in sdk.get("files", []) if f.get("rid") == rid and f["name"].endswith(".tar.gz")), None)
            if found is not None:
                return Download(exact, found["url"], found["hash"], algo="sha512")
    raise WorkflowError(f"No .NET SDK {exact} for this machine")


async def resolve_zig(selector: str, arch: str, fetch: Fetchers) -> Download:
    index = await fetch.json("https://ziglang.org/download/index.json")
    target = f"{arch}-linux"
    builds = {v: b[target] for v, b in index.items() if v != "master" and target in b}
    version = pick_version(list(builds), selector, "Zig")
    return Download(version, builds[version]["tarball"], builds[version]["shasum"])


# --- Infrastructure ------------------------------------------------------------------


async def resolve_terraform(selector: str, arch: str, fetch: Fetchers) -> Download:
    version = selector.removeprefix("v")
    if version in DEFAULT_SELECTORS:
        version = (await fetch.json("https://checkpoint-api.hashicorp.com/v1/check/terraform"))["current_version"]
    base = f"https://releases.hashicorp.com/terraform/{version}"
    name = f"terraform_{version}_linux_{arch}.zip"
    sums = await fetch.text(f"{base}/terraform_{version}_SHA256SUMS")
    return Download(version, f"{base}/{name}", checksum_in(sums, name))


async def resolve_kubectl(selector: str, arch: str, fetch: Fetchers) -> Download:
    wanted = selector.removeprefix("v")
    if wanted in (*DEFAULT_SELECTORS, "stable"):
        version = (await fetch.text("https://dl.k8s.io/release/stable.txt")).strip()
    elif wanted.count(".") == 1:  # "1.30": the latest patch of that minor
        version = (await fetch.text(f"https://dl.k8s.io/release/stable-{wanted}.txt")).strip()
    else:
        version = f"v{wanted}"
    url = f"https://dl.k8s.io/release/{version}/bin/linux/{arch}/kubectl"
    return Download(version.removeprefix("v"), url, checksum_in(await fetch.text(url + ".sha256")), single_file="kubectl")


async def resolve_helm(selector: str, arch: str, fetch: Fetchers) -> Download:
    version = await _github_version(fetch, "helm/helm", selector, prefix="")
    version = version.removeprefix("v")
    url = f"https://get.helm.sh/helm-v{version}-linux-{arch}.tar.gz"
    return Download(version, url, checksum_in(await fetch.text(url + ".sha256sum")))


async def resolve_uv(selector: str, arch: str, fetch: Fetchers) -> Download:
    version = await _github_version(fetch, "astral-sh/uv", selector, prefix="")
    url = f"https://github.com/astral-sh/uv/releases/download/{version}/uv-{arch}-unknown-linux-gnu.tar.gz"
    return Download(version, url, checksum_in(await fetch.text(url + ".sha256")))


ARCHIVES: dict[str, Archive] = {
    "rust": Archive(
        'Rust (rustc, cargo; no C linker). Version: "stable" (default) or exact ("1.80.0")',
        ("bin/rustc", "bin/cargo", "bin/rustdoc"),
        "stable",
        resolve_rust,
        X86_ARM,
    ),
    "java": Archive(
        'Temurin JDK (java, javac, jar). Version: "lts" (default) or a major ("21")',
        ("bin/java", "bin/javac", "bin/jar"),
        "lts",
        resolve_java,
        X64_ARM,
    ),
    "maven": Archive(
        'Apache Maven (mvn; needs java). Version: "latest" (default), a major ("3"), minor ("3.9") or exact',
        ("bin/mvn",),
        "latest",
        resolve_maven,
        X86_ARM,
    ),
    "gradle": Archive(
        'Gradle (gradle; needs java). Version: "latest" (default) or exact ("8.10.2")',
        ("bin/gradle",),
        "latest",
        resolve_gradle,
        X86_ARM,
    ),
    "kotlin": Archive(
        'Kotlin compiler (kotlinc, kotlin; needs java). Version: "latest" (default) or exact ("2.0.21")',
        ("bin/kotlinc", "bin/kotlin"),
        "latest",
        resolve_kotlin,
        X86_ARM,
    ),
    "deno": Archive(
        'Deno. Version: "latest" (default) or exact ("2.1.4")',
        ("deno",),
        "latest",
        resolve_deno,
        X86_ARM,
    ),
    "bun": Archive(
        'Bun. Version: "latest" (default) or exact ("1.1.38")',
        ("bun",),
        "latest",
        resolve_bun,
        {"x86_64": "x64", "aarch64": "aarch64"},
    ),
    "dotnet": Archive(
        '.NET SDK (dotnet). Version: "lts" (default), "latest", a channel ("9.0") or an exact SDK ("9.0.100")',
        ("dotnet",),
        "lts",
        resolve_dotnet,
        X64_ARM,
    ),
    "zig": Archive(
        'Zig (zig, also a C/C++ compiler). Version: "latest" (default), a minor ("0.13") or exact ("0.13.0")',
        ("zig",),
        "latest",
        resolve_zig,
        X86_ARM,
    ),
    "terraform": Archive(
        'Terraform. Version: "latest" (default) or exact ("1.9.8")',
        ("terraform",),
        "latest",
        resolve_terraform,
        AMD_ARM,
    ),
    "kubectl": Archive(
        'kubectl. Version: "stable" (default), a minor ("1.30") or exact ("1.30.2")',
        ("kubectl",),
        "stable",
        resolve_kubectl,
        AMD_ARM,
    ),
    "helm": Archive(
        'Helm. Version: "latest" (default) or exact ("3.16.2")',
        ("helm",),
        "latest",
        resolve_helm,
        AMD_ARM,
    ),
    "uv": Archive(
        'uv and uvx (fast Python package manager). Version: "latest" (default) or exact ("0.5.4")',
        ("uv", "uvx"),
        "latest",
        resolve_uv,
        X86_ARM,
    ),
}

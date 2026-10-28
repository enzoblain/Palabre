# Palabre

A company of AI agents (Claude Code) working for you: a software team building your
app on GitHub, or a research group investigating a topic. You are the CEO; you talk to
them from the desktop app or a browser.

- **Server**: runs on your NAS or any machine with Docker (API, agents, database).
- **Desktop app**: macOS, Windows and Linux, connects to your server.
- **Web app**: the same app in a browser (phone, tablet...), served by the server.

## Install the server

You need Docker with Compose, a Claude subscription and, for software projects, a GitHub
token.

```sh
mkdir palabre && cd palabre
curl -fsSLO https://raw.githubusercontent.com/enzoblain/Palabre/main/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/enzoblain/Palabre/main/.env.example -o .env
# Fill in .env (see the comments in it), then:
docker compose pull
docker compose up -d
```

The server listens on port `2710` (`PALABRE_PORT` in `.env`), and the web app on port
`2810` (`PALABRE_WEB_PORT`): open `http://<your NAS>:2810` and enter the `ADMIN_TOKEN`
from `.env`. To update:
`docker compose pull && docker compose up -d`, or let it update itself: with
`COMPOSE_PROFILES=autoupdate` in `.env`, an `updater` container checks for a new version
every 5 minutes. `PALABRE_VERSION` in `.env` pins a
version (e.g. `0.1.0`); the default is the latest release.

## Install the desktop app

Download it from the [latest release](https://github.com/enzoblain/Palabre/releases/latest):

- **macOS**: the `.dmg` (`aarch64` for Apple Silicon, `x64` for Intel). The app is not
  signed yet: the first time, right-click it → Open, or run
  `xattr -dr com.apple.quarantine /Applications/Palabre.app`.
- **Windows**: the `.msi` or the `-setup.exe`.
- **Linux**: the `.AppImage`, `.deb` or `.rpm`.

On first launch, enter your server's address (e.g. `http://192.168.1.10:2710`) and the
`ADMIN_TOKEN` from `.env`, then your name in the settings.

## Develop

```sh
docker compose up -d --build            # server and web app, built from backend/ and frontend/
cd frontend && npm install && npm run tauri dev   # desktop app
```

A release is published by pushing a version tag (`git tag v0.1.0 && git push origin v0.1.0`):
GitHub Actions builds the server and web images for amd64 and arm64
(`ghcr.io/enzoblain/palabre`, `ghcr.io/enzoblain/palabre-web`) and the desktop app for every system, attached to the release.

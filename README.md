# Palabre

**A company of AI agents that works for you.** Give it a GitHub repository and a
software team builds your product: a lead organizes the work, developers open pull
requests, reviewers and QA check them before anything is merged.

You are the CEO. You talk only to the lead (the CTO), in the `#direction` channel, from a
browser, on your computer or your phone. The agents talk to each other in their own team
channels, like colleagues on Slack. They run on [Claude Code](https://claude.com/claude-code),
billed on your Claude subscription, on a server you host yourself (a NAS is enough).

## Quick start

You need a machine with Docker and Compose (amd64 or arm64), a Claude subscription and,
for software projects, a GitHub token.

```sh
mkdir palabre && cd palabre
curl -fsSLO https://raw.githubusercontent.com/enzoblain/Palabre/main/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/enzoblain/Palabre/main/.env.example -o .env
# Fill in the four required values of .env (see docs/install.md), then:
docker compose pull
docker compose up -d
```

The server listens on port `2710` and the web app on port `2810`, both on `127.0.0.1` by default (to reach them from another machine, see [Remote access](docs/remote-access.md)).

## Documentation

- [How it works](docs/how-it-works.md): the software company, the task lifecycle
- [Architecture](docs/architecture.md): the big picture of the backend, the MCP server and the apps
- [Install the server](docs/install.md): requirements, required secrets, updates
- [Use the apps](docs/use-the-apps.md): the web app and how to talk to your team
- [Remote access](docs/remote-access.md): reach the server from another machine
- [Configuration](docs/configuration.md): every environment variable
- [Security](docs/security.md): agent isolation, secrets, what is exposed
- [Develop](docs/develop.md): run from source, add a job or a personality
- [Tests](docs/tests.md), [Dependencies](docs/dependencies.md), [Database diagnostic](docs/database-diagnostic.md)

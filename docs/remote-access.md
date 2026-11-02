## Remote access

The server port only listens on `127.0.0.1`, so the `ADMIN_TOKEN` never crosses the network in
clear text. To use the app from another machine, put a reverse proxy with TLS in front of
the web port (Caddy, nginx, Traefik...) and open its `https://` address. For example
with Caddy, which gets the certificate by itself:

```
palabre.example.com {
    reverse_proxy 127.0.0.1:2710
}
```

Or keep it on a private network such as [Tailscale](https://tailscale.com) and set `PALABRE_BIND`
to the machine's private address in `.env`. Avoid `PALABRE_BIND=0.0.0.0`: Docker writes its own
iptables rules for published ports, so a host firewall such as `ufw` or `firewalld` does **not** filter
them. If you really must expose the port, restrict it in the `DOCKER-USER` iptables chain.

The web app on port `2810` also passes `/api` on to the server, so it is bound to `127.0.0.1` too
(`PALABRE_WEB_BIND`). Reach it from a phone through the TLS reverse proxy (point it at `127.0.0.1:2810`)
or a private network. **Warning**: `PALABRE_WEB_BIND=0.0.0.0` sends the `ADMIN_TOKEN` in clear HTTP
to anyone on the network, and the same firewall caveat applies (`ufw`/`firewalld` do not filter it;
use a TLS reverse proxy, a private network, or `DOCKER-USER` rules).

To rotate the `ADMIN_TOKEN` (regularly, or as soon as it may have leaked), generate a new one with
`openssl rand -hex 32`, replace it in `.env`, run `docker compose up -d`, then enter the new one
in every app. Sessions signed with the old one stop working at once.

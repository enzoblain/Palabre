# Database diagnostic

One command, from the folder with `docker-compose.yml`, prints the `conversation_throttled` events of the last 24 h
(per hour and conversation) and checks the `request_status` CHECK constraint (rows outside the enum, then adds the
constraint if missing), then reports whether a foreign key still covers `messages.request_author_id` (it should be absent).
It only writes the CHECK constraint:

```sh
docker compose exec backend python -m scripts.diagnose_db
```

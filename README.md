# 3week_codex

FastAPI demo board with SQLite for persistent post data and Mini Redis for in-memory cache/session data.

## Local setup

1. Install dependencies.
   `pip install -r requirements.txt`
2. Run the server.
   `powershell -ExecutionPolicy Bypass -File scripts/run_server.ps1`

By default, the app stores posts in `data/posts.sqlite3` and seeds the database from `data/posts.json` the first time it is empty.

## Storage model

- Persistent post data uses the `sqlite` backend by default.
- Cache hits, sessions, and counters stay in Mini Redis memory so the web benchmark can compare local disk reads against memory reads.
- Set `REDIS_DUMP_FILE` to a path only if you want cache/session snapshots persisted as JSON.

## Optional backends

- Set `POSTS_BACKEND=postgres` and `POSTGRES_DSN=...` if you want to keep using PostgreSQL.
- Set `POSTS_BACKEND=json` if you want the old JSON file repository for simple local testing.

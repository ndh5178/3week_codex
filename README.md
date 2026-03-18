# 3week_codex

FastAPI demo board with local MongoDB for persistent post data and Mini Redis for in-memory cache/session data.

## Local setup

1. Install dependencies.
   `pip install -r requirements.txt`
2. If your Python environment was already partially configured, make sure the active interpreter also has `certifi`.
   `pip install certifi`
3. Start local MongoDB.
   `mongod --dbpath C:\data\db`
4. Start the Mini Redis server on a separate port.
   `python -m uvicorn redis_app:app --host 127.0.0.1 --port 6380 --reload`
5. Start the board server.
   Recommended on this workspace: `powershell -ExecutionPolicy Bypass -File scripts/run_server.ps1`
   Or use your own interpreter: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`

By default, the app stores posts in local MongoDB at `mongodb://localhost:27017`, database `mini_board`, collection `posts`, and seeds the collection from `data/posts.json` the first time it is empty.

## Storage model

- Persistent post data uses the `mongodb` backend by default.
- Cache hits, sessions, and counters stay in Mini Redis memory, but the Mini Redis process now runs as a separate server from the board API.
- By default, Mini Redis also writes a JSON dump to `data/redis_dump.json` so cache/session/counter data can be restored after a restart.
- If you want a different dump location, set `REDIS_DUMP_FILE` to another path.

## Mini Redis connection

- The board API talks to Mini Redis through `MINI_REDIS_URL`.
- Default: `http://127.0.0.1:6380`
- If you want the old in-process mode for tests, set `MINI_REDIS_BACKEND=embedded`.

## MongoDB settings

- `MONGODB_URI=mongodb://localhost:27017`
- `MONGODB_DATABASE=mini_board`
- `MONGODB_COLLECTION=posts`
- `POSTS_SEED_FILE=data/posts.json`

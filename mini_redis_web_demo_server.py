import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse


HOST = "127.0.0.1"
PORT = 8000
CLIENT_FILE = Path(__file__).with_name("mini_redis_web_demo.html")

POSTS_DB = [
    {
        "id": 1,
        "title": "왜 Redis를 쓰면 인기 페이지가 빨라질까?",
        "author": "미나",
        "body": "사람들이 자주 보는 페이지는 계속 반복해서 요청됩니다. 이때 결과를 메모리에 캐시하면 같은 느린 작업을 다시 하지 않아도 됩니다.",
    },
    {
        "id": 2,
        "title": "조회수 카운터는 작아 보여도 정말 중요하다",
        "author": "준",
        "body": "누군가 게시글을 열 때마다 숫자를 1씩 올려야 합니다. Redis는 이런 증가 연산을 아주 빠르게 처리하기에 잘 어울립니다.",
    },
    {
        "id": 3,
        "title": "로그인 세션도 결국 키 하나로 관리된다",
        "author": "소라",
        "body": "로그인 후 서버는 세션 키를 저장해 두고, 다음 요청에서 이 사용자가 누구인지 아주 빠르게 확인합니다.",
    },
]

INITIAL_VIEWS = {
    1: 132,
    2: 89,
    3: 57,
}


class MiniRedis:
    def __init__(self):
        self.store = {}
        self.expire_at = {}
        self.lock = RLock()

    def _purge_expired_locked(self):
        now = time.time()
        expired_keys = [key for key, expires in self.expire_at.items() if now >= expires]
        for key in expired_keys:
            self.store.pop(key, None)
            self.expire_at.pop(key, None)

    def get(self, key):
        with self.lock:
            self._purge_expired_locked()
            return self.store.get(key)

    def set(self, key, value):
        with self.lock:
            self.store[key] = str(value)
            self.expire_at.pop(key, None)
            return "OK"

    def setex(self, key, seconds, value):
        with self.lock:
            self.store[key] = str(value)
            self.expire_at[key] = time.time() + seconds
            return "OK"

    def incr(self, key):
        with self.lock:
            self._purge_expired_locked()
            current = int(self.store.get(key, "0"))
            current += 1
            self.store[key] = str(current)
            return current

    def exists(self, key):
        with self.lock:
            self._purge_expired_locked()
            return 1 if key in self.store else 0

    def delete(self, key):
        with self.lock:
            self._purge_expired_locked()
            existed = key in self.store
            self.store.pop(key, None)
            self.expire_at.pop(key, None)
            return 1 if existed else 0

    def flushall(self):
        with self.lock:
            self.store.clear()
            self.expire_at.clear()
            return "OK"

    def snapshot(self):
        with self.lock:
            self._purge_expired_locked()
            now = time.time()
            items = []
            for key in sorted(self.store):
                ttl_seconds = self.expire_at.get(key)
                ttl = "영구"
                if ttl_seconds is not None:
                    ttl = f"{max(0, int(ttl_seconds - now))}s"
                items.append(
                    {
                        "key": key,
                        "value": self.store[key],
                        "ttl": ttl,
                    }
                )
            return items


redis = MiniRedis()


def format_value(value):
    return "(없음)" if value is None else str(value)


def add_log(logs, command, result, explanation):
    logs.append(
        {
            "command": command,
            "result": format_value(result),
            "explanation": explanation,
        }
    )


def redis_get(key, logs, explanation):
    value = redis.get(key)
    add_log(logs, f"GET {key}", value, explanation)
    return value


def redis_set(key, value, logs, explanation):
    result = redis.set(key, value)
    add_log(logs, f"SET {key} {value}", result, explanation)
    return result


def redis_setex(key, seconds, value, logs, explanation):
    result = redis.setex(key, seconds, value)
    add_log(logs, f"SETEX {key} {seconds} {value}", result, explanation)
    return result


def redis_incr(key, logs, explanation):
    result = redis.incr(key)
    add_log(logs, f"INCR {key}", result, explanation)
    return result


def redis_exists(key, logs, explanation):
    result = redis.exists(key)
    add_log(logs, f"EXISTS {key}", result, explanation)
    return result


def redis_delete(key, logs, explanation):
    result = redis.delete(key)
    add_log(logs, f"DEL {key}", result, explanation)
    return result


def bootstrap_demo_state(logs=None):
    if logs is not None:
        result = redis.flushall()
        add_log(logs, "FLUSHALL", result, "데모를 처음 상태로 되돌리기 위해 모든 키를 비웁니다.")
    else:
        redis.flushall()

    for post in POSTS_DB:
        key = f"views:post:{post['id']}"
        views = INITIAL_VIEWS[post["id"]]
        if logs is not None:
            redis_set(key, views, logs, "게시판이 바로 보이도록 초기 조회수를 미리 넣어둡니다.")
        else:
            redis.set(key, views)


def build_posts():
    posts = []
    for post in POSTS_DB:
        views = int(redis.get(f"views:post:{post['id']}") or "0")
        posts.append({**post, "views": views})
    return posts


def build_top_posts():
    posts = build_posts()
    posts.sort(key=lambda item: (-item["views"], item["id"]))
    return [
        {
            "id": post["id"],
            "title": post["title"],
            "views": post["views"],
        }
        for post in posts[:3]
    ]


def get_session_token(headers):
    return headers.get("X-Session-Token", "").strip()


def current_session_payload(token, logs=None):
    if not token:
        return {
            "logged_in": False,
            "username": None,
            "session_key": None,
        }

    session_key = f"session:{token}"
    if logs is not None:
        exists = redis_exists(session_key, logs, "브라우저가 이미 유효한 로그인 세션을 가지고 있는지 확인합니다.")
    else:
        exists = redis.exists(session_key)

    if not exists:
        return {
            "logged_in": False,
            "username": None,
            "session_key": session_key,
        }

    if logs is not None:
        username = redis_get(session_key, logs, "세션 키 안에 저장된 사용자 이름을 꺼냅니다.")
    else:
        username = redis.get(session_key)

    return {
        "logged_in": True,
        "username": username,
        "session_key": session_key,
    }


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "MiniRedisBoardDemo/1.0"

    def log_message(self, format_string, *args):
        print("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format_string % args))

    def do_GET(self):
        path = urlparse(self.path).path

        if path in {"/", "/index.html", "/mini_redis_web_demo.html"}:
            self.serve_client()
            return

        if path == "/api/posts":
            self.handle_posts()
            return

        if path == "/api/session":
            self.handle_session()
            return

        if path == "/api/top-posts":
            self.handle_top_posts()
            return

        self.send_json({"ok": False, "error": "요청한 주소를 찾을 수 없습니다."}, status=404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/login":
            self.handle_login()
            return

        if path == "/api/logout":
            self.handle_logout()
            return

        if path == "/api/view-post":
            self.handle_view_post()
            return

        if path == "/api/reset-demo":
            self.handle_reset_demo()
            return

        self.send_json({"ok": False, "error": "요청한 주소를 찾을 수 없습니다."}, status=404)

    def parse_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length > 0 else b"{}"
        if not raw_body.strip():
            return {}
        try:
            return json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "JSON 형식이 올바르지 않습니다."}, status=400)
            return None

    def serve_client(self):
        if not CLIENT_FILE.exists():
            self.send_text("클라이언트 파일을 찾을 수 없습니다.", status=500)
            return

        content = CLIENT_FILE.read_text(encoding="utf-8")
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload, status=200):
        if isinstance(payload, dict) and "snapshot" not in payload:
            payload["snapshot"] = redis.snapshot()

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_posts(self):
        logs = []
        posts = []
        for post in POSTS_DB:
            key = f"views:post:{post['id']}"
            views = int(redis_get(key, logs, "각 게시글의 현재 조회수를 Redis에서 읽어옵니다.") or "0")
            posts.append({**post, "views": views})

        self.send_json(
            {
                "ok": True,
                "posts": posts,
                "redis_logs": logs,
                "message": "게시글 목록과 현재 조회수를 불러왔습니다.",
            }
        )

    def handle_session(self):
        logs = []
        session = current_session_payload(get_session_token(self.headers), logs=logs)
        self.send_json(
            {
                "ok": True,
                "session": session,
                "redis_logs": logs,
                "message": "브라우저에 저장된 로그인 세션이 있는지 확인했습니다.",
            }
        )

    def handle_top_posts(self):
        logs = []
        cache_key = "cache:top_posts"
        cached = redis_get(cache_key, logs, "인기 게시글 목록이 이미 캐시에 있는지 먼저 확인합니다.")

        if cached is not None:
            top_posts = json.loads(cached)
            self.send_json(
                {
                    "ok": True,
                    "source": "cache",
                    "top_posts": top_posts,
                    "redis_logs": logs,
                    "message": "캐시 적중입니다. 인기 게시글 목록을 Redis에서 바로 가져왔습니다.",
                }
            )
            return

        time.sleep(0.8)
        top_posts = build_top_posts()
        redis_setex(
            cache_key,
            15,
            json.dumps(top_posts),
            logs,
            "인기글 계산은 비용이 드니 15초 동안 캐시에 저장해서 다음 요청을 더 빠르게 만듭니다.",
        )
        self.send_json(
            {
                "ok": True,
                "source": "db",
                "top_posts": top_posts,
                "redis_logs": logs,
                "message": "캐시 미스입니다. 인기글을 다시 계산한 뒤 Redis에 저장했습니다.",
            }
        )

    def handle_login(self):
        payload = self.parse_json_body()
        if payload is None:
            return

        username = str(payload.get("username", "")).strip()
        if not username:
            self.send_json({"ok": False, "error": "사용자 이름을 입력해주세요."}, status=400)
            return

        logs = []
        session_token = secrets.token_hex(6)
        session_key = f"session:{session_token}"
        redis_setex(
            session_key,
            180,
            username,
            logs,
            "다음 요청에서 사용자를 빠르게 확인할 수 있도록 로그인 세션을 Redis에 저장합니다.",
        )
        session = current_session_payload(session_token)
        self.send_json(
            {
                "ok": True,
                "session_token": session_token,
                "session": session,
                "redis_logs": logs,
                "message": f"{username}님이 로그인했습니다. 세션 정보는 Redis에 저장됩니다.",
            }
        )

    def handle_logout(self):
        logs = []
        session_token = get_session_token(self.headers)
        if not session_token:
            self.send_json(
                {
                    "ok": True,
                    "session": current_session_payload(""),
                    "redis_logs": logs,
                    "message": "삭제할 세션 토큰이 없었습니다.",
                }
            )
            return

        session_key = f"session:{session_token}"
        redis_delete(session_key, logs, "로그아웃 시에는 로그인 세션 키를 Redis에서 삭제합니다.")
        self.send_json(
            {
                "ok": True,
                "session": current_session_payload(""),
                "redis_logs": logs,
                "message": "로그아웃했고, 세션 키도 Redis에서 삭제했습니다.",
            }
        )

    def handle_view_post(self):
        payload = self.parse_json_body()
        if payload is None:
            return

        try:
            post_id = int(payload.get("post_id"))
        except (TypeError, ValueError):
            self.send_json({"ok": False, "error": "숫자 형태의 post_id가 필요합니다."}, status=400)
            return

        post = next((item for item in POSTS_DB if item["id"] == post_id), None)
        if post is None:
            self.send_json({"ok": False, "error": "게시글을 찾을 수 없습니다."}, status=404)
            return

        logs = []
        new_views = redis_incr(
            f"views:post:{post_id}",
            logs,
            "사용자가 게시글을 열 때마다 조회수를 1 증가시킵니다.",
        )
        redis_delete(
            "cache:top_posts",
            logs,
            "인기글 순위는 조회수에 따라 달라지므로, 조회수가 바뀌면 기존 캐시를 무효화합니다.",
        )

        self.send_json(
            {
                "ok": True,
                "post": {**post, "views": new_views},
                "posts": build_posts(),
                "redis_logs": logs,
                "message": "게시글을 열었습니다. 조회수가 증가했고 인기글 캐시는 무효화되었습니다.",
            }
        )

    def handle_reset_demo(self):
        logs = []
        bootstrap_demo_state(logs=logs)
        self.send_json(
            {
                "ok": True,
                "posts": build_posts(),
                "session": current_session_payload(""),
                "redis_logs": logs,
                "message": "게시판, 조회수, 세션, 캐시를 모두 초기 상태로 되돌렸습니다.",
            }
        )


def main():
    bootstrap_demo_state()
    print("미니 Redis 게시판 데모 서버를 시작합니다.")
    print(f"브라우저에서 http://{HOST}:{PORT} 를 열어주세요.")
    print("F12로 개발자 도구를 열고, 콘솔에서 Redis 동작 설명을 함께 확인해보세요.")
    server = ThreadingHTTPServer((HOST, PORT), DemoHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n데모 서버를 종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

# 웹 기능별 API/Redis 동작 흐름

이 문서는 웹페이지에서 버튼이나 기능을 사용할 때,
브라우저 -> FastAPI -> 서비스 레이어 -> Mini Redis/DB 파일 순서로
무슨 일이 일어나는지 정리한 문서입니다.

## 1. 페이지 처음 접속

1. 브라우저가 `/` 요청을 보냅니다.
2. `app/main.py`의 `read_index()`가 `index.html`을 반환합니다.
3. 브라우저는 이어서 `/static/style.css`, `/static/app.js`도 불러옵니다.
4. `app.js`의 `bootstrap()`이 실행됩니다.
5. `bootstrap()`은 아래 순서로 API를 호출합니다.
   - `GET /health`
   - `POST /session/check` 또는 로그아웃 상태 표시
   - `GET /posts`
   - `GET /top-posts`

## 2. 로그인 버튼 클릭

1. 브라우저에서 `POST /login` 요청을 보냅니다.
2. `app/api/routes.py`의 `login_route()`가 요청을 받습니다.
3. `app/services/board_service.py`의 `login()`이 실행됩니다.
4. `login()`은:
   - 사용자 이름을 정리합니다.
   - 랜덤 토큰을 만듭니다.
   - `session:{token}` 형태의 Redis key를 만듭니다.
   - `setex()`로 세션을 저장합니다.
5. 저장된 세션은 `redis_engine/commands.py` -> `redis_engine/storage.py`를 거쳐
   메모리에 저장되고, `redis_engine/persistence.py`가 파일에도 저장합니다.
6. 브라우저는 받은 토큰을 `localStorage`에 저장하고 로그인 상태를 화면에 표시합니다.

## 3. 새로고침 후 로그인 복구

1. `app.js`가 `localStorage`에서 토큰을 읽습니다.
2. 브라우저가 `POST /session/check`를 호출합니다.
3. `routes.py`의 `session_check_route()`가 받습니다.
4. `board_service.py`의 `check_session()`이 실행됩니다.
5. `check_session()`은 `session:{token}` key를 Redis에서 읽습니다.
6. 세션이 있으면 `authenticated: true`, 없으면 `false`를 반환합니다.
7. 브라우저는 결과에 따라 로그인 상태를 복구하거나 로그아웃 상태로 바꿉니다.

## 4. 게시글 목록 불러오기

1. 브라우저가 `GET /posts`를 호출합니다.
2. `routes.py`의 `read_posts()`가 받습니다.
3. `board_service.py`의 `list_posts()`가 실행됩니다.
4. `list_posts()`는 `posts.json`의 각 게시글에 대해 `_get_cached_or_db_post()`를 호출합니다.
5. `_get_cached_or_db_post()`의 흐름:
   - 먼저 `post:{id}` 캐시를 찾습니다.
   - 있으면 cache 출처로 반환합니다.
   - 없으면 `posts.json`에서 읽고 Redis에 저장한 뒤 db 출처로 반환합니다.
6. 최종적으로 브라우저는 게시글 목록과 `cache/db` 통계를 함께 받습니다.

## 5. 게시글 열기

1. 브라우저가 `POST /posts/{id}/view`를 호출합니다.
2. `routes.py`의 `view_post_route()`가 받습니다.
3. `board_service.py`의 `view_post()`가 실행됩니다.
4. `view_post()`는:
   - 먼저 `posts.json`에서 해당 글이 있는지 확인합니다.
   - `views:post:{id}` key를 `incr()`로 1 증가시킵니다.
   - `cache:top_posts` 키를 삭제해서 인기글 캐시를 무효화합니다.
   - 게시글 본문은 `_get_cached_or_db_post()`로 다시 가져옵니다.
5. 브라우저는 응답을 받은 뒤 다시:
   - `GET /posts`
   - `GET /top-posts`
   를 호출해 화면을 최신 상태로 갱신합니다.

## 6. 인기글 불러오기

1. 브라우저가 `GET /top-posts`를 호출합니다.
2. `routes.py`의 `read_top_posts()`가 받습니다.
3. `board_service.py`의 `get_top_posts()`가 실행됩니다.
4. `get_top_posts()` 흐름:
   - 먼저 `cache:top_posts`를 확인합니다.
   - 있으면 그대로 반환합니다.
   - 없으면 `list_posts()` 결과를 조회수 기준으로 정렬합니다.
   - 상위 3개를 다시 Redis에 `setex()`로 저장합니다.
5. 브라우저는 응답의 `source` 값을 보고
   "Redis 캐시에서 가져왔는지" 또는 "다시 계산했는지"를 화면에 보여줍니다.

## 7. 게시글 수정

1. 사용자가 수정 모달에서 저장 버튼을 누릅니다.
2. 브라우저가 `PUT /posts/{id}` 요청을 보냅니다.
3. `routes.py`의 `update_post_route()`가 받습니다.
4. `board_service.py`의 `update_post()`가 실행됩니다.
5. `update_post()`는:
   - `posts.json`에서 해당 글을 찾아 수정합니다.
   - 수정된 내용을 파일에 다시 저장합니다.
   - `post:{id}` 캐시를 삭제합니다.
   - `cache:top_posts` 캐시도 삭제합니다.
6. 브라우저는 수정 후 다시 목록과 인기글을 불러와 최신 상태를 반영합니다.

## 8. 새 글 작성

1. 사용자가 글쓰기 모달에서 저장 버튼을 누릅니다.
2. 브라우저가 `POST /posts` 요청을 보냅니다.
3. `routes.py`의 `create_post_route()`가 받습니다.
4. `board_service.py`의 `create_post()`가 실행됩니다.
5. `create_post()`는:
   - 현재 가장 큰 id를 찾습니다.
   - 새 게시글 객체를 만듭니다.
   - `posts.json`에 저장합니다.
   - `cache:top_posts`를 삭제합니다.
   - 혹시 있을지 모를 새 글 본문 캐시도 정리합니다.
6. 브라우저는 새 글 작성 후 다시 목록과 인기글을 불러옵니다.

## 9. 로그아웃

1. 브라우저가 `POST /logout`을 호출합니다.
2. `routes.py`의 `logout_route()`가 받습니다.
3. `board_service.py`의 `logout()`이 실행됩니다.
4. `logout()`은 `session:{token}` 키를 Redis에서 삭제합니다.
5. 브라우저도 `localStorage`에서 토큰을 지웁니다.
6. 화면은 로그아웃 상태로 바뀝니다.

## 10. Mini Redis 내부 레이어 정리

Mini Redis는 안에서 이렇게 역할이 나뉩니다.

- `redis_engine/mini_redis.py`
  - 바깥에서 쓰는 진입점
  - `get`, `set`, `delete`, `exists`, `incr`, `setex` 제공

- `redis_engine/commands.py`
  - 명령 규칙 처리
  - key 문자열 통일
  - value가 JSON 저장 가능한지 검사

- `redis_engine/storage.py`
  - 실제 메모리 저장소
  - `store`, `expire_at`, `lock`
  - TTL 검사와 삭제

- `redis_engine/persistence.py`
  - 파일 저장/복구
  - 메모리 상태를 JSON 파일로 저장
  - 서버 시작 시 다시 읽어오기

## 한 줄 요약

- 게시글 본문은 `post:{id}` 캐시로 관리됩니다.
- 조회수는 `views:post:{id}`로 따로 관리됩니다.
- 인기글은 `cache:top_posts`로 캐시됩니다.
- 로그인은 `session:{token}`으로 저장됩니다.
- DB 역할은 현재 `data/posts.json` 파일이 대신합니다.

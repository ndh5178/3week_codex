import time


class MiniRedis:
    def __init__(self):
        self.store = {}
        self.expire_at = {}

    def _delete_if_expired(self, key):
        expires = self.expire_at.get(key)
        if expires is not None and time.time() >= expires:
            self.store.pop(key, None)
            self.expire_at.pop(key, None)

    def set(self, key, value):
        self.store[key] = str(value)
        self.expire_at.pop(key, None)
        return "OK"

    def get(self, key):
        self._delete_if_expired(key)
        return self.store.get(key)

    def setex(self, key, seconds, value):
        self.store[key] = str(value)
        self.expire_at[key] = time.time() + seconds
        return "OK"

    def incr(self, key):
        self._delete_if_expired(key)
        current = int(self.store.get(key, "0"))
        current += 1
        self.store[key] = str(current)
        return current

    def exists(self, key):
        self._delete_if_expired(key)
        return 1 if key in self.store else 0

    def delete(self, key):
        self._delete_if_expired(key)
        existed = key in self.store
        self.store.pop(key, None)
        self.expire_at.pop(key, None)
        return 1 if existed else 0


FAKE_DB = {
    "product:1": "Cola, price=2000, stock=12",
}


def print_section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def print_command(command, result):
    print(f"> {command}")
    print(result if result is not None else "(nil)")


def load_product_from_db(product_id):
    print("DB 조회 중... 1초 정도 걸린다고 가정합니다.")
    time.sleep(1)
    return FAKE_DB.get(product_id)


def demo_intro():
    print_section("1. Redis는 무엇인가요?")
    print("Redis는 메모리에 데이터를 저장하는 아주 빠른 Key-Value 저장소입니다.")
    print("쉽게 말하면 서버가 쓰는 초고속 딕셔너리라고 생각하면 됩니다.")
    print("자주 쓰는 곳: 캐시, 로그인 세션, 인증번호, 조회수 카운터")


def demo_cache(redis):
    print_section("2. 기능 1 - SET/GET으로 캐시 흉내 내기")
    print("상황: 상품 정보를 처음엔 DB에서 가져오고, 다음부터는 Redis에서 바로 꺼냅니다.")

    product_id = "product:1"

    start = time.perf_counter()
    cached = redis.get(product_id)
    first_check = time.perf_counter() - start
    print_command(f"GET {product_id}", cached)
    print(f"첫 조회 시 캐시에 없어서 확인 시간: {first_check:.6f}초")

    if cached is None:
        value = load_product_from_db(product_id)
        print_command(f'SET {product_id} "{value}"', redis.set(product_id, value))

    start = time.perf_counter()
    cached = redis.get(product_id)
    second_check = time.perf_counter() - start
    print_command(f"GET {product_id}", cached)
    print(f"두 번째 조회는 Redis에서 바로 꺼내서 확인 시간: {second_check:.6f}초")

    print("\n핵심 포인트:")
    print("- DB는 상대적으로 느리고, Redis는 메모리에 있어서 빠릅니다.")
    print("- 그래서 자주 보는 데이터를 Redis에 넣어두면 서비스가 빨라집니다.")


def demo_counter(redis):
    print_section("3. 기능 2 - INCR로 조회수 카운터 만들기")
    print("상황: 게시글이나 영상이 열릴 때마다 조회수를 1씩 올립니다.")

    key = "views:post:100"
    print_command(f"SET {key} 100", redis.set(key, 100))
    print_command(f"INCR {key}", redis.incr(key))
    print_command(f"INCR {key}", redis.incr(key))
    print_command(f"GET {key}", redis.get(key))

    print("\n핵심 포인트:")
    print("- 조회수, 좋아요, 방문자 수처럼 숫자가 계속 올라가는 데이터에 잘 맞습니다.")
    print("- 실제 서비스에서 Redis가 자주 쓰이는 대표적인 이유 중 하나입니다.")


def demo_session(redis):
    print_section("4. 기능 3 - EXISTS와 DEL로 로그인 세션 보기")
    print("상황: 로그인에 성공하면 세션을 저장하고, 로그아웃하면 세션을 지웁니다.")

    session_key = "session:abc123"
    print_command(f"SET {session_key} user1", redis.set(session_key, "user1"))
    print_command(f"EXISTS {session_key}", redis.exists(session_key))
    print_command(f"GET {session_key}", redis.get(session_key))
    print_command(f"DEL {session_key}", redis.delete(session_key))
    print_command(f"EXISTS {session_key}", redis.exists(session_key))

    print("\n핵심 포인트:")
    print("- 서버는 세션 키를 보고 이 사용자가 로그인 상태인지 빠르게 확인할 수 있습니다.")
    print("- 로그아웃할 때는 DEL 한 번으로 상태를 바로 지울 수 있습니다.")


def demo_ttl(redis):
    print_section("5. 기능 4 - SETEX로 자동 만료 데이터 만들기")
    print("상황: 문자 인증번호는 잠깐만 유효해야 하므로 시간이 지나면 자동 삭제되어야 합니다.")

    key = "auth:user1"
    code = "482913"

    print_command(f"SETEX {key} 3 {code}", redis.setex(key, 3, code))
    print_command(f"GET {key}", redis.get(key))

    print("\n3초 동안만 유효하도록 저장했습니다. 4초 기다려보겠습니다...")
    time.sleep(4)

    print_command(f"GET {key}", redis.get(key))

    print("\n핵심 포인트:")
    print("- 인증번호, 로그인 만료 정보처럼 잠깐만 살아야 하는 데이터에 잘 맞습니다.")
    print("- 시간이 지나면 자동 삭제되므로 따로 정리하지 않아도 됩니다.")


def main():
    redis = MiniRedis()
    demo_intro()
    demo_cache(redis)
    demo_counter(redis)
    demo_session(redis)
    demo_ttl(redis)

    print_section("6. 한 줄 정리")
    print("이 데모의 미니 Redis는 빠르게 저장하고, 필요하면 자동으로 지우는 메모리 저장소입니다.")
    print("실제 Redis도 이 아이디어를 훨씬 더 빠르고 안정적으로 제공한다고 생각하면 됩니다.")


if __name__ == "__main__":
    main()

"""Mini Redis 명령 처리 레이어.

이 파일은 실제 Redis 명령처럼 보이는 동작을 함수 단위로 분리할 자리다.

여기에 들어갈 대표 기능:
- SET / GET
- DEL / EXISTS
- INCR
- SETEX

즉, storage가 "데이터를 들고 있는 장소"라면
commands는 "그 데이터를 어떻게 조작할지"를 담당한다.
"""

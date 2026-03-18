# Mini Redis Board

## 1. Mini Redis와 게시판 웹

우리 팀은 게시글 원본 데이터는 MongoDB에 저장하고, 세션·조회수·게시글 캐시·인기글 캐시는 Mini Redis에 저장하는 게시판 웹 서비스를 구현했다.  
영속성이 필요한 데이터와 빠른 재사용이 필요한 데이터를 분리해서, DB와 캐시가 각각 어떤 역할을 맡아야 하는지 한 프로젝트 안에서 드러나도록 구성했다.

Mini Redis는 단순한 내부 자료구조로 두지 않고, 별도 API 서버로 분리된 key-value 저장소 형태로 만들었다.  
게시판 서비스는 이 저장소를 HTTP로 호출하도록 연결했고, 이를 통해 외부 재사용이 가능한 구조와 캐시 시스템의 기본 동작을 함께 확인할 수 있도록 했다.

## 2. 시스템 아키텍처

```mermaid
flowchart LR
    U["Browser / Client"] --> B["Board API Server"]
    B --> M["MongoDB<br/>게시글 원본 저장"]
    B --> R["Mini Redis API Server"]
    R --> S["MemoryStore<br/>hash table + expire_at"]
    R --> J["JSON dump<br/>재시작 복구"]
```

- Board API: 게시글 CRUD, 세션 처리, 캐시 활용 로직을 담당하도록 구성했다.
- MongoDB: 게시글 본문과 같은 영속 데이터를 저장하도록 사용했다.
- Mini Redis: 캐시, 세션, 조회수 카운터를 메모리 기반으로 처리하도록 분리했다.
- JSON dump: Mini Redis 상태를 파일로 저장하고 재시작 시 복구할 수 있게 연결했다.

## 3. 주요 쟁점

### 3-1. 해시테이블 구조로 Mini Redis 접근 시간 줄임

Mini Redis의 메모리 저장소는 Python `dict` 기반 해시테이블로 구현했다.  
이 구조를 선택해서 key 기준 탐색을 평균적으로 `O(1)`에 가깝게 가져가려 했고, 실제로 세션 확인이나 게시글 캐시 조회처럼 반복되는 접근을 단순한 구조로 빠르게 처리할 수 있게 만들었다.

### 3-2. 동시성 문제를 방지하기 위해 고려한 점

Mini Redis 내부의 `store`와 `expire_at`은 `RLock`으로 보호해 동시에 여러 요청이 들어와도 메모리 상태가 깨지지 않도록 처리했다.  
이 프로젝트의 동시성 대응은 주로 Mini Redis의 메모리 저장소를 안전하게 다루는 데 초점을 맞췄다.

### 3-3. 보관 기간이 만료된 값을 요청받았을 때 이를 처리하기 위한 방안

TTL이 있는 값은 만료 시간을 함께 저장하고, 값을 읽거나 확인할 때 먼저 만료 여부를 검사하도록 구현했다.  
이미 만료된 값은 즉시 제거하고 없는 값처럼 응답하는 lazy expiration 방식을 적용해서, 별도의 주기 작업 없이도 실제 요청 흐름 안에서 만료 상태가 반영되도록 처리했다.

### 3-4. 외부에서도 Mini Redis를 쉽게 사용할 수 있도록 API 형태 구조 설계

Mini Redis는 별도 FastAPI 서버로 분리했고, Board API는 이를 HTTP로 호출하도록 연결했다.  
이 구조를 통해 게시판 내부 캐시로만 끝나지 않고, 다른 서비스나 외부 클라이언트도 같은 방식으로 Mini Redis를 사용할 수 있는 형태를 만들었다.

### 3-5. Redis 서버가 다운되는 상황에서도 보관 중인 데이터를 안전하게 유지하기 위한 방식

Mini Redis는 메모리 기반이지만 현재 상태를 JSON dump 파일로 저장하고, 서버 시작 시 이를 다시 읽어 복구하도록 구현했다.  
완전한 운영 환경용 지속성 전략까지는 아니지만, 학습 및 데모 환경에서는 세션·캐시·카운터 데이터를 최대한 유지하기 위한 단순하고 현실적인 복구 방식으로 정리했다.

## 4. 품질

- `unittest` 기반 자동 테스트 9개를 추가했고 모두 통과했다.
- 테스트는 외부 MongoDB나 원격 Redis에 직접 의존하지 않도록 레이어를 나눠 진행했다.
- `MemoryStore`는 시간 함수를 제어하는 방식으로 TTL, lazy expiration, TTL 제거, `incr` 예외 처리를 검증했다.
- `Mini Redis persistence`는 임시 JSON dump 파일을 사용하는 방식으로 저장과 재시작 복구를 검증했다.
- `board_service`는 가짜 게시글 저장소와 in-memory Mini Redis를 주입하는 방식으로 cache miss -> DB read -> cache write, cache hit, 캐시 무효화, 세션 흐름, 조회수 증가를 검증했다.
- 성능 비교는 별도 스크립트와 엔드포인트를 통해 DB read와 cache hit의 평균 시간을 비교하고, MongoDB 방식의 조회수 증가와 Redis `INCR` 방식의 차이도 함께 확인할 수 있도록 구성했다.

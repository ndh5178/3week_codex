const SESSION_TOKEN_KEY = "mini-redis-session-token";
const noopButton = { addEventListener() {} };
const noopTextNode = { textContent: "" };

const userStatus = document.getElementById("user-status");
const userMeta = document.getElementById("user-meta");
const debugLog = document.getElementById("debug-log");
const postDetail = document.getElementById("post-detail");
const cacheStatus = document.getElementById("cache-status");
const topViewsMetric = document.getElementById("metric-top-views");
const topTitleMetric = document.getElementById("metric-top-title");
const serverMetric = document.getElementById("metric-server-status");
const postCountMetric = document.getElementById("metric-post-count");
const dbLatencyMetric = document.getElementById("metric-db-latency");
const cacheLatencyMetric = document.getElementById("metric-cache-latency");
const cacheTtlMetric = document.getElementById("metric-cache-ttl");
const speedupMetric = document.getElementById("metric-speedup");
const dataStoreMetric = document.getElementById("metric-data-store");
const cacheStoreMetric = document.getElementById("metric-cache-store");

const speedStatus = document.getElementById("speed-status") || noopTextNode;
const speedMeta = document.getElementById("speed-meta") || noopTextNode;
const speedDbMs = document.getElementById("speed-db-ms") || noopTextNode;
const speedCacheMs = document.getElementById("speed-cache-ms") || noopTextNode;

const loginButton = document.getElementById("login-button");
const logoutButton = document.getElementById("logout-button");
const refreshPostsButton = document.getElementById("refresh-posts-button");
const createPostButton = document.getElementById("create-post-button");
const openCreateModalButton = document.getElementById("open-create-modal-button");
const openEditModalButton = document.getElementById("open-edit-modal-button");
const generateDemoPostsButton = document.getElementById("generate-demo-posts-button") || noopButton;
const randomizeViewsButton = document.getElementById("randomize-views-button") || noopButton;
const resetDbButton = document.getElementById("reset-db-button") || noopButton;
const measureSpeedButton = document.getElementById("measure-speed-button") || noopButton;
const usernameInput = document.getElementById("username-input");
const postsList = document.getElementById("posts-list");
const topPostsList = document.getElementById("top-posts-list");

const modalOverlay = document.getElementById("modal-overlay");
const modalTitle = document.getElementById("modal-title");
const modalKicker = document.getElementById("modal-kicker");
const modalForm = document.getElementById("post-modal-form");
const modalTitleInput = document.getElementById("modal-title-input");
const modalContentInput = document.getElementById("modal-content-input");
const modalAuthorInput = document.getElementById("modal-author-input");
const modalSubmitButton = document.getElementById("modal-submit-button");
const closeModalButton = document.getElementById("close-modal-button");
const modalCancelButton = document.getElementById("modal-cancel-button");
const runBenchmarkButton = document.getElementById("run-benchmark-button");
const clearPostCacheButton = document.getElementById("clear-post-cache-button");
const benchmarkStatus = document.getElementById("benchmark-status");
const benchmarkMeta = document.getElementById("benchmark-meta");
const storageSummary = document.getElementById("storage-summary");
const storageMeta = document.getElementById("storage-meta");
const benchmarkIterationsInput = document.getElementById("benchmark-iterations-input");

let currentPostId = null;
let currentPosts = [];
let currentTopPosts = [];
let currentSessionToken = "";
let currentPostDetail = null;
let currentLiveAccess = null;
let currentCacheInfo = null;
let lastDbReadMsByPostId = {};
let modalMode = "create";
let selectedPostCachePollId = null;

function addDebugMessage(message) {
  const item = document.createElement("li");
  item.textContent = message;
  debugLog.prepend(item);
}

function formatMilliseconds(value) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return "--";
  }
  return `${numericValue.toFixed(3)} ms`;
}

function formatSpeedup(value) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return "--";
  }
  return `${numericValue.toFixed(2)}x`;
}

function toFiniteNumberOrNull(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return null;
  }

  return numericValue;
}

function formatTtl(value) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return "--";
  }
  return `${Math.max(0, Math.round(numericValue))}s`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const rawText = await response.text();
  const data = rawText ? JSON.parse(rawText) : {};

  if (!response.ok) {
    throw new Error(data.detail || "요청에 실패했습니다.");
  }

  return data;
}

function saveSessionToken(token) {
  currentSessionToken = token;

  if (token) {
    localStorage.setItem(SESSION_TOKEN_KEY, token);
    return;
  }

  localStorage.removeItem(SESSION_TOKEN_KEY);
}

function loadSavedSessionToken() {
  return localStorage.getItem(SESSION_TOKEN_KEY) || "";
}

function updateAuthButtons(isLoggedIn) {
  loginButton.classList.toggle("hidden", isLoggedIn);
  logoutButton.classList.toggle("hidden", !isLoggedIn);
}

function renderLoggedOutState(message = "로그인하면 사용자 이름과 세션 상태가 여기에 표시됩니다.") {
  userStatus.textContent = "로그아웃 상태";
  userMeta.textContent = message;
  updateAuthButtons(false);
}

function renderLoggedInState(username, token, sessionKey = "") {
  const shortToken = token.slice(0, 8);
  userStatus.textContent = `${username} 로그인 상태`;
  userMeta.textContent = `토큰 ${shortToken}... / Redis 키 ${sessionKey || `session:${token}`}`;
  updateAuthButtons(true);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function findPostById(postId) {
  return currentPosts.find((post) => Number(post.id) === Number(postId)) || null;
}

function updateSelectedCacheStatusUi() {
  const cacheInfo = currentCacheInfo;
  const cacheLiveNode = document.getElementById("selected-post-cache-live");

  if (!cacheInfo || !cacheInfo.exists) {
    cacheTtlMetric.textContent = "--";
    if (cacheLiveNode) {
      cacheLiveNode.textContent = "현재 선택한 게시글 캐시는 비어 있습니다.";
    }
    return;
  }

  const ttlText = formatTtl(cacheInfo.ttl_seconds);
  cacheTtlMetric.textContent = ttlText;
  if (cacheLiveNode) {
    cacheLiveNode.textContent = `캐시 키 ${cacheInfo.cache_key} / 남은 TTL ${ttlText}`;
  }
}

function renderLiveAccessSummary(liveAccess, cacheInfo = currentCacheInfo) {
  currentLiveAccess = liveAccess;
  currentCacheInfo = cacheInfo;
  updateSelectedCacheStatusUi();

  if (!liveAccess) {
    benchmarkStatus.textContent = "게시글을 클릭하면 실시간 읽기 결과가 여기에 표시됩니다.";
    benchmarkMeta.textContent = "첫 클릭은 DB READ, 캐시가 있으면 CACHE READ와 SPEEDUP이 같이 표시됩니다.";
    dbLatencyMetric.textContent = "--";
    cacheLatencyMetric.textContent = "--";
    speedupMetric.textContent = "--";
    return;
  }

  const baselineDbReadMs =
    toFiniteNumberOrNull(liveAccess.db_read_ms) !== null
      ? toFiniteNumberOrNull(liveAccess.db_read_ms)
      : currentPostId !== null
        ? lastDbReadMsByPostId[currentPostId]
        : null;

  if (currentPostId !== null && toFiniteNumberOrNull(liveAccess.db_read_ms) !== null) {
    lastDbReadMsByPostId[currentPostId] = toFiniteNumberOrNull(liveAccess.db_read_ms);
  }

  const computedSpeedup =
    toFiniteNumberOrNull(baselineDbReadMs) !== null && toFiniteNumberOrNull(liveAccess.cache_read_ms) !== null
      ? Number(baselineDbReadMs) / Number(liveAccess.cache_read_ms)
      : null;

  dbLatencyMetric.textContent = formatMilliseconds(baselineDbReadMs);
  cacheLatencyMetric.textContent = formatMilliseconds(liveAccess.cache_read_ms);
  speedupMetric.textContent = formatSpeedup(computedSpeedup);

  if (liveAccess.source === "db") {
    benchmarkStatus.textContent = `DB READ ${formatMilliseconds(liveAccess.db_read_ms)}`;
    benchmarkMeta.textContent = "캐시가 없어서 DB에서 읽었고, 방금 Redis 캐시를 새로 만들었습니다.";
    return;
  }

  benchmarkStatus.textContent =
    `CACHE READ ${formatMilliseconds(liveAccess.cache_read_ms)} / DB READ ${formatMilliseconds(baselineDbReadMs)}`;
  benchmarkMeta.textContent =
    Number.isFinite(Number(computedSpeedup))
      ? `캐시 hit 입니다. 현재 속도 차이는 ${formatSpeedup(computedSpeedup)} 입니다.`
      : "캐시 hit 입니다. DB 기준값은 직전 miss에서 측정한 값을 사용합니다.";
}

function renderTopPosts(posts, source = "db", rankingRule = "") {
  if (posts.length === 0) {
    topPostsList.innerHTML = `
      <article class="leaderboard-card first-place">
        <div class="leaderboard-copy">
          <h4>아직 인기글이 없습니다.</h4>
          <p>게시글을 먼저 준비한 뒤 다시 확인해 주세요.</p>
        </div>
      </article>
    `;
  } else {
    topPostsList.innerHTML = posts.map((post, index) => `
      <article class="leaderboard-card ${index === 0 ? "first-place" : ""}">
        <div class="rank-pill">${String(index + 1).padStart(2, "0")}</div>
        <div class="leaderboard-copy">
          <h4>${escapeHtml(post.title)}</h4>
          <p>${escapeHtml(post.content)}</p>
        </div>
        <div class="leaderboard-meta">
          <span>조회수 ${escapeHtml(post.views ?? 0)}</span>
          <span>작성자 ${escapeHtml(post.author ?? "익명")}</span>
        </div>
      </article>
    `).join("");
  }

  cacheStatus.textContent = source === "cache"
    ? "인기글을 Redis 캐시에서 바로 가져왔습니다."
    : `인기글을 다시 계산해서 가져왔습니다.${rankingRule ? ` (${rankingRule})` : ""}`;
}

function renderPosts(posts) {
  if (posts.length === 0) {
    postsList.innerHTML = `
      <article class="post-row">
        <div class="post-row-copy">
          <h4>게시글이 없습니다.</h4>
          <p>새 글 작성이나 데모 데이터 생성을 먼저 진행해 주세요.</p>
        </div>
      </article>
    `;
    return;
  }

  postsList.innerHTML = posts.map((post) => `
    <article class="post-row" data-post-id="${post.id}">
      <div class="post-row-copy">
        <h4>${escapeHtml(post.title)}</h4>
        <p>${escapeHtml(post.content)}</p>
      </div>
      <div class="post-row-side">
        <span>작성자 ${escapeHtml(post.author)} / 조회수 ${escapeHtml(post.views ?? 0)} / 출처 ${escapeHtml(post.source)}</span>
        <button class="primary-button view-post-button" type="button" data-post-id="${post.id}">게시글 보기</button>
      </div>
    </article>
  `).join("");

  document.querySelectorAll(".view-post-button").forEach((button) => {
    button.addEventListener("click", () => {
      openPost(Number(button.dataset.postId)).catch(showError);
    });
  });
}

function updateMetrics(posts) {
  const topPost = posts.reduce((currentBest, post) => {
    if (!currentBest) {
      return post;
    }
    return Number(post.views ?? 0) > Number(currentBest.views ?? 0) ? post : currentBest;
  }, null);

  topViewsMetric.textContent = String(Number(topPost?.views ?? 0)).padStart(2, "0");
  topTitleMetric.textContent = topPost
    ? `${topPost.title} / 작성자 ${topPost.author}`
    : "아직 게시글이 없습니다.";
  postCountMetric.textContent = String(posts.length).padStart(2, "0");
}

function renderPostDetail(post) {
  currentPostDetail = post;
  openEditModalButton.disabled = false;

  const liveAccess = post.live_access || currentLiveAccess;
  const cacheInfo = post.cache || currentCacheInfo;
  const liveLabel = !liveAccess
    ? "READY"
    : liveAccess.source === "cache"
      ? "CACHE READ"
      : "DB READ";
  const cacheStateLabel = cacheInfo?.exists
    ? `cache hit 가능 / TTL ${formatTtl(cacheInfo.ttl_seconds)}`
    : "cache miss 상태";

  postDetail.innerHTML = `
    <h4>${escapeHtml(post.title)}</h4>
    <p>${escapeHtml(post.content)}</p>
    <div class="detail-meta">
      <span>작성자 ${escapeHtml(post.author)}</span>
      <span>조회수 ${escapeHtml(post.views ?? 0)}</span>
      <span>출처 ${escapeHtml(post.source || "unknown")}</span>
      <span>게시글 ID ${escapeHtml(post.id)}</span>
    </div>
    <div class="detail-live-status">
      <strong>${liveLabel}</strong>
      <span id="selected-post-cache-live">${escapeHtml(cacheStateLabel)}</span>
    </div>
    <div class="detail-toolbar">
      <button class="ghost-button inline-edit-button" type="button">선택 글 수정하기</button>
      <button class="ghost-button inline-delete-button" type="button">선택 글 삭제하기</button>
    </div>
  `;

  const inlineEditButton = postDetail.querySelector(".inline-edit-button");
  const inlineDeleteButton = postDetail.querySelector(".inline-delete-button");
  inlineEditButton.addEventListener("click", openEditModal);
  inlineDeleteButton.addEventListener("click", () => {
    deleteCurrentPost().catch(showError);
  });
  updateSelectedCacheStatusUi();
}

function renderBenchmarkSummary(summary) {
  if (!summary) {
    renderLiveAccessSummary(null, null);
    return;
  }

  benchmarkStatus.textContent =
    `MongoDB ${formatMilliseconds(summary.db.average_ms)} / Redis ${formatMilliseconds(summary.cache.average_ms)}`;
  benchmarkMeta.textContent = `평균 속도 차이 ${formatSpeedup(summary.speedup)}`;
  dbLatencyMetric.textContent = formatMilliseconds(summary.db.average_ms);
  cacheLatencyMetric.textContent = formatMilliseconds(summary.cache.average_ms);
  speedupMetric.textContent = formatSpeedup(summary.speedup);
}

function openModal(mode, post = null) {
  modalMode = mode;

  if (mode === "edit" && post) {
    modalKicker.textContent = "Edit Post";
    modalTitle.textContent = "게시글 수정";
    modalSubmitButton.textContent = "수정 저장";
    modalTitleInput.value = post.title ?? "";
    modalContentInput.value = post.content ?? "";
    modalAuthorInput.value = post.author ?? "";
  } else {
    modalKicker.textContent = "Create Post";
    modalTitle.textContent = "새 글 작성";
    modalSubmitButton.textContent = "게시글 저장";
    modalTitleInput.value = "";
    modalContentInput.value = "";
    modalAuthorInput.value = usernameInput.value.trim() || "동현";
  }

  modalOverlay.classList.remove("hidden");
  modalTitleInput.focus();
}

function closeModal() {
  modalOverlay.classList.add("hidden");
}

function openCreateModal() {
  openModal("create");
}

function openEditModal() {
  if (!currentPostDetail) {
    addDebugMessage("수정할 게시글이 아직 선택되지 않았습니다.");
    return;
  }

  openModal("edit", currentPostDetail);
}

function stopSelectedPostCachePolling() {
  if (selectedPostCachePollId !== null) {
    window.clearInterval(selectedPostCachePollId);
    selectedPostCachePollId = null;
  }
}

function startSelectedPostCachePolling() {
  stopSelectedPostCachePolling();

  if (currentPostId === null) {
    return;
  }

  selectedPostCachePollId = window.setInterval(async () => {
    if (currentPostId === null) {
      return;
    }

    try {
      const cacheInfo = await requestJson(`/posts/${currentPostId}/cache/status`);
      currentCacheInfo = cacheInfo;
      updateSelectedCacheStatusUi();

      if (!cacheInfo.exists) {
        cacheTtlMetric.textContent = "expired";
      }
    } catch (error) {
      stopSelectedPostCachePolling();
      showError(error);
    }
  }, 1000);
}

async function checkHealth() {
  const data = await requestJson("/health");
  serverMetric.textContent = String(data.status).toUpperCase();
  addDebugMessage("GET /health 호출 완료: 서버가 정상 동작 중입니다.");
}

async function fetchStorageSummary() {
  const data = await requestJson("/storage");
  const postsLabel = data.posts?.label || "Persistent store";
  const cacheLabel = data.cache?.label || "Cache";
  const postsBackend = String(data.posts?.backend || "unknown").toUpperCase();
  const postsPath = data.posts?.path
    ? `원본 데이터 위치: ${data.posts.path}`
    : "원본 데이터 위치: 외부 서버";
  const cachePersistence = data.cache?.persistence_enabled
    ? `캐시 스냅샷: ${data.cache.persistence_path}`
    : "캐시 스냅샷: 비활성화";

  dataStoreMetric.textContent = postsBackend;
  cacheStoreMetric.textContent = `${postsLabel} / ${cacheLabel}`;
  storageSummary.textContent = `${postsLabel}가 원본 게시글을 저장하고, ${cacheLabel}가 빠른 캐시 역할을 합니다.`;
  storageMeta.textContent = `${postsPath} / ${cachePersistence}`;
  addDebugMessage(`GET /storage 호출 완료: ${postsLabel}를 원본 저장소로, ${cacheLabel}를 캐시 저장소로 사용합니다.`);

  return data;
}

async function fetchPosts() {
  const data = await requestJson("/posts");
  currentPosts = Array.isArray(data.posts) ? data.posts : [];
  renderPosts(currentPosts);
  updateMetrics(currentPosts);

  if (currentPostId !== null) {
    const refreshedPost = findPostById(currentPostId);
    if (refreshedPost) {
      renderPostDetail({
        ...refreshedPost,
        live_access: currentLiveAccess,
        cache: currentCacheInfo,
      });
    }
  }

  addDebugMessage(`GET /posts 호출 완료: cache ${data.sources?.cache ?? 0}개, db ${data.sources?.db ?? 0}개 게시글을 확인했습니다.`);
  return data;
}

async function fetchTopPosts() {
  const data = await requestJson("/top-posts");
  currentTopPosts = Array.isArray(data.posts) ? data.posts : [];
  renderTopPosts(currentTopPosts, data.source, data.ranking_rule || "");
  addDebugMessage(`GET /top-posts 호출 완료: ${data.source} 방식으로 상위 ${currentTopPosts.length}개를 불러왔습니다.`);
  return data;
}

async function refreshBoard() {
  await Promise.all([fetchPosts(), fetchTopPosts()]);
}

async function openPost(postId) {
  const post = await requestJson(`/posts/${postId}/view`, {
    method: "POST",
  });

  currentPostId = postId;
  currentLiveAccess = post.live_access || null;
  currentCacheInfo = post.cache || null;
  renderPostDetail(post);
  renderLiveAccessSummary(currentLiveAccess, currentCacheInfo);
  startSelectedPostCachePolling();

  addDebugMessage(
    `POST /posts/${postId}/view 호출 완료: ${post.live_access?.source === "cache" ? "CACHE READ" : "DB READ"} / 조회수 ${post.views}`,
  );
  await refreshBoard();
}

async function createPost(payload) {
  const createdPost = await requestJson("/posts", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  currentPostId = createdPost.id;
  currentLiveAccess = null;
  currentCacheInfo = null;
  renderPostDetail(createdPost);
  renderLiveAccessSummary(null, null);
  closeModal();
  addDebugMessage("POST /posts 호출 완료: 새 게시글을 만들고 목록을 다시 불러왔습니다.");
  await refreshBoard();
}

async function updatePost(postId, payload) {
  const updatedPost = await requestJson(`/posts/${postId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  currentPostId = updatedPost.id;
  currentLiveAccess = null;
  currentCacheInfo = null;
  renderPostDetail(updatedPost);
  renderLiveAccessSummary(null, null);
  closeModal();
  addDebugMessage(`PUT /posts/${postId} 호출 완료: 게시글을 수정하고 관련 캐시를 비웠습니다.`);
  await refreshBoard();
}

async function deleteCurrentPost() {
  if (!currentPostDetail) {
    addDebugMessage("삭제할 게시글이 아직 선택되지 않았습니다.");
    return;
  }

  const shouldDelete = window.confirm(`"${currentPostDetail.title}" 게시글을 삭제할까요?`);
  if (!shouldDelete) {
    return;
  }

  const deletedPostId = currentPostDetail.id;
  await requestJson(`/posts/${deletedPostId}`, {
    method: "DELETE",
  });

  stopSelectedPostCachePolling();
  currentPostId = null;
  currentPostDetail = null;
  currentLiveAccess = null;
  currentCacheInfo = null;
  lastDbReadMsByPostId = {};
  openEditModalButton.disabled = true;
  renderLiveAccessSummary(null, null);
  postDetail.innerHTML = `
    <h4>게시글이 삭제되었습니다.</h4>
    <p>다른 게시글을 선택하면 내용, 조회수, 캐시 상태가 여기에 표시됩니다.</p>
  `;

  addDebugMessage(`DELETE /posts/${deletedPostId} 호출 완료: 선택 게시글을 삭제했습니다.`);
  await refreshBoard();
}

async function clearSelectedPostCache() {
  if (currentPostId === null) {
    addDebugMessage("캐시를 비울 게시글이 없습니다. 먼저 게시글을 선택해 주세요.");
    return;
  }

  await requestJson(`/posts/${currentPostId}/cache/clear`, {
    method: "POST",
  });

  currentCacheInfo = {
    post_id: currentPostId,
    cache_key: `post:${currentPostId}`,
    exists: false,
    ttl_seconds: null,
    is_persistent: false,
    is_expired: true,
  };
  updateSelectedCacheStatusUi();
  benchmarkStatus.textContent = "선택 게시글 캐시를 비웠습니다.";
  benchmarkMeta.textContent = "이제 다시 클릭하면 DB READ가 먼저 표시됩니다.";
  cacheLatencyMetric.textContent = "--";
  speedupMetric.textContent = "--";
  addDebugMessage(`POST /posts/${currentPostId}/cache/clear 호출 완료: 선택 게시글 캐시를 비웠습니다.`);
}

async function runBenchmark() {
  if (currentPostId === null) {
    addDebugMessage("읽기 속도 비교를 하려면 먼저 게시글 하나를 선택해 주세요.");
    return;
  }

  const iterations = Math.min(100000, Math.max(1, Number(benchmarkIterationsInput.value) || 20));
  benchmarkIterationsInput.value = String(iterations);
  benchmarkStatus.textContent = "측정 중...";
  benchmarkMeta.textContent = `${iterations}회 반복`;

  const summary = await requestJson(`/posts/${currentPostId}/benchmark?iterations=${iterations}`, {
    method: "POST",
  });

  renderBenchmarkSummary(summary);
  addDebugMessage(
    `POST /posts/${currentPostId}/benchmark 호출 완료: MongoDB 평균 ${formatMilliseconds(summary.db.average_ms)}, Redis 평균 ${formatMilliseconds(summary.cache.average_ms)}.`,
  );
}

async function submitModalForm(event) {
  event.preventDefault();

  const payload = {
    title: modalTitleInput.value.trim(),
    content: modalContentInput.value.trim(),
    author: modalAuthorInput.value.trim(),
  };

  if (!payload.title || !payload.content || !payload.author) {
    addDebugMessage("제목, 내용, 작성자는 모두 입력해야 합니다.");
    return;
  }

  if (modalMode === "edit" && currentPostDetail) {
    await updatePost(currentPostDetail.id, payload);
    return;
  }

  await createPost(payload);
}

async function login() {
  const username = usernameInput.value.trim() || "사용자";
  const data = await requestJson("/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ username }),
  });

  saveSessionToken(data.token);
  renderLoggedInState(data.username, data.token, data.session_key);
  addDebugMessage(`POST /login 호출 완료: ${data.session_key} 세션을 Redis에 저장했습니다.`);
}

async function restoreSessionFromServer() {
  const savedToken = loadSavedSessionToken();
  if (!savedToken) {
    renderLoggedOutState();
    addDebugMessage("저장된 세션 토큰이 없어 로그아웃 상태로 시작합니다.");
    return;
  }

  const data = await requestJson("/session/check", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ token: savedToken }),
  });

  if (!data.authenticated) {
    saveSessionToken("");
    renderLoggedOutState("저장된 세션이 만료되어 다시 로그인해야 합니다.");
    addDebugMessage("POST /session/check 호출 완료: 저장된 세션이 만료되어 로그인 상태를 복구하지 못했습니다.");
    return;
  }

  saveSessionToken(savedToken);
  renderLoggedInState(data.username, savedToken, data.session_key);
  addDebugMessage("POST /session/check 호출 완료: 저장된 세션으로 로그인 상태를 복구했습니다.");
}

async function logout() {
  if (!currentSessionToken) {
    renderLoggedOutState("현재 로그아웃 상태입니다.");
    addDebugMessage("로그아웃 버튼 클릭: 저장된 세션 토큰이 없습니다.");
    return;
  }

  const result = await requestJson("/logout", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ token: currentSessionToken }),
  });

  saveSessionToken("");
  renderLoggedOutState();
  addDebugMessage(`POST /logout 호출 완료: ${result.session_key} 삭제 결과는 ${result.deleted} 입니다.`);
}

async function generateDemoPosts() {
  const data = await requestJson("/demo/generate-posts", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ count: 100 }),
  });

  addDebugMessage(`POST /demo/generate-posts 호출 완료: 게시글 ${data.created_count}개를 자동 생성했습니다.`);
  await refreshBoard();
}

async function randomizeViews() {
  const data = await requestJson("/demo/randomize-views", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ max_views: 1000 }),
  });

  addDebugMessage(`POST /demo/randomize-views 호출 완료: ${data.updated_posts}개 게시글에 조회수를 랜덤으로 넣었습니다.`);
  await refreshBoard();
}

async function measureSpeed() {
  speedStatus.textContent = "조회수 증가 속도를 측정하는 중입니다.";
  speedMeta.textContent = "같은 게시글의 조회수를 1 올리는 작업을 MongoDB 방식과 Redis 방식으로 반복 측정하고 있습니다.";

  const data = await requestJson("/demo/speed-test");

  speedStatus.textContent = data.speed_ratio
    ? `MongoDB가 Redis보다 약 ${data.speed_ratio}배 느렸습니다.`
    : "속도 비율을 계산할 수 없습니다.";
  speedMeta.textContent =
    `${data.message} (대상 게시글 ${data.target_post_id}, MongoDB ${data.db_iterations}회, Redis ${data.redis_iterations}회 반복)`;
  speedDbMs.textContent = `${data.db_average_ms.toFixed(3)} ms`;
  speedCacheMs.textContent = `${data.redis_average_ms.toFixed(3)} ms`;

  addDebugMessage(
    `GET /demo/speed-test 호출 완료: 게시글 ${data.target_post_id} 조회수 증가 기준 MongoDB 평균 ${data.db_average_ms}ms, Redis 평균 ${data.redis_average_ms}ms`,
  );
}

async function resetDemoDatabase() {
  const data = await requestJson("/demo/reset-db", {
    method: "POST",
  });

  speedStatus.textContent = "아직 측정하지 않았습니다.";
  speedMeta.textContent = "같은 게시글의 조회수를 1 올리는 작업을 MongoDB 방식과 Redis 방식으로 반복 측정합니다.";
  speedDbMs.textContent = "0.000 ms";
  speedCacheMs.textContent = "0.000 ms";
  currentPostId = null;
  currentPostDetail = null;
  currentLiveAccess = null;
  currentCacheInfo = null;
  lastDbReadMsByPostId = {};
  stopSelectedPostCachePolling();
  renderLiveAccessSummary(null, null);
  openEditModalButton.disabled = true;

  addDebugMessage(`POST /demo/reset-db 호출 완료: ${data.post_count}개 게시글 기준으로 초기화했습니다.`);
  await refreshBoard();

  postDetail.innerHTML = `
    <h4>아직 선택된 게시글이 없습니다.</h4>
    <p>게시글 목록에서 글을 클릭하면 내용, 조회수, 캐시 상태가 여기에 표시됩니다.</p>
  `;
}

function showError(error) {
  addDebugMessage(`오류: ${error.message}`);
}

async function bootstrap() {
  openEditModalButton.disabled = true;
  renderLiveAccessSummary(null, null);
  await checkHealth();
  await fetchStorageSummary();
  await restoreSessionFromServer();
  await refreshBoard();
}

loginButton.addEventListener("click", () => {
  login().catch(showError);
});

logoutButton.addEventListener("click", () => {
  logout().catch(showError);
});

refreshPostsButton.addEventListener("click", () => {
  refreshBoard().catch(showError);
});

runBenchmarkButton.addEventListener("click", () => {
  runBenchmark().catch(showError);
});

clearPostCacheButton.addEventListener("click", () => {
  clearSelectedPostCache().catch(showError);
});

createPostButton.addEventListener("click", openCreateModal);
openCreateModalButton.addEventListener("click", openCreateModal);
openEditModalButton.addEventListener("click", openEditModal);
generateDemoPostsButton.addEventListener("click", () => {
  generateDemoPosts().catch(showError);
});
randomizeViewsButton.addEventListener("click", () => {
  randomizeViews().catch(showError);
});
resetDbButton.addEventListener("click", () => {
  resetDemoDatabase().catch(showError);
});
measureSpeedButton.addEventListener("click", () => {
  measureSpeed().catch(showError);
});
closeModalButton.addEventListener("click", closeModal);
modalCancelButton.addEventListener("click", closeModal);
modalOverlay.addEventListener("click", (event) => {
  if (event.target === modalOverlay) {
    closeModal();
  }
});
modalForm.addEventListener("submit", (event) => {
  submitModalForm(event).catch(showError);
});

bootstrap().catch(showError);

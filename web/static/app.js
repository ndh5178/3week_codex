/*
  FastAPI board frontend wired to the API routes in this project.
  The latency cards reflect direct storage access times:
  - first click after cache clear -> DB only
  - later cache hit -> CACHE only
  - manual benchmark button -> both sides together
*/

const SESSION_TOKEN_KEY = "mini-redis-session-token";

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
const speedupMetric = document.getElementById("metric-speedup");
const dataStoreMetric = document.getElementById("metric-data-store");
const cacheStoreMetric = document.getElementById("metric-cache-store");

const loginButton = document.getElementById("login-button");
const logoutButton = document.getElementById("logout-button");
const refreshPostsButton = document.getElementById("refresh-posts-button");
const createPostButton = document.getElementById("create-post-button");
const openCreateModalButton = document.getElementById("open-create-modal-button");
const openEditModalButton = document.getElementById("open-edit-modal-button");
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
let modalMode = "create";

let isPostOpenBusy = false;
let busyPostId = null;
let isBenchmarkBusy = false;
let benchmarkRequestSerial = 0;

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

  if (numericValue < 0.01) {
    return `${numericValue.toFixed(6)} ms`;
  }

  if (numericValue < 1) {
    return `${numericValue.toFixed(4)} ms`;
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

function parseMetricMilliseconds(text) {
  const match = String(text || "").match(/[\d.]+/);
  if (!match) {
    return null;
  }

  const numericValue = Number(match[0]);
  return Number.isFinite(numericValue) ? numericValue : null;
}

function updateSpeedupFromVisibleMetrics() {
  const dbMs = parseMetricMilliseconds(dbLatencyMetric.textContent);
  const cacheMs = parseMetricMilliseconds(cacheLatencyMetric.textContent);

  if (dbMs === null || cacheMs === null || cacheMs <= 0) {
    speedupMetric.textContent = "--";
    return;
  }

  speedupMetric.textContent = formatSpeedup(dbMs / cacheMs);
}

function syncInteractiveState() {
  document.querySelectorAll(".view-post-button").forEach((button) => {
    if (!button.dataset.defaultLabel) {
      button.dataset.defaultLabel = button.textContent;
    }

    const buttonPostId = Number(button.dataset.postId);
    button.disabled = isPostOpenBusy;
    button.textContent = isPostOpenBusy && buttonPostId === busyPostId
      ? "불러오는 중..."
      : button.dataset.defaultLabel;
  });

  const hasSelection = currentPostId !== null;
  createPostButton.disabled = isPostOpenBusy;
  openCreateModalButton.disabled = isPostOpenBusy;
  refreshPostsButton.disabled = isPostOpenBusy;
  openEditModalButton.disabled = isPostOpenBusy || currentPostDetail === null;
  runBenchmarkButton.disabled = isPostOpenBusy || isBenchmarkBusy || !hasSelection;
  clearPostCacheButton.disabled = isPostOpenBusy || isBenchmarkBusy || !hasSelection;
}

function setPostOpenBusy(postId, busy) {
  isPostOpenBusy = busy;
  busyPostId = busy ? postId : null;
  syncInteractiveState();
}

function setBenchmarkBusy(busy) {
  isBenchmarkBusy = busy;
  syncInteractiveState();
}

function invalidateBenchmarkState() {
  benchmarkRequestSerial += 1;
  setBenchmarkBusy(false);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const rawText = await response.text();
  const data = rawText ? JSON.parse(rawText) : {};

  if (!response.ok) {
    throw new Error(data.detail || "요청이 실패했습니다.");
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
  userStatus.textContent = `${username}님 로그인 상태`;
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
    ? `게시글 저장 위치: ${data.posts.path}`
    : "게시글 저장 위치: 서버 연결";
  const cachePersistence = data.cache?.persistence_enabled
    ? `캐시 스냅샷: ${data.cache.persistence_path}`
    : "캐시 스냅샷: 비활성화";

  dataStoreMetric.textContent = postsBackend;
  cacheStoreMetric.textContent = `${postsLabel} / ${cacheLabel}`;
  storageSummary.textContent = `${postsLabel}가 게시글을 저장하고 ${cacheLabel}가 캐시를 처리합니다.`;
  storageMeta.textContent = `${postsPath} · ${cachePersistence}`;
  addDebugMessage(`GET /storage 호출 완료: ${postsLabel} 기반 저장소와 ${cacheLabel} 캐시를 사용합니다.`);

  return data;
}

function renderTopPosts(posts, source = "db", rankingRule = "") {
  if (posts.length === 0) {
    topPostsList.innerHTML = `
      <article class="leaderboard-card first-place">
        <div class="leaderboard-copy">
          <h4>표시할 인기글이 없습니다.</h4>
          <p>게시글을 불러온 뒤 다시 확인해 주세요.</p>
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
    ? "인기글은 Redis 캐시에서 바로 가져왔습니다."
    : `인기글을 다시 계산해 가져왔습니다.${rankingRule ? ` (${rankingRule})` : ""}`;
}

function renderPosts(posts) {
  if (posts.length === 0) {
    postsList.innerHTML = `
      <article class="post-row">
        <div class="post-row-copy">
          <h4>게시글이 없습니다.</h4>
          <p>새 글 작성 버튼으로 첫 게시글을 만들어 보세요.</p>
        </div>
      </article>
    `;
    syncInteractiveState();
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
        <button class="primary-button view-post-button" type="button" data-post-id="${post.id}">게시글 열기</button>
      </div>
    </article>
  `).join("");

  document.querySelectorAll(".view-post-button").forEach((button) => {
    button.addEventListener("click", () => {
      openPost(Number(button.dataset.postId)).catch(showError);
    });
  });

  syncInteractiveState();
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
    ? `${topPost.title} · 작성자 ${topPost.author}`
    : "아직 표시할 게시글이 없습니다.";
  postCountMetric.textContent = String(posts.length).padStart(2, "0");
}

function renderPostDetail(post) {
  currentPostDetail = post;

  postDetail.innerHTML = `
    <h4>${escapeHtml(post.title)}</h4>
    <p>${escapeHtml(post.content)}</p>
    <div class="detail-meta">
      <span>작성자 ${escapeHtml(post.author)}</span>
      <span>조회수 ${escapeHtml(post.views ?? 0)}</span>
      <span>출처 ${escapeHtml(post.source || "unknown")}</span>
      <span>게시글 ID ${escapeHtml(post.id)}</span>
    </div>
    <div class="detail-toolbar">
      <button class="ghost-button inline-edit-button" type="button">이 글 수정하기</button>
    </div>
  `;

  const inlineEditButton = postDetail.querySelector(".inline-edit-button");
  inlineEditButton.addEventListener("click", openEditModal);
  syncInteractiveState();
}

function resetLatencyMetrics(message, meta) {
  benchmarkStatus.textContent = message;
  benchmarkMeta.textContent = meta;
  dbLatencyMetric.textContent = "--";
  cacheLatencyMetric.textContent = "--";
  speedupMetric.textContent = "--";
}

function renderBenchmarkSummary(summary) {
  if (!summary || !summary.db || !summary.cache) {
    resetLatencyMetrics(
      "게시글을 선택하면 실제 저장소/메모리 접근 시간을 표시합니다.",
      "첫 접근은 DB 카드만, 이후 cache hit는 CACHE 카드만 갱신합니다. 전체 비교는 버튼으로 실행할 수 있습니다.",
    );
    return;
  }

  const databaseLabel = summary.comparison?.database_label || "Disk";
  const cacheLabel = summary.comparison?.cache_label || "Memory";

  benchmarkStatus.textContent = `${summary.post_id}번 글 기준 ${databaseLabel} ${formatMilliseconds(summary.db.average_ms)} / ${cacheLabel} ${formatMilliseconds(summary.cache.average_ms)}`;
  benchmarkMeta.textContent = `${summary.iterations}회 평균 직접 접근 기준입니다.`;
  dbLatencyMetric.textContent = formatMilliseconds(summary.db.average_ms);
  cacheLatencyMetric.textContent = formatMilliseconds(summary.cache.average_ms);
  updateSpeedupFromVisibleMetrics();
}

function renderBenchmarkPending(postId) {
  resetLatencyMetrics(
    `${postId}번 글을 선택했습니다.`,
    "캐시를 비운 뒤 첫 클릭이면 DB 카드만 갱신되고, 이후 cache hit 클릭이면 CACHE 카드가 갱신됩니다.",
  );
}

function renderPartialBenchmark(summary, sourceMode) {
  const label = sourceMode === "cache" ? "cache hit" : "DB direct read";
  benchmarkStatus.textContent = `${summary.post_id}번 글 ${label}`;

  if (sourceMode === "db" && summary.db) {
    dbLatencyMetric.textContent = formatMilliseconds(summary.db.average_ms);
    cacheLatencyMetric.textContent = "--";
    benchmarkMeta.textContent = "이번 클릭은 캐시가 비어 있어 DB 직접 조회만 측정했습니다.";
  } else if (sourceMode === "cache" && summary.cache) {
    cacheLatencyMetric.textContent = formatMilliseconds(summary.cache.average_ms);
    benchmarkMeta.textContent = "이번 클릭은 메모리 cache hit라 CACHE 직접 조회만 측정했습니다.";
  }

  updateSpeedupFromVisibleMetrics();
}

function renderBenchmarkMeasuring(postId, mode, iterations) {
  const target = mode === "cache" ? "메모리 키 조회" : mode === "db" ? "저장소 직접 조회" : "전체 비교";
  benchmarkStatus.textContent = `${postId}번 글 ${target}를 측정하는 중입니다.`;
  benchmarkMeta.textContent = `${iterations}회 반복 평균을 계산하고 있습니다.`;
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
    modalAuthorInput.value = usernameInput.value.trim() || "사용자";
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

async function fetchPosts() {
  const data = await requestJson("/posts");
  currentPosts = Array.isArray(data.posts) ? data.posts : [];
  renderPosts(currentPosts);
  updateMetrics(currentPosts);

  if (currentPostId !== null) {
    const refreshedPost = findPostById(currentPostId);
    if (refreshedPost) {
      renderPostDetail(refreshedPost);
    }
  }

  addDebugMessage(
    `GET /posts 호출 완료: 목록 원본 ${data.list_source ?? "unknown"}, 게시글 출처 cache ${data.sources?.cache ?? 0}개 / db ${data.sources?.db ?? 0}개를 확인했습니다.`,
  );
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

async function measureAccessForSource(postId, sourceMode, iterations = 5) {
  const requestSerial = ++benchmarkRequestSerial;
  setBenchmarkBusy(true);
  renderBenchmarkMeasuring(postId, sourceMode, iterations);

  try {
    const summary = await requestJson(
      `/posts/${postId}/benchmark?iterations=${iterations}&mode=${sourceMode}`,
      { method: "POST" },
    );

    if (requestSerial !== benchmarkRequestSerial || postId !== currentPostId) {
      return;
    }

    renderPartialBenchmark(summary, sourceMode);
    addDebugMessage(`POST /posts/${postId}/benchmark 호출 완료: ${sourceMode} 직접 접근 평균 ${formatMilliseconds(sourceMode === "db" ? summary.db?.average_ms : summary.cache?.average_ms)}.`);
  } finally {
    if (requestSerial === benchmarkRequestSerial) {
      setBenchmarkBusy(false);
    }
  }
}

async function openPost(postId) {
  if (isPostOpenBusy) {
    addDebugMessage("이전 게시글 열기 요청을 처리 중입니다. 잠시만 기다려 주세요.");
    return;
  }

  const isNewSelection = currentPostId !== postId;
  invalidateBenchmarkState();
  setPostOpenBusy(postId, true);

  try {
    const post = await requestJson(`/posts/${postId}/view`, {
      method: "POST",
    });

    currentPostId = postId;
    renderPostDetail(post);
    if (isNewSelection || post.source === "db") {
      renderBenchmarkPending(postId);
    }
    addDebugMessage(`POST /posts/${postId}/view 호출 완료: 조회수를 1 올리고 상세 보기를 갱신했습니다. source ${post.source}`);
    await refreshBoard();

    const metricMode = post.source === "cache" ? "cache" : "db";
    await measureAccessForSource(postId, metricMode);
  } finally {
    setPostOpenBusy(postId, false);
  }
}

async function createPost(payload) {
  invalidateBenchmarkState();

  const createdPost = await requestJson("/posts", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  currentPostId = createdPost.id;
  renderPostDetail(createdPost);
  renderBenchmarkPending(createdPost.id);
  closeModal();
  addDebugMessage("POST /posts 호출 완료: 새 게시글을 만들고 목록을 다시 불러왔습니다.");
  await refreshBoard();
}

async function updatePost(postId, payload) {
  invalidateBenchmarkState();

  const updatedPost = await requestJson(`/posts/${postId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  currentPostId = updatedPost.id;
  renderPostDetail(updatedPost);
  renderBenchmarkPending(updatedPost.id);
  closeModal();
  addDebugMessage(`PUT /posts/${postId} 호출 완료: 게시글을 수정하고 관련 캐시를 비웠습니다.`);
  await refreshBoard();
}

async function clearSelectedPostCache() {
  if (currentPostId === null) {
    addDebugMessage("먼저 게시글을 하나 선택해 주세요.");
    return;
  }

  invalidateBenchmarkState();
  const result = await requestJson(`/posts/${currentPostId}/cache/clear`, {
    method: "POST",
  });

  renderBenchmarkPending(currentPostId);
  benchmarkMeta.textContent = `post cache 삭제 ${result.post_cache_deleted}, top-posts cache 삭제 ${result.top_posts_cache_deleted}`;
  addDebugMessage(`POST /posts/${currentPostId}/cache/clear 호출 완료: 선택 게시글 캐시를 비웠습니다.`);
}

async function runBenchmark() {
  if (currentPostId === null) {
    addDebugMessage("먼저 게시글을 선택한 뒤 benchmark를 실행해 주세요.");
    return;
  }

  invalidateBenchmarkState();
  const iterations = Math.min(200, Math.max(1, Number(benchmarkIterationsInput.value) || 20));
  benchmarkIterationsInput.value = String(iterations);

  const requestSerial = ++benchmarkRequestSerial;
  setBenchmarkBusy(true);
  renderBenchmarkMeasuring(currentPostId, "both", iterations);

  try {
    const summary = await requestJson(
      `/posts/${currentPostId}/benchmark?iterations=${iterations}&mode=both`,
      { method: "POST" },
    );

    if (requestSerial !== benchmarkRequestSerial) {
      return;
    }

    renderBenchmarkSummary(summary);
    addDebugMessage(`POST /posts/${currentPostId}/benchmark 호출 완료: disk 평균 ${formatMilliseconds(summary.db?.average_ms)}, memory 평균 ${formatMilliseconds(summary.cache?.average_ms)}.`);
  } finally {
    if (requestSerial === benchmarkRequestSerial) {
      setBenchmarkBusy(false);
    }
  }
}

async function submitModalForm(event) {
  event.preventDefault();

  const payload = {
    title: modalTitleInput.value.trim(),
    content: modalContentInput.value.trim(),
    author: modalAuthorInput.value.trim(),
  };

  if (!payload.title || !payload.content || !payload.author) {
    addDebugMessage("제목, 내용, 작성자를 모두 입력해 주세요.");
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
    addDebugMessage("저장된 세션 토큰이 없어 로그아웃 요청을 보내지 않았습니다.");
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

function showError(error) {
  addDebugMessage(`오류: ${error.message}`);
}

async function bootstrap() {
  currentPostDetail = null;
  syncInteractiveState();
  renderBenchmarkSummary(null);
  await checkHealth();
  await fetchStorageSummary();
  await restoreSessionFromServer();
  await refreshBoard();

  if (currentPosts.length > 0) {
    currentPostId = currentPosts[0].id;
    renderPostDetail(currentPosts[0]);
    renderBenchmarkPending(currentPostId);
  }

  syncInteractiveState();
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

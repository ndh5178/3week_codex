/*
  이 파일은 웹페이지와 FastAPI 라우트를 실제로 연결하는 스크립트입니다.

  병합 충돌을 정리하면서 아래 기능을 함께 유지했습니다.
  1. 로그인 시 버튼 상태 전환
  2. localStorage 기반 세션 복구
  3. 게시글 수정/생성 모달
  4. 인기글 cache/db 흐름 표시
  5. 게시글 목록 cache/db 개수 통계 반영
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
  storageSummary.textContent = `${postsLabel}가 게시글을 저장하고, ${cacheLabel}가 캐시를 처리합니다.`;
  storageMeta.textContent = `${postsPath} · ${cachePersistence}`;
  addDebugMessage(`GET /storage 호출 완료: ${postsLabel} 기반 영속 저장소와 ${cacheLabel} 캐시를 사용합니다.`);

  return data;
}

function renderTopPosts(posts, source = "db", rankingRule = "") {
  if (posts.length === 0) {
    topPostsList.innerHTML = `
      <article class="leaderboard-card first-place">
        <div class="leaderboard-copy">
          <h4>표시할 인기글이 아직 없습니다.</h4>
          <p>게시글을 먼저 불러온 뒤 다시 확인해 주세요.</p>
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
          <p>새 글 작성 버튼으로 첫 게시글을 만들어 보세요.</p>
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
        <button class="primary-button view-post-button" type="button" data-post-id="${post.id}">게시글 열기</button>
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
    ? `${topPost.title} · 작성자 ${topPost.author}`
    : "대표 게시글이 아직 없습니다.";
  postCountMetric.textContent = String(posts.length).padStart(2, "0");
}

function renderPostDetail(post) {
  currentPostDetail = post;
  openEditModalButton.disabled = false;

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
}

function renderBenchmarkSummary(summary) {
  if (!summary) {
    benchmarkStatus.textContent = "게시글을 선택한 뒤 SQLite vs Cache 측정을 눌러 주세요.";
    benchmarkMeta.textContent = "같은 게시글을 여러 번 읽어 평균 시간을 계산하고, 영속 저장소와 메모리 캐시 차이를 보여줍니다.";
    dbLatencyMetric.textContent = "--";
    cacheLatencyMetric.textContent = "--";
    speedupMetric.textContent = "--";
    return;
  }

  const databaseLabel = summary.comparison?.database_label || "DB";
  const cacheLabel = summary.comparison?.cache_label || "Cache";
  const postsPath = summary.storage?.posts?.path ? `, 파일 ${summary.storage.posts.path}` : "";

  benchmarkStatus.textContent = `${summary.post_id}번 글 기준 ${databaseLabel} ${formatMilliseconds(summary.db.average_ms)} / ${cacheLabel} ${formatMilliseconds(summary.cache.average_ms)}`;
  benchmarkMeta.textContent = `${summary.iterations}회 평균, 측정 시각 ${summary.measured_at}, 속도 차이 ${formatSpeedup(summary.speedup)}${postsPath}`;
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
    modalSubmitButton.textContent = "새 글 저장";
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
    addDebugMessage("수정 모달을 열 수 없습니다: 아직 선택된 게시글이 없습니다.");
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
    `GET /posts 호출 완료: cache ${data.sources?.cache ?? 0}개, db ${data.sources?.db ?? 0}개 게시글을 확인했습니다.`,
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

async function openPost(postId) {
  const post = await requestJson(`/posts/${postId}/view`, {
    method: "POST",
  });

  currentPostId = postId;
  renderPostDetail(post);
  addDebugMessage(`POST /posts/${postId}/view 호출 완료: 조회수를 1 올리고 상세 보기를 갱신했습니다.`);
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
  renderPostDetail(createdPost);
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
  renderPostDetail(updatedPost);
  closeModal();
  addDebugMessage(`PUT /posts/${postId} 호출 완료: 게시글을 수정하고 관련 캐시를 비웠습니다.`);
  await refreshBoard();
}

async function clearSelectedPostCache() {
  if (currentPostId === null) {
    addDebugMessage("캐시를 비울 수 없습니다: 먼저 게시글 하나를 선택해 주세요.");
    return;
  }

  const result = await requestJson(`/posts/${currentPostId}/cache/clear`, {
    method: "POST",
  });
  benchmarkStatus.textContent = `${currentPostId}번 글의 캐시를 비웠습니다.`;
  benchmarkMeta.textContent = `post cache 삭제 ${result.post_cache_deleted}, top-posts cache 삭제 ${result.top_posts_cache_deleted}`;
  dbLatencyMetric.textContent = "--";
  cacheLatencyMetric.textContent = "--";
  speedupMetric.textContent = "--";
  addDebugMessage(`POST /posts/${currentPostId}/cache/clear 호출 완료: 선택 게시글 캐시를 비웠습니다.`);
}

async function runBenchmark() {
  if (currentPostId === null) {
    addDebugMessage("속도 비교를 할 수 없습니다: 먼저 게시글 하나를 선택해 주세요.");
    return;
  }

  const iterations = Math.min(200, Math.max(1, Number(benchmarkIterationsInput.value) || 20));
  benchmarkIterationsInput.value = String(iterations);
  const summary = await requestJson(`/posts/${currentPostId}/benchmark?iterations=${iterations}`, {
    method: "POST",
  });

  renderBenchmarkSummary(summary);
  addDebugMessage(`POST /posts/${currentPostId}/benchmark 호출 완료: DB 평균 ${formatMilliseconds(summary.db.average_ms)}, cache 평균 ${formatMilliseconds(summary.cache.average_ms)}.`);
}

async function submitModalForm(event) {
  event.preventDefault();

  const payload = {
    title: modalTitleInput.value.trim(),
    content: modalContentInput.value.trim(),
    author: modalAuthorInput.value.trim(),
  };

  if (!payload.title || !payload.content || !payload.author) {
    addDebugMessage("모달 저장 실패: 제목, 내용, 작성자는 모두 입력해야 합니다.");
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

function showError(error) {
  addDebugMessage(`오류: ${error.message}`);
}

async function bootstrap() {
  openEditModalButton.disabled = true;
  renderBenchmarkSummary(null);
  await checkHealth();
  await fetchStorageSummary();
  await restoreSessionFromServer();
  await refreshBoard();

  if (currentPosts.length > 0) {
    currentPostId = currentPosts[0].id;
    renderPostDetail(currentPosts[0]);
    await runBenchmark();
  }
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

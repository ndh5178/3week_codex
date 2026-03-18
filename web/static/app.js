/*
  HTML structure stays the same.
  This file only swaps placeholder behavior for real FastAPI calls.
*/

const userStatus = document.getElementById("user-status");
const userMeta = document.getElementById("user-meta");
const debugLog = document.getElementById("debug-log");
const postDetail = document.getElementById("post-detail");
const cacheStatus = document.getElementById("cache-status");
const topViewsMetric = document.getElementById("metric-top-views");
const serverMetric = document.getElementById("metric-server-status");
const postCountMetric = document.getElementById("metric-post-count");

const loginButton = document.getElementById("login-button");
const logoutButton = document.getElementById("logout-button");
const refreshPostsButton = document.getElementById("refresh-posts-button");
const usernameInput = document.getElementById("username-input");
const postsList = document.getElementById("posts-list");
const topPostsList = document.getElementById("top-posts-list");

let currentPostId = null;
let currentPosts = [];
let currentTopPosts = [];
let currentSessionToken = null;


function addDebugMessage(message) {
  const item = document.createElement("li");
  item.textContent = message;
  debugLog.prepend(item);
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderLoggedOutState() {
  userStatus.textContent = "로그아웃 상태";
  userMeta.textContent = "로그인 후 세션 상태와 사용자 이름이 여기에 표시됩니다.";
}

function renderLoggedInState(session) {
  const shortToken = session.token.slice(0, 8);
  userStatus.textContent = `${session.username}님 로그인 상태`;
  userMeta.textContent = `토큰 ${shortToken}... / Redis 키 ${session.session_key}`;
}

function renderTopPosts(payload) {
  const posts = Array.isArray(payload.posts) ? payload.posts : [];

  if (posts.length === 0) {
    topPostsList.innerHTML = `
      <article class="leaderboard-card first-place">
        <div class="leaderboard-copy">
          <h4>표시할 인기글이 없습니다.</h4>
          <p>먼저 게시글을 불러온 뒤 다시 확인해주세요.</p>
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
          <span>조회수 ${post.views}</span>
          <span>출처 ${escapeHtml(post.source || "unknown")}</span>
        </div>
      </article>
    `).join("");
  }

  cacheStatus.textContent = `GET /top-posts · ${payload.source} · ${payload.ranking_rule}`;
}

function renderPosts(posts) {
  if (posts.length === 0) {
    postsList.innerHTML = `
      <article class="post-row">
        <div class="post-row-copy">
          <h4>게시글이 없습니다.</h4>
          <p>데이터 파일을 확인한 뒤 다시 시도해주세요.</p>
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
        <span>작성자 ${escapeHtml(post.author)} · 조회수 ${post.views} · 출처 ${escapeHtml(post.source)}</span>
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

function renderPostDetail(post) {
  postDetail.innerHTML = `
    <h4>${escapeHtml(post.title)}</h4>
    <p>${escapeHtml(post.content)}</p>
    <div class="detail-meta">
      <span>작성자 ${escapeHtml(post.author)}</span>
      <span>출처 ${escapeHtml(post.source || "unknown")}</span>
      <span>조회수 ${post.views}</span>
      <span>게시글 ID ${post.id}</span>
    </div>
    <div class="detail-form">
      <label class="field-label" for="detail-title-input">제목 수정</label>
      <input id="detail-title-input" type="text" value="${escapeHtml(post.title)}">

      <label class="field-label" for="detail-content-input">내용 수정</label>
      <textarea id="detail-content-input">${escapeHtml(post.content)}</textarea>

      <label class="field-label" for="detail-author-input">작성자 수정</label>
      <input id="detail-author-input" type="text" value="${escapeHtml(post.author)}">

      <div class="detail-actions">
        <button id="save-post-button" class="primary-button" type="button">수정 저장</button>
      </div>
    </div>
  `;

  const saveButton = document.getElementById("save-post-button");
  saveButton.addEventListener("click", () => {
    updatePost(post.id).catch(showError);
  });
}

function updateMetrics(posts, topPosts) {
  const bestViews = topPosts.length > 0 ? topPosts[0].views : 0;
  topViewsMetric.textContent = String(bestViews).padStart(2, "0");
  postCountMetric.textContent = String(posts.length).padStart(2, "0");
}

async function checkHealth() {
  const data = await requestJson("/health");
  serverMetric.textContent = String(data.status).toUpperCase();
  addDebugMessage("GET /health 완료: 서버가 정상 동작 중입니다.");
}

async function fetchPosts() {
  const data = await requestJson("/posts");
  currentPosts = Array.isArray(data.posts) ? data.posts : [];
  renderPosts(currentPosts);
  updateMetrics(currentPosts, currentTopPosts);
  addDebugMessage(
    `GET /posts 완료: cache ${data.sources?.cache ?? 0}개, db ${data.sources?.db ?? 0}개 게시글을 확인했습니다.`,
  );
  return data;
}

async function fetchTopPosts() {
  const data = await requestJson("/top-posts");
  currentTopPosts = Array.isArray(data.posts) ? data.posts : [];
  renderTopPosts(data);
  updateMetrics(currentPosts, currentTopPosts);
  addDebugMessage(`GET /top-posts 완료: ${data.source} 흐름으로 상위 ${currentTopPosts.length}개를 불러왔습니다.`);
  return data;
}

async function refreshBoard() {
  await Promise.all([fetchPosts(), fetchTopPosts()]);
}

async function openPost(postId, options = {}) {
  const { trackView = true, refreshAfter = true } = options;

  if (trackView) {
    const viewData = await requestJson(`/posts/${postId}/view`, {
      method: "POST",
    });
    addDebugMessage(`POST /posts/${postId}/view 완료: 조회수가 ${viewData.views}로 증가했습니다.`);
  }

  const post = await requestJson(`/posts/${postId}`);
  currentPostId = postId;
  renderPostDetail(post);
  addDebugMessage(`GET /posts/${postId} 완료: 게시글 상세를 불러왔습니다.`);

  if (refreshAfter) {
    await refreshBoard();
  }
}

async function updatePost(postId) {
  const titleInput = document.getElementById("detail-title-input");
  const contentInput = document.getElementById("detail-content-input");
  const authorInput = document.getElementById("detail-author-input");

  const payload = {
    title: titleInput.value.trim(),
    content: contentInput.value.trim(),
    author: authorInput.value.trim(),
  };

  const updatedPost = await requestJson(`/posts/${postId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  renderPostDetail(updatedPost);
  addDebugMessage(`PUT /posts/${postId} 완료: 게시글을 수정하고 관련 캐시를 비웠습니다.`);
  await refreshBoard();
}

async function login() {
  const username = usernameInput.value.trim();
  if (!username) {
    throw new Error("사용자 이름을 입력해주세요.");
  }

  const session = await requestJson("/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ username }),
  });

  currentSessionToken = session.token;
  renderLoggedInState(session);
  addDebugMessage(`POST /login 완료: ${session.session_key} 세션을 저장했습니다.`);
}

async function logout() {
  if (!currentSessionToken) {
    renderLoggedOutState();
    addDebugMessage("로그아웃할 세션이 없어 화면 상태만 초기화했습니다.");
    return;
  }

  const result = await requestJson("/logout", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ token: currentSessionToken }),
  });

  currentSessionToken = null;
  renderLoggedOutState();
  addDebugMessage(`POST /logout 완료: ${result.session_key} 삭제 결과는 ${result.logged_out}입니다.`);
}

function showError(error) {
  addDebugMessage(`오류: ${error.message}`);
}

async function bootstrap() {
  renderLoggedOutState();
  await checkHealth();
  await refreshBoard();

  if (currentPosts.length > 0) {
    await openPost(currentPosts[0].id, {
      trackView: false,
      refreshAfter: false,
    });
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

bootstrap().catch(showError);

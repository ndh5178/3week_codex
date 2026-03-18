/*
  이 파일은 현재 만들어진 FastAPI 라우트와 웹페이지를 연결한다.

  연결된 라우트:
  - GET /health
  - GET /posts/{post_id}
  - PUT /posts/{post_id}

  아직 없는 라우트:
  - /login
  - /logout
  - /top-posts
  - /posts (목록 전체 조회)

  그래서 목록은 현재 화면에 있는 post id(1,2,3)를 기준으로 각각 GET 요청을 보내서 만든다.
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


function getPostIdsFromPage() {
  return [...document.querySelectorAll(".view-post-button")]
    .map((button) => Number(button.dataset.postId))
    .filter((value) => Number.isInteger(value));
}

function addDebugMessage(message) {
  const item = document.createElement("li");
  item.textContent = message;
  debugLog.prepend(item);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "요청에 실패했습니다.");
  }
  return data;
}

async function checkHealth() {
  const data = await requestJson("/health");
  serverMetric.textContent = String(data.status).toUpperCase();
  userMeta.textContent = "서버와 정적 파일이 정상 연결된 상태입니다.";
  addDebugMessage("GET /health 호출 완료: 서버가 정상 동작 중입니다.");
}

function renderTopPosts(posts) {
  const sortedPosts = [...posts].sort((left, right) => right.id - left.id);
  const topPosts = sortedPosts.slice(0, 3);

  topPostsList.innerHTML = topPosts.map((post, index) => `
    <article class="leaderboard-card ${index === 0 ? "first-place" : ""}">
      <div class="rank-pill">${String(index + 1).padStart(2, "0")}</div>
      <div class="leaderboard-copy">
        <h4>${escapeHtml(post.title)}</h4>
        <p>${escapeHtml(post.content)}</p>
      </div>
      <div class="leaderboard-meta">
        <span>ID ${post.id}</span>
        <span>출처 ${post.source}</span>
      </div>
    </article>
  `).join("");

  cacheStatus.textContent = "현재 API 기준 게시글 요약 표시";
}

function renderPosts(posts) {
  postsList.innerHTML = posts.map((post) => `
    <article class="post-row" data-post-id="${post.id}">
      <div class="post-row-copy">
        <h4>${escapeHtml(post.title)}</h4>
        <p>${escapeHtml(post.content)}</p>
      </div>
      <div class="post-row-side">
        <span>작성자 ${escapeHtml(post.author)}</span>
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
  topViewsMetric.textContent = String(posts.length > 0 ? posts[0].id : 0);
  postCountMetric.textContent = String(posts.length).padStart(2, "0");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function fetchPosts() {
  const postIds = getPostIdsFromPage();
  const posts = [];

  for (const postId of postIds) {
    const post = await requestJson(`/posts/${postId}`);
    posts.push(post);
  }

  currentPosts = posts;
  renderPosts(posts);
  renderTopPosts(posts);
  updateMetrics(posts);
  addDebugMessage("GET /posts/{id} 요청들로 게시글 목록을 새로 불러왔습니다.");
}

function renderPostDetail(post) {
  postDetail.innerHTML = `
    <h4>${escapeHtml(post.title)}</h4>
    <p>${escapeHtml(post.content)}</p>
    <div class="detail-meta">
      <span>작성자 ${escapeHtml(post.author)}</span>
      <span>데이터 출처 ${escapeHtml(post.source || "unknown")}</span>
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

async function openPost(postId) {
  const post = await requestJson(`/posts/${postId}`);
  currentPostId = postId;
  renderPostDetail(post);
  addDebugMessage(`GET /posts/${postId} 호출 완료: 게시글 상세를 불러왔습니다.`);
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
  addDebugMessage(`PUT /posts/${postId} 호출 완료: 게시글이 수정되고 캐시가 무효화되었습니다.`);
  await fetchPosts();
}

function loginPlaceholder() {
  const username = usernameInput.value.trim() || "사용자";
  userStatus.textContent = `${username}님 로그인 상태`;
  userMeta.textContent = "현재 API에는 로그인 라우트가 없어서 화면 상태만 임시로 바꿉니다.";
  addDebugMessage("로그인 버튼 클릭: 현재 서버에는 /login 라우트가 아직 없습니다.");
}

function logoutPlaceholder() {
  userStatus.textContent = "로그아웃 상태";
  userMeta.textContent = "로그인하면 사용자 이름과 세션 상태가 여기에 표시됩니다.";
  addDebugMessage("로그아웃 버튼 클릭: 현재 서버에는 /logout 라우트가 아직 없습니다.");
}

function showError(error) {
  addDebugMessage(`오류: ${error.message}`);
}

async function bootstrap() {
  await checkHealth();
  await fetchPosts();
  if (currentPosts.length > 0) {
    await openPost(currentPosts[0].id);
  }
}

loginButton.addEventListener("click", loginPlaceholder);
logoutButton.addEventListener("click", logoutPlaceholder);
refreshPostsButton.addEventListener("click", () => {
  fetchPosts().catch(showError);
});

bootstrap().catch(showError);

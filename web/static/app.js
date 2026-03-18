/*
  이 파일은 "API 연결 전 임시 껍데기용 스크립트" 입니다.

  지금은 실제 서버 요청을 보내지 않고,
  버튼을 눌렀을 때 어떤 요소를 나중에 연결하면 되는지 보여주는 용도로만 작성했습니다.

  API 담당자가 나중에 주로 교체하게 될 부분:
  - login()
  - logout()
  - fetchPosts()
  - fetchTopPosts()
  - openPost(postId)
*/

const userStatus = document.getElementById("user-status");
const userMeta = document.getElementById("user-meta");
const debugLog = document.getElementById("debug-log");
const postDetail = document.getElementById("post-detail");
const cacheStatus = document.getElementById("cache-status");

const loginButton = document.getElementById("login-button");
const logoutButton = document.getElementById("logout-button");
const refreshPostsButton = document.getElementById("refresh-posts-button");
const viewPostButtons = document.querySelectorAll(".view-post-button");
const usernameInput = document.getElementById("username-input");

function addDebugMessage(message) {
  const item = document.createElement("li");
  item.textContent = message;
  debugLog.prepend(item);
}

function mockLogin() {
  const username = usernameInput.value.trim() || "사용자";

  userStatus.textContent = `${username}님 로그인 상태`;
  userMeta.textContent = "지금은 더미 동작입니다. 나중에 API 응답으로 세션 정보를 표시하면 됩니다.";
  addDebugMessage("로그인 버튼 클릭: 추후 /login API와 연결하면 됩니다.");
}

function mockLogout() {
  userStatus.textContent = "로그아웃 상태";
  userMeta.textContent = "로그인하면 사용자 이름과 세션 상태가 여기에 표시됩니다.";
  addDebugMessage("로그아웃 버튼 클릭: 추후 /logout API와 연결하면 됩니다.");
}

function mockRefreshPosts() {
  addDebugMessage("게시글 새로고침 클릭: 추후 /posts API와 연결하면 됩니다.");
}

function mockOpenPost(postId) {
  postDetail.innerHTML = `
    <h3>선택한 게시글 ID: ${postId}</h3>
    <p>지금은 더미 화면이라 실제 서버 데이터는 없습니다.</p>
    <p>나중에는 이 자리에 게시글 제목, 내용, 조회수, 작성자 정보가 API 응답으로 들어오면 됩니다.</p>
  `;

  cacheStatus.textContent = "인기글 캐시 재계산 예정";
  addDebugMessage(`게시글 ${postId} 열기 클릭: 추후 /posts/${postId}/view API와 연결하면 됩니다.`);
}

loginButton.addEventListener("click", mockLogin);
logoutButton.addEventListener("click", mockLogout);
refreshPostsButton.addEventListener("click", mockRefreshPosts);

viewPostButtons.forEach((button) => {
  button.addEventListener("click", () => {
    mockOpenPost(button.dataset.postId);
  });
});

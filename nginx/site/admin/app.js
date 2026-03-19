const adminState = {
  token: localStorage.getItem("adminAccessToken") || null,
  me: null,
  groups: [],
  streams: [],
  users: [],
  currentView: "pending",
};

const loginForm = document.getElementById("login-form");
const loginStatus = document.getElementById("login-status");
const adminApp = document.getElementById("admin-app");
const adminMe = document.getElementById("admin-me");
const viewTitle = document.getElementById("view-title");
const viewBody = document.getElementById("view-body");
const detailBody = document.getElementById("detail-body");
const refreshButton = document.getElementById("refresh-button");

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  try {
    const payload = await fetchJson("/api/v1/admin/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    adminState.token = payload.access_token;
    localStorage.setItem("adminAccessToken", adminState.token);
    await bootstrapAdmin();
  } catch (error) {
    showLoginError(error.message || "Admin login failed.");
  }
});

refreshButton.addEventListener("click", () => {
  loadView(adminState.currentView).catch(renderError);
});

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    loadView(button.dataset.view).catch(renderError);
  });
});

initialize().catch(renderError);

async function initialize() {
  if (!adminState.token) {
    return;
  }
  try {
    await bootstrapAdmin();
  } catch (_) {
    localStorage.removeItem("adminAccessToken");
    adminState.token = null;
  }
}

async function bootstrapAdmin() {
  adminState.me = await api("/api/v1/admin/auth/me");
  adminApp.classList.remove("hidden");
  loginStatus.classList.add("hidden");
  renderMe();
  await loadView(adminState.currentView);
}

function renderMe() {
  adminMe.innerHTML = `
    <p><strong>${adminState.me.username}</strong></p>
    <p class="muted">role: ${adminState.me.role}</p>
    <p class="muted">auth: ${adminState.me.auth_mode}</p>
  `;
}

async function loadView(view) {
  adminState.currentView = view;
  detailBody.innerHTML = '<p class="muted">Select a user or stream to inspect details.</p>';
  if (view === "pending") {
    viewTitle.textContent = "Pending Users";
    const payload = await api("/api/v1/admin/users?status=pending&limit=100");
    adminState.users = payload.users;
    renderUsers(payload.users, true);
    return;
  }
  if (view === "users") {
    viewTitle.textContent = "All Users";
    const payload = await api("/api/v1/admin/users?limit=100");
    adminState.users = payload.users;
    renderUsers(payload.users, false);
    return;
  }
  if (view === "streams") {
    viewTitle.textContent = "Output Streams";
    const payload = await api("/api/v1/admin/output-streams");
    adminState.streams = payload.output_streams;
    adminState.groups = (await api("/api/v1/admin/groups")).groups;
    renderStreams(payload.output_streams);
    return;
  }
  if (view === "groups") {
    viewTitle.textContent = "Groups";
    const payload = await api("/api/v1/admin/groups");
    adminState.groups = payload.groups;
    renderGroups(payload.groups);
    return;
  }
  if (view === "audit") {
    viewTitle.textContent = "Audit Log";
    const payload = await api("/api/v1/admin/audit?limit=100");
    renderAudit(payload.audit_logs);
  }
}

function renderUsers(users, pendingOnly) {
  const actions = pendingOnly ? ["approve", "reject", "block"] : ["approve", "reject", "block", "unblock"];
  viewBody.innerHTML = `
    <div class="card-list">
      ${users.map((user) => `
        <article class="card">
          <div>
            <strong>${user.display_name}</strong>
            <div class="muted">${user.client_code}</div>
            <div class="badge">${user.status}</div>
          </div>
          <div class="button-row">
            <button data-user-detail="${user.user_id}" class="secondary">Details</button>
            ${actions.map((action) => `<button data-user-action="${action}" data-user-id="${user.user_id}">${action}</button>`).join("")}
          </div>
        </article>
      `).join("")}
    </div>
  `;
  bindUserActions();
}

function bindUserActions() {
  viewBody.querySelectorAll("[data-user-detail]").forEach((button) => {
    button.addEventListener("click", () => openUserDetail(button.dataset.userDetail).catch(renderError));
  });
  viewBody.querySelectorAll("[data-user-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/v1/admin/users/${button.dataset.userId}/${button.dataset.userAction}`, { method: "POST" });
      await loadView(adminState.currentView);
    });
  });
}

async function openUserDetail(userId) {
  const detail = await api(`/api/v1/admin/users/${userId}`);
  const groups = await api("/api/v1/admin/groups");
  const streams = await api("/api/v1/admin/output-streams");
  detailBody.innerHTML = `
    <p><strong>${detail.user.display_name}</strong></p>
    <p class="muted">status: ${detail.user.status}</p>
    <p class="muted">client code: ${detail.user.client_code}</p>
    <p class="muted">groups: ${detail.group_ids.join(", ") || "none"}</p>
    <p class="muted">direct streams: ${detail.output_stream_ids.join(", ") || "none"}</p>
    <form id="group-member-form" class="inline-form">
      <select id="detail-group-id">
        ${groups.groups.map((group) => `<option value="${group.group_id}">${group.name}</option>`).join("")}
      </select>
      <button type="submit">Add To Group</button>
    </form>
    <form id="grant-user-form" class="inline-form">
      <select id="detail-stream-id">
        ${streams.output_streams.map((stream) => `<option value="${stream.output_stream_id}">${stream.title}</option>`).join("")}
      </select>
      <button type="submit">Grant Stream</button>
    </form>
  `;
  document.getElementById("group-member-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const groupId = document.getElementById("detail-group-id").value;
    await api(`/api/v1/admin/users/${userId}/groups/${groupId}`, { method: "POST" });
    await openUserDetail(userId);
  });
  document.getElementById("grant-user-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const outputStreamId = document.getElementById("detail-stream-id").value;
    await api(`/api/v1/admin/output-streams/${outputStreamId}/grant-user`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    await openUserDetail(userId);
  });
}

function renderStreams(streams) {
  viewBody.innerHTML = `
    <form id="create-stream-form" class="stack-form">
      <input id="stream-name" placeholder="Output stream name" required>
      <input id="stream-public-name" placeholder="public name" required>
      <input id="stream-title" placeholder="title" required>
      <input id="stream-playback-path" placeholder="playback path" required>
      <button type="submit">Create Output Stream</button>
    </form>
    <div class="card-list">
      ${streams.map((stream) => `
        <article class="card">
          <div>
            <strong>${stream.title}</strong>
            <div class="muted">${stream.playback_path}</div>
            <div class="badge">${stream.visibility}</div>
          </div>
          <button data-stream-detail="${stream.output_stream_id}" class="secondary">Details</button>
        </article>
      `).join("")}
    </div>
  `;
  document.getElementById("create-stream-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await api("/api/v1/admin/output-streams", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: document.getElementById("stream-name").value.trim(),
        public_name: document.getElementById("stream-public-name").value.trim(),
        title: document.getElementById("stream-title").value.trim(),
        playback_path: document.getElementById("stream-playback-path").value.trim(),
      }),
    });
    await loadView("streams");
  });
  viewBody.querySelectorAll("[data-stream-detail]").forEach((button) => {
    button.addEventListener("click", () => openStreamDetail(button.dataset.streamDetail).catch(renderError));
  });
}

async function openStreamDetail(outputStreamId) {
  const detail = await api(`/api/v1/admin/output-streams/${outputStreamId}`);
  const groups = await api("/api/v1/admin/groups");
  const users = await api("/api/v1/admin/users?limit=100");
  detailBody.innerHTML = `
    <p><strong>${detail.output_stream.title}</strong></p>
    <p class="muted">playback path: ${detail.output_stream.playback_path}</p>
    <p class="muted">users: ${detail.user_ids.join(", ") || "none"}</p>
    <p class="muted">groups: ${detail.group_ids.join(", ") || "none"}</p>
    <form id="grant-stream-user-form" class="inline-form">
      <select id="stream-user-id">${users.users.map((user) => `<option value="${user.user_id}">${user.display_name}</option>`).join("")}</select>
      <button type="submit">Grant User</button>
    </form>
    <form id="grant-stream-group-form" class="inline-form">
      <select id="stream-group-id">${groups.groups.map((group) => `<option value="${group.group_id}">${group.name}</option>`).join("")}</select>
      <button type="submit">Grant Group</button>
    </form>
  `;
  document.getElementById("grant-stream-user-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await api(`/api/v1/admin/output-streams/${outputStreamId}/grant-user`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: document.getElementById("stream-user-id").value }),
    });
    await openStreamDetail(outputStreamId);
  });
  document.getElementById("grant-stream-group-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await api(`/api/v1/admin/output-streams/${outputStreamId}/grant-group`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: document.getElementById("stream-group-id").value }),
    });
    await openStreamDetail(outputStreamId);
  });
}

function renderGroups(groups) {
  viewBody.innerHTML = `
    <form id="create-group-form" class="stack-form">
      <input id="group-name" placeholder="Group name" required>
      <button type="submit">Create Group</button>
    </form>
    <div class="card-list">
      ${groups.map((group) => `
        <article class="card">
          <div>
            <strong>${group.name}</strong>
            <div class="muted">members: ${group.member_count}</div>
          </div>
        </article>
      `).join("")}
    </div>
  `;
  document.getElementById("create-group-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await api("/api/v1/admin/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: document.getElementById("group-name").value.trim() }),
    });
    await loadView("groups");
  });
}

function renderAudit(items) {
  viewBody.innerHTML = `
    <div class="card-list">
      ${items.map((item) => `
        <article class="card">
          <div>
            <strong>${item.action}</strong>
            <div class="muted">${item.target_type}:${item.target_id || "-"}</div>
            <div class="muted">${item.actor_type}:${item.actor_id || "-"}</div>
          </div>
          <code class="meta">${JSON.stringify(item.metadata_json)}</code>
        </article>
      `).join("")}
    </div>
  `;
}

async function api(path, options = {}) {
  return fetchJson(path, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${adminState.token}`,
    },
  });
}

async function fetchJson(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error(typeof body === "string" ? body : JSON.stringify(body));
  }
  return body;
}

function showLoginError(message) {
  loginStatus.classList.remove("hidden");
  loginStatus.textContent = message;
}

function renderError(error) {
  loginStatus.classList.remove("hidden");
  loginStatus.textContent = error.message || "Request failed.";
}

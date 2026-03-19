const adminState = {
  token: localStorage.getItem("adminAccessToken") || null,
  me: null,
  groups: [],
  ingests: [],
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
const userActionLabels = {
  approve: "Одобрить",
  reject: "Отклонить",
  block: "Заблокировать",
  unblock: "Разблокировать",
};

const userStatusLabels = {
  pending: "ожидает",
  approved: "одобрен",
  rejected: "отклонён",
  blocked: "заблокирован",
};

function formatUserStatus(status) {
  return userStatusLabels[status] || status;
}

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
    showLoginError(error.message || "Не удалось выполнить вход администратора.");
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
    <p class="muted">роль: ${adminState.me.role}</p>
    <p class="muted">авторизация: ${adminState.me.auth_mode}</p>
  `;
}

async function loadView(view) {
  adminState.currentView = view;
  detailBody.innerHTML = '<p class="muted">Выберите пользователя или поток для просмотра деталей.</p>';
  if (view === "pending") {
    viewTitle.textContent = "Заявки";
    const payload = await api("/api/v1/admin/users?status=pending&limit=100");
    adminState.users = payload.users;
    renderUsers(payload.users, true);
    return;
  }
  if (view === "users") {
    viewTitle.textContent = "Пользователи";
    const payload = await api("/api/v1/admin/users?limit=100");
    adminState.users = payload.users;
    renderUsers(payload.users, false);
    return;
  }
  if (view === "streams") {
    viewTitle.textContent = "Выходные потоки";
    const payload = await api("/api/v1/admin/output-streams");
    adminState.streams = payload.output_streams;
    adminState.groups = (await api("/api/v1/admin/groups")).groups;
    renderStreams(payload.output_streams);
    return;
  }
  if (view === "active-ingests") {
    viewTitle.textContent = "Активные потоки на одобрение";
    const [ingestPayload, streamPayload] = await Promise.all([
      api("/api/v1/admin/ingest-sessions"),
      api("/api/v1/admin/output-streams"),
    ]);
    adminState.ingests = ingestPayload.ingest_sessions;
    adminState.streams = streamPayload.output_streams;
    renderActiveIngests(ingestPayload.ingest_sessions, streamPayload.output_streams);
    return;
  }
  if (view === "groups") {
    viewTitle.textContent = "Группы";
    const payload = await api("/api/v1/admin/groups");
    adminState.groups = payload.groups;
    renderGroups(payload.groups);
    return;
  }
  if (view === "audit") {
    viewTitle.textContent = "Журнал аудита";
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
            <div class="badge">${formatUserStatus(user.status)}</div>
          </div>
          <div class="button-row">
            <button data-user-detail="${user.user_id}" class="secondary">Детали</button>
            ${actions.map((action) => `<button data-user-action="${action}" data-user-id="${user.user_id}">${userActionLabels[action] || action}</button>`).join("")}
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
    <p class="muted">статус: ${formatUserStatus(detail.user.status)}</p>
    <p class="muted">код клиента: ${detail.user.client_code}</p>
    <p class="muted">группы: ${detail.group_ids.join(", ") || "нет"}</p>
    <p class="muted">прямые доступы к потокам: ${detail.output_stream_ids.join(", ") || "нет"}</p>
    <form id="group-member-form" class="inline-form">
      <select id="detail-group-id">
        ${groups.groups.map((group) => `<option value="${group.group_id}">${group.name}</option>`).join("")}
      </select>
      <button type="submit">Добавить в группу</button>
    </form>
    <form id="grant-user-form" class="inline-form">
      <select id="detail-stream-id">
        ${streams.output_streams.map((stream) => `<option value="${stream.output_stream_id}">${stream.title}</option>`).join("")}
      </select>
      <button type="submit">Выдать доступ к потоку</button>
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
      <input id="stream-name" placeholder="Служебное имя потока" required>
      <input id="stream-public-name" placeholder="Публичное имя" required>
      <input id="stream-title" placeholder="Название" required>
      <input id="stream-playback-path" placeholder="Playback path" required>
      <button type="submit">Создать выходной поток</button>
    </form>
    <div class="card-list">
      ${streams.map((stream) => `
        <article class="card">
          <div>
            <strong>${stream.title}</strong>
            <div class="muted">${stream.playback_path}</div>
            <div class="badge">${stream.visibility}</div>
          </div>
          <button data-stream-detail="${stream.output_stream_id}" class="secondary">Детали</button>
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
    <p class="muted">пользователи: ${detail.user_ids.join(", ") || "нет"}</p>
    <p class="muted">группы: ${detail.group_ids.join(", ") || "нет"}</p>
    <form id="grant-stream-user-form" class="inline-form">
      <select id="stream-user-id">${users.users.map((user) => `<option value="${user.user_id}">${user.display_name}</option>`).join("")}</select>
      <button type="submit">Выдать пользователю</button>
    </form>
    <form id="grant-stream-group-form" class="inline-form">
      <select id="stream-group-id">${groups.groups.map((group) => `<option value="${group.group_id}">${group.name}</option>`).join("")}</select>
      <button type="submit">Выдать группе</button>
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

function renderActiveIngests(ingests, streams) {
  const liveIngests = ingests.filter((session) => session.status === "live");
  const streamById = new Map(streams.map((stream) => [stream.output_stream_id, stream]));
  const approvalQueue = liveIngests
    .map((session) => ({
      session,
      stream: session.current_output_stream_id ? streamById.get(session.current_output_stream_id) : null,
    }))
    .filter(({ session, stream }) => {
      if (!stream) {
        return true;
      }
      const streamMeta = stream.metadata_json || {};
      const sessionMeta = session.metadata_json || {};
      return sessionMeta.auto_registered_from_publish === true && streamMeta.admin_approved !== true;
    });

  viewBody.innerHTML = `
    <div class="card-list">
      ${approvalQueue.length === 0 ? '<article class="card"><div><strong>Нет активных потоков на одобрение</strong><div class="muted">Все живые ingest-сессии уже проверены или сейчас никто не публикует поток.</div></div></article>' : approvalQueue.map(({ session, stream }) => `
        <article class="card">
          <div>
            <strong>${session.source_label || session.ingest_key || session.ingest_session_id}</strong>
            <div class="muted">ingest key: ${session.ingest_key || "-"}</div>
            <div class="muted">выходной поток: ${stream ? stream.playback_path : "не привязан"}</div>
            <div class="muted">старт: ${session.started_at || "нет данных"}</div>
            <div class="badge">${stream ? "требует одобрения" : "требует привязки"}</div>
          </div>
          <div class="button-row">
            <button data-ingest-detail="${session.ingest_session_id}" class="secondary">Детали</button>
            ${stream ? `<button data-approve-stream="${stream.output_stream_id}">Одобрить</button>` : ""}
          </div>
        </article>
      `).join("")}
    </div>
  `;
  viewBody.querySelectorAll("[data-ingest-detail]").forEach((button) => {
    button.addEventListener("click", () => openIngestDetail(button.dataset.ingestDetail).catch(renderError));
  });
  viewBody.querySelectorAll("[data-approve-stream]").forEach((button) => {
    button.addEventListener("click", async () => {
      const stream = streamById.get(button.dataset.approveStream);
      const metadata = {
        ...(stream?.metadata_json || {}),
        admin_approved: true,
        admin_approved_at: new Date().toISOString(),
      };
      await api(`/api/v1/admin/output-streams/${button.dataset.approveStream}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metadata_json: metadata }),
      });
      await loadView("active-ingests");
    });
  });
}

async function openIngestDetail(ingestSessionId) {
  const detail = await api(`/api/v1/admin/ingest-sessions/${ingestSessionId}`);
  const streams = await api("/api/v1/admin/output-streams");
  const currentStream = streams.output_streams.find((stream) => stream.output_stream_id === detail.current_output_stream_id) || null;
  detailBody.innerHTML = `
    <p><strong>${detail.source_label || detail.ingest_key || detail.ingest_session_id}</strong></p>
    <p class="muted">статус: ${detail.status}</p>
    <p class="muted">ingest key: ${detail.ingest_key || "-"}</p>
    <p class="muted">старт: ${detail.started_at || "нет данных"}</p>
    <p class="muted">привязанный выходной поток: ${currentStream ? `${currentStream.title} (${currentStream.playback_path})` : "нет"}</p>
    <p class="muted">метаданные: ${JSON.stringify(detail.metadata_json || {})}</p>
    <form id="bind-ingest-form" class="inline-form">
      <select id="ingest-output-stream-id">
        <option value="">Отвязать</option>
        ${streams.output_streams.map((stream) => `<option value="${stream.output_stream_id}" ${stream.output_stream_id === detail.current_output_stream_id ? "selected" : ""}>${stream.title} (${stream.playback_path})</option>`).join("")}
      </select>
      <button type="submit">Привязать выходной поток</button>
    </form>
  `;
  document.getElementById("bind-ingest-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const outputStreamId = document.getElementById("ingest-output-stream-id").value || null;
    await api(`/api/v1/admin/ingest-sessions/${ingestSessionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_output_stream_id: outputStreamId }),
    });
    await openIngestDetail(ingestSessionId);
    if (adminState.currentView === "active-ingests") {
      await loadView("active-ingests");
    }
  });
}

function renderGroups(groups) {
  viewBody.innerHTML = `
    <form id="create-group-form" class="stack-form">
      <input id="group-name" placeholder="Название группы" required>
      <button type="submit">Создать группу</button>
    </form>
    <div class="card-list">
      ${groups.map((group) => `
        <article class="card">
          <div>
            <strong>${group.name}</strong>
            <div class="muted">участников: ${group.member_count}</div>
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
  loginStatus.textContent = error.message || "Запрос завершился ошибкой.";
}

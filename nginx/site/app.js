const state = {
  viewerToken: sessionStorage.getItem("viewerToken") || null,
  profile: null,
  config: null,
  currentPlayback: null,
  pollHandle: null,
  autoPlayRequested: false,
  autoPlayConsumed: false,
};

const connectForm = document.getElementById("connect-form");
const clientCodeInput = document.getElementById("client-code");
const sessionStatus = document.getElementById("session-status");
const viewerPanel = document.getElementById("viewer-panel");
const profileBox = document.getElementById("profile");
const streamsList = document.getElementById("streams-list");
const streamCount = document.getElementById("stream-count");
const refreshButton = document.getElementById("refresh-streams");
const playerState = document.getElementById("player-state");
const playerMessage = document.getElementById("player-message");
const playbackUrl = document.getElementById("playback-url");
const video = document.getElementById("video");

connectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await openSession(clientCodeInput.value.trim().toUpperCase());
  } catch (error) {
    resetSession();
    sessionStatus.classList.remove("hidden");
    sessionStatus.textContent = error.message || "Viewer session failed.";
  }
});

refreshButton.addEventListener("click", async () => {
  await loadStreams();
});

window.addEventListener("beforeunload", () => {
  teardownPlayback();
});

const initialClientCode = new URLSearchParams(window.location.search).get("client-code");
const autoPlay = new URLSearchParams(window.location.search).get("autoplay");
if (initialClientCode) {
  clientCodeInput.value = initialClientCode.toUpperCase();
}
if (autoPlay === "1") {
  state.autoPlayRequested = true;
}

initialize().catch((error) => {
  resetSession();
  sessionStatus.classList.remove("hidden");
  sessionStatus.textContent = error.message || "Failed to initialize viewer session.";
});

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.viewerToken) {
    headers.set("Authorization", `Bearer ${state.viewerToken}`);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function initialize() {
  if (initialClientCode) {
    resetSession();
    await openSession(initialClientCode.toUpperCase());
    return;
  }

  if (state.viewerToken) {
    await bootstrapFromSession();
  }
}

async function openSession(clientCode) {
  if (!clientCode) {
    throw new Error("Client code is required.");
  }
  sessionStatus.classList.remove("hidden");
  sessionStatus.textContent = "Authorizing viewer session...";
  const payload = await fetch("/api/v1/viewer/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_code: clientCode }),
  }).then(async (response) => {
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail || "viewer session failed");
    }
    return body;
  });

  renderSessionStatus(payload);
  if (!payload.viewer_token) {
    sessionStatus.classList.remove("hidden");
    return;
  }

  state.viewerToken = payload.viewer_token;
  state.profile = payload.user;
  sessionStorage.setItem("viewerToken", state.viewerToken);
  await bootstrapFromSession();
}

async function bootstrapFromSession() {
  const me = await api("/api/v1/viewer/me");
  const config = await api("/api/v1/viewer/config");
  state.profile = me.user;
  state.config = config;
  renderProfile();
  viewerPanel.classList.remove("hidden");
  sessionStatus.classList.add("hidden");
  await loadStreams();
  startPolling();
}

async function loadStreams() {
  const payload = await api("/api/v1/viewer/streams");
  renderStreams(payload.streams || []);
}

function renderSessionStatus(payload) {
  sessionStatus.classList.remove("hidden");
  sessionStatus.innerHTML = `
    <strong>${payload.user.display_name}</strong><br>
    status: ${payload.user.status}${payload.detail ? `<br>${payload.detail}` : ""}
  `;
}

function renderProfile() {
  profileBox.innerHTML = `
    <p><strong>${state.profile.display_name}</strong></p>
    <p class="muted">client code: ${state.profile.client_code}</p>
    <p class="muted">status: ${state.profile.status}</p>
  `;
}

function renderStreams(streams) {
  streamCount.textContent = `${streams.length} stream(s)`;
  if (!streams.length) {
    streamsList.innerHTML = `<div class="status-card">No streams assigned.</div>`;
    return;
  }

  streamsList.innerHTML = streams.map((stream) => {
    const isLive = stream.is_active !== false;
    const status = isLive ? "available" : "offline";
    const badgeClass = isLive ? "live" : "offline";
    const streamId = stream.output_stream_id || stream.stream_id;
    return `
      <article class="stream-card">
        <div class="stream-meta">
          <div>
            <strong>${stream.title || stream.name}</strong>
            <div class="muted">${stream.playback_path}</div>
          </div>
          <span class="badge ${badgeClass}">${status}</span>
        </div>
        <button data-stream-id="${streamId}">Open</button>
      </article>
    `;
  }).join("");

  streamsList.querySelectorAll("button[data-stream-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await openStream(button.dataset.streamId);
      } catch (error) {
        playerState.className = "badge danger";
        playerState.textContent = "Error";
        playerMessage.textContent = error.message || "Playback failed.";
      }
    });
  });

  if (state.autoPlayRequested && !state.autoPlayConsumed) {
    const firstStreamId = streams[0]?.output_stream_id || streams[0]?.stream_id;
    if (firstStreamId) {
      state.autoPlayConsumed = true;
      openStream(firstStreamId).catch(() => {
        state.autoPlayConsumed = false;
      });
    }
  }
}

async function openStream(streamId) {
  playerState.className = "badge warn";
  playerState.textContent = "Loading";
  playerMessage.textContent = "Requesting playback session...";
  const payload = await api(`/api/v1/viewer/streams/${streamId}/playback-session`, { method: "POST" });
  playbackUrl.classList.remove("hidden");
  playbackUrl.textContent = payload.playback.webrtc_url;
  await startWhepPlayback(payload.playback.webrtc_url);
}

async function startWhepPlayback(url) {
  teardownPlayback();
  const iceServers = (state.config?.stun_urls || []).map((urlItem) => ({ urls: urlItem }));
  const pc = new RTCPeerConnection({ iceServers });
  state.currentPlayback = { pc };
  video.srcObject = new MediaStream();

  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });
  pc.ontrack = (event) => {
    const [stream] = event.streams;
    video.srcObject = stream;
    playerState.className = "badge live";
    playerState.textContent = "Live";
    playerMessage.textContent = "Playback connected.";
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await waitForIce(pc);

  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/sdp" },
    body: pc.localDescription.sdp,
  });
  if (!response.ok) {
    throw new Error(`Playback failed: HTTP ${response.status}`);
  }

  const answer = await response.text();
  await pc.setRemoteDescription({ type: "answer", sdp: answer });
}

function waitForIce(pc) {
  if (pc.iceGatheringState === "complete") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const handle = () => {
      if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", handle);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", handle);
  });
}

function teardownPlayback() {
  if (state.currentPlayback?.pc) {
    state.currentPlayback.pc.close();
  }
  state.currentPlayback = null;
}

function startPolling() {
  if (state.pollHandle) {
    clearInterval(state.pollHandle);
  }
  const intervalMs = Math.max((state.config?.stream_list_poll_interval || 5) * 1000, 3000);
  state.pollHandle = setInterval(() => {
    loadStreams().catch(() => {
      playerState.className = "badge danger";
      playerState.textContent = "Error";
    });
  }, intervalMs);
}

function resetSession() {
  state.viewerToken = null;
  state.profile = null;
  state.config = null;
  state.autoPlayConsumed = false;
  sessionStorage.removeItem("viewerToken");
  viewerPanel.classList.add("hidden");
}

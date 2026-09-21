"use strict";

const $ = (id) => document.getElementById(id);
const ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"];
const sourceNames = {player: "Your hand", dealer_up: "Dealer up-card", dealer_hole: "Dealer revealed", other: "Other / exposed"};
let state = null;
let connected = false;
let busy = false;
let rulesDirty = false;
let toastTimer;
let fixingCard = null;
let socket;
let reconnectTimer;
let reconnectDelay = 1000;
let stream = null;
let fileURL = null;
let cameraMode = null;
let cameraGeneration = 0;
let cameraStarting = false;

function hiLo(rank) { return ["2", "3", "4", "5", "6"].includes(rank) ? 1 : ["7", "8", "9"].includes(rank) ? 0 : -1; }
function signed(number, digits = 0) { return `${number > 0 ? "+" : ""}${number.toFixed(digits)}`; }
function rankClass(rank) { return hiLo(rank) > 0 ? "low" : hiLo(rank) < 0 ? "high" : "neutral"; }
function notify(message, error = false) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").className = error ? "error" : "";
  $("toast").hidden = false;
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 9000 : 3500);
}

function setControls() {
  const disabled = !connected || busy;
  $("entry-controls").disabled = disabled;
  $("rules-controls").disabled = disabled;
  $("new-hand").disabled = disabled;
  $("new-shoe").disabled = disabled;
  $("undo").disabled = disabled || !state?.can_undo;
  document.querySelectorAll(".recent-row button").forEach((button) => { button.disabled = disabled; });
  $("fix-form").querySelector("button[type=submit]").disabled = disabled;
}

async function request(path, body, method = "POST") {
  const response = await fetch(path, {method, headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  let payload;
  try { payload = await response.json(); } catch { throw new Error(`Server returned ${response.status}. Please reconnect.`); }
  if (!response.ok) {
    const detail = Array.isArray(payload.detail) ? payload.detail.map((item) => item.msg).join("; ") : payload.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return payload;
}

async function mutate(path, body, method = "POST") {
  if (!connected || busy) return false;
  busy = true;
  setControls();
  $("save-status").textContent = "Saving…";
  try {
    render(await request(path, body, method));
    $("save-status").textContent = "Saved on this laptop";
    return true;
  } catch (error) {
    $("save-status").textContent = "Not saved — try again";
    notify(error.message, true);
    return false;
  } finally { busy = false; setControls(); }
}

function cardElement(rank) {
  const element = document.createElement("span");
  element.className = `playing-card ${rankClass(rank)}`;
  element.dataset.rank = rank;
  element.textContent = rank;
  element.setAttribute("aria-label", rank);
  return element;
}

function drawCards(container, cards, emptyCount) {
  container.replaceChildren(...cards.map(cardElement));
  if (!cards.length) {
    for (let index = 0; index < emptyCount; index++) {
      const placeholder = document.createElement("span");
      placeholder.className = "card-placeholder";
      placeholder.textContent = "—";
      container.append(placeholder);
    }
  }
}

function renderHand() {
  if (!state) return;
  const handId = $("hand-id").value;
  const hand = state.player_hands.find((item) => item.id === handId) || {cards: [], total: 0};
  drawCards($("player-cards"), hand.cards, 2);
  drawCards($("dealer-cards"), state.dealer_cards, 1);
  $("player-label").textContent = `YOUR HAND${handId === "1" ? "" : ` ${handId}`}`;
  $("dealer-description").textContent = state.dealer_blackjack ? "Blackjack" : state.dealer_up ? `Up-card ${state.dealer_up}` : "Waiting for up-card";
  $("hand-total").textContent = hand.cards.length ? `${hand.total} · ${hand.soft ? "Soft" : "Hard"}` : "—";
  $("hand-hint").textContent = hand.bust ? "Bust. Start the next hand when the round ends." : hand.blackjack ? "A natural blackjack." : hand.from_split ? "Split hand · a two-card 21 is not a natural." : hand.cards.length >= 2 ? "Basic strategy assumes the dealer has checked for blackjack." : "Add your first two cards to get a recommendation.";
  const descriptions = {
    HIT: "Take another card, then add its rank to your hand.",
    STAND: "Keep your total. Enter other exposed cards as the round finishes.",
    DOUBLE: "Double your wager and take exactly one more card.",
    SPLIT: "Separate the pair into two hands. Use Fix to move a card and mark both hands as split.",
    SURRENDER: "Give up this hand for half your wager, after the dealer checks for blackjack.",
  };
  let title = "Ready when you are.";
  let detail = "Add your hand and the dealer’s up-card to see the recommended play.";
  if (state.dealer_blackjack) { title = "Dealer blackjack"; detail = "This round is complete. A player natural pushes."; }
  else if (hand.bust) { title = "Bust"; detail = "Keep counting the other exposed cards, then move to the next hand."; }
  else if (hand.blackjack) { title = "Blackjack"; detail = "A natural 21. Resolve the dealer’s hand before starting the next round."; }
  else if (hand.total === 21) { title = "21 · Stand"; detail = "Your hand is complete."; }
  else if (hand.from_split && hand.cards[0] === "A" && hand.cards.length >= 2) { title = "Stand"; detail = "Split aces receive one card each under these rules."; }
  else if (hand.action) { title = hand.action; detail = descriptions[hand.action]; }
  $("recommended-action").textContent = title;
  $("action-detail").textContent = detail;
  $("action-symbol").textContent = {HIT: "+", STAND: "—", DOUBLE: "×2", SPLIT: "⑂", SURRENDER: "↩"}[hand.action] || "↗";
}

function renderRecent() {
  $("recent-empty").hidden = state.recent_cards.length > 0;
  $("recent-list").replaceChildren();
  for (const card of state.recent_cards) {
    const row = document.createElement("div");
    row.className = "recent-row";
    const rank = document.createElement("span");
    rank.className = "mini-card";
    rank.textContent = card.rank;
    const description = document.createElement("div");
    description.className = "recent-description";
    description.textContent = sourceNames[card.source];
    const meta = document.createElement("small");
    meta.textContent = `Round ${card.hand_number} · Hand ${card.hand_id}${card.from_split ? " · split" : ""}`;
    description.append(meta);
    const count = document.createElement("span");
    count.className = "count-value";
    count.textContent = signed(hiLo(card.rank));
    const fix = document.createElement("button");
    fix.textContent = "Fix";
    fix.setAttribute("aria-label", `Fix ${card.rank} from ${sourceNames[card.source]}`);
    fix.addEventListener("click", () => openFix(card));
    const remove = document.createElement("button");
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${card.rank} from ${sourceNames[card.source]}`);
    remove.addEventListener("click", () => mutate("/api/remove-card", {card_id: card.id}));
    row.append(rank, description, count, fix, remove);
    $("recent-list").append(row);
  }
}

function renderConfig(config) {
  $("rule-decks").value = String(config.decks);
  $("rule-h17").value = String(config.dealer_hits_soft_17);
  $("rule-das").checked = config.double_after_split;
  $("rule-surrender").checked = config.surrender;
  $("rule-rounding").value = config.rounding;
  $("rule-penetration").value = String(config.penetration * 100);
  $("penetration-output").textContent = `${Math.round(config.penetration * 100)}%`;
}

function render(next) {
  if (state && next.revision < state.revision) return;
  state = next;
  $("running-count").textContent = signed(state.running_count);
  $("true-count").textContent = state.true_count === null ? "—" : signed(state.true_count, state.config.rounding === "none" ? 1 : 0);
  $("rounding-label").textContent = {none: "Unrounded", floor: "Rounded down", round: "Nearest integer"}[state.config.rounding];
  $("cards-seen").textContent = state.cards_seen;
  $("decks-left").textContent = state.decks_remaining.toFixed(2);
  $("shoe-progress").value = state.penetration;
  $("shoe-progress-label").textContent = `${Math.round(state.penetration * 100)}% of shoe seen`;
  $("shuffle-label").textContent = `Shuffle at ${Math.round(state.config.penetration * 100)}%`;
  $("shuffle-warning").hidden = !state.shuffle_due;
  $("session-number").textContent = `SHOE ${String(state.shoe_number).padStart(2, "0")}`;
  $("hand-number").textContent = `Hand ${String(state.hand_number).padStart(2, "0")}`;
  $("rules-summary").textContent = `${state.config.decks} decks · ${state.config.dealer_hits_soft_17 ? "H17" : "S17"} · ${state.config.double_after_split ? "DAS" : "No DAS"} · ${state.config.surrender ? "Late surrender" : "No surrender"}`;
  if (!rulesDirty) renderConfig(state.config);
  renderHand();
  renderRecent();
  setControls();
  if (cameraMode === "opencv" && state.camera) updateServerCamera(state.camera);
}

function connect() {
  clearTimeout(reconnectTimer);
  socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws`);
  socket.onmessage = (event) => {
    if (!connected) state = null;
    connected = true;
    reconnectDelay = 1000;
    $("connection").classList.add("online");
    $("connection").lastElementChild.textContent = "Session connected";
    $("connection-warning").hidden = true;
    render(JSON.parse(event.data));
  };
  socket.onclose = () => {
    connected = false;
    $("connection").classList.remove("online");
    $("connection").lastElementChild.textContent = "Reconnecting…";
    $("connection-warning").hidden = false;
    setControls();
    reconnectTimer = setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 10000);
  };
  socket.onerror = () => socket.close();
}

function addCard(rank) {
  return mutate("/api/card", {rank, source: $("card-source").value, hand_id: $("hand-id").value, from_split: $("card-source").value === "player" && $("from-split").checked});
}
for (const rank of ranks) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `rank-button ${rankClass(rank)}`;
  button.textContent = rank;
  button.setAttribute("aria-label", `Add ${rank}`);
  button.addEventListener("click", () => addCard(rank));
  $("rank-buttons").append(button);
  $("fix-rank").add(new Option(rank, rank));
}
$("hand-id").addEventListener("change", () => {
  const existing = state?.player_hands.find((hand) => hand.id === $("hand-id").value);
  $("from-split").checked = existing?.from_split || $("hand-id").value !== "1";
  renderHand();
});
$("new-hand").addEventListener("click", async () => {
  if (await mutate("/api/new-hand")) { $("hand-id").value = "1"; $("from-split").checked = false; renderHand(); }
});
$("undo").addEventListener("click", () => mutate("/api/undo"));
$("new-shoe").addEventListener("click", async () => {
  if (!state?.cards_seen || confirm("Start a fresh shoe and reset the count? You can undo this.")) {
    if (await mutate("/api/new-shoe")) { $("hand-id").value = "1"; $("from-split").checked = false; renderHand(); }
  }
});
$("rules-form").addEventListener("input", () => { rulesDirty = true; $("penetration-output").textContent = `${$("rule-penetration").value}%`; });
$("rules-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const config = {decks: Number($("rule-decks").value), dealer_hits_soft_17: $("rule-h17").value === "true", double_after_split: $("rule-das").checked, surrender: $("rule-surrender").checked, rounding: $("rule-rounding").value, penetration: Number($("rule-penetration").value) / 100};
  const changedDecks = config.decks !== state.config.decks;
  if (changedDecks && !confirm("Changing decks starts a new shoe. Continue?")) return;
  if (await mutate("/api/config", config, "PUT")) {
    rulesDirty = false;
    renderConfig(state.config);
    if (changedDecks) { $("hand-id").value = "1"; $("from-split").checked = false; renderHand(); }
    notify("Table rules saved.");
  }
});
function openFix(card) {
  fixingCard = card;
  $("fix-rank").value = card.rank;
  $("fix-source").value = card.source;
  $("fix-hand").value = card.hand_id;
  $("fix-split").checked = card.from_split;
  $("fix-dialog").showModal();
}
$("fix-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!fixingCard) return;
  if (await mutate("/api/card", {rank: $("fix-rank").value, source: $("fix-source").value, hand_id: $("fix-hand").value, from_split: $("fix-split").checked, replaces: fixingCard.id})) { $("fix-dialog").close(); fixingCard = null; }
});
$("help-button").addEventListener("click", () => $("help-dialog").showModal());
document.querySelectorAll(".close-dialog").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
document.addEventListener("keydown", (event) => {
  if (event.repeat || event.metaKey || event.ctrlKey || event.altKey || document.querySelector("dialog[open]") || /INPUT|SELECT|TEXTAREA|BUTTON/.test(event.target.tagName)) return;
  const key = event.key.toUpperCase();
  if (ranks.includes(key) || key === "0" || key === "T") { event.preventDefault(); addCard(key === "0" || key === "T" ? "10" : key); }
  else if (key === "U") { event.preventDefault(); $("undo").click(); }
  else if (key === "N") { event.preventDefault(); $("new-hand").click(); }
});

function cameraView(active, message, starting = false) {
  cameraStarting = starting;
  $("camera-badge").textContent = starting ? "CONNECTING" : active ? "PREVIEW ON" : "CAMERA OFF";
  $("camera-badge").classList.toggle("active", active);
  $("preview-dot").classList.toggle("active", active);
  $("preview-label").textContent = active ? "LOCAL PREVIEW" : "PREVIEW READY";
  $("camera-empty").hidden = active;
  $("camera-message").textContent = message;
  $("start-camera").disabled = starting;
  $("camera-toggle").textContent = active || starting ? "Stop preview" : "Start preview";
}

function releaseLocalCamera() {
  if (stream) { stream.getTracks().forEach((track) => track.stop()); stream = null; }
  $("preview").pause();
  $("preview").srcObject = null;
  $("preview").removeAttribute("src");
  $("preview").load();
  $("preview").hidden = true;
  $("preview").controls = false;
  $("server-preview").hidden = true;
  $("server-preview").removeAttribute("src");
  if (fileURL) { URL.revokeObjectURL(fileURL); fileURL = null; }
}

async function stopCamera() {
  ++cameraGeneration;
  const oldMode = cameraMode;
  cameraMode = null;
  releaseLocalCamera();
  cameraView(false, "Preview stopped. Manual card entry is always available.");
  if (oldMode === "opencv") {
    try { await request("/api/camera/stop"); } catch (error) { notify(`Could not stop the server camera: ${error.message}`, true); }
  }
}

async function refreshDevices() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  try {
    const selected = $("camera-device").value;
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter((device) => device.kind === "videoinput");
    $("camera-device").replaceChildren(new Option("Default webcam", ""));
    devices.forEach((device, index) => $("camera-device").add(new Option(device.label || `Webcam ${index + 1}`, device.deviceId)));
    if ([...$("camera-device").options].some((option) => option.value === selected)) $("camera-device").value = selected;
  } catch { /* Device names are optional until camera permission is granted. */ }
}

async function startCamera() {
  await stopCamera();
  const generation = cameraGeneration;
  const source = $("camera-source").value;
  if (source === "file") { $("video-file").click(); return; }
  cameraMode = source;
  cameraView(false, source === "browser" ? "Allow camera access in your browser. No microphone access is requested." : "Opening the local OpenCV camera…", true);
  try {
    if (source === "opencv") {
      if (!connected) throw new Error("Connect to the local server before starting OpenCV.");
      const result = await request("/api/camera/start", {index: Number($("camera-index").value)});
      if (generation !== cameraGeneration) {
        if (cameraMode !== "opencv") await request("/api/camera/stop");
        return;
      }
      updateServerCamera(result);
    } else {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera access is unavailable here. Open http://localhost:8000 in Chrome, Edge, Firefox, or Safari.");
      const device = $("camera-device").value;
      const acquired = await navigator.mediaDevices.getUserMedia({audio: false, video: {width: {ideal: 1280}, height: {ideal: 720}, ...(device ? {deviceId: {exact: device}} : {})}});
      if (generation !== cameraGeneration) { acquired.getTracks().forEach((track) => track.stop()); return; }
      stream = acquired;
      $("preview").srcObject = acquired;
      await $("preview").play();
      if (generation !== cameraGeneration) return;
      $("preview").hidden = false;
      cameraView(true, "Webcam is live. Preview only — enter visible cards below to update counts. No video is saved or uploaded.");
      acquired.getVideoTracks()[0].addEventListener("ended", () => { if (stream === acquired) stopCamera(); });
      await refreshDevices();
    }
  } catch (error) {
    if (generation !== cameraGeneration) return;
    releaseLocalCamera();
    cameraMode = null;
    const messages = {NotAllowedError: "Camera permission was denied. Allow camera access for localhost in your browser and operating-system settings, then try again.", NotFoundError: "No webcam found. Connect one or choose a recorded video.", NotReadableError: "The webcam could not be opened. Close other camera apps and try again.", OverconstrainedError: "That webcam is unavailable. Choose Default webcam and try again."};
    const message = messages[error.name] || error.message;
    cameraView(false, message);
    notify(message, true);
  }
}

function updateServerCamera(camera) {
  if (cameraMode !== "opencv") return;
  if (camera.status === "running") {
    if (!$("server-preview").getAttribute("src")) $("server-preview").src = `/video_feed?session=${Date.now()}`;
    $("server-preview").hidden = false;
    cameraView(true, "OpenCV preview is live. Outlines show card-shaped objects; ranks are not recognized or counted yet.");
  } else if (camera.status === "starting") cameraView(false, "Opening webcam… If prompted, allow camera access for the terminal running Python.", true);
  else if (camera.status === "error" || camera.status === "ended") {
    releaseLocalCamera();
    cameraView(false, camera.message || "The camera stream ended.");
    cameraMode = null;
  } else if (camera.status === "stopped" && !cameraStarting) {
    releaseLocalCamera();
    cameraView(false, "The OpenCV preview was stopped.");
    cameraMode = null;
  }
}

$("start-camera").addEventListener("click", startCamera);
$("camera-toggle").addEventListener("click", () => cameraMode || cameraStarting ? stopCamera() : startCamera());
$("camera-source").addEventListener("change", async () => {
  await stopCamera();
  const source = $("camera-source").value;
  $("camera-device").hidden = source !== "browser";
  $("camera-index-label").hidden = source !== "opencv";
  $("video-file-label").hidden = source !== "file";
  $("start-camera").textContent = source === "file" ? "Choose a video ↗" : "Enable webcam ↗";
});
$("camera-device").addEventListener("change", () => { if (cameraMode === "browser") startCamera(); });
$("video-file").addEventListener("change", async () => {
  const file = $("video-file").files[0];
  if (!file) return;
  await stopCamera();
  cameraMode = "file";
  fileURL = URL.createObjectURL(file);
  $("preview").src = fileURL;
  $("preview").controls = true;
  $("preview").hidden = false;
  cameraView(true, `Playing ${file.name} locally. Pause to enter cards. Nothing is uploaded.`);
  try { await $("preview").play(); } catch (error) { if (error.name !== "NotAllowedError") cameraView(false, "This video could not be played. Try a browser-compatible MP4 or WebM file."); }
  $("video-file").value = "";
});
$("preview").addEventListener("error", () => { if (cameraMode === "file") { stopCamera(); notify("Unable to decode this video. Try an MP4 or WebM file.", true); } });
navigator.mediaDevices?.addEventListener("devicechange", refreshDevices);
window.addEventListener("pagehide", () => { ++cameraGeneration; releaseLocalCamera(); });
connect();

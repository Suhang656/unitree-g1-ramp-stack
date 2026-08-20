const state = {
  token: localStorage.getItem("g1-control-token") || "",
  commands: [],
  localized: false,
  tourOnline: false,
  selected: null,
  activeTasks: new Map(),
  markingWaypoint: false,
  tourConfig: null,
  pendingTourPoint: null,
};

const $ = (selector) => document.querySelector(selector);
const tokenGate = $("#token-gate");
const confirmModal = $("#confirm-modal");
const tourConfirmModal = $("#tour-confirm-modal");
const log = $("#activity-log");

function headers() {
  return { "Content-Type": "application/json", "X-G1-Control-Token": state.token };
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (response.status === 401) {
    tokenGate.classList.add("visible");
    throw new Error("访问令牌无效");
  }
  if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("visible"), 2600);
}

function addLog(label, result) {
  if (log.querySelector(".muted")) log.innerHTML = "";
  const row = document.createElement("div");
  const status = result.state || (result.accepted ? "queued" : "unknown");
  row.className = `log-row ${status}`;
  const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  row.innerHTML = `<time>${time}</time><strong></strong><span class="state"></span>`;
  row.querySelector("strong").textContent = label;
  row.querySelector(".state").textContent = result.error || result.reason || result.phase || status;
  log.prepend(row);
}

function renderCommands() {
  const targets = { ramp: $("#ramp-actions"), mode: $("#mode-actions"), gesture: $("#gesture-actions") };
  Object.values(targets).forEach((node) => { node.innerHTML = ""; });
  for (const command of state.commands) {
    const button = document.createElement("button");
    button.className = `action-card${command.warning ? " warning" : ""}`;
    button.dataset.commandId = command.id;
    button.dataset.category = command.category;
    button.innerHTML = `<span class="card-kicker">${command.category.toUpperCase()}</span><strong></strong><small></small>`;
    button.querySelector("strong").textContent = command.label;
    button.querySelector("small").textContent = command.description;
    button.addEventListener("click", () => openConfirm(command));
    targets[command.category].appendChild(button);
  }
  updateAvailability();
}

function updateAvailability() {
  document.querySelectorAll('[data-category="ramp"]').forEach((button) => {
    button.disabled = !state.localized;
    button.title = state.localized ? "" : "本次开机全局定位尚未成功";
  });
  const start = $("#start-tour");
  if (start) start.disabled = !state.localized || !state.tourOnline || !state.tourConfig;
}

function openConfirm(command) {
  state.selected = command;
  $("#confirm-title").textContent = command.label;
  $("#confirm-description").textContent = command.description;
  confirmModal.classList.add("visible");
}

function closeConfirm() {
  state.selected = null;
  confirmModal.classList.remove("visible");
}

async function sendAction(commandId, confirmed = true) {
  const command = state.commands.find((item) => item.id === commandId);
  const label = command?.label || "立即停止";
  try {
    const result = await api("/api/actions", {
      method: "POST",
      body: JSON.stringify({ command_id: commandId, confirmed }),
    });
    addLog(label, result);
    if (result.task_id) state.activeTasks.set(result.task_id, { label, startedAt: Date.now(), timeoutMs: 180000, type: "action" });
    toast(`${label}已发送`);
  } catch (error) {
    addLog(label, { state: "error", error: error.message });
    toast(error.message);
  }
}

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    const bridge = $("#bridge-status");
    bridge.className = `pill ${status.online ? "online" : "offline"}`;
    bridge.innerHTML = `<i></i>${status.online ? "运动桥在线" : "运动桥离线"}`;
    const location = $("#location-status");
    location.className = `pill ${status.localized ? "ready" : "waiting"}`;
    location.innerHTML = `<i></i>${status.localized ? "全局定位成功" : "等待定位"}`;
    state.localized = status.localized;
    state.tourOnline = Boolean(status.tour_online);
    $("#tour-online-state").textContent = state.tourOnline ? "导览执行器在线" : "导览执行器离线";
    const markButton = $("#mark-waypoint");
    if (markButton) markButton.disabled = !status.localized || state.markingWaypoint;
    const addTourButton = $("#tour-add-button");
    if (addTourButton && addTourButton.textContent !== "正在采集50帧稳定定位…") {
      addTourButton.disabled = !status.localized;
    }
    updateAvailability();
    const odom = status.odom || status.pose || {};
    $("#pose-x").textContent = Number.isFinite(Number(odom.x)) ? Number(odom.x).toFixed(3) : "--";
    $("#pose-y").textContent = Number.isFinite(Number(odom.y)) ? Number(odom.y).toFixed(3) : "--";
    $("#odom-age").textContent = Number.isFinite(status.odom_age_seconds) ? `${status.odom_age_seconds.toFixed(2)} s` : "--";
    if (status.latest_result?.state) $("#task-state").textContent = status.latest_result.phase || status.latest_result.state;
  } catch (_) {}
}

function renderWaypoints(waypoints) {
  const list = $("#waypoint-list");
  list.innerHTML = "";
  if (!waypoints.length) {
    list.innerHTML = '<p class="muted">尚未标记导览点</p>';
    return;
  }
  for (const waypoint of waypoints) {
    const row = document.createElement("div");
    row.className = "waypoint-row";
    row.innerHTML = '<div><strong></strong><small></small></div><span></span>';
    row.querySelector("strong").textContent = waypoint.name;
    row.querySelector("small").textContent = `X ${Number(waypoint.x).toFixed(3)} · Y ${Number(waypoint.y).toFixed(3)}`;
    const degrees = Number(waypoint.yaw_degrees);
    row.querySelector("span").textContent = Number.isFinite(degrees) ? `${degrees.toFixed(1)}°` : "--";
    list.appendChild(row);
  }
}

async function refreshWaypoints() {
  try {
    const data = await api("/api/waypoints");
    renderWaypoints(data.waypoints || []);
  } catch (error) { toast(error.message); }
}

async function markWaypoint(event) {
  event.preventDefault();
  if (state.markingWaypoint) return;
  const name = $("#waypoint-name").value.trim();
  if (!name) return;
  if (!window.confirm(`确认将当前位置标记为“${name}”？\n\n请确认 G1 已站直、静止，并保持讲解朝向。`)) return;
  state.markingWaypoint = true;
  const button = $("#mark-waypoint");
  button.disabled = true;
  button.textContent = "等待连续50帧稳定定位…";
  try {
    await api("/api/waypoints/mark", { method: "POST", body: JSON.stringify({ name }) });
    addLog(`标记点位 ${name}`, { state: "completed" });
    toast(`点位 ${name} 已保存`);
    $("#waypoint-name").value = "";
    await refreshWaypoints();
  } catch (error) {
    addLog(`标记点位 ${name}`, { state: "error", error: error.message });
    toast(error.message);
  } finally {
    state.markingWaypoint = false;
    button.textContent = "标记当前位置";
    button.disabled = !state.localized;
  }
}

function renderTourEditor() {
  const editor = $("#tour-editor");
  editor.innerHTML = "";
  if (!state.tourConfig) {
    editor.innerHTML = '<p class="muted">尚未读取导览配置</p>';
    return;
  }
  state.tourConfig.order.forEach((name, index) => {
    const station = state.tourConfig.stations[name];
    const point = state.tourConfig.points[name];
    const card = document.createElement("div");
    card.className = "tour-station";
    card.dataset.pointName = name;
    card.innerHTML = `<div class="tour-order"><button class="move-up" type="button">↑</button><strong>${index + 1}</strong><button class="move-down" type="button">↓</button></div><div class="tour-station-fields"><div class="tour-station-meta"><div><strong>${name}</strong><button class="tour-delete" type="button">删除</button></div><span></span></div><input class="station-title" maxlength="40"><textarea class="station-speech" maxlength="1000"></textarea></div>`;
    card.querySelector(".tour-station-meta span").textContent = `X ${Number(point.x).toFixed(3)} · Y ${Number(point.y).toFixed(3)}${point.ramp_demo ? " · 固定坡道展示" : ""}`;
    card.querySelector(".station-title").value = station.display_name;
    card.querySelector(".station-speech").value = station.speech;
    card.querySelector(".move-up").disabled = index === 0;
    card.querySelector(".move-down").disabled = index === state.tourConfig.order.length - 1;
    const deleteButton = card.querySelector(".tour-delete");
    deleteButton.disabled = name === "guide_1";
    deleteButton.title = name === "guide_1" ? "guide_1是坡道待命安全点，不能删除" : "软删除该导览点";
    card.querySelector(".move-up").addEventListener("click", () => moveTourStation(index, -1));
    card.querySelector(".move-down").addEventListener("click", () => moveTourStation(index, 1));
    deleteButton.addEventListener("click", () => deleteTourStation(name));
    editor.appendChild(card);
  });
}

function captureTourEditor() {
  if (!state.tourConfig) return;
  document.querySelectorAll(".tour-station").forEach((card) => {
    const name = card.dataset.pointName;
    state.tourConfig.stations[name] = {
      display_name: card.querySelector(".station-title").value.trim(),
      speech: card.querySelector(".station-speech").value.trim(),
    };
  });
}

function moveTourStation(index, delta) {
  captureTourEditor();
  const target = index + delta;
  if (target < 0 || target >= state.tourConfig.order.length) return;
  const order = state.tourConfig.order;
  [order[index], order[target]] = [order[target], order[index]];
  renderTourEditor();
}

async function loadTourConfig() {
  try {
    state.tourConfig = await api("/api/tour/config");
    renderTourEditor();
    updateAvailability();
  } catch (error) {
    $("#tour-editor").innerHTML = `<p class="error-text"></p>`;
    $("#tour-editor .error-text").textContent = error.message;
  }
}

async function saveTourConfig() {
  if (!state.tourConfig) return;
  captureTourEditor();
  try {
    state.tourConfig = await api("/api/tour/config", {
      method: "POST",
      body: JSON.stringify({ order: state.tourConfig.order, stations: state.tourConfig.stations }),
    });
    renderTourEditor();
    toast("导览顺序和讲解内容已保存");
  } catch (error) { toast(error.message); }
}

async function addTourStation(event) {
  event.preventDefault();
  const name = $("#tour-new-name").value.trim();
  const displayName = $("#tour-new-title").value.trim();
  const speech = $("#tour-new-speech").value.trim();
  if (!name || !displayName || !speech) return;
  if (!window.confirm(`确认现场采集“${name}”？\n\n请确认 G1 已站直、静止并保持讲解朝向。采集将持续到获得50帧稳定定位。`)) return;
  const button = $("#tour-add-button");
  button.disabled = true;
  button.textContent = "正在采集50帧稳定定位…";
  try {
    const result = await api("/api/tour/stations/add", {
      method: "POST",
      body: JSON.stringify({ name, display_name: displayName, speech }),
    });
    state.tourConfig = result.config;
    renderTourEditor();
    await refreshWaypoints();
    $("#tour-new-name").value = "";
    $("#tour-new-title").value = "";
    $("#tour-new-speech").value = "";
    addLog(`新增导览点 ${name}`, { state: "completed" });
    toast(`导览点 ${name} 已采集并加入路线`);
  } catch (error) {
    addLog(`新增导览点 ${name}`, { state: "error", error: error.message });
    toast(error.message);
  } finally {
    button.disabled = !state.localized;
    button.textContent = "采集50帧实时点位并加入路线";
  }
}

async function deleteTourStation(name) {
  if (name === "guide_1") return;
  if (!window.confirm(`确认从导览路线删除“${name}”？\n\n点位文件会被软归档，可以从 G1 备份中恢复。`)) return;
  try {
    const result = await api("/api/tour/stations/delete", {
      method: "POST",
      body: JSON.stringify({ point_name: name, confirmed: true }),
    });
    state.tourConfig = result.config;
    renderTourEditor();
    await refreshWaypoints();
    addLog(`删除导览点 ${name}`, { state: "completed" });
    toast(`导览点 ${name} 已从路线移除`);
  } catch (error) { toast(error.message); }
}

function resetTourDisplay() {
  for (const [taskId, task] of [...state.activeTasks.entries()]) {
    if (task.type === "tour") state.activeTasks.delete(taskId);
  }
  localStorage.removeItem("g1-active-tour-task");
  localStorage.removeItem("g1-tour-next-index");
  state.pendingTourPoint = null;
  $("#tour-progress").textContent = "导览任务显示已清除，可重新开始";
  $("#continue-tour").disabled = true;
  toast("已清除浏览器中的旧导览任务显示");
}

function openTourConfirm(pointName) {
  if (!state.tourConfig || !state.tourConfig.order.includes(pointName)) return;
  state.pendingTourPoint = pointName;
  const station = state.tourConfig.stations[pointName];
  const number = state.tourConfig.order.indexOf(pointName) + 1;
  $("#tour-confirm-title").textContent = `第 ${number} 站：${station.display_name}`;
  $("#tour-confirm-description").textContent = `目标点 ${pointName}。到达后先执行 Please 示教动作，再播报已保存的讲解内容。`;
  tourConfirmModal.classList.add("visible");
  $("#continue-tour").disabled = false;
}

function closeTourConfirm() { tourConfirmModal.classList.remove("visible"); }

async function sendTourVisit() {
  const pointName = state.pendingTourPoint;
  closeTourConfirm();
  if (!pointName || !state.tourConfig) return;
  const station = state.tourConfig.stations[pointName];
  const label = `导览：${station.display_name}`;
  try {
    const result = await api("/api/tour/visit", {
      method: "POST",
      body: JSON.stringify({ point_name: pointName, confirmed: true }),
    });
    addLog(label, result);
    state.activeTasks.set(result.task_id, { label, pointName, startedAt: Date.now(), timeoutMs: 1800000, type: "tour" });
    localStorage.setItem("g1-active-tour-task", JSON.stringify({ taskId: result.task_id, label, pointName, startedAt: Date.now() }));
    $("#tour-progress").textContent = `正在执行 ${station.display_name}`;
    $("#continue-tour").disabled = true;
    toast(`${station.display_name}已交给 G1 本机执行`);
  } catch (error) {
    addLog(label, { state: "error", error: error.message });
    toast(error.message);
  }
}

function startTour() {
  if (!state.tourConfig) return;
  localStorage.setItem("g1-tour-next-index", "0");
  openTourConfirm(state.tourConfig.order[0]);
}

function offerNextTourPoint(completedPoint) {
  if (!state.tourConfig) return;
  const currentIndex = state.tourConfig.order.indexOf(completedPoint);
  const nextIndex = currentIndex + 1;
  if (nextIndex >= state.tourConfig.order.length) {
    localStorage.removeItem("g1-tour-next-index");
    state.pendingTourPoint = null;
    $("#continue-tour").disabled = true;
    $("#tour-progress").textContent = "本轮三个导览点均已完成";
    toast("本轮导览完成");
    return;
  }
  localStorage.setItem("g1-tour-next-index", String(nextIndex));
  $("#tour-progress").textContent = `上一站已完成，等待确认第 ${nextIndex + 1} 站`;
  openTourConfirm(state.tourConfig.order[nextIndex]);
}

function recoverTourTask() {
  const raw = localStorage.getItem("g1-active-tour-task");
  if (!raw) return;
  try {
    const item = JSON.parse(raw);
    if (item.taskId && item.pointName) {
      state.activeTasks.set(item.taskId, { ...item, timeoutMs: 1800000, type: "tour" });
      $("#tour-progress").textContent = `正在恢复 ${item.label} 的执行状态`;
    }
  } catch (_) { localStorage.removeItem("g1-active-tour-task"); }
}

async function pollTasks() {
  for (const [taskId, task] of [...state.activeTasks.entries()]) {
    const label = task.label;
    if (Date.now() - task.startedAt > task.timeoutMs) {
      addLog(label, { state: "timeout", error: "等待结果超时，请检查机器人状态" });
      state.activeTasks.delete(taskId);
      if (task.type === "tour") localStorage.removeItem("g1-active-tour-task");
      continue;
    }
    try {
      const result = await api(`/api/results/${encodeURIComponent(taskId)}`);
      if (result.state === "running" && result.phase) {
        $("#task-state").textContent = result.phase;
        if (task.type === "tour") $("#tour-progress").textContent = `${label}：${result.phase}`;
      }
      if (result.state && result.state !== "queued" && result.state !== "running") {
        addLog(label, result);
        state.activeTasks.delete(taskId);
        if (task.type === "tour") {
          localStorage.removeItem("g1-active-tour-task");
          if (result.state === "completed") offerNextTourPoint(task.pointName);
          else {
            $("#tour-progress").textContent = `${label} 未完成，请检查后重试`;
            state.pendingTourPoint = task.pointName;
            $("#continue-tour").disabled = false;
          }
        }
      }
    } catch (_) {}
  }
}

async function enter() {
  const data = await api("/api/commands");
  state.commands = data.commands;
  localStorage.setItem("g1-control-token", state.token);
  tokenGate.classList.remove("visible");
  renderCommands();
  await refreshStatus();
  await refreshWaypoints();
  await loadTourConfig();
  recoverTourTask();
}

$("#token-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.token = $("#token-input").value.trim();
  $("#token-error").textContent = "";
  try { await enter(); } catch (error) { $("#token-error").textContent = error.message; }
});
$("#cancel-action").addEventListener("click", closeConfirm);
$("#confirm-action").addEventListener("click", async () => {
  const command = state.selected;
  closeConfirm();
  if (command) await sendAction(command.id, true);
});
$("#stop-button").addEventListener("click", () => sendAction("stop", true));
$("#clear-log").addEventListener("click", () => { log.innerHTML = '<p class="muted">执行记录已清空</p>'; });
$("#waypoint-form").addEventListener("submit", markWaypoint);
$("#refresh-waypoints").addEventListener("click", refreshWaypoints);
$("#save-tour").addEventListener("click", saveTourConfig);
$("#tour-add-form").addEventListener("submit", addTourStation);
$("#start-tour").addEventListener("click", startTour);
$("#reset-tour-ui").addEventListener("click", resetTourDisplay);
$("#continue-tour").addEventListener("click", () => {
  const point = state.pendingTourPoint || state.tourConfig?.order[Number(localStorage.getItem("g1-tour-next-index") || 0)];
  if (point) openTourConfirm(point);
});
$("#cancel-tour").addEventListener("click", closeTourConfirm);
$("#confirm-tour").addEventListener("click", sendTourVisit);
confirmModal.addEventListener("click", (event) => { if (event.target === confirmModal) closeConfirm(); });
tourConfirmModal.addEventListener("click", (event) => { if (event.target === tourConfirmModal) closeTourConfirm(); });

if (state.token) enter().catch(() => tokenGate.classList.add("visible"));
setInterval(refreshStatus, 1200);
setInterval(pollTasks, 1200);

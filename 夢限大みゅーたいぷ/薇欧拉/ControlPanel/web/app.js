"use strict";

const $ = (selector) => document.querySelector(selector);
const labels = { action: "动作", expression: "表情", costume: "衣装", voice: "语音", favorites: "收藏" };
const directions = { body: "正面动作", left: "左向动作", right: "右向动作", other: "其他动作" };
const view = {
  library: [], catalog: null, state: null, tab: "action",
  onlyFavorites: false, favoriteCategory: "all", request: 0, model: null,
  app: null, mouthIds: [], mouth: 0, thumbnails: new Map(), visibleVoice: null,
  currentAction: null, currentExpression: null, modelKey: null, volume: null,
  switchingCostume: false, desiredCostume: null, modelReady: Promise.resolve(),
  itemsSignature: "", listContext: "", scrollPositions: new Map(),
};
const audio = new Audio();
audio.preload = "metadata";
let audioContext;
let analyser;
let audioData;
let toastTimer;
let actionTimer;
let audioGeneration = 0;
let thumbnailBusy = false;
let preferenceQueue = Promise.resolve();
const pendingPreferences = new Map();

function preferenceValue(key) {
  return pendingPreferences.has(key) ? pendingPreferences.get(key).value : view.state.settings[key];
}

async function savePreference(key, value) {
  const change = { value };
  pendingPreferences.set(key, change);
  renderState();
  const request = preferenceQueue.then(() => api("preference", { key, value }));
  preferenceQueue = request.catch(() => {});
  try {
    const state = await request;
    if (state.sequence >= view.state.sequence) view.state = state;
  } finally {
    if (pendingPreferences.get(key) === change) pendingPreferences.delete(key);
    renderState();
  }
}

function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").classList.add("visible");
  toastTimer = setTimeout(() => $("#toast").classList.remove("visible"), 3300);
}

async function api(path, data) {
  const response = await fetch(`/api/${path}`, data === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Studio-Request": "1" },
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "操作未能完成，请重试");
  return result;
}

function safely(callback) {
  return (...arguments_) => Promise.resolve(callback(...arguments_)).catch((error) => toast(error.message));
}

function currentCostume() {
  return view.catalog?.costumes.find((costume) => costume.id === view.state?.settings.costume);
}

function itemSymbol(item, kind) {
  const faces = {
    neutral: '<path d="M8 10h.01M16 10h.01M8 16h8"/>',
    smile: '<path d="M8 10h.01M16 10h.01M7 14q5 6 10 0"/>',
    laugh: '<path d="m6 10 2-2 2 2m4 0 2-2 2 2M7 14h10q-5 9-10 0Z"/>',
    angry: '<path d="m6 8 4 2m8-2-4 2M8 12h.01M16 12h.01M8 17q4-4 8 0"/>',
    sad: '<path d="M8 10h.01M16 10h.01M8 17q4-4 8 0m-3-4 1 2-1 1-1-1Z"/>',
    surprise: '<path d="M8 9h.01M16 9h.01"/><ellipse cx="12" cy="16" rx="2" ry="3"/>',
    shy: '<path d="M8 10h.01M16 10h.01M10 16q2 2 4 0M6 13l1 1m10-1 1 1"/>',
    think: '<path d="M7 9h3m4 1h3M8 16h7m2-10 1-2"/>',
    tired: '<path d="M6 10h4m4 0h4M10 16h4"/>',
    confident: '<path d="m6 9 4 1m4 0 4-1M8 15q5 4 9-1"/>',
    wink: '<path d="m6 10 4 1M16 10h.01M8 15q4 4 8 0"/>',
    dizzy: '<path d="M9 9c-4-3-5 4-1 3 2-1 0-3-1-2m9-1c-4-3-5 4-1 3 2-1 0-3-1-2M9 17h6"/>',
    singing: '<path d="M7 9h.01M15 9h.01"/><ellipse cx="11" cy="16" rx="2" ry="3"/><path d="M18 3v5l3-1V2Zm0 5-1 1m4-2-1 1"/>',
    sparkle: '<path d="m8 8 1 2 2 1-2 1-1 2-1-2-2-1 2-1Zm8 0 1 2 2 1-2 1-1 2-1-2-2-1 2-1ZM9 17h6"/>',
    heart: '<path d="M8 10h.01M16 10h.01M8 15q4 4 8 0M19 5c-4-2-1-5 1-3 2-2 5 1 1 3l-1 1Z"/>',
    special: '<path d="M8 10h.01M16 10h.01M9 16h6M20 2v4m-2-2h4"/>',
  };
  const categories = [
    [/眩晕/, 'dizzy'], [/歌唱/, 'singing'], [/眨眼/, 'wink'], [/开怀大笑|大笑|咧嘴笑/, 'laugh'],
    [/生气|气愤|愤怒|不满|厌恶/, 'angry'], [/哭|难过|悲|绝望|寂寞|痛苦/, 'sad'],
    [/惊|震|慌/, 'surprise'], [/害羞|脸红|尴尬/, 'shy'],
    [/自信|得意|冷笑|轻蔑|偷笑|窃笑/, 'confident'], [/微笑|浅笑|笑容|含笑|开心|安心/, 'smile'],
    [/困倦|疲惫|叹气|无聊|泄气/, 'tired'], [/思|困惑|疑|不安|担心|出神|犹豫|忐忑/, 'think'],
    [/心动/, 'heart'], [/爱心眼|闪亮眼/, 'sparkle'], [/特殊|专属|高光|隐藏|阴影|苍白|面具/, 'special'],
  ];
  let paths;
  if (kind === 'expression') {
    const category = categories.find(([pattern]) => pattern.test(item.name))?.[1] || 'neutral';
    paths = '<circle cx="12" cy="12" r="9"/>' + faces[category];
  } else {
    paths = {
      body: '<circle cx="12" cy="5" r="2"/><path d="M12 7v7m-6-4 6 2 6-2m-6 4-4 7m4-7 4 7"/>',
      left: '<path d="m9 6-5 5 5 5M4 11h9q7 0 7 8"/>',
      right: '<path d="m15 6 5 5-5 5m5-5h-9q-7 0-7 8"/>',
      other: '<path d="m4 5 16-2 1 5-16 2ZM5 10v10h16V9M8 5l3 4m3-5 3 4M5 14h16"/>',
    }[item.category || 'other'];
  }
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
}

function favoriteSet() {
  return new Set(view.state?.settings.favorites || []);
}

function itemList(kind) {
  if (!view.catalog) return [];
  if (kind === "voice") return view.catalog.voices;
  if (kind === "costume") return view.catalog.costumes;
  return currentCostume()?.[kind === "action" ? "actions" : "expressions"] || [];
}

function asset(path) {
  return `/assets/${view.catalog.id}/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function receiveVoiceCatalog(result) {
  if (view.catalog.id !== result.catalog.id) return;
  if ((result.catalog.voiceLibraryRevision || 0) < (view.catalog.voiceLibraryRevision || 0)) return;
  view.catalog = result.catalog;
  if (result.state.sequence >= view.state.sequence) view.state = result.state;
  if (view.visibleVoice && !view.catalog.voices.some(item => item.id === view.visibleVoice.id)) stopLocal("voice");
  view.itemsSignature = "";
  renderState();
}

async function prepareVoiceAudio(file) {
  if (file.size > 100 * 1024 * 1024) throw new Error("音频超过 100 MB");
  await enableAudio();
  const decoded = await audioContext.decodeAudioData(await file.arrayBuffer());
  const rate = 44100;
  const frames = Math.ceil(decoded.duration * rate);
  if (!frames || frames * 2 + 44 > 100 * 1024 * 1024) throw new Error("音频为空或超过 100 MB");
  const offline = new OfflineAudioContext(1, frames, rate);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const samples = (await offline.startRendering()).getChannelData(0);
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const data = new DataView(buffer);
  const text = (offset, value) => [...value].forEach((character, index) => data.setUint8(offset + index, character.charCodeAt(0)));
  text(0, "RIFF"); data.setUint32(4, buffer.byteLength - 8, true); text(8, "WAVE");
  text(12, "fmt "); data.setUint32(16, 16, true); data.setUint16(20, 1, true); data.setUint16(22, 1, true);
  data.setUint32(24, rate, true); data.setUint32(28, rate * 2, true); data.setUint16(32, 2, true); data.setUint16(34, 16, true);
  text(36, "data"); data.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, index) => {
    const value = Math.max(-1, Math.min(1, sample));
    data.setInt16(44 + index * 2, value * (value < 0 ? 32768 : 32767), true);
  });
  return buffer;
}

async function uploadVoice(event) {
  event.preventDefault();
  const dialog = $("#voice-upload-dialog");
  const submit = $("#voice-upload-submit");
  const error = $("#voice-upload-error");
  const file = $("#voice-file").files[0];
  if (!file) return;
  const role = dialog.dataset.role;
  const subtitle = $("#voice-caption").value.trim();
  if (!subtitle) { error.textContent = "请输入字幕"; error.hidden = false; return; }
  error.hidden = true;
  submit.disabled = true;
  submit.textContent = "上传中";
  dialog.dataset.busy = "true";
  try {
    const audio = await prepareVoiceAudio(file);
    const response = await fetch("/api/voices/upload", {method: "POST", body: audio, headers: {
      "Content-Type": "audio/wav", "X-Studio-Request": "1",
      "X-Voice-Metadata": encodeURIComponent(JSON.stringify({role, subtitle, filename: file.name})),
    }});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "上传失败");
    receiveVoiceCatalog(result);
    dialog.close();
    $("#voice-upload-form").reset();
  } catch (failure) {
    error.textContent = failure.name === "EncodingError" ? "无法读取音频，请选择其他文件" : failure.message;
    error.hidden = false;
  } finally {
    submit.disabled = false;
    submit.textContent = "上传";
    delete dialog.dataset.busy;
  }
}

function requestVoiceDeletion(item) {
  const dialog = $("#voice-delete-dialog");
  dialog.dataset.role = view.catalog.id;
  dialog.dataset.voice = String(item.id);
  $("#voice-delete-caption").textContent = item.caption || item.name;
  $("#voice-delete-error").hidden = true;
  dialog.showModal();
}

async function deleteVoice(event) {
  event.preventDefault();
  const dialog = $("#voice-delete-dialog");
  const submit = $("#voice-delete-submit");
  const error = $("#voice-delete-error");
  submit.disabled = true;
  dialog.dataset.busy = "true";
  error.hidden = true;
  try {
    receiveVoiceCatalog(await api("voices/delete", {role: dialog.dataset.role, id: Number(dialog.dataset.voice)}));
    dialog.close();
  } catch (failure) {
    error.textContent = failure.message;
    error.hidden = false;
  } finally { submit.disabled = false; delete dialog.dataset.busy; }
}


function makeItem(item, kind, favorites) {
  const card = document.createElement("article");
  card.className = "item-card";
  card.dataset.kind = kind;
  card.dataset.item = String(item.id);
  const playing = kind === "voice" ? view.visibleVoice?.id === item.id : kind === "action" ? view.currentAction?.id === item.id : kind === "expression" ? view.currentExpression === item.id : false;
  card.classList.toggle("playing", playing);
  const wearing = kind === "costume" && item.id === currentCostume().id;
  card.classList.toggle("wearing", wearing);
  const main = document.createElement("button");
  main.className = "item-main";
  main.disabled = Boolean(view.switchingCostume && kind !== "costume");
  main.title = item.name;
  main.setAttribute("aria-label", (kind === "costume" ? "换上" : kind === "expression" ? "应用" : "播放") + item.name);
  main.addEventListener("click", safely(() => playItem(kind, item)));
  const title = document.createElement("strong");
  title.textContent = item.name || `语音 ${item.id + 1}`;
  if (kind === "voice") {
    const play = document.createElement("span");
    play.className = "voice-play";
    play.textContent = playing ? "Ⅱ" : "▶";
    const copy = document.createElement("span");
    copy.className = "voice-copy";
    const detail = document.createElement("small");
    detail.textContent = `${Math.round(item.duration)} 秒`;
    copy.append(title, detail);
    main.append(play, copy);
  } else if (kind === "costume") {
    const picture = document.createElement("span");
    picture.className = "costume-picture";
    picture.dataset.costume = String(item.id);
    const thumbnail = view.thumbnails.get(`${view.catalog.id}:${item.id}`) || item.thumbnail;
    if (thumbnail) {
      const image = document.createElement("img");
      image.src = thumbnail;
      image.alt = item.name;
      image.loading = "lazy";
      image.addEventListener("error", () => {
        item.thumbnail = null;
        view.thumbnails.delete(`${view.catalog.id}:${item.id}`);
        picture.replaceChildren();
        queueVisibleThumbnails();
      }, { once: true });
      picture.append(image);
    } else {
      const symbol = document.createElement("span");
      symbol.className = "item-symbol";
      symbol.textContent = "♧";
      picture.append(symbol);
    }
    main.append(picture, title);
    if (wearing) {
      const tag = document.createElement("span");
      tag.className = "wearing-tag";
      tag.textContent = "当前";
      card.append(tag);
    }
  } else {
    const symbol = document.createElement("span");
    symbol.className = "item-symbol";
    symbol.innerHTML = itemSymbol(item, kind);
    main.append(symbol, title);
    if (kind === "action") {
      const direction = document.createElement("small");
      direction.textContent = directions[item.category];
      main.append(direction);
    }
  }
  const heart = document.createElement("button");
  const enabled = favorites.has(item.flag);
  heart.className = "heart-button" + (enabled ? " favorited" : "");
  heart.textContent = enabled ? "♥" : "♡";
  heart.title = enabled ? "取消收藏" : "添加收藏";
  heart.setAttribute("aria-label", heart.title + " " + item.name);
  heart.setAttribute("aria-pressed", String(enabled));
  heart.addEventListener("click", safely(async () => {
    heart.disabled = true;
    try {
      view.state = await api("favorite", { flag: item.flag, enabled: !favoriteSet().has(item.flag) });
      renderItems();
    } finally { heart.disabled = false; }
  }));
  if (view.tab === "favorites") {
    const type = document.createElement("span");
    type.className = "item-kind";
    type.textContent = labels[kind];
    card.append(type);
  }
  card.append(main, heart);
  if (kind === "voice") {
    const remove = document.createElement("button");
    remove.className = "voice-delete";
    remove.title = "删除语音及字幕";
    remove.setAttribute("aria-label", remove.title);
    remove.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/></svg>';
    remove.addEventListener("click", () => requestVoiceDeletion(item));
    card.append(remove);
  }
  return card;
}

function refreshCards(entries, favorites) {
  const cards = $("#items").children;
  entries.forEach(({ item, kind }, index) => {
    const card = cards[index];
    const playing = kind === "voice" ? view.visibleVoice?.id === item.id : kind === "action" ? view.currentAction?.id === item.id : kind === "expression" && view.currentExpression === item.id;
    card.classList.toggle("playing", Boolean(playing));
    const wearing = kind === "costume" && item.id === currentCostume().id;
    card.classList.toggle("wearing", wearing);
    const main = card.querySelector(".item-main");
    main.disabled = Boolean(view.switchingCostume && kind !== "costume");
    let tag = card.querySelector(".wearing-tag");
    if (wearing && !tag) {
      tag = document.createElement("span");
      tag.className = "wearing-tag";
      tag.textContent = "当前";
      card.append(tag);
    } else if (!wearing) tag?.remove();
    const heart = card.querySelector(".heart-button");
    const enabled = favorites.has(item.flag);
    heart.classList.toggle("favorited", enabled);
    heart.textContent = enabled ? "♥" : "♡";
    heart.title = enabled ? "取消收藏" : "添加收藏";
    heart.setAttribute("aria-label", heart.title + " " + item.name);
    heart.setAttribute("aria-pressed", String(enabled));
    const voice = card.querySelector(".voice-play");
    if (voice) voice.textContent = playing ? "Ⅱ" : "▶";
  });
}

function renderItems() {
  if (!view.catalog || !view.state) return;
  const hasLoop = ["action", "voice", "costume"].includes(view.tab);
  if (hasLoop) view.onlyFavorites = Boolean(preferenceValue(view.tab + "Scope"));
  const favorites = favoriteSet();
  let entries;
  if (view.tab === "favorites") {
    entries = ["action", "expression", "costume", "voice"].flatMap((kind) => itemList(kind).map((item) => ({ item, kind })))
      .filter(({ item, kind }) => favorites.has(item.flag) && (view.favoriteCategory === "all" || kind === view.favoriteCategory));
  } else entries = itemList(view.tab).map((item) => ({ item, kind: view.tab }));
  if (view.onlyFavorites) entries = entries.filter(({ item }) => favorites.has(item.flag));
  const query = $("#item-search").value.trim().toLocaleLowerCase();
  if (query) entries = entries.filter(({ item }) => `${item.name} ${item.caption || ""} ${directions[item.category] || ""}`.toLocaleLowerCase().includes(query));
  const list = $("#items");
  const costumeKey = ["action", "expression", "favorites"].includes(view.tab) ? currentCostume().id : "";
  const context = [view.catalog.id, view.tab, costumeKey, query, view.onlyFavorites, view.favoriteCategory].join("|");
  const signature = context + "|" + entries.map(({ item, kind }) => kind + ":" + item.id + ":" + item.flag).join(",");
  if (view.itemsSignature !== signature) {
    if (view.listContext) view.scrollPositions.set(view.listContext, list.scrollTop);
    list.className = "items " + ({ action: "action-grid", expression: "expression-grid", costume: "costume-grid", voice: "voice-list", favorites: "action-grid" }[view.tab]);
    list.setAttribute("aria-labelledby", "tab-" + view.tab);
    list.replaceChildren(...entries.map(({ item, kind }) => makeItem(item, kind, favorites)));
    list.scrollTop = view.scrollPositions.get(context) || 0;
    view.itemsSignature = signature;
    view.listContext = context;
  } else refreshCards(entries, favorites);
  if (view.tab === "costume") requestAnimationFrame(queueVisibleThumbnails);
  $("#empty").hidden = entries.length > 0;
  $("#items").hidden = entries.length === 0;
  const searching = Boolean(query);
  const favoritesEmpty = view.tab === "favorites" || view.onlyFavorites;
  $("#empty-icon").textContent = searching ? "⌕" : favoritesEmpty ? "♡" : "◇";
  $("#empty-title").textContent = searching ? "无结果" : favoritesEmpty ? "暂无收藏" : `暂无${labels[view.tab]}`;
  $("#empty-reset").hidden = !searching;
  $("#item-search").placeholder = `搜索${labels[view.tab]}`;
  $("#favorites-filter").hidden = view.tab === "favorites";
  $("#favorite-categories").hidden = view.tab !== "favorites";
  $("#clear-expression").hidden = view.tab !== "expression";
  $("#upload-voice").hidden = view.tab !== "voice";
  $("#favorites-filter").classList.toggle("selected", view.onlyFavorites);
  $("#favorites-filter").setAttribute("aria-pressed", String(view.onlyFavorites));
  $("#favorites-filter span").textContent = view.onlyFavorites ? "♥" : "♡";
  $("#favorites-filter").title = hasLoop ? "收藏列表与循环范围" : "收藏表情";
  $("#playback-bar").hidden = !hasLoop;
  const scope = hasLoop && view.onlyFavorites;
  const looping = Boolean(view.state.looping[view.tab]);
  $("#loop").classList.toggle("active", looping);
  $("#loop").setAttribute("aria-pressed", String(looping));
  $("#loop-label").textContent = looping ? "停止循环" : view.tab === "costume" ? "循环换装" : "循环播放";
  const order = preferenceValue(view.tab + "Order") || "random";
  document.querySelectorAll("[data-order]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.order === order);
    button.setAttribute("aria-pressed", String(button.dataset.order === order));
  });
  if (document.activeElement !== $("#loop-interval")) $("#loop-interval").value = preferenceValue(view.tab + "Interval") ?? 0;
  $("#loop-interval").min = view.tab === "costume" ? "1" : "0";
  $("#interval-label").textContent = view.tab === "costume" ? "每套停留" : "结束后等待";
  const playable = itemList(view.tab).some((item) => !scope || favorites.has(item.flag));
  $("#loop").disabled = !playable && !looping;
}

function renderState() {
  if (!view.state || !view.catalog) return;
  const settings = view.state.settings;
  $("#captions-toggle").checked = Boolean(settings.captions);
  $("#body-toggle").checked = Boolean(settings.bodyOnly);
  $("#connect").classList.toggle("connected", view.state.linked);
  $("#connect-label").textContent = view.state.linked ? "桌面已连接" : view.state.reconnecting ? "桌面重连中" : "连接桌面";
  $("#connect").title = view.state.linked ? `控制桌面模型位 ${view.state.slot + 1}` : "将当前角色连接到 Live2DViewerEX";
  if (view.volume) view.volume.gain.value = view.state.linked ? 0 : 1;
  $("#game-name").textContent = view.catalog.game;
  $("#band-name").textContent = view.catalog.group.replace(/（Garupa）/g, "");
  document.title = view.catalog.name.replace(/（Garupa）/g, "") + " · BandoriLove";
  renderItems();
  updatePlaying();
  updateSubtitle();
}

function setTab(tab) {
  view.tab = tab;
  view.onlyFavorites = false;
  $("#item-search").value = "";
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const selected = button.dataset.tab === tab;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    button.setAttribute("aria-controls", "items");
  });
  renderItems();
  updateTabIndicator();
}

function updateTabIndicator() {
  const tab = document.querySelector("[data-tab].selected");
  const indicator = $("#tab-indicator");
  if (!tab || !indicator) return;
  indicator.style.width = tab.offsetWidth + "px";
  indicator.style.transform = `translateX(${tab.offsetLeft}px)`;
}

async function applySelection(state) {
  view.state = state;
  const roleChanged = view.catalog?.id !== state.role;
  if (roleChanged || (view.catalog.voiceLibraryRevision || 0) !== (state.voiceLibraryRevision || 0)) {
    view.catalog = await api("catalog/" + state.role);
    if (roleChanged) view.currentExpression = null;
    view.itemsSignature = "";
    if (roleChanged) $("#item-search").value = "";
  }
  renderState();
  const key = view.catalog.id + ":" + currentCostume().id;
  if (view.modelKey !== key) view.modelReady = loadModel(key);
  await view.modelReady;
}

function resetModelView() {
  if (!view.model || !view.app) return;
  const model = view.model;
  const host = $("#canvas-host");
  const width = host.clientWidth;
  const height = host.clientHeight;
  model.scale.set(1);
  const bounds = model.getLocalBounds();
  const scale = Math.min(width * .9 / bounds.width, height * .94 / bounds.height);
  model.scale.set(scale);
  model.anchor.set(.5, 1);
  model.position.set(width / 2, height * .98);
}

function synchronizeMotionFades(model, metadata = {}) {
  const manager = model.internalModel.motionManager;
  if (metadata.pageMotionFadePolicy === "source" && !metadata.FileReferences && manager.queueManager) {
    // Keep the outgoing SDK2 motion until its source fade finishes, matching
    // Bestdori's MotionQueueManager instead of discarding it at each switch.
    manager._startMotion = (motion, onFinish) => {
      motion.onFinishHandler = onFinish;
      return manager.queueManager.startMotion(motion);
    };
  }
  const apply = (group, index, motion) => {
    if (!motion) return;
    if (metadata.pageMotionFadePolicy === "source") {
      const definitions = metadata.FileReferences?.Motions || metadata.motions;
      const definition = definitions?.[group]?.[index];
      if (!definition) return;
      motion.setFadeIn?.(definition.fade_in);
      motion.setFadeOut?.(definition.fade_out);
      motion.setFadeInTime?.(definition.FadeInTime);
      motion.setFadeOutTime?.(definition.FadeOutTime);
      return;
    }
    motion.setFadeIn?.(0);
    motion.setFadeOut?.(0);
    motion.setFadeInTime?.(0);
    motion.setFadeOutTime?.(0);
  };
  manager.on("motionLoaded", apply);
  for (const [group, motions] of Object.entries(manager.motionGroups)) {
    motions.forEach((motion, index) => apply(group, index, motion));
  }
}

async function loadModel(key) {
  const token = ++view.request;
  view.modelKey = key;
  stopLocal("action");
  stopLocal("voice");
  view.currentExpression = null;
  $("#model-loading").hidden = false;
  $("#stage-error").hidden = true;
  const host = $("#canvas-host");
  view.model = null;
  if (view.app) {
    for (const model of view.app.stage.removeChildren()) {
      model.internalModel?.off("beforeModelUpdate", updateMouth);
      model.destroy({ children: true });
    }
    view.app.renderer.clear();
  }
  try {
    if (!window.PIXI?.live2d) throw new Error("Live2D 预览组件未载入");
    if (!view.app) {
      view.app = new PIXI.Application({ resizeTo: host, backgroundAlpha: 0, clearBeforeRender: true, antialias: true, resolution: Math.min(devicePixelRatio, 2), autoDensity: true, preserveDrawingBuffer: true });
      host.append(view.app.view);
      view.app.renderer.textureGC.maxIdle = 300;
      view.app.renderer.textureGC.checkCountMax = 300;
    }
    const url = `/api/preview/${view.catalog.id}/${currentCostume().id}`;
    const metadata = await fetch(url).then((response) => response.json());
    metadata.url = location.origin + url;
    const model = await PIXI.live2d.Live2DModel.from(metadata, { autoInteract: false, motionPreload: "NONE" });
    synchronizeMotionFades(model, metadata);
    if (token !== view.request) { model.destroy({ children: true }); return; }
    view.model = model;
    view.mouthIds = metadata.pageMouthIds || [];
    view.app.stage.addChild(model);
    model.autoInteract = false;
    resetModelView();
    model.internalModel.on("beforeModelUpdate", updateMouth);
    view.app.renderer.render(view.app.stage, { clear: true });
    host.onpointermove = (event) => {
      if (!view.model || !$("#model-loading").hidden) return;
      const rectangle = host.getBoundingClientRect();
      if (event.clientX < rectangle.left || event.clientX > rectangle.right || event.clientY < rectangle.top || event.clientY > rectangle.bottom) {
        view.model.internalModel.focusController.focus(0, 0);
        return;
      }
      view.model.internalModel.focusController.focus((event.clientX - rectangle.left) / rectangle.width * 2 - 1, 1 - (event.clientY - rectangle.top) / rectangle.height * 2);
    };
    host.onpointerleave = () => view.model?.internalModel.focusController.focus(0, 0);
    host.onpointercancel = host.onpointerleave;
    host.onclick = safely(async (event) => {
      event.stopPropagation();
      if (event.target !== view.app.view) return;
      if (!view.model || !$("#model-loading").hidden) return;
      const rectangle = host.getBoundingClientRect();
      const point = view.model.toModelPosition(new PIXI.Point(event.clientX - rectangle.left, event.clientY - rectangle.top));
      const internal = view.model.internalModel;
      if (currentCostume().cubism3) {
        point.x = (point.x - internal.originalWidth / 2) / internal.pixelsPerUnit;
        point.y = (point.y - internal.originalHeight / 2) / internal.pixelsPerUnit;
      }
      const regions = currentCostume().hitRegions || {};
      const region = ["expression", "voice", "left", "right", "body", "wardrobe", "menu"].find((name) => {
        const box = regions[name];
        return box && point.x >= box[0] && point.x <= box[2] && point.y >= box[1] && point.y <= box[3];
      });
      if (!region) return;
      if (region === "menu") { await api("menu", {}); return; }
      if (region === "voice") await enableAudio();
      const kind = region === "wardrobe" ? "costume" : ["body", "left", "right"].includes(region) ? "action" : region;
      view.state = await api("operate", { kind, random: true, body: true, direction: region });
      if (kind === "costume") await applySelection(view.state);
      else renderState();
    });
    setTimeout(() => {
      if (token !== view.request || !view.model) return;
      captureThumbnail(key);
      if (view.tab === "costume") renderItems();
    }, 1000);
  } catch (error) {
    if (token === view.request) {
      $("#stage-error").hidden = false;
      console.error("Model preview", error);
    }
  } finally {
    if (token === view.request) $("#model-loading").hidden = true;
  }
}

function captureThumbnail(key) {
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 220;
    canvas.height = 330;
    const source = view.app.view;
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    const image = canvas.toDataURL("image/webp", .8);
    view.thumbnails.set(key, image);
    const [role, costume] = key.split(":");
    api("thumbnail", { role, costume: Number(costume), image }).catch((error) => console.debug("Thumbnail cache", error));
    if (view.catalog.id === role) {
      const picture = $("#items").querySelector(`.costume-picture[data-costume="${costume}"]`);
      if (picture) {
        const thumbnail = document.createElement("img");
        thumbnail.src = image;
        thumbnail.alt = currentCostume().name;
        picture.replaceChildren(thumbnail);
      }
    }
    if (view.thumbnails.size > 80) view.thumbnails.delete(view.thumbnails.keys().next().value);
  } catch (error) { console.debug("Thumbnail", error); }
}

async function queueVisibleThumbnails() {
  if (thumbnailBusy || view.switchingCostume || view.tab !== "costume" || !view.app || !view.model || !$("#model-loading").hidden) return;
  const list = $("#items");
  const viewport = list.getBoundingClientRect();
  const candidates = [...list.querySelectorAll(".costume-picture")].filter((element) => {
    const costume = view.catalog.costumes.find((item) => item.id === Number(element.dataset.costume));
    return !costume.thumbnail && !view.thumbnails.has(`${view.catalog.id}:${element.dataset.costume}`);
  });
  const picture = candidates.find((element) => {
    const rectangle = element.getBoundingClientRect();
    return rectangle.bottom > viewport.top && rectangle.top < viewport.bottom + 120;
  });
  if (!picture) return;
  thumbnailBusy = true;
  const role = view.catalog.id;
  const id = Number(picture.dataset.costume);
  let model;
  let texture;
  try {
    const url = `/api/preview/${role}/${id}`;
    const metadata = await fetch(url).then((response) => response.json());
    metadata.url = location.origin + url;
    model = await PIXI.live2d.Live2DModel.from(metadata, { autoUpdate: false, autoInteract: false, motionPreload: "NONE" });
    synchronizeMotionFades(model, metadata);
    const bounds = model.getLocalBounds();
    model.anchor.set(.5, 1);
    model.scale.set(Math.min(208 / bounds.width, 315 / bounds.height));
    model.position.set(110, 325);
    model.update(0);
    texture = PIXI.RenderTexture.create({ width: 220, height: 330 });
    view.app.renderer.render(model, { renderTexture: texture });
    const imageUrl = await view.app.renderer.extract.base64(texture, "image/webp", .8);
    view.thumbnails.set(`${role}:${id}`, imageUrl);
    api("thumbnail", { role, costume: id, image: imageUrl }).catch((error) => console.debug("Thumbnail cache", error));
    if (view.thumbnails.size > 80) view.thumbnails.delete(view.thumbnails.keys().next().value);
    if (view.catalog.id === role) {
      const target = list.querySelector(`.costume-picture[data-costume="${id}"]`);
      if (target) {
        const image = document.createElement("img");
        image.src = imageUrl;
        image.alt = view.catalog.costumes.find((costume) => costume.id === id).name;
        target.replaceChildren(image);
      }
    }
  } catch (error) {
    view.thumbnails.set(`${role}:${id}`, null);
    console.debug("Costume thumbnail", error);
  }
  finally {
    model?.destroy({ children: true });
    texture?.destroy(true);
    thumbnailBusy = false;
    if (view.tab === "costume") setTimeout(queueVisibleThumbnails, 350);
  }
}

function enableAudio() {
  if (!audioContext) {
    audioContext = new AudioContext();
    const source = audioContext.createMediaElementSource(audio);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    audioData = new Uint8Array(analyser.fftSize);
    view.volume = audioContext.createGain();
    source.connect(analyser);
    analyser.connect(view.volume);
    view.volume.connect(audioContext.destination);
    view.volume.gain.value = view.state?.linked ? 0 : 1;
  }
  return audioContext.resume();
}

function updateMouth() {
  const core = view.model?.internalModel.coreModel;
  if (!core || !view.mouthIds.length) return;
  if (audio.paused || audio.ended || !analyser) { view.mouth = 0; return; }
  let target = 0;
  if (analyser && !audio.paused) {
    analyser.getByteTimeDomainData(audioData);
    target = Math.min(1, audioData.reduce((total, value) => total + Math.abs(value - 128) / 128, 0) / audioData.length * 10);
  }
  view.mouth += (target - view.mouth) * .35;
  for (const id of view.mouthIds) {
    if (core.addParameterValueById) core.addParameterValueById(id, view.mouth);
    else if (core.addToParamFloat) core.addToParamFloat(id, view.mouth);
  }
}

async function playItem(kind, item) {
  if (kind === "voice") await enableAudio();
  if (kind === "voice" && view.visibleVoice?.id === item.id && !audio.paused) {
    view.state = await api("stop", { kind });
    stopLocal(kind);
    return;
  }
  if (kind === "costume" && currentCostume().id === item.id) return;
  if (kind === "costume") return chooseCostume(item.id);
  view.state = await api("operate", { kind, id: item.id });
  if (kind === "costume") await applySelection(view.state);
  else renderState();
}

async function chooseCostume(id) {
  view.desiredCostume = id;
  if (view.switchingCostume) return;
  view.switchingCostume = true;
  document.body.dataset.switching = "true";
  $("#model-loading").textContent = "正在换装";
  $("#model-loading").hidden = false;
  renderItems();
  try {
    while (view.desiredCostume !== view.state.settings.costume) {
      const target = view.desiredCostume;
      const result = await api("select", { role: view.catalog.id, costume: target });
      view.state = result;
      if (view.desiredCostume === target) await applySelection(result);
    }
  } finally {
    view.switchingCostume = false;
    delete document.body.dataset.switching;
    $("#model-loading").hidden = true;
    renderState();
  }
}

async function applyPlay(data) {
  const { kind, item } = data;
  if (data.costume !== undefined && data.costume !== currentCostume().id) return;
  if (kind === "voice") {
    const generation = ++audioGeneration;
    audio.pause();
    audio.src = asset(item.file);
    view.visibleVoice = item;
    updateSubtitle();
    try {
      await enableAudio();
      if (generation !== audioGeneration) return;
      await audio.play();
    } catch (error) {
      if (generation === audioGeneration && !view.state.linked) toast("浏览器已阻止声音播放");
    }
  } else if (kind === "action") {
    clearTimeout(actionTimer);
    view.currentAction = item;
    await view.model?.motion("page_" + item.id, 0, 3);
    const key = view.modelKey;
    actionTimer = setTimeout(() => {
      if (key !== view.modelKey || view.currentAction?.id !== item.id) return;
      view.currentAction = null;
      renderItems();
      updatePlaying();
    }, item.duration * 1000);
  } else if (kind === "expression") {
    if (item.file) {
      const model = view.model;
      const manager = model?.internalModel.motionManager.expressionManager;
      if (!manager) return;
      const applied = await model.expression(String(item.id));
      if (view.model !== model) return;
      const index = manager.getExpressionIndex(String(item.id));
      if (!applied && manager.currentExpression !== manager.expressions[index]) throw new Error("表情加载失败");
      manager.restoreExpression();
      view.currentExpression = item.id;
    } else resetExpression();
  }
  renderItems();
  updatePlaying();
}

function resetExpression() {
  view.currentExpression = null;
  const manager = view.model?.internalModel.motionManager.expressionManager;
  if (manager) {
    manager.reserveExpressionIndex = -1;
    manager.currentExpression = manager.defaultExpression;
    manager.resetExpression();
  }
  renderItems();
}

function stopLocal(kind) {
  if (kind === "voice") {
    ++audioGeneration;
    audio.pause();
    view.visibleVoice = null;
    view.mouth = 0;
    updateSubtitle();
  } else if (kind === "action") {
    clearTimeout(actionTimer);
    view.currentAction = null;
    const manager = view.model?.internalModel.motionManager;
    manager?.stopAllMotions();
  }
  updatePlaying();
  if (view.catalog) renderItems();
}

function updateSubtitle() {
  const visible = Boolean(view.visibleVoice && view.state?.settings.captions && !audio.ended);
  $("#subtitle").hidden = !visible;
  if (visible) {
    $("#subtitle-speaker").textContent = view.catalog.name.replace(/（Garupa）/g, "");
    $("#subtitle-text").textContent = view.visibleVoice.caption || view.visibleVoice.name;
  }
}

function updatePlaying() {
  const item = view.visibleVoice || view.currentAction || (view.state?.looping.costume ? currentCostume() : null);
  $("#playing-title").textContent = item?.name || "待机";
  $("#playing-detail").textContent = item ? (view.visibleVoice ? "语音播放中" : view.currentAction ? "动作播放中" : view.state.waitingForCostume ? "等待换装" : "循环换装中") : "";
  $("#equalizer").classList.toggle("playing", Boolean(item));
}

async function stopAll() {
  view.state = await api("reset", {});
  for (const kind of ["action", "voice", "costume"]) stopLocal(kind);
  resetExpression();
  renderState();
}

async function boot() {
  view.library = await api("library");
  view.state = await api("state");
  const query = new URLSearchParams(location.search);
  if (query.get("role") !== view.state.role && view.library.some((role) => role.id === query.get("role"))) {
    view.state = await api("select", { role: query.get("role"), costume: Number(query.get("costume")) || undefined });
  }
  if (query.get("desktop") === "1") {
    view.state = await api("connect", { attach: true });
  }
  await applySelection(view.state);
  const events = new EventSource("/api/events");
  let eventQueue = Promise.resolve();
  const handleEvent = async (message) => {
    const event = JSON.parse(message.data);
    if (event.state.role !== view.state?.role && event.type !== "selection") return;
    if (event.state.sequence < view.state.sequence) return;
    view.state = event.state;
    if (event.type === "selection") {
      if (!view.switchingCostume || event.state.settings.costume === view.desiredCostume) await applySelection(event.state);
    }
    else if (event.type === "play") await applyPlay(event.data);
    else if (event.type === "catalog" && event.data.role === view.catalog.id) {
      receiveVoiceCatalog({catalog: await api("catalog/" + view.catalog.id), state: event.state});
    }
    else if (event.type === "stop" || (event.type === "ended" && event.data !== "voice")) stopLocal(event.data);
    else if (event.type === "clear-expression") resetExpression();
    else if (event.type === "reset") { for (const kind of ["action", "voice", "costume"]) stopLocal(kind); resetExpression(); }
    else if (event.type === "notice") toast(event.data);
    renderState();
  };
  events.onmessage = (message) => {
    eventQueue = eventQueue.then(() => handleEvent(message)).catch((error) => toast(error.message));
  };
  events.onopen = safely(async () => {
    const state = await api("state");
    await applySelection(state);
  });
  events.onerror = () => { $("#connect-label").textContent = "页面连接恢复中"; };
}

document.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => setTab(button.dataset.tab)));
document.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => {
  view.favoriteCategory = button.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach((entry) => entry.classList.toggle("selected", entry === button));
  renderItems();
}));
$("#item-search").addEventListener("input", renderItems);
$("#upload-voice").addEventListener("click", () => {
  $("#voice-upload-dialog").dataset.role = view.catalog.id;
  $("#voice-upload-error").hidden = true;
  $("#voice-upload-dialog").showModal();
});
$("#voice-upload-form").addEventListener("submit", uploadVoice);
$("#voice-delete-form").addEventListener("submit", deleteVoice);
document.querySelectorAll("[data-close-dialog]").forEach(button => button.addEventListener("click", () => {
  const dialog = button.closest("dialog");
  if (!dialog.dataset.busy) dialog.close();
}));
document.querySelectorAll(".voice-dialog").forEach(dialog => dialog.addEventListener("cancel", event => {
  if (dialog.dataset.busy) event.preventDefault();
}));
$("#items").addEventListener("scroll", queueVisibleThumbnails, { passive: true });
$("#favorites-filter").addEventListener("click", safely(async () => {
  if (["action", "voice", "costume"].includes(view.tab)) {
    await savePreference(view.tab + "Scope", view.onlyFavorites ? 0 : 1);
  } else { view.onlyFavorites = !view.onlyFavorites; renderItems(); }
}));
$("#empty-reset").addEventListener("click", () => { $("#item-search").value = ""; renderItems(); });
$("#loop").addEventListener("click", safely(async () => {
  const kind = view.tab;
  await preferenceQueue;
  if (view.state.looping[kind]) {
    view.state = await api("stop", { kind });
    stopLocal(kind);
  } else {
    if (kind === "voice") await enableAudio();
    view.state = await api("operate", { kind, random: true, loop: true });
  }
  renderState();
}));
document.querySelectorAll("[data-order]").forEach((button) => button.addEventListener("click", safely(() =>
  savePreference(view.tab + "Order", button.dataset.order)
)));
$("#loop-interval").addEventListener("change", safely((event) =>
  savePreference(view.tab + "Interval", Number(event.target.value))
));
for (const [id, key] of [["#captions-toggle", "captions"], ["#body-toggle", "bodyOnly"]]) {
  $(id).addEventListener("change", safely(async (event) => {
    try { view.state = await api("preference", { key, value: event.target.checked }); }
    finally { renderState(); }
  }));
}
$("#connect").addEventListener("click", safely(async () => {
  const button = $("#connect");
  button.disabled = true;
  $("#connect-label").textContent = "正在连接桌面";
  try {
    view.state = await api("connect", {});
  } finally { button.disabled = false; renderState(); }
}));
$("#stop-all").addEventListener("click", safely(stopAll));
document.querySelectorAll(".control-panel, .bottom-bar").forEach((element) => {
  element.addEventListener("pointerdown", (event) => event.stopPropagation());
  element.addEventListener("pointerup", (event) => event.stopPropagation());
  element.addEventListener("click", (event) => event.stopPropagation());
});
$("#clear-expression").addEventListener("click", safely(async () => {
  resetExpression();
  await api("operate", { kind: "expression", id: -1 });
}));
$("#reload-preview").addEventListener("click", safely(() => loadModel(view.modelKey)));
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) { event.preventDefault(); $("#item-search").focus(); }
  if (event.target.matches("[role=tab]") && ["ArrowLeft", "ArrowRight"].includes(event.key)) {
    event.preventDefault();
    const tabs = [...document.querySelectorAll("[role=tab]")];
    const next = tabs[(tabs.indexOf(event.target) + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    setTab(next.dataset.tab);
    next.focus();
  }
});
audio.addEventListener("ended", () => { view.visibleVoice = null; updateSubtitle(); updatePlaying(); renderItems(); });
audio.addEventListener("error", () => { if (audio.src) toast("语音载入失败，请重试"); });
new ResizeObserver(resetModelView).observe($("#canvas-host"));
new ResizeObserver(updateTabIndicator).observe($(".tabs"));
document.fonts.ready.then(updateTabIndicator);
boot().catch((error) => toast(error.message));

"use strict";

const $ = (selector) => document.querySelector(selector);
const labels = { action: "动作", expression: "表情", costume: "衣装", voice: "语音", favorites: "收藏" };
const directions = { body: "正面动作", left: "左手动作", right: "右手动作", other: "其他动作" };
const headings = {
  action: ["让角色动起来", "点击播放，心动的动作随手收藏。"],
  expression: ["每一种小情绪", "点击切换表情，再次选择即可覆盖。"],
  costume: ["今天，穿哪一套", "挑选喜欢的衣装，收藏你的常用搭配。"],
  voice: ["听一段熟悉的声音", "点击即播，字幕随语音一起出现。"],
  favorites: ["心动，随时可见", "所有收藏都在这里，点击即可使用。"],
};
const view = {
  library: [], catalog: null, state: null, game: "OurNotes", tab: "action",
  onlyFavorites: false, favoriteCategory: "all", request: 0, model: null,
  app: null, mouthIds: [], mouth: 0, thumbnails: new Map(), visibleVoice: null,
  currentAction: null, currentExpression: null, modelKey: null, volume: null,
  switchingCostume: false, desiredCostume: null, modelReady: Promise.resolve(),
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


function makeItem(item, kind) {
  const card = document.createElement("article");
  card.className = "item-card";
  const playing = kind === "voice" ? view.visibleVoice?.id === item.id : kind === "action" ? view.currentAction?.id === item.id : kind === "expression" ? view.currentExpression === item.id : false;
  card.classList.toggle("playing", playing);
  const wearing = kind === "costume" && item.id === currentCostume().id;
  card.classList.toggle("wearing", wearing);
  const main = document.createElement("button");
  main.className = "item-main";
  main.disabled = Boolean(view.switchingCostume && kind !== "costume");
  main.title = item.name;
  main.setAttribute("aria-label", (kind === "costume" ? "穿上" : "播放") + item.name);
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
      tag.textContent = "正在穿着";
      card.append(tag);
    }
  } else {
    const symbol = document.createElement("span");
    symbol.className = "item-symbol";
    symbol.textContent = kind === "expression" ? ["◡", "◠", "⌣", "◕"][item.id % 4] : ({ body: "⟡", left: "↶", right: "↷", other: "✧" }[item.category] || "⟡");
    main.append(symbol, title);
    if (kind === "action") {
      const direction = document.createElement("small");
      direction.textContent = directions[item.category];
      main.append(direction);
    }
  }
  const heart = document.createElement("button");
  const enabled = favoriteSet().has(item.flag);
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
  return card;
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
  $("#items").className = "items " + ({ action: "action-grid", expression: "expression-grid", costume: "costume-grid", voice: "voice-list", favorites: "action-grid" }[view.tab]);
  $("#items").setAttribute("aria-labelledby", "tab-" + view.tab);
  $("#items").replaceChildren(...entries.map(({ item, kind }) => makeItem(item, kind)));
  if (view.tab === "costume") requestAnimationFrame(queueVisibleThumbnails);
  $("#item-count").textContent = `${entries.length} 个${view.tab === "favorites" ? "收藏" : labels[view.tab]}`;
  $("#empty").hidden = entries.length > 0;
  $("#items").hidden = entries.length === 0;
  const searching = Boolean(query);
  const favoritesEmpty = view.tab === "favorites" || view.onlyFavorites;
  $("#empty-icon").textContent = searching ? "⌕" : favoritesEmpty ? "♡" : "◇";
  $("#empty-title").textContent = searching ? "没有找到匹配内容" : favoritesEmpty ? "还没有心动收藏" : `当前${labels[view.tab]}暂未收录`;
  $("#empty-description").textContent = searching ? "换个关键词试试看。" : favoritesEmpty ? "点亮条目旁的爱心，就能在这里找到它。" : "可以先体验其他内容。";
  $("#empty-reset").hidden = !searching;
  const [heading, description] = headings[view.tab];
  $("#section-title").textContent = heading;
  $("#section-description").textContent = description;
  $("#item-search").placeholder = `搜索${labels[view.tab]}`;
  $("#favorites-filter").hidden = view.tab === "favorites";
  $("#favorite-categories").hidden = view.tab !== "favorites";
  $("#clear-expression").hidden = view.tab !== "expression";
  $("#favorites-filter").classList.toggle("selected", view.onlyFavorites);
  $("#favorites-filter").setAttribute("aria-pressed", String(view.onlyFavorites));
  $("#favorites-filter span").textContent = view.onlyFavorites ? "♥" : "♡";
  $("#favorites-filter").title = hasLoop ? "同时设置列表和循环范围；搜索只筛选列表" : "只显示收藏的表情";
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
  $("#loop-concurrency-hint").hidden = view.tab !== "costume" || !(view.state.looping.action || view.state.looping.voice);
  const playable = itemList(view.tab).some((item) => !scope || favorites.has(item.flag));
  $("#loop").disabled = !playable && !looping;
  $("#range-hint").hidden = !scope || playable || looping;
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
  $("#character-name").textContent = view.catalog.name.replace(/（Garupa）/g, "");
  document.title = view.catalog.name.replace(/（Garupa）/g, "") + " · 角色菜单";
  $("#costume-caption").textContent = currentCostume().name;
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
}

async function selectRole(role, costume) {
  const selected = await api("select", { role, ...(costume ? { costume } : {}) });
  await applySelection(selected);
}

async function applySelection(state) {
  view.state = state;
  const roleChanged = view.catalog?.id !== state.role;
  if (roleChanged) {
    view.catalog = await api("catalog/" + state.role);
    view.game = view.catalog.game;
    view.currentExpression = null;
    $("#item-search").value = "";
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
  try {
    if (!window.PIXI?.live2d) throw new Error("Live2D 预览组件未载入");
    if (!view.app) {
      view.app = new PIXI.Application({ resizeTo: host, backgroundAlpha: 0, antialias: true, resolution: Math.min(devicePixelRatio, 2), autoDensity: true, preserveDrawingBuffer: true });
      host.append(view.app.view);
      view.app.renderer.textureGC.maxIdle = 300;
      view.app.renderer.textureGC.checkCountMax = 300;
    }
    if (view.model) {
      view.app.stage.removeChild(view.model);
      view.model.destroy({ children: true });
      view.model = null;
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
    host.onpointermove = (event) => {
      if (!view.model) return;
      const rectangle = host.getBoundingClientRect();
      view.model.internalModel.focusController.focus((event.clientX - rectangle.left) / rectangle.width * 2 - 1, 1 - (event.clientY - rectangle.top) / rectangle.height * 2);
    };
    host.onclick = safely(async (event) => {
      event.stopPropagation();
      if (event.target !== view.app.view) return;
      if (!view.model) return;
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
  }) || candidates[0];
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
  let target = 0;
  if (analyser && !audio.paused) {
    analyser.getByteTimeDomainData(audioData);
    target = Math.min(1, audioData.reduce((total, value) => total + Math.abs(value - 128) / 128, 0) / audioData.length * 10);
  }
  view.mouth += (target - view.mouth) * .35;
  for (const id of view.mouthIds) {
    if (core.setParameterValueById) core.setParameterValueById(id, view.mouth);
    else if (core.setParamFloat) core.setParamFloat(id, view.mouth);
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
      if (generation === audioGeneration && !view.state.linked) toast("请点击一次播放按钮以启用声音");
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
    view.currentExpression = item.id;
    if (item.file) await view.model?.expression(String(item.id));
    else resetExpression();
  }
  renderItems();
  updatePlaying();
}

function resetExpression() {
  view.currentExpression = null;
  view.model?.internalModel.motionManager.expressionManager?.resetExpression();
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
  $("#playing-title").textContent = item?.name || "此刻，与你一起";
  $("#playing-detail").textContent = item ? (view.visibleVoice ? "语音播放中" : view.currentAction ? "动作播放中" : view.state.waitingForCostume ? "等待当前动作和语音结束后换装" : "循环换装中") : "选择一个动作或一段语音";
  $("#equalizer").classList.toggle("playing", Boolean(item));
}

async function stopAll() {
  for (const kind of ["action", "voice", "costume"]) {
    view.state = await api("stop", { kind });
    stopLocal(kind);
  }
  renderState();
}

async function boot() {
  view.library = await api("library");
  view.state = await api("state");
  const query = new URLSearchParams(location.search);
  if (view.library.some((role) => role.id === query.get("role"))) {
    view.state = await api("select", { role: query.get("role"), costume: Number(query.get("costume")) || undefined });
  }
  await applySelection(view.state);
  if (query.get("desktop") === "1") {
    view.state = await api("connect", { attach: true });
    renderState();
  }
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
    toast("已连接桌面，页面操作会同步到桌面角色");
  } finally { button.disabled = false; renderState(); }
}));
$("#stop-all").addEventListener("click", safely(stopAll));
$("#quiet-stop").addEventListener("click", safely(async () => {
  view.state = await api("reset", {});
  for (const kind of ["action", "voice", "costume"]) stopLocal(kind);
  resetExpression();
  renderState();
}));
document.querySelectorAll(".stage-tools, .control-panel, .bottom-bar").forEach((element) => {
  element.addEventListener("pointerdown", (event) => event.stopPropagation());
  element.addEventListener("pointerup", (event) => event.stopPropagation());
  element.addEventListener("click", (event) => event.stopPropagation());
});
$("#clear-expression").addEventListener("click", safely(async () => {
  resetExpression();
  await api("operate", { kind: "expression", id: -1 });
}));
$("#reset-view").addEventListener("click", resetModelView);
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
boot().catch((error) => toast(error.message));

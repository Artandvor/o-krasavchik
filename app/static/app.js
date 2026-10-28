"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (p, o = {}) => { const r = await fetch(p, { headers: { "Content-Type": "application/json" }, ...o }); if (!r.ok) throw new Error(await r.text()); return r.json(); };
const post = (p, b) => api(p, { method: "POST", body: JSON.stringify(b ?? {}) });
const toast = (m) => { const t = $("#toast"); t.textContent = m; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 2800); };
const qs = (o) => Object.entries(o).filter(([, v]) => v != null && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

const MON = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const MON_IN = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"];
const MON_S = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const SIDE = Win.SIDE;
const side = (c) => SIDE[c] || c;
const SRC = { geo: "расчёт по геоданным", osm_tag: "OpenStreetMap", hotelier: "отельер", open_api: "открытые данные", guest: "гость после поездки", human: "разметка" };
const KIND = { hotel: "отель", guest_house: "гостевой дом", hostel: "хостел", apartment: "апартаменты", motel: "мотель", chalet: "шале" };
const ROADS = { trunk: "трасса", primary: "оживлённая дорога", secondary: "оживлённая дорога", tertiary: "улица", motorway: "шоссе" };
const roadName = (r) => ROADS[String(r).replace("_link", "")] || r;
const plural = (n, a, b, c) => { const m = n % 10, mm = n % 100; return m === 1 && mm !== 11 ? a : m >= 2 && m <= 4 && (mm < 12 || mm > 14) ? b : c; };
const humanDate = (d) => { const [, m, dd] = d.split("-").map(Number); return `${dd} ${MON[m - 1]}`; };
const monthOf = (d) => Number(d.split("-")[1]);
const ago = (iso) => { if (!iso) return ""; const d = Math.round((Date.now() - new Date(iso)) / 86400000); return d <= 0 ? "сегодня" : `${d} дн. назад`; };
function monthsText(ms) {
  if (!ms.length || typeof ms[0] !== "number") return ms.join(", ");
  if (new Set(ms).size === 12) return "круглый год";
  const s = [...ms].sort((a, b) => a - b), g = []; let a = s[0], p = s[0];
  for (const m of s.slice(1)) { if (m === p + 1) { p = m; continue; } g.push([a, p]); a = p = m; }
  g.push([a, p]);
  return g.map(([x, y]) => x === y ? MON_S[x - 1] : `${MON_S[x - 1]}–${MON_S[y - 1]}`).join(", ");
}
const fmt = (v, unit) => v === true ? "да" : v === false ? "нет" : v == null ? "—" : Array.isArray(v) ? monthsText(v) : typeof v === "number" ? `${Math.round(v * 10) / 10}${unit ? " " + unit : ""}` : String(v);
const dots = (c) => c == null ? "" : `<span class="dots" aria-hidden="true">${[0, 1, 2, 3, 4].map((i) => `<i class="${i < Math.round(c * 5) ? "f" : ""}"></i>`).join("")}</span>${Math.round(c * 100)}%`;
function noiseWord(db) {
  if (db == null) return "";
  if (db < 40) return "тише шёпота";
  if (db < 45) return "как в тихой спальне";
  if (db < 50) return "как в тихом дворе";
  if (db < 55) return "как в спокойном офисе";
  if (db < 60) return "как на живой улице, беруши не помешают";
  return "громко: берите беруши или другую сторону";
}
function hhmmMinus(t, min) { const [h, m] = t.split(":").map(Number); const x = h * 60 + m - min; return `${String(Math.floor(x / 60)).padStart(2, "0")}:${String(((x % 60) + 60) % 60).padStart(2, "0")}`; }
function tripDate(m, d) {
  const now = new Date(); let y = now.getFullYear();
  if (m - 1 < now.getMonth() || (m - 1 === now.getMonth() && d < now.getDate())) y += 1;
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}
const DEFAULT_DATE = tripDate(7, 15);
// дата из адреса: «2027-07-15» или «07-15»; всё остальное — дата по умолчанию
function normDate(d) {
  const p = String(d || "").split("-").map(Number);
  const [m, dd] = p.length === 3 ? [p[1], p[2]] : p.length === 2 ? p : [NaN, NaN];
  if (!(m >= 1 && m <= 12 && dd >= 1 && dd <= 31)) return DEFAULT_DATE;
  return p.length === 3 && p[0] > 2000 ? `${p[0]}-${String(m).padStart(2, "0")}-${String(dd).padStart(2, "0")}` : tripDate(m, dd);
}

const I = {
  sunset: '<path d="M3 18h18M7 18a5 5 0 0 1 10 0M12 4v5M5.6 9.6l1.4 1.4M18.4 9.6 17 11M2 14h2M20 14h2"/>',
  sunrise: '<path d="M3 18h18M7 18a5 5 0 0 1 10 0M12 9V4M9.5 6.5 12 4l2.5 2.5"/>',
  sea: '<path d="M2 9c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M2 15c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/>',
  mountain: '<path d="M2 20 9 8l4 6 3-4 6 10z"/>',
  walk: '<circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M8 18h5a3 3 0 0 0 0-6h-2a3 3 0 0 1 0-6h5"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  cup: '<path d="M4 8h12v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM16 10h2a2 2 0 0 1 0 4h-2M8 3v2M12 3v2"/>',
  temp: '<path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  play: '<path d="M8 5v14l11-7z"/>',
  shade: '<path d="M12 3v2M12 19v2M4 12H2M22 12h-2M6 6 4.6 4.6M19.4 19.4 18 18M6 18l-1.4 1.4M19.4 4.6 18 6M3 3l18 18"/>',
};
const ico = (n) => `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${I[n]}</svg>`;
const state = { meta: null, hotels: null, basemap: null };

// ====================================================================== роутер
const view = () => $("#view");
async function route() {
  const [path, query] = (location.hash || "#/guest").slice(1).split("?");
  const parts = path.split("/").filter(Boolean);
  const q = Object.fromEntries(new URLSearchParams(query || ""));
  const role = parts[0] || "guest";
  $$(".roles a").forEach((a) => a.dataset.role === role ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  $("#bar").classList.toggle("on-dark", role === "guest" && !parts[1]);
  window.scrollTo(0, 0);
  try {
    if (role === "guest") {
      if (!parts[1]) return guestHome();
      if (parts[1] === "find") return guestResults(q.q || "", normDate(q.d));
      if (parts[1] === "window") return guestWindow(parts[2], q);
      if (parts[1] === "trip") return guestTrip(parts[2], q);
    }
    if (role === "host") return hostView(parts[1]);
    if (role === "ops") return opsView(parts[1] || "overview");
    guestHome();
  } catch (e) { console.error(e); view().innerHTML = `<div class="wrap"><h1 class="page-title">Что-то пошло не так</h1><p class="page-sub">${esc(e.message)}</p></div>`; }
}
addEventListener("hashchange", route);

// ====================================================================== ГОСТЬ · главная
const MOODS = [
  ["Закат в море из окна", "хочу смотреть из окна, как солнце садится в море"],
  ["Выспаться в тишине", "тихий номер, чтобы выспаться, плотные шторы"],
  ["Горы за завтраком", "вид на горы из окна"],
  ["С детьми — к морю без светофоров", "с детьми, чтобы к морю без перехода через железную дорогу и трассу"],
  ["С собакой", "можно с собакой, рядом пляж"],
  ["Купаться в октябре", "купаться в октябре, тёплое море, вид на море"],
];
function whenSelects(d) {
  const [, m, dd] = d.split("-").map(Number);
  return `<select id="wd" aria-label="День">${Array.from({ length: 31 }, (_, i) => `<option ${i + 1 === dd ? "selected" : ""}>${i + 1}</option>`).join("")}</select>
    <select id="wm" aria-label="Месяц">${MON.map((x, i) => `<option value="${i + 1}" ${i + 1 === m ? "selected" : ""}>${x}</option>`).join("")}</select>`;
}
const readWhen = () => tripDate(Number($("#wm").value), Number($("#wd").value));
async function guestHome() {
  view().innerHTML = `
  <section class="hero">
    <div class="hero-window" id="heroWin"></div>
    <div class="hero-in">
      <h1>Сначала закат.<br>Потом отель.</h1>
      <p class="lead">Расскажи, ради какого момента ты едешь. Мы по рельефу, домам и солнцу найдём окно, из которого это правда случится, и попросим отель дать тебе именно его.</p>
      <form class="search" id="dream">
        <div class="seg"><label for="dq">Какой момент</label><input id="dq" autocomplete="off" placeholder="Проснуться под шум моря, вечером — закат в воду, ночью — тишина"></div>
        <div class="seg"><label>Когда</label><div class="when">${whenSelects(DEFAULT_DATE)}</div></div>
        <button class="orb" type="submit" aria-label="Найти моё окно">${ico("search")}</button>
      </form>
      <div class="moods">${MOODS.map(([t, q]) => `<button class="pill" type="button" data-q="${esc(q)}">${esc(t)}</button>`).join("")}</div>
    </div>
    <div class="hero-cap" id="heroCap"></div>
    <div class="hero-how">Это не фото. Это расчёт: рельеф Copernicus, 30 000 домов из OpenStreetMap и положение солнца в эту дату.</div>
  </section>`;
  const go = () => { const q = $("#dq").value.trim() || $("#dq").placeholder; location.hash = `#/guest/find?${qs({ q, d: readWhen() })}`; };
  $("#dream").addEventListener("submit", (e) => { e.preventDefault(); go(); });
  $$(".moods .pill").forEach((c) => c.addEventListener("click", () => { $("#dq").value = c.dataset.q; go(); }));
  heroShowcase();
}
async function heroShowcase() {
  try {
    const sc = await api(`/api/showcase?month=${monthOf(DEFAULT_DATE)}`);
    if (!sc.id) return;
    const p = await api(`/api/panorama/${sc.id}?${qs({ floor: sc.floor, date: DEFAULT_DATE })}`);
    const sd = p.sides.find((x) => x.side === sc.side) || p.sides[0];
    const ev = Win.events(sd, p.sun);
    if (!ev.sunset) return;
    const box = $("#heroWin"); if (!box) return;
    const track = p.sun.track.filter(([t]) => t >= hhmmMinus(ev.sunset.t, 42) && t <= hhmmMinus(ev.sunset.t, 2));
    const aspect = innerHeight / innerWidth;
    const draw = (pt) => { box.innerHTML = Win.render(sd, { az: pt[1], el: pt[2] }, { w: 1600, h: 900, horizon: 0.64, vex: 2.4, cropTo: ev.sunset.az - 10, cropSpan: 72, cropAspect: aspect, grain: true, alt: `Вид из окна: ${p.hotel.name}` }); };
    $("#heroCap").innerHTML = `<b>${esc(p.hotel.name)}</b>${p.floor} этаж, окна на ${side(sd.side)}, ${humanDate(DEFAULT_DATE)}, ${ev.sunset.t}`;
    if (REDUCED || track.length < 2) { draw(track[track.length - 1] || p.sun.track[0]); return; }
    let i = 0;
    const tick = () => { if (!$("#heroWin")) return; draw(track[i]); if (++i < track.length) setTimeout(tick, 420); };
    tick();
  } catch (e) { console.warn(e); }
}

// ====================================================================== ГОСТЬ · выдача окон
const critKeys = (parsed) => new Set((parsed?.criteria || []).map((c) => c.key));
function titleOf(key) { for (const g of Object.values(state.meta.groups)) for (const c of g) if (c.key === key) return c.title; return key; }
function pickRoom(r, keys) {
  const v = r.brief.views;
  if (r.room?.side) return { side: r.room.side, floor: typeof r.room.floor === "number" ? r.room.floor : Math.min(r.levels || 3, 3) };
  for (const pass of [true, false]) for (const k of ["sunset_view", "sea_view", "mountain_view"]) {
    if (pass && keys.size && !keys.has(k)) continue;
    const sides = Object.entries(v[k] || {}).sort((a, b) => a[1] - b[1]);
    if (sides.length) return { side: sides[0][0], floor: sides[0][1] };
  }
  const q = Object.entries(r.brief.quiet || {}).sort((a, b) => a[1] - b[1]);
  return { side: q[0]?.[0], floor: Math.min(r.levels || 3, 3) };
}
/* Обещания карточки и страницы окна — из расчёта панорамы и сводки фактов */
function promises(b, ev, sd, keys, date) {
  const out = [], month = monthOf(date), want = (k) => !keys.size || keys.has(k);
  if (ev?.sunset) out.push({ k: "sunset_view", icon: "sunset", big: ev.sunset.t, t: ev.sunset.intoSea ? "солнце садится в море прямо в этом окне" : `солнце уходит за ${ev.sunset.behind || "горизонт"}, до этого — золотой час` });
  else if (ev?.evening) out.push({ k: "sunset_view", icon: "sunset", big: `до ${ev.evening.t}`, cls: keys.has("sunset_view") ? "warn" : "", t: ev.evening.leaves ? `солнце в окне, сам закат в ${ev.evening.real} — за углом дома` : `потом солнце прячется за соседний дом; закат в ${ev.evening.real} — не здесь` });
  else if (keys.has("sunset_view")) out.push({ k: "sunset_view", icon: "sunset", big: "нет", cls: "warn", t: "закат из этого окна не виден" });
  if (ev && ev.seaShare > 0.03) out.push({ k: "sea_view", icon: "sea", big: `${Math.round(ev.seaShare * 100)}%`, t: `окна — море${ev.seaDist > 1500 ? ", вдали" : ev.seaDist ? `, до воды ${ev.seaDist} м` : ""}` });
  else if (keys.has("sea_view")) out.push({ k: "sea_view", icon: "sea", big: "0%", cls: "warn", t: "моря из этого окна не видно" });
  if (ev && ev.mtnShare > 0.08 && (want("mountain_view") || !ev.sunset)) out.push({ k: "mountain_view", icon: "mountain", big: `${Math.round(ev.mtnShare * 100)}%`, t: "окна — Кавказский хребет" });
  if (b.beach && b.beach.min != null) {
    const m = Math.max(1, Math.round(b.beach.min));
    const t = b.beach.m < 40 ? "до пляжа: первая линия" : b.beach.rail?.length ? `до пляжа, через железную дорогу (${b.beach.rail[0]})` : b.beach.roads?.length ? `до пляжа, с переходом: ${roadName(b.beach.roads[0])}` : "до пляжа, ничего не нужно переходить";
    out.push({ k: "beach_walk", icon: "walk", big: `${m} мин`, cls: b.beach.rail?.length && keys.has("beach_no_crossing") ? "warn" : "", t });
  }
  const db = sd ? b.quiet?.[sd] : null;
  if (db != null) out.push({ k: "quiet_night", icon: "moon", big: `${Math.round(db)} дБ`, cls: db >= 55 ? "warn" : "", t: `ночью у окна — ${noiseWord(db)}` });
  const sea = b.climate?.sea?.[month - 1];
  if (sea != null && (keys.has("swim_season") || keys.has("sea_view") || !keys.size)) out.push({ k: "swim_season", icon: "temp", big: `${Math.round(sea)}°`, t: `море в ${MON_IN[month - 1]}${sea >= 20 ? ", можно купаться" : ", купаться — для смелых"}` });
  if (b.pets === true && keys.has("pets")) out.push({ k: "pets", icon: "walk", big: "да", t: "с питомцем можно, отельер подтвердил" });
  if (b.late_food && keys.has("late_food")) out.push({ k: "late_food", icon: "cup", big: "23:00+", t: "рядом есть где поесть после 23:00" });
  out.sort((a, c) => (keys.has(c.k) ? 1 : 0) - (keys.has(a.k) ? 1 : 0));
  return out;
}
function minConf(r) { const c = (r.lines || []).filter((l) => l.confidence).map((l) => l.confidence); return c.length ? Math.min(...c) : (r.brief.sea_view_conf || 0.6); }
async function guestResults(q, date) {
  view().innerHTML = `<div class="wrap"><div class="loading">Ищем окна, из которых это правда видно</div></div>`;
  const r = await api(`/api/search?${qs({ q, limit: 12, month: monthOf(date) })}`);
  const keys = critKeys(r.parsed);
  const heardNothing = !(r.parsed.criteria || []).length;
  const good = heardNothing ? [] : r.results.filter((x) => x.score >= 40);
  const list = (good.length ? good : r.results).slice(0, 9);
  view().innerHTML = `<div class="wrap">
    <h1 class="page-title">${heardNothing ? "Этого мы пока не проверяем" : good.length ? `${good.length} ${plural(good.length, "окно", "окна", "окон")}, где это случится ${humanDate(date)}` : "Всё сразу в одном окне — редкость"}</h1>
    <p class="page-sub">${heardNothing ? "Мы проверяем то, что видно из окна и что вокруг: закат, море, горы, тишину ночью, путь к пляжу, детскую площадку, собаку, ночную аптеку, парковку. Балкон, завтрак и цены — в карточке отеля." : good.length ? "Порядок — по тому, насколько это правда, а не по рекламе. У каждого обещания есть источник." : "В Адлере такое сочетание почти не встречается. Вот лучшие компромиссы — с честными оговорками, что сбудется, а что нет."}</p>
    <div class="heard"><span class="small muted">Мы услышали:</span>${(r.parsed.criteria || []).map((c) => `<span class="chip">${esc(titleOf(c.key))}</span>`).join("") || `<span class="small">ничего знакомого — показываем лучшие виды Адлера</span>`}<a class="link small" href="#/guest">изменить</a></div>
    <div class="grid">${list.map((x, i) => `<a class="card" id="card${i}" href="#"><div class="img skel"></div><div class="meta"><div class="top"><span class="name">${esc(x.name)}</span></div><div class="line2">считаем вид из окна</div></div></a>`).join("")}</div>
  </div>`;
  list.forEach((x, i) => fillCard(x, i, keys, date, q));
}
async function fillCard(x, i, keys, date, q) {
  const room = pickRoom(x, keys), card = $(`#card${i}`); if (!card) return;
  let p, sd, ev;
  try { p = await api(`/api/panorama/${x.id}?${qs({ floor: room.floor, date })}`); sd = p.sides.find((s) => s.side === room.side) || p.sides[0]; ev = Win.events(sd, p.sun); } catch (e) { console.warn(e); }
  const t = ev?.sunset ? hhmmMinus(ev.sunset.t, 8) : ev?.evening ? hhmmMinus(ev.evening.t, 25) : ev?.sunrise ? hhmmMinus(ev.sunrise.t, -50) : "18:00";
  const s = p ? Win.sunAt(p.sun, t) : null;
  const href = `#/guest/window/${x.id}?${qs({ side: sd?.side, floor: p?.floor, d: date, q })}`;
  card.href = href;
  const pr = promises(x.brief, ev, sd?.side, keys, date);
  const main = pr[0], rest = pr.slice(1, 3);
  card.innerHTML = `<div class="img">${sd ? Win.render(sd, s, { w: 1200, h: 900, horizon: 0.66, vex: 2.0, cropTo: (ev?.sunset?.az ?? sd.az), cropSpan: 96, cropAspect: 0.75, alt: `Вид из окна: ${x.name}` }) : ""}
      <span class="badge">${x.score >= 80 ? "всё сходится" : x.score >= 60 ? "почти всё" : "компромисс"}</span><span class="badge r">${p?.floor} этаж, на ${side(sd?.side)}</span></div>
    <div class="meta"><div class="top"><span class="name">${esc(x.name)}</span><span class="conf">${dots(minConf(x))}</span></div>
      ${main ? `<div class="line1 ${main.cls || ""}"><b>${esc(main.big)}</b> — ${esc(main.t)}</div>` : ""}
      <div class="line2">${rest.map((o) => `${esc(o.big)} ${esc(o.t)}`).join("; ") || esc(KIND[x.kind] || "")}</div>
      ${x.brief.conflicts.length ? `<div class="line2 warn">Отельер с нами спорит — уже перепроверяем</div>` : ""}</div>`;
}

// ====================================================================== ГОСТЬ · окно
async function guestWindow(id, q) {
  view().innerHTML = `<div class="wrap"><div class="loading">Открываем окно</div></div>`;
  let date = normDate(q.d), floor = Number(q.floor) || 0;
  const [h, brief, p0] = await Promise.all([api(`/api/hotels/${id}`), api(`/api/brief/${id}`), api(`/api/panorama/${id}?${qs({ floor, date })}`)]);
  let p = p0; floor = p.floor;
  let sideC = q.side && p.sides.find((s) => s.side === q.side) ? q.side : p.sides[0].side;
  const keys = q.q ? critKeys((await api(`/api/search?${qs({ q: q.q, limit: 1, log: false })}`)).parsed) : new Set();
  const facts = Object.fromEntries(h.facts.map((f) => [f.key, f]));
  const hotel = h.hotel;
  view().innerHTML = `<div class="wrap">
    <a class="link small" href="javascript:history.back()">Назад к окнам</a>
    <div class="detail-head"><div><h1>${esc(hotel.name)}</h1><div class="small muted">${esc(KIND[hotel.kind] || "")}${hotel.stars ? `, ${hotel.stars}★` : ""}${hotel.address ? `, ${esc(hotel.address)}` : ""}${hotel.levels ? `, ${hotel.levels} ${plural(hotel.levels, "этаж", "этажа", "этажей")}` : ""}</div></div></div>
    <section class="stage" id="stage"></section>
    <div class="two">
      <div>
        <div class="signature" id="sig"></div>
        <div class="section"><h2 class="h2">Твой день здесь</h2><ul class="day" id="day"></ul></div>
        <div class="section"><h2 class="h2">Путь к морю</h2><div id="minimap" style="height:300px;border-radius:16px;overflow:hidden;border:1px solid var(--line)"></div><p class="small muted" id="routecap" style="margin-top:10px"></p></div>
        <div class="section"><h2 class="h2">Почему мы так уверены</h2><p class="small muted" style="margin-top:-8px">У каждого обещания есть источник, метод и дата. Нажми, чтобы раскрыть.</p><ul class="facts" id="facts"></ul></div>
        <div class="section"><h2 class="h2">Где мы можем ошибаться</h2><ul class="risk" id="risk"></ul></div>
        <p class="small">Уже съездил? <a class="link" id="triplink" href="#">Скажи, совпало ли</a> — так следующий гость получит ещё более честный прогноз.</p>
      </div>
      <aside class="book" id="book"></aside>
    </div></div>`;
  let timeIdx = 0, playing = null;
  const sdOf = () => p.sides.find((s) => s.side === sideC) || p.sides[0];
  const setDefaultTime = () => {
    const ev = Win.events(sdOf(), p.sun);
    const t = ev.sunset ? hhmmMinus(ev.sunset.t, 14) : ev.evening ? hhmmMinus(ev.evening.t, 30) : ev.sunrise ? hhmmMinus(ev.sunrise.t, -40) : "12:00";
    timeIdx = Math.max(0, p.sun.track.findIndex((x) => x[0] >= t));
  };
  const drawStage = () => {
    // дробный индекс: между точками трека (шаг 5 мин) — плавная интерполяция по минутам
    const tr = p.sun.track, i0 = Math.min(tr.length - 1, Math.floor(timeIdx)), i1 = Math.min(tr.length - 1, i0 + 1), fr = timeIdx - i0;
    const toMin = (h) => { const [a, b] = h.split(":").map(Number); return a * 60 + b; };
    let daz = tr[i1][1] - tr[i0][1]; if (daz > 180) daz -= 360; if (daz < -180) daz += 360;
    const mm = Math.round(toMin(tr[i0][0]) + (toMin(tr[i1][0]) - toMin(tr[i0][0]) || 5) * fr);
    const pt = [`${String(Math.floor(mm / 60) % 24).padStart(2, "0")}:${String(mm % 60).padStart(2, "0")}`, (tr[i0][1] + daz * fr + 360) % 360, tr[i0][2] + (tr[i1][2] - tr[i0][2]) * fr];
    $("#stage").innerHTML = Win.render(sdOf(), { az: pt[1], el: pt[2] }, { w: 1600, h: 900, horizon: 0.66, vex: 2.0, labels: true, cropAspect: 7 / 16, cropTo: sdOf().az, cropSpan: 120, grain: true, alt: `Вид из окна: ${hotel.name}` }) +
      `<div class="ctrl tl" role="group" aria-label="Сторона здания">${p.sides.map((s) => `<button class="opt" data-side="${s.side}" aria-pressed="${s.side === sideC}">окна на ${side(s.side)}</button>`).join("")}</div>
       <div class="ctrl tr"><div class="stepper"><button id="fdown" aria-label="Этаж ниже">−</button><span>${floor} этаж</span><button id="fup" aria-label="Этаж выше">+</button></div></div>
       <div class="ctrl bot"><button class="play" id="play" aria-label="Проиграть до заката"><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M8 5v14l11-7z" fill="#fff"/></svg></button><span class="clock">${pt[0]}</span><input type="range" id="time" min="0" max="${p.sun.track.length - 1}" step="any" value="${timeIdx}" aria-label="Время дня"></div>`;
    $("#time").addEventListener("input", (e) => { stop(); timeIdx = +e.target.value; drawStage(); });
    $$("[data-side]").forEach((b) => b.addEventListener("click", () => { stop(); sideC = b.dataset.side; setDefaultTime(); drawStage(); fillText(); }));
    $("#fdown").addEventListener("click", () => changeFloor(-1));
    $("#fup").addEventListener("click", () => changeFloor(1));
    $("#play").addEventListener("click", playToSunset);
  };
  const stop = () => { if (playing) { clearTimeout(playing); playing = null; } };
  const playToSunset = () => {
    stop();
    const ev = Win.events(sdOf(), p.sun);
    const end = p.sun.track.findIndex((x) => x[0] >= (ev.sunset ? hhmmMinus(ev.sunset.t, -6) : p.sun.sunset?.[0] || "20:00"));
    // проигрываем последний час перед закатом по минуте: солнце плавно опускается в море
    timeIdx = Math.max(0, end - 14);
    const step = () => { if (!$("#stage")) return; if (timeIdx < end) { timeIdx = Math.min(end, timeIdx + 0.2); drawStage(); playing = setTimeout(step, 60); } };
    step();
  };
  const changeFloor = async (d) => {
    const nf = Math.min(Math.max(1, floor + d), p.floors[p.floors.length - 1]);
    if (nf === floor) { toast(d > 0 ? "Выше этажей нет" : "Ниже — только улица"); return; }
    stop(); floor = nf; p = await api(`/api/panorama/${id}?${qs({ floor, date })}`); drawStage(); fillText();
    history.replaceState(null, "", `#/guest/window/${id}?${qs({ side: sideC, floor, d: date, q: q.q })}`);
  };
  const fillText = () => {
    const sd = sdOf(), ev = Win.events(sd, p.sun), month = monthOf(date), db = brief.quiet?.[sideC];
    const sea = brief.climate?.sea?.[month - 1];
    // главная цифра экрана
    $("#sig").innerHTML = ev.sunset
      ? `<span class="num">${ev.sunset.t}</span><span class="txt">${humanDate(date)} солнце ${ev.sunset.intoSea ? "<b>сядет в море прямо в этом окне</b>" : `уйдёт за ${ev.sunset.behind || "горизонт"}, а до этого будет <b>золотой час</b>`}. Окна на ${side(sideC)}, ${floor} этаж.</span>`
      : ev.evening ? `<span class="num">${ev.evening.t}</span><span class="txt">До этого времени солнце в окне. Сам закат в ${ev.evening.real} — <b>за углом дома</b>: хочешь его — переключи сторону.</span>`
        : ev.seaShare > .05 ? `<span class="num">${Math.round(ev.seaShare * 100)}%</span><span class="txt">окна — <b>море</b>. Закат с этой стороны не виден.</span>`
          : `<span class="num no">—</span><span class="txt">Ни заката, ни моря из этого окна. Покрути стороны и этажи — где-то будет лучше.</span>`;
    const items = [];
    if (ev.sunrise) items.push(["sunrise", "Утро", ev.sunrise.t, ev.sunrise.overMountains ? "Солнце встаёт из-за гор прямо в окне." : "Солнце заглядывает в окно с рассвета."]);
    else items.push(["shade", "Утро", "в тени", ev.sunFrom ? `Утром без прямого солнца — выспишься. Солнце придёт в окно в ${ev.sunFrom}.` : "Прямое солнце в это окно не заглядывает. Выспишься."]);
    if (brief.beach) items.push(["walk", "День", `${Math.max(1, Math.round(brief.beach.min))} мин`, (brief.beach.m < 40 ? `Пляж${brief.beach.name ? ` «${brief.beach.name.replace(/^"|"$/g, "")}»` : ""} прямо у дома` : `До пляжа${brief.beach.name ? ` «${brief.beach.name.replace(/^"|"$/g, "")}»` : ""} — ${brief.beach.m} м по реальным дорожкам`) + `${brief.beach.gain > 5 ? `, на обратном пути подъём ${Math.round(brief.beach.gain)} м` : ""}. ${brief.beach.rail?.length ? `Через железную дорогу: ${brief.beach.rail[0]}.` : brief.beach.roads?.length ? `По пути переход: ${roadName(brief.beach.roads[0])}.` : "Ничего не нужно переходить."}${sea != null ? ` Море в ${MON_IN[month - 1]} около ${Math.round(sea)} °C.` : ""}`]);
    items.push(["sunset", "Вечер", ev.sunset ? ev.sunset.t : ev.evening ? `до ${ev.evening.t}` : "—", ev.sunset ? (ev.sunset.intoSea ? "Солнце уходит в море. Займи подоконник заранее." : `Солнце скрывается за ${ev.sunset.behind || "горизонтом"}. Золотой час — твой.`) : ev.evening ? `Солнце в окне до ${ev.evening.t}, закат в ${ev.evening.real} — с другой стороны.` : "Закат с этой стороны не виден."]);
    if (db != null) items.push(["moon", "Ночь", `${Math.round(db)} дБ`, `У этого окна ${noiseWord(db)}.`]);
    const lf = facts.late_food?.resolved, ph = facts.night_pharmacy?.resolved;
    if (lf?.value || ph?.value) items.push(["cup", "Поздно", "23:00+", [lf?.value ? `Поесть: ${lf.scope}.` : "", ph?.value ? `Аптека: ${ph.scope}.` : ""].filter(Boolean).join(" ")]);
    $("#day").innerHTML = items.map(([ic, w, t, x]) => `<li>${ico(ic)}<span class="when">${esc(t)}<small>${esc(w)}</small></span><span class="what">${esc(x)}</span></li>`).join("");
    const reason = ev.sunset?.intoSea ? " — мы едем ради заката над морем" : ev.seaShare > .05 ? " — нам очень важен вид на море" : keys.has("quiet_night") ? " — нам важно выспаться" : "";
    const req = `Здравствуйте! Бронирую у вас на ${humanDate(date)}. Если возможно, поселите в номер с окнами на ${side(sideC)}, не ниже ${floor}-го этажа${reason}. Спасибо!`;
    $("#book").innerHTML = `<div class="big">Это окно — твоё</div>
      <div class="rows"><div><b>Когда</b><span class="when" style="display:flex;gap:6px">${whenSelects(date)}</span></div><div><b>Окна</b>на ${side(sideC)}, ${floor} этаж</div><div><b>Мы обещаем</b>${esc(promises(brief, ev, sideC, keys, date).slice(0, 2).map((o) => `${o.big} ${o.t}`).join("; ") || "честный прогноз")}</div></div>
      <button class="cta" id="bookbtn">Забронировать это окно</button>
      <blockquote>${esc(req)}</blockquote>
      <div style="display:flex;justify-content:center;margin-top:10px"><button class="link small" id="copy">Скопировать просьбу отелю</button></div>
      <div class="fine">Прототип: бронь имитируется, отелю ничего не уходит.</div>`;
    $$("#book select").forEach((s) => s.addEventListener("change", async () => { date = tripDate(Number($("#wm").value), Number($("#wd").value)); p = await api(`/api/panorama/${id}?${qs({ floor, date })}`); setDefaultTime(); drawStage(); fillText(); }));
    $("#bookbtn").addEventListener("click", () => bookSheet(hotel, sideC, floor, date, id));
    $("#copy").addEventListener("click", async () => { try { await navigator.clipboard.writeText(req); toast("Просьба скопирована"); } catch (e) { toast("Не удалось скопировать"); } });
    const notes = [...(facts.sea_view?.resolved?.detail?.notes || [])].map((n) => n[0].toUpperCase() + n.slice(1) + ".");
    if (brief.conflicts?.length) notes.push(`Отельер оспаривает: ${brief.conflicts.map(titleOf).join(", ").toLowerCase()}. Расчёт уже перепроверяется.`);
    notes.push("Шум — модель по дорогам, железной дороге и аэропорту, а не замер: сравнивать стороны надёжнее, чем верить точным децибелам.");
    $("#risk").innerHTML = notes.map((n) => `<li>${esc(n)}</li>`).join("");
    $("#triplink").href = `#/guest/trip/${id}?${qs({ side: sideC, floor, d: date })}`;
  };
  const show = ["sunset_view", "sea_view", "mountain_view", "quiet_night", "beach_walk", "beach_no_crossing", "beach_surface", "late_food", "night_pharmacy", "playground", "pets", "car_access", "construction_nearby", "swim_season", "air_quality"];
  $("#facts").innerHTML = show.filter((k) => facts[k]).map((k) => factLi(facts[k])).join("");
  $$("#facts .h").forEach((x) => x.addEventListener("click", () => x.parentElement.classList.toggle("open")));
  setDefaultTime(); drawStage(); fillText();
  miniMap(hotel, facts.beach_walk?.resolved);
}
function factLi(f) {
  const r = f.resolved;
  if (!r) return `<li><div class="h"><span><span class="t">${esc(f.title)}</span><span class="s">пока не знаем — спросили отельера</span></span></div></li>`;
  const tags = (r.conflict && !r.conflict.resolved ? `<span class="tag c">источники спорят</span>` : "") + (r.sources.some((s) => s.type === "hotelier") ? `<span class="tag g">подтвердил отельер</span>` : "") + (r.sources.some((s) => s.type === "guest") ? `<span class="tag g">проверил гость</span>` : "");
  const val = f.key === "beach_walk" ? (r.value < 1 ? "меньше минуты" : `${Math.round(r.value)} мин`) : fmt(r.value, f.unit);
  return `<li><div class="h"><span><span class="t">${esc(f.title)}: ${esc(val)}</span>${tags}<span class="s">${esc(r.scope)}</span></span><span class="small">${dots(r.confidence)}</span></div>
    <div class="b">${r.sources.map((s) => `<div><b>${esc(SRC[s.type] || s.type)}</b>: ${esc(f.key === "beach_walk" && typeof s.value === "number" ? (s.value < 1 ? "меньше минуты" : `${Math.round(s.value)} мин`) : fmt(s.value, f.unit))}, уверенность ${Math.round(s.confidence * 100)}%${s.agrees ? "" : ", расходится"}. ${esc(methodRu(s.method))} ${s.ref && String(s.ref).startsWith("http") ? `<a href="${esc(s.ref)}" target="_blank" rel="noopener">Источник</a>. ` : ""}Получено ${new Date(s.obtained_at).toLocaleDateString("ru-RU")}.</div>`).join("")}
      <div class="muted">Пересчитаем до ${new Date(r.valid_until).toLocaleDateString("ru-RU")} или раньше, если рядом что-то изменится.</div></div></li>`;
}
// метод факта — по-человечески: без кодов инструментов, тегов карты и JSON
const METHOD_NAME = { viewshed: "Расчёт вида", walk: "Пеший маршрут", noise: "Модель шума", poi_nearby: "Поиск мест на карте", air: "Качество воздуха",
  climate: "Климат", drive_access: "Подъезд на машине", construction: "Стройки на карте", distance_to: "Расстояние по карте", osm: "Теги карты", hotelier: "Ответ отельера", guest: "Ответ гостя" };
const METHOD_FIX = [
  [/пересечения маршрута с railway=\* и highway∈\{[^}]*\}/, "пересечения маршрута с железной дорогой и крупными улицами"],
  [/Дейкстра по пешеходному графу OSM, скорость по Тоблеру/, "кратчайший путь по пешеходным дорожкам, скорость с учётом уклонов"],
  [/^natural=beach surface$/, "покрытие пляжа"], [/^tags?$/, ""], [/^answer, parser=rules$/, "разобран по правилам"], [/^answer, parser=llm$/, "разобран языковой моделью"], [/^feedback$/, "после поездки"],
  [/\{[^}]*\}\s*|\bnull\s*/g, ""], [/по графу/g, "пешком"],
];
function methodRu(m) {
  if (!m) return "";
  const x = String(m).match(/^([a-z_]+)(?:\/\w+)?(?:\s+(\d{4}\.\d+-\w+))?:?\s*(.*)$/i);
  if (!x) return m;
  let rest = x[3] || "";
  for (const [re, to] of METHOD_FIX) rest = rest.replace(re, to);
  rest = rest.trim();
  return `${METHOD_NAME[x[1]] || "Метод"}${rest ? ": " + rest : ""}${x[2] ? ` (методика ${x[2]})` : ""}.`;
}
async function getBasemap() { if (!state.basemap) state.basemap = await api("/api/basemap"); return state.basemap; }
function basemapLayer(bm) {
  return L.geoJSON(bm, { interactive: false, pointToLayer: () => null, style: (f) => {
    const k = f.properties.k;
    if (k === "sea") return { stroke: false, fillColor: "#BFE0EA", fillOpacity: 1 };
    if (k === "land") return { stroke: false, fillColor: "#F2F4F3", fillOpacity: 1 };
    if (k === "beach") return { stroke: false, fillColor: "#F3E3B8", fillOpacity: 1 };
    if (k === "park") return { stroke: false, fillColor: "#DCEBD8", fillOpacity: 1 };
    if (k === "rail") return { color: "#8B8F95", weight: 2, dashArray: "6 5" };
    const r = f.properties.r; return { color: r <= 2 ? "#FFFFFF" : "#FFFFFF", weight: r <= 1 ? 5 : r === 2 ? 4 : r === 3 ? 2.5 : 1.5, opacity: 1 };
  } });
}
async function miniMap(hotel, bw) {
  const el = $("#minimap"); if (!el || !window.L) return;
  const m = L.map(el, { zoomControl: false, attributionControl: true, scrollWheelZoom: false });
  m.attributionControl.setPrefix(false).addAttribution("данные © участники OpenStreetMap");
  const route = bw?.detail?.coords_ll;
  // сначала вид, потом слои: Leaflet не умеет рисовать линии на карте без центра
  if (route?.length > 1) m.fitBounds(L.latLngBounds(route).pad(0.35)); else m.setView([hotel.lat, hotel.lon], 16);
  basemapLayer(await getBasemap()).addTo(m);
  if (route?.length > 1) L.polyline(route, { color: "#FF5A36", weight: 4 }).addTo(m);
  L.circleMarker([hotel.lat, hotel.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#1F2124", fillOpacity: 1 }).addTo(m);
  if (bw) $("#routecap").textContent = bw.scope;
}
function bookSheet(hotel, sideC, floor, date, id) {
  const bg = document.createElement("div");
  bg.className = "sheet-bg";
  bg.innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sh">
    <h2 id="sh">Готово. Окна на ${esc(side(sideC))}, ${floor} этаж — за тобой.</h2>
    <p>${esc(hotel.name)} получил просьбу на ${humanDate(date)}. Когда вернёшься, мы спросим одно: совпало ли. Если нет — нам будет стыдно, а следующему гостю мы скажем правду.</p>
    <p class="small muted">Прототип: бронь имитируется, отелю ничего не уходит.</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:20px"><a class="cta" href="#/guest/trip/${id}?${qs({ side: sideC, floor, d: date })}">Перемотать к возвращению</a><button class="btn quiet" id="shclose">Закрыть</button></div></div>`;
  document.body.appendChild(bg);
  const close = () => bg.remove();
  $("#shclose", bg).addEventListener("click", close);
  bg.addEventListener("click", (e) => { if (e.target === bg) close(); });
  $$("a", bg).forEach((a) => a.addEventListener("click", close));
  $("#shclose", bg).focus();
}

// ====================================================================== ГОСТЬ · совпало?
async function guestTrip(id, q) {
  const date = normDate(q.d), floor = Number(q.floor) || 0;
  const [h, p] = await Promise.all([api(`/api/hotels/${id}`), api(`/api/panorama/${id}?${qs({ floor, date })}`)]);
  const sd = p.sides.find((s) => s.side === q.side) || p.sides[0];
  const ev = Win.events(sd, p.sun);
  const facts = Object.fromEntries(h.facts.map((f) => [f.key, f]));
  const bw = facts.beach_walk?.resolved;
  const items = [
    { key: "sunset_view", q: ev.sunset ? `Закат в ${ev.sunset.t} был виден из окна?` : "Закат был виден из окна?", sub: ev.sunset ? "Мы обещали, что да" : "Мы предупреждали, что нет", yes: true, no: false },
    { key: "sea_view", q: "Море из окна было видно?", sub: ev.seaShare > .03 ? `Мы обещали ${Math.round(ev.seaShare * 100)}% окна` : "Мы предупреждали, что нет", yes: true, no: false },
    { key: "quiet_night", q: "Ночью было тихо?", sub: "С закрытыми окнами, как ты обычно спишь", yes: "тихо", no: "шумно" },
    bw ? { key: "beach_walk", q: `До пляжа дошли примерно за ${Math.max(1, Math.round(bw.value))} мин?`, sub: "Обычным шагом", yes: bw.value, no: null, input: true } : null,
    { key: "beach_no_crossing", q: "К морю — без перехода через пути и трассу?", sub: facts.beach_no_crossing?.resolved?.scope || "", yes: true, no: false },
  ].filter(Boolean);
  view().innerHTML = `<div class="wrap" style="max-width:760px">
    <h1 class="page-title">Ну что, совпало?</h1>
    <p class="page-sub">${esc(h.hotel.name)}, ${p.floor} этаж, окна на ${side(sd.side)}, ${humanDate(date)}. Пять вопросов. Твой ответ весит больше любого нашего расчёта.</p>
    <ul class="verdict" style="margin-top:24px">${items.map((it, i) => `<li data-i="${i}"><span class="q">${esc(it.q)}<small>${esc(it.sub)}</small></span>
      <span class="yn"><button class="y" aria-pressed="false">Да, так и было</button><button class="n" aria-pressed="false">Нет</button></span>
      ${it.input ? `<input class="field hidden" type="number" min="1" placeholder="Сколько минут на самом деле?" style="grid-column:1/-1;max-width:300px">` : ""}</li>`).join("")}</ul>
    <textarea class="field" id="tc" rows="3" placeholder="Что ещё стоит знать следующему гостю? Необязательно." style="margin-top:20px"></textarea>
    <div style="margin-top:18px"><button class="cta" id="send">Отправить правду</button></div></div>`;
  const ans = {};
  $$(".verdict li").forEach((li) => {
    const i = +li.dataset.i;
    $$(".yn button", li).forEach((b) => b.addEventListener("click", () => {
      $$(".yn button", li).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      ans[i] = b.classList.contains("y");
      const inp = $("input", li); if (inp) inp.classList.toggle("hidden", ans[i]);
    }));
  });
  $("#send").addEventListener("click", async () => {
    const comment = $("#tc").value.trim();
    let n = 0;
    for (const [i, yes] of Object.entries(ans)) {
      const it = items[i]; let value = yes ? it.yes : it.no;
      if (it.input && !yes) { const v = Number($(`li[data-i="${i}"] input`).value); if (!v) continue; value = v; }
      if (value == null) continue;
      await post("/api/guest/feedback", { hotel_id: id, key: it.key, value, comment, side: sd.side, floor: p.floor });
      n++;
    }
    if (!n) { toast("Ответь хотя бы на один вопрос"); return; }
    const miss = Object.values(ans).filter((v) => !v).length;
    view().innerHTML = `<div class="wrap" style="max-width:760px"><h1 class="page-title">${miss ? "Спасибо, что сказал правду." : "Совпало. Мы так и знали."}</h1>
      <p class="page-sub">${miss ? `Мы не угадали в ${miss} ${plural(miss, "пункте", "пунктах", "пунктах")}. Расчёт уже перепроверяется, а следующий гость увидит твою поправку.` : "Твой ответ подтвердил расчёт: для следующего гостя уверенность выросла."} В этом весь «О!дин шаг»: каждое окно становится честнее после каждой поездки.</p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:24px"><a class="cta" href="#/guest">Спланировать следующую поездку</a><a class="btn quiet" href="#/guest/window/${id}?${qs({ side: sd.side, floor: p.floor, d: date })}">Вернуться к окну</a></div></div>`;
  });
}

// ====================================================================== ОТЕЛЬЕР
async function hotelsList() { if (!state.hotels) state.hotels = (await api("/api/hotels")).sort((a, b) => a.name.localeCompare(b.name, "ru")); return state.hotels; }
async function hostView(id) {
  const hs = await hotelsList();
  if (!id) { const d = await api("/api/conflicts"); id = d[0]?.hotel_id || hs[0].id; history.replaceState(null, "", `#/host/${id}`); }
  view().innerHTML = `<div class="wrap"><div class="loading">Открываем кабинет</div></div>`;
  const [cab, ins] = await Promise.all([api(`/api/hotelier/${id}`), api(`/api/hotelier/${id}/insights`)]);
  const name = cab.hotel.name, qn = cab.questions.length, top = ins.strengths[0];
  view().innerHTML = `<div class="wrap">
    <h1 class="page-title">${esc(name)} глазами гостей</h1>
    <p class="page-sub">Мы уже знаем о вас ${ins.known} из ${ins.total} вещей — из карт, рельефа и солнца. ${qn ? `Ответьте на ${qn} ${plural(qn, "вопрос", "вопроса", "вопросов")}, и вас увидят те, кто ищет именно то, что у вас есть.` : "Вопросов к вам нет: гости знают всё, о чём спрашивают."}</p>
    <div class="picker"><select id="hp" aria-label="Ваш отель">${hs.map((h) => `<option value="${h.id}" ${h.id === id ? "selected" : ""}>${esc(h.name)}</option>`).join("")}</select><a class="btn quiet s" href="#/guest/window/${id}">Посмотреть глазами гостя</a></div>
    <div class="stats">
      <div class="stat"><b>${ins.known}<span style="font-size:20px;color:var(--faint)">/${ins.total}</span></b><span>характеристик известно</span></div>
      <div class="stat"><b>${qn}</b><span>${plural(qn, "вопрос", "вопроса", "вопросов")} к вам</span></div>
      <div class="stat"><b>${top ? Math.round(top.percentile * 100) + "%" : "—"}</b><span>${top ? `соседей вы обходите по пункту «${esc(top.title.toLowerCase())}»` : "сильные стороны появятся после ответов"}</span></div>
      <div class="stat"><b>${ins.searches_total}</b><span>запросов гостей в Адлере</span></div>
    </div>
    <div class="cols">
      <div>
        <h2 class="h2">${qn ? `${qn} ${plural(qn, "вопрос", "вопроса", "вопросов")} — одна минута` : "Все вопросы закрыты"}</h2>
        <p class="small muted" style="margin:-8px 0 16px">Спрашиваем только то, что ищут гости и в чём мы не уверены. Там, где мы уже посчитали, достаточно подтвердить.</p>
        <div id="qs">${cab.questions.map(qCard).join("") || `<button class="btn quiet" id="replan">Проверить, нет ли новых вопросов</button>`}</div>
        <h2 class="h2" style="margin-top:36px">Здесь мы с вами расходимся</h2><div id="cf">${conflictsHost(cab)}</div>
      </div>
      <div>
        <h2 class="h2">Чем вы сильнее соседей</h2>
        <ul class="rank">${ins.strengths.slice(0, 5).map((s) => `<li><span class="pct ${s.percentile < .5 ? "low" : ""}">${Math.round(s.percentile * 100)}%</span><span><b>${esc(s.title)}</b>: лучше, чем у ${Math.round(s.percentile * 100)}% отелей Адлера<br><span class="small muted">${esc(s.scope)}</span></span></li>`).join("")}</ul>
        <h2 class="h2" style="margin-top:36px">Что ищут гости</h2>
        <ul class="demand">${ins.demand.map((d) => { const mx = ins.demand[0].searches || 1; const you = d.you === null ? ["u", "не знаем — расскажите"] : d.you === false ? ["n", "у вас нет"] : ["y", d.you === true ? "у вас есть" : d.key === "beach_walk" ? `у вас ${Math.max(1, Math.round(d.you))} мин` : `у вас: ${fmt(d.you)}`]; return `<li><span>${esc(d.title)}</span><span class="meter"><span style="width:${(d.searches / mx) * 100}%"></span></span><span class="you ${you[0]}">${esc(you[1])}</span></li>`; }).join("")}</ul>
      </div>
    </div>
    <div class="section" style="margin-top:40px"><h2 class="h2">Что мы обещаем гостям о вас</h2><p class="small muted" style="margin:-8px 0 8px">Подтвердите — и гости увидят отметку «подтвердил отельер». Если что-то не так, поправьте: мы перепроверим.</p>
      <ul class="facts facts-host" id="hf">${cab.facts.filter((f) => f.scope !== "region").map((f) => `<li><div class="h"><span><span class="t">${esc(f.title)}: ${f.resolved ? esc(f.key === "beach_walk" ? (f.resolved.value < 1 ? "меньше минуты" : `${Math.round(f.resolved.value)} мин`) : fmt(f.resolved.value, f.unit)) : `<span class="muted">не знаем</span>`}</span>${f.resolved?.conflict && !f.resolved.conflict.resolved ? `<span class="tag c">расходимся</span>` : ""}<span class="s">${esc(f.resolved?.scope || f.description || "")}</span></span>
        <span class="acts">${f.resolved ? `<button class="btn quiet s" data-ok="${f.key}">Так и есть</button>` : ""}${f.type === "bool" ? `<button class="btn quiet s" data-set="${f.key}" data-v="true">Да</button><button class="btn quiet s" data-set="${f.key}" data-v="false">Нет</button>` : ""}</span></div></li>`).join("")}</ul></div>
  </div>`;
  $("#hp").addEventListener("change", (e) => { location.hash = `#/host/${e.target.value}`; });
  $("#replan")?.addEventListener("click", async () => { const r = await post(`/api/hotelier/${id}/plan`); toast(r.created.length ? `Новых вопросов: ${r.created.length}` : "Новых вопросов нет"); hostView(id); });
  $$("#qs .q").forEach((box) => {
    const qid = box.dataset.q, ta = $("textarea", box), out = $(".out", box);
    const send = async (text) => { const r = await post(`/api/questions/${qid}/answer`, { text }); out.innerHTML = r.resolved?.conflict && !r.resolved.conflict.resolved ? "Записали. Это расходится с нашим расчётом — перепроверим." : `<span class="done">Записали. Гости это увидят.</span>`; setTimeout(() => hostView(id), 1400); };
    $$("[data-quick]", box).forEach((b) => b.addEventListener("click", () => send(b.dataset.quick)));
    $("[data-send]", box).addEventListener("click", () => ta.value.trim() && send(ta.value.trim()));
    $("[data-sim]", box).addEventListener("click", async () => { ta.value = (await post(`/api/questions/${qid}/simulate`)).text; });
  });
  $$("#cf [data-win]").forEach((b) => b.addEventListener("click", async () => { await post(`/api/conflicts/${b.dataset.cid}/resolve`, { winner: b.dataset.win }); toast("Принято"); hostView(id); }));
  $$("#hf [data-ok]").forEach((b) => b.addEventListener("click", async () => { const f = cab.facts.find((x) => x.key === b.dataset.ok); await post(`/api/facts/${id}/${f.key}/correct`, { value: f.resolved.value, comment: "подтверждено отельером" }); toast("Подтверждено. Гости увидят отметку"); hostView(id); }));
  $$("#hf [data-set]").forEach((b) => b.addEventListener("click", async () => { await post(`/api/facts/${id}/${b.dataset.set}/correct`, { value: b.dataset.v === "true", comment: "указано отельером" }); toast("Сохранено"); hostView(id); }));
}
function qCard(q) {
  return `<div class="q" data-q="${q.id}"><div class="qt">${esc(q.text)}</div><div class="why">Почему спрашиваем: ${esc(q.reason)}</div>
    <div class="row">${(q.options || []).filter((o) => !/^(Частично|Уточню)/.test(o)).map((o, i) => `<button class="btn ${i ? "quiet" : "dark"} s" data-quick="${esc(o)}">${esc(o)}</button>`).join("")}</div>
    <textarea class="field" rows="2" placeholder="Или своими словами: «с собаками до 10 кг, 500 ₽ в сутки»"></textarea>
    <div class="row"><button class="btn quiet s" data-send>Ответить</button><button class="link small" data-sim>Подставить ответ симулятора</button></div><div class="out small"></div></div>`;
}
function conflictsHost(cab) {
  const open = cab.conflicts.filter((c) => c.status === "open");
  if (!open.length) return `<p class="small muted">Расхождений нет.</p>`;
  return open.map((c) => `<div class="q"><div class="qt">${esc(titleOf(c.key))}</div><div class="why">${esc(c.description)}</div>
    <div class="row"><button class="btn dark s" data-cid="${c.id}" data-win="a">Верно первое</button><button class="btn quiet s" data-cid="${c.id}" data-win="b">Верно второе</button></div></div>`).join("");
}

// ====================================================================== ОСТРОВОК
const OPS = [["overview", "Обзор"], ["conflicts", "Противоречия"], ["chars", "Характеристики"], ["quality", "Качество и разметка"], ["fresh", "Актуализация"], ["log", "Журнал агентов"]];
const pct = (v) => v == null ? "—" : `${Math.round(v * 100)}%`;
async function opsView(tab) {
  view().innerHTML = `<div class="wrap"><h1 class="page-title">Пульт правды</h1><p class="page-sub">Всё, что система знает об отелях Адлера, — с источником, уверенностью и сроком годности. Здесь разбираем, где источники спорят.</p>
    <div class="ops"><nav class="side" aria-label="Разделы">${OPS.map(([k, t]) => `<a href="#/ops/${k}" ${k === tab ? 'aria-current="page"' : ""}>${t}</a>`).join("")}</nav><div id="ob"><div class="loading">Считаем</div></div></div></div>`;
  const b = $("#ob");
  return ({ overview: opsOverview, conflicts: opsConflicts, chars: opsChars, quality: opsQuality, fresh: opsFresh, log: opsLog }[tab] || opsOverview)(b);
}
async function opsOverview(b) {
  const m = await api("/api/metrics");
  b.innerHTML = `<div class="stats" style="margin-top:0">
      <div class="stat"><b>${m.hotels}</b><span>отелей в Адлере</span></div><div class="stat"><b>${m.characteristics}</b><span>характеристик</span></div>
      <div class="stat"><b>${pct(m.avg_confident_coverage)}</b><span>известно с уверенностью от 70%</span></div><div class="stat"><b>${m.questions.per_hotel}</b><span>вопроса на отель (лимит — 3)</span></div></div>
    <div class="stats"><div class="stat"><b>${pct(m.questions.parsed_ok)}</b><span>ответов отельеров разобрано</span></div><div class="stat"><b>${m.conflicts.open || 0}</b><span>противоречий открыто</span></div><div class="stat"><b>${m.conflicts.resolved || 0}</b><span>противоречий решено</span></div><div class="stat"><b>${m.labels.n}</b><span>меток разметки</span></div></div>
    <h2 class="h2" style="margin-top:32px">Покрытие по характеристикам</h2>
    <table class="t"><thead><tr><th>Характеристика</th><th style="width:28%">Известно уверенно</th><th>Посчитано само</th><th>От отельера</th></tr></thead><tbody>
    ${Object.values(m.coverage).map((c) => `<tr><td>${esc(c.title)}<div class="tiny muted">${esc(c.group)}</div></td><td><div class="meter" style="margin:7px 0 4px"><span style="width:${c.confident * 100}%"></span></div><span class="tiny">${pct(c.confident)}</span></td><td>${pct(c.auto)}</td><td>${pct(c.hotelier)}</td></tr>`).join("")}</tbody></table>`;
}
async function opsConflicts(b) {
  const d = await api("/api/conflicts");
  b.innerHTML = `<h2 class="h2">${d.length} ${plural(d.length, "противоречие ждёт", "противоречия ждут", "противоречий ждут")} решения</h2>
    <p class="small muted" style="margin:-8px 0 16px">Когда отельер или гость спорит с расчётом, уверенность снижается, расчёт уходит на перепроверку, а здесь видны обе стороны.</p>
    <table class="t"><thead><tr><th>Отель</th><th>Что</th><th>Первое</th><th>Второе</th><th></th></tr></thead><tbody>
    ${d.map((c) => `<tr><td><a class="link" href="#/host/${c.hotel_id}">${esc(c.hotel)}</a></td><td>${esc(titleOf(c.key))}</td>
      <td>${c.a ? `<b>${esc(SRC[c.a.source_type] || c.a.source_type)}</b>: ${esc(fmt(c.a.value))}<div class="tiny muted">${esc(c.a.scope)}</div>` : ""}</td>
      <td>${c.b ? `<b>${esc(SRC[c.b.source_type] || c.b.source_type)}</b>: ${esc(fmt(c.b.value))}<div class="tiny muted">${esc(c.b.scope)}</div>` : ""}</td>
      <td style="white-space:nowrap"><button class="btn dark s" data-cid="${c.id}" data-win="a">Первое</button> <button class="btn quiet s" data-cid="${c.id}" data-win="b">Второе</button></td></tr>`).join("")}</tbody></table>`;
  $$("[data-win]", b).forEach((x) => x.addEventListener("click", async () => { await post(`/api/conflicts/${x.dataset.cid}/resolve`, { winner: x.dataset.win }); toast("Решено"); opsConflicts(b); }));
}
const TOOL_RU = { viewshed: "расчёт вида", facade_noise: "модель шума", walk_route: "пеший маршрут", poi_nearby: "места рядом", distance_to: "расстояние", drive_access: "подъезд на машине", construction_nearby: "стройки рядом", building_history: "история здания", osm_tag: "теги карты", hotelier_only: "только у отельера", climate: "климат" };
async function opsChars(b) {
  const d = await api("/api/characteristics");
  const groups = {}; for (const s of d.specs) (groups[s.group] ||= []).push(s);
  b.innerHTML = `<div class="q" style="padding:24px"><h2 class="h2">Новая характеристика — обычным текстом</h2>
      <p class="small muted" style="margin:-8px 0 14px">Агент сам подберёт инструмент и теги OpenStreetMap, проверит на нескольких отелях и соберёт по всем. Код менять не нужно.</p>
      <textarea class="field" id="nc" rows="2" placeholder="рядом есть кафе, открытое после 23:00, в 300 метрах"></textarea>
      <div class="row" style="margin-top:12px"><button class="btn dark" id="cmp">Собрать</button>${["банкомат в 200 м", "кофейня в 5 минутах пешком", "есть ли в номерах кухня"].map((x) => `<button class="pill" data-ex="${x}">${x}</button>`).join("")}</div><div id="cmpout"></div></div>
    ${Object.entries(groups).map(([g, ss]) => `<h2 class="h2" style="margin-top:32px">${esc(g)}</h2><table class="t"><thead><tr><th>Характеристика</th><th>Инструмент агента</th><th>Источники</th><th>Живёт</th></tr></thead><tbody>
      ${ss.map((s) => `<tr><td><b>${esc(s.title)}</b><div class="tiny muted">${esc(s.description || "")}</div></td><td><b class="small">${esc(TOOL_RU[s.tool] || s.tool)}</b><details class="tiny muted"><summary>параметры</summary><code>${esc(s.tool)}</code> ${esc(JSON.stringify(s.params))}</details></td><td class="small">${esc((s.sources || []).join(", "))}</td><td style="white-space:nowrap">${s.ttl_days} дн.</td></tr>`).join("")}</tbody></table>`).join("")}`;
  $$("[data-ex]", b).forEach((x) => x.addEventListener("click", () => { $("#nc").value = x.dataset.ex; }));
  $("#cmp").addEventListener("click", async () => {
    const text = $("#nc").value.trim(); if (!text) return;
    const r = await post("/api/characteristics/compile", { text }), spec = r.spec;
    $("#cmpout").innerHTML = `<p class="small" style="margin-top:16px">${String(spec._compiler || "").startsWith("fallback") ? "В открытых данных этого нет — заполнят отельеры: после сохранения вопрос появится у них в кабинете." : `Собрано ${esc(String(spec._compiler || "").startsWith("llm") ? "языковой моделью" : "по шаблонам")}.`} Проверка на первых отелях:</p>
      <pre class="spec">${esc(JSON.stringify(Object.fromEntries(Object.entries(spec).filter(([k]) => !k.startsWith("_"))), null, 2))}</pre>
      ${r.errors.length ? `<p class="tag c">${esc(r.errors.join("; "))}</p>` : ""}
      <table class="t">${r.preview.map((p) => `<tr><td>${esc(p.hotel)}</td><td>${esc(fmt(p.value))}</td><td class="tiny muted">${esc(p.scope)}</td></tr>`).join("")}</table>
      <div class="row" style="margin-top:12px"><button class="cta" id="save" ${r.errors.length ? "disabled" : ""}>Добавить и собрать по всем отелям</button><span class="small muted" id="job"></span></div>`;
    $("#save").addEventListener("click", async () => {
      const s = await post("/api/characteristics", spec);
      const tick = async () => { const j = await api(`/api/jobs/${encodeURIComponent(s.job)}`); $("#job").textContent = `собрано ${j.done} из ${j.total}`; if (j.done < j.total) setTimeout(tick, 700); else { toast("Готово: гости уже могут искать по новой характеристике"); state.meta = await api("/api/meta"); } };
      tick();
    });
  });
}
async function opsQuality(b, key = "sea_view") {
  const [m, d] = await Promise.all([api("/api/metrics"), api(`/api/labels/queue?key=${key}&n=12`)]);
  const lab = m.labels;
  b.innerHTML = `<h2 class="h2">Точность по разметке: ${lab.n} ${plural(lab.n, "метка", "метки", "меток")}</h2>
    ${Object.keys(lab.accuracy).length ? `<table class="t"><thead><tr><th></th><th>меток</th><th>точность</th><th>precision</th><th>recall</th></tr></thead><tbody>${Object.values(lab.accuracy).map((a) => `<tr><td>${esc(a.title)}</td><td>${a.n}</td><td>${pct(a.accuracy)}</td><td>${pct(a.precision)}</td><td>${pct(a.recall)}</td></tr>`).join("")}</tbody></table>
      <p class="small">Brier score: ${lab.brier ?? "—"} (0 — идеально, 0,25 — монетка). Калибровка: ${lab.calibration.map((c) => `при уверенности ${c.bin} верно ${pct(c.accuracy)} (${c.n})`).join("; ")}.</p>` : `<p class="muted">Меток пока нет. Разметьте отели ниже — без этого точность не доказать.</p>`}
    <h2 class="h2" style="margin-top:32px">Разметка вслепую</h2>
    <p class="small muted" style="margin:-8px 0 14px">Ответ системы скрыт, чтобы не подсказывать. В выборке поровну отелей, где система говорит «да», «нет» и где не уверена. Размечено: ${d.labeled}.</p>
    <select class="field" id="lk" style="max-width:320px;margin-bottom:12px">${["sea_view", "sunset_view", "mountain_view", "beach_no_crossing", "quiet_night"].map((k) => `<option value="${k}" ${k === key ? "selected" : ""}>${esc(titleOf(k))}</option>`).join("")}</select>
    <table class="t">${d.items.map((it) => `<tr><td><b>${esc(it.name)}</b><div class="tiny"><a class="link" target="_blank" rel="noopener" href="https://yandex.ru/maps/?ll=${it.lon},${it.lat}&z=18&l=stv,sta">панорамы</a> &nbsp; <a class="link" target="_blank" rel="noopener" href="https://yandex.ru/search/?text=${encodeURIComponent(it.name + " Адлер вид из окна отзывы")}">отзывы</a></div></td>
      <td style="white-space:nowrap;text-align:right">${key === "quiet_night" ? ["тихо", "умеренно", "шумно"].map((v) => `<button class="btn quiet s" data-l="${it.id}" data-v='${JSON.stringify(v)}'>${v}</button>`).join(" ") : `<button class="btn quiet s" data-l="${it.id}" data-v="true">да</button> <button class="btn quiet s" data-l="${it.id}" data-v="false">нет</button>`}</td></tr>`).join("")}</table>`;
  $("#lk").addEventListener("change", (e) => opsQuality(b, e.target.value));
  $$("[data-l]", b).forEach((x) => x.addEventListener("click", async () => { await post("/api/labels", { hotel_id: x.dataset.l, key, value: JSON.parse(x.dataset.v), evidence: "разметка вслепую" }); x.closest("tr").remove(); toast("Метка сохранена"); }));
}
async function opsFresh(b) {
  b.innerHTML = `<h2 class="h2">Что, если рядом построят дом?</h2>
    <p class="small muted" style="margin:-8px 0 14px">Кликните по карте — там появится дом выбранной высоты. Агент пересчитает вид и шум у соседей и покажет, у кого что изменилось.</p>
    <div class="row" style="display:flex;gap:10px;align-items:center;margin-bottom:12px"><label for="wh">Высота дома, м</label><input class="field" id="wh" type="number" value="45" style="max-width:100px"><span class="small muted" id="wout"></span></div>
    <div id="opsmap"></div><div id="wres" style="margin-top:14px"></div>
    <h2 class="h2" style="margin-top:36px">Срок годности данных</h2><p class="small muted" style="margin:-8px 0 14px">Стройки живут 30 дней, часы работы — 90, вид из окна — год. Если гость или отельер оспорил расчёт, он пересчитывается сразу.</p>
    <button class="btn dark" id="stale">Перепроверить устаревшее</button> <span class="small" id="sout"></span>`;
  $("#stale").addEventListener("click", async () => { const r = await post("/api/refresh/stale"); $("#sout").textContent = `перепроверено отелей: ${r.hotels}, изменилось значений: ${r.changed.length}`; });
  if (!window.L) { $("#opsmap").innerHTML = `<div class="loading">Карта не загрузилась.</div>`; return; }
  const bb = state.meta.bbox, hs = await hotelsList();
  const map = L.map("opsmap").fitBounds([[bb[0], bb[1]], [bb[2], bb[3]]]);
  window.__opsmap = map;
  map.attributionControl.setPrefix(false).addAttribution("данные © участники OpenStreetMap");
  basemapLayer(await getBasemap()).addTo(map);
  hs.forEach((h) => L.circleMarker([h.lat, h.lon], { radius: 5, color: "#fff", weight: 1.5, fillColor: "#1F2124", fillOpacity: 1 }).bindTooltip(h.name).addTo(map));
  map.on("click", async (e) => {
    const height = +$("#wh").value || 45;
    $("#wout").textContent = "пересчитываю…";
    const r = await post("/api/whatif/building", { lat: e.latlng.lat, lon: e.latlng.lng, height });
    L.polygon(r.polygon, { color: "#FF5A36", weight: 2, fillOpacity: .7 }).bindTooltip(`новый дом, ${height} м`).addTo(map);
    $("#wout").textContent = `проверено отелей рядом: ${r.checked}, изменений: ${r.changes.length}`;
    $("#wres").innerHTML = r.changes.length ? `<table class="t">${r.changes.slice(0, 15).map((c) => `<tr><td><b>${esc(c.hotel)}</b></td><td>${esc(c.title)}</td><td class="tiny">было: ${esc(c.before)}<br>стало: ${esc(c.after)}</td></tr>`).join("")}</table>` : `<p class="small muted">Ни у кого вид не изменился: дом далеко или ниже соседей.</p>`;
  });
}
const AGENT_RU = { collector: "сборщик", hotelier: "агент отельера", refresher: "актуализатор", compiler: "конструктор характеристик", search: "поиск", guest: "гость" };
async function opsLog(b) {
  const [d, hs] = await Promise.all([api("/api/log?limit=200"), hotelsList()]);
  const name = (id) => hs.find((h) => h.id === id)?.name || id;
  b.innerHTML = `<h2 class="h2">Журнал агентов</h2><p class="small muted" style="margin:-8px 0 14px">Каждое решение агентов: что посчитано, чем и с какой уверенностью, что спросили у отельера и почему.</p>
    <ul class="log">${d.map((l) => `<li><span class="ag">${esc(AGENT_RU[l.agent] || l.agent)}</span>${l.hotel_id && l.hotel_id !== "_region" ? `<a class="link" href="#/host/${l.hotel_id}">${esc(name(l.hotel_id))}</a>: ` : ""}${esc(l.message)} <span class="tiny muted">${ago(l.ts)}</span></li>`).join("")}</ul>`;
}

// ====================================================================== старт
(async function boot() {
  state.meta = await api("/api/meta");
  $("#barinfo").textContent = `${state.meta.region}, ${state.meta.hotels} отелей${state.meta.llm.available ? `, LLM: ${state.meta.llm.model}` : ""}`;
  route();
})();

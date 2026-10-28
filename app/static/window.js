"use strict";
/* Вид из окна по реальным данным: профиль горизонта (здания и рельеф до 4 км), дальний рельеф (горы),
   море по азимутам и положение солнца в выбранный момент. Это не фото и не картинка из стока —
   это иллюстрация расчёта: что видно, а что закрыто, определяет геометрия. */
const Win = (() => {
  const FOV = 60;
  const SIDE = { "С": "север", "СВ": "северо-восток", "В": "восток", "ЮВ": "юго-восток", "Ю": "юг", "ЮЗ": "юго-запад", "З": "запад", "СЗ": "северо-запад" };
  const rel = (az, n) => ((az - n + 540) % 360) - 180;
  const lerp = (a, b, t) => a + (b - a) * t;
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const mix = (a, b, t) => { const A = hex(a), B = hex(b); return "#" + A.map((v, i) => Math.round(lerp(v, B[i], Math.max(0, Math.min(1, t)))).toString(16).padStart(2, "0")).join(""); };

  // небо по высоте солнца: [зенит, середина, низ, у горизонта]
  const SKY = [
    [-12, ["#04081A", "#0A1230", "#141E44", "#1C2A55"]],
    [-6, ["#0B1336", "#23295C", "#5A3E78", "#9A5A7A"]],
    [-2, ["#18224F", "#4B3C7A", "#B0607A", "#F08A5D"]],
    [1.5, ["#22397A", "#6E5A93", "#E58A72", "#FFB46A"]],
    [5, ["#2B5BA6", "#7FA3D6", "#F2C2A0", "#FFD9A6"]],
    [12, ["#2F78C8", "#71ADE6", "#B7DAF3", "#E2F1FA"]],
    [30, ["#2C74C4", "#5FA3E2", "#A6D0F0", "#D6ECF8"]],
  ];
  function palette(el) {
    let i = 0;
    while (i < SKY.length - 1 && el > SKY[i + 1][0]) i++;
    if (i >= SKY.length - 1) return SKY[SKY.length - 1][1];
    const [e0, c0] = SKY[i], [e1, c1] = SKY[i + 1];
    return c0.map((c, k) => mix(c, c1[k], (el - e0) / (e1 - e0)));
  }
  const light = (el) => Math.max(0, Math.min(1, (el + 6) / 18));

  function sunAt(sun, hhmm) {
    let best = sun.track[0];
    for (const p of sun.track) if (p[0] <= hhmm) best = p;
    return { t: best[0], az: best[1], el: best[2] };
  }
  function horizonAt(side, az) {
    const d = rel(az, side.az);
    if (Math.abs(d) > FOV) return null;
    const i = Math.round((d + FOV) / (2 * FOV) * (side.azs.length - 1));
    return { near: side.near[i], far: side.far[i], sea: side.sea[i], i };
  }

  /* События дня для одной стороны окна */
  function events(side, sun) {
    const vis = sun.track.map(([t, az, el]) => {
      const h = horizonAt(side, az);
      if (!h || el < -0.6) return { t, ok: false, az, el };
      return { t, ok: el > Math.max(h.near, h.far, -0.6) + 0.2, az, el, h };
    });
    const out = { side: side.side };
    const pm = vis.filter((v) => v.az > 180), am = vis.filter((v) => v.az <= 180);
    const lastPm = [...pm].reverse().find((v) => v.ok);
    if (lastPm && lastPm.el <= 3) {
      const intoSea = lastPm.h && lastPm.h.sea && lastPm.el < 1.5 && lastPm.h.near < 0.6;
      out.sunset = { t: lastPm.t, intoSea, behind: lastPm.el > 1.5 ? (lastPm.h.far > lastPm.h.near ? "горы" : "дома") : null, real: sun.sunset ? sun.sunset[0] : null, az: lastPm.az };
    } else if (lastPm) {
      const next = vis[vis.indexOf(lastPm) + 1];
      out.evening = { t: lastPm.t, leaves: !next || !horizonAt(side, next.az), el: lastPm.el, real: sun.sunset ? sun.sunset[0] : null };
    }
    const firstAm = am.find((v) => v.ok);
    if (firstAm && firstAm.el < 6) out.sunrise = { t: firstAm.t, overMountains: firstAm.h && firstAm.h.far > 0.8 && firstAm.h.far >= firstAm.h.near, az: firstAm.az };
    const firstAny = vis.find((v) => v.ok);
    if (firstAny && !out.sunrise) out.sunFrom = firstAny.t;
    out.seaShare = side.sea.filter(Boolean).length / side.sea.length;
    out.mtnShare = side.far.filter((f, i) => f > 0.7 && f > side.near[i]).length / side.far.length;
    const seaD = side.sea_d.filter((x) => x != null).sort((a, b) => a - b);
    out.seaDist = seaD.length ? seaD[Math.floor(seaD.length / 2)] : null;
    return out;
  }

  function rand(seed) { let s = seed % 2147483647; if (s <= 0) s += 2147483646; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
  const smooth = (pts) => pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");

  /* SVG-кадр. opts: w, h, horizon (доля высоты), vex (вертикальное усиление), labels, cropTo/cropSpan/cropAspect, grain */
  function render(side, s, opts = {}) {
    const W = opts.w || 1200, H = opts.h || 900, y0 = H * (opts.horizon || 0.64), k = (W / (2 * FOV)) * (opts.vex || 1.8);
    const n = side.azs.length, X = (i) => (i / (n - 1)) * W, Y = (el) => y0 - el * k;
    const el = s ? s.el : 8;
    const [z0, z1, z2, z3] = palette(el), L = light(el);
    const id = "w" + Math.random().toString(36).slice(2, 8);
    const sunRel = s ? rel(s.az, side.az) : 999, sunIn = s && Math.abs(sunRel) <= FOV + 12 && s.el > -3;
    const sunX = ((sunRel + FOV) / (2 * FOV)) * W, sunY = s ? Y(s.el) : 0;
    const warm = sunIn ? Math.max(0, 1 - Math.abs(s.el - 1) / 10) : 0;   // сила закатного света
    const mtnTop = mix(mix("#2A3160", "#9AA9C8", L), z3, 0.35), mtnBot = mix(mix("#151B3A", "#6C7FA3", L), z2, 0.2);
    const bldTop = mix(mix("#121834", "#62717F", L), z3, 0.12 + warm * 0.18), bldBot = mix("#0A0F22", "#3E4B57", L);
    const seaTop = mix(z3, mix("#1D3A66", "#5BA8C8", L), 0.35), seaBot = mix("#081028", mix("#0F4E6B", "#1E7194", L), L);
    const grd0 = mix("#070B1A", "#33423E", L), grd1 = mix("#03050D", "#1C2622", L);
    let g = `<defs>
      <linearGradient id="${id}s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${z0}"/><stop offset=".45" stop-color="${z1}"/><stop offset=".82" stop-color="${z2}"/><stop offset="1" stop-color="${z3}"/></linearGradient>
      <linearGradient id="${id}m" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${mtnTop}"/><stop offset="1" stop-color="${mtnBot}"/></linearGradient>
      <linearGradient id="${id}b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${bldTop}"/><stop offset="1" stop-color="${bldBot}"/></linearGradient>
      <linearGradient id="${id}w" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${seaTop}"/><stop offset="1" stop-color="${seaBot}"/></linearGradient>
      <linearGradient id="${id}e" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${grd0}"/><stop offset="1" stop-color="${grd1}"/></linearGradient>
      <linearGradient id="${id}h" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${z3}" stop-opacity="0"/><stop offset="1" stop-color="${mix(z3, "#ffffff", .25)}" stop-opacity=".55"/></linearGradient>
      <radialGradient id="${id}g"><stop offset="0" stop-color="#FFF6E0" stop-opacity="1"/><stop offset=".12" stop-color="#FFE2A6" stop-opacity=".85"/><stop offset=".35" stop-color="#FFB46A" stop-opacity=".35"/><stop offset="1" stop-color="#FF7A45" stop-opacity="0"/></radialGradient>
      <radialGradient id="${id}v" cx=".5" cy=".45" r=".75"><stop offset=".6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".38"/></radialGradient>
      ${opts.grain ? `<filter id="${id}n"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 .5 0 0 0 0 .5 0 0 0 0 .5 0 0 0 .07 0"/></filter>` : ""}
    </defs>`;
    g += `<rect width="${W}" height="${y0 + 2}" fill="url(#${id}s)"/>`;
    if (el < -5) { const r = rand(7); for (let i = 0; i < 90; i++) g += `<circle cx="${(r() * W).toFixed(0)}" cy="${(r() * y0 * .75).toFixed(0)}" r="${(r() * 1.2 + .3).toFixed(1)}" fill="#fff" opacity="${(r() * .6 + .2 * (1 - L)).toFixed(2)}"/>`; }
    // солнце и его ореол
    if (sunIn) {
      const R = Math.max(10, k * 0.55);
      g += `<circle cx="${sunX}" cy="${sunY}" r="${R * (6 + warm * 8)}" fill="url(#${id}g)" opacity="${.55 + warm * .45}"/>`;
      g += `<circle cx="${sunX}" cy="${sunY}" r="${R}" fill="${s.el < 4 ? "#FFE4B0" : "#FFFBF0"}"/>`;
    }
    // дымка у горизонта
    g += `<rect y="${y0 - H * 0.12}" width="${W}" height="${H * 0.12}" fill="url(#${id}h)"/>`;
    // горы (дальний рельеф) + подсветка гребня, если солнце низко
    const mp = [[0, y0]]; for (let i = 0; i < n; i++) mp.push([X(i), Y(Math.max(side.far[i], 0))]); mp.push([W, y0]);
    g += `<polygon points="${smooth(mp)}" fill="url(#${id}m)"/>`;
    if (warm > .2) g += `<polyline points="${smooth(mp.slice(1, -1).filter((p) => p[1] < y0 - 2))}" fill="none" stroke="${mix(z3, "#ffffff", .3)}" stroke-opacity="${(warm * .35).toFixed(2)}" stroke-width="1.5"/>`;
    // земля под горизонтом
    g += `<rect y="${y0}" width="${W}" height="${H - y0}" fill="url(#${id}e)"/>`;
    // море по азимутам
    const eye = side.eye_m || 10;
    let i = 0;
    while (i < n) {
      if (!side.sea[i]) { i++; continue; }
      let j = i; while (j + 1 < n && side.sea[j + 1]) j++;
      const top = [], bot = [];
      for (let q = i; q <= j; q++) {
        const dip = Math.atan(eye / Math.max(60, side.sea_d[q] || 800)) * 180 / Math.PI;
        top.push([X(q - 0.5), y0], [X(q + 0.5), y0]);
        bot.unshift([X(q + 0.5), y0 + dip * k + 2], [X(q - 0.5), y0 + dip * k + 2]);
      }
      g += `<polygon points="${smooth(top.concat(bot))}" fill="url(#${id}w)"/>`;
      // рябь
      const r = rand(31 + i), depth = Math.max(...bot.map((p) => p[1])) - y0;
      for (let w = 0; w < (j - i + 1) * 1.2; w++) {
        const yy = y0 + 2 + Math.pow(r(), 1.8) * depth, xx = X(i) + r() * (X(j) - X(i)), ll = 8 + r() * 40 * (yy - y0) / Math.max(depth, 1);
        g += `<rect x="${xx.toFixed(0)}" y="${yy.toFixed(1)}" width="${ll.toFixed(0)}" height="1" fill="#fff" opacity="${(.05 + .1 * L).toFixed(2)}"/>`;
      }
      g += `<rect x="${X(i)}" y="${y0 - 0.5}" width="${X(j) - X(i)}" height="1.2" fill="${mix(z3, "#ffffff", .4)}" opacity=".55"/>`;
      i = j + 1;
    }
    // дорожка солнца на воде
    if (sunIn && s.el < 25 && s.el > -1.5) {
      const hi = horizonAt(side, s.az);
      if (hi && hi.sea) {
        const r = rand(11);
        for (let q = 0; q < 34; q++) {
          const yy = y0 + 1.5 + q * q * 0.09 + q * 1.1, ww = 6 + q * 2.6 + r() * 12;
          g += `<rect x="${(sunX - ww / 2 + (r() - .5) * q * 1.6).toFixed(1)}" y="${yy.toFixed(1)}" width="${ww.toFixed(1)}" height="${(1.2 + q * .05).toFixed(2)}" rx="1" fill="#FFE1A8" opacity="${Math.max(0, .9 - q * .026).toFixed(2)}"/>`;
        }
      }
    }
    // ближние силуэты: дома и холмы
    const bp = [[0, y0]]; for (let q = 0; q < n; q++) bp.push([X(q), Y(Math.max(side.near[q], 0))]); bp.push([W, y0]);
    g += `<polygon points="${smooth(bp)}" fill="url(#${id}b)"/>`;
    if (warm > .15) g += `<polyline points="${smooth(bp.slice(1, -1).filter((p) => p[1] < y0 - 3))}" fill="none" stroke="#FFC890" stroke-opacity="${(warm * .4).toFixed(2)}" stroke-width="1.2"/>`;
    // окна соседей: днём еле видны, вечером горят
    const r = rand(23), lit = el < 4;
    for (let q = 0; q < n; q += 1) {
      if (side.near[q] < 0.8 || !side.near_is_building[q]) continue;
      const top = Y(side.near[q]), rows = Math.min(9, Math.floor((y0 - top) / 13));
      for (let c = 0; c < rows; c++) {
        if (r() > (lit ? 0.32 : 0.22)) continue;
        g += `<rect x="${(X(q) + (r() - .5) * k * .8).toFixed(1)}" y="${(top + 7 + c * 13).toFixed(1)}" width="3" height="4" fill="${lit ? "#FFD58C" : "#B9C8D3"}" opacity="${lit ? (.55 + r() * .45).toFixed(2) : ".22"}"/>`;
      }
    }
    if (opts.labels) {
      for (let a = Math.ceil((side.az - FOV) / 45) * 45; a <= side.az + FOV; a += 45) {
        const x = ((rel(a, side.az) + FOV) / (2 * FOV)) * W;
        const nm = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"][(((a % 360) + 360) % 360) / 45];
        g += `<text x="${x}" y="${H - 26}" text-anchor="middle" font-family="Onest, sans-serif" font-size="${Math.round(W * .012)}" font-weight="600" fill="#fff" opacity=".75">${SIDE[nm]}</text>`;
      }
    }
    g += `<rect width="${W}" height="${H}" fill="url(#${id}v)"/>`;
    if (opts.grain) g += `<rect width="${W}" height="${H}" filter="url(#${id}n)"/>`;
    let vb = `0 0 ${W} ${H}`;
    if (opts.cropTo != null) {
      const span = opts.cropSpan || 80, c = ((rel(opts.cropTo, side.az) + FOV) / (2 * FOV)) * W, wpx = (span / (2 * FOV)) * W;
      const x0 = Math.max(0, Math.min(W - wpx, c - wpx / 2)), hpx = Math.min(H, wpx * (opts.cropAspect || 0.62)), ytop = Math.max(0, Math.min(H - hpx, y0 - hpx * 0.64));
      vb = `${x0.toFixed(1)} ${ytop.toFixed(1)} ${wpx.toFixed(1)} ${hpx.toFixed(1)}`;
    }
    return `<svg viewBox="${vb}" preserveAspectRatio="xMidYMid slice" role="img" aria-label="${esc(opts.alt || "Вид из окна")}">${g}</svg>`;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  return { render, events, sunAt, horizonAt, palette, SIDE };
})();

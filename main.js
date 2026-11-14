/* Shade Queue static web map. Reads files exported by `python -m pipeline export` (no server needed).
   MapLibre basemap (CARTO Positron, no token) + deck.gl layers. */
const COLORS = { lidar: [47, 125, 79], allometric: [138, 166, 91], predicted: [224, 123, 38] };
const HVI_COLORS = { 1: [255, 255, 204], 2: [255, 217, 142], 3: [254, 178, 76], 4: [253, 141, 60], 5: [227, 26, 28] };
const state = {
  aoi: null, meta: null, trees: [], buildings: null, sites: null, hvi: null, scen: {},
  dayIdx: [], idx: 0, tShadows: [], bShadows: [],
  colorMode: "source", show: { bshadow: true, tshadow: true, sites: true, hvi: false },
  selected: null, planted: null, plantedYear: 10, species: null, topN: 50, playing: null,
};
const $ = (id) => document.getElementById(id);
const getJSON = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(`${u}: ${r.status}`); return r.json(); });
const dataUrl = (f) => `data/${state.aoi}/${f}`;

/* ---------- meshes (loaders.gl Mesh format, non-indexed triangles) ---------- */
function meshFrom(tris) {
  const pos = new Float32Array(tris.flatMap((t) => t.p)), nor = new Float32Array(tris.flatMap((t) => t.n));
  return { header: { vertexCount: pos.length / 3 }, mode: 4, topology: "triangle-list",
           attributes: { POSITION: { value: pos, size: 3 }, NORMAL: { value: nor, size: 3 } } };
}
function sphereMesh(lat = 12, lon = 18) {
  const v = (i, j) => { const th = (i / lat) * Math.PI, ph = (j / lon) * 2 * Math.PI;
    return [Math.sin(th) * Math.cos(ph), Math.sin(th) * Math.sin(ph), Math.cos(th)]; };
  const tris = [];
  for (let i = 0; i < lat; i++) for (let j = 0; j < lon; j++) {
    const a = v(i, j), b = v(i + 1, j), c = v(i + 1, j + 1), d = v(i, j + 1);
    tris.push({ p: [...a, ...b, ...c], n: [...a, ...b, ...c] }, { p: [...a, ...c, ...d], n: [...a, ...c, ...d] });
  }
  return meshFrom(tris);
}
function coneMesh(seg = 18) {
  const tris = [];
  for (let j = 0; j < seg; j++) {
    const a0 = (j / seg) * 2 * Math.PI, a1 = ((j + 1) / seg) * 2 * Math.PI;
    const p0 = [Math.cos(a0), Math.sin(a0), -1], p1 = [Math.cos(a1), Math.sin(a1), -1];
    tris.push({ p: [...p0, ...p1, 0, 0, 1], n: [Math.cos(a0), Math.sin(a0), 0.5, Math.cos(a1), Math.sin(a1), 0.5, 0, 0, 1] });
    tris.push({ p: [...p1, ...p0, 0, 0, -1], n: [0, 0, -1, 0, 0, -1, 0, 0, -1] });
  }
  return meshFrom(tris);
}
const SPHERE = sphereMesh(), CONE = coneMesh();

/* ---------- geometry helpers (mirror pipeline/shade/geometry.py) ---------- */
function decodeRings(rings) {
  const o = state.meta.origin;
  return rings.map((r) => { const ring = [];
    for (let i = 0; i < r.length; i += 2) ring.push([o.lon0 + r[i] / 10 / o.kx, o.lat0 + r[i + 1] / 10 / o.ky]);
    ring.push(ring[0]); return ring; });
}
function crownProfile(shape, base, top, R, n = 7) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const z = base + (top - base) * (i / (n - 1)), t = i / (n - 1);
    let r;
    if (shape === "cone") r = R * (1 - t);
    else if (shape === "cylinder") r = R;
    else if (shape === "umbrella") { const u = (t - 0.65) / (t < 0.65 ? 0.65 : 0.35); r = R * Math.sqrt(Math.max(0, 1 - u * u)); }
    else r = R * Math.sqrt(Math.max(0, 1 - (2 * t - 1) ** 2));
    out.push([z, Math.max(r, 0.15 * R)]);
  }
  return out;
}
function hull(pts) {  // monotone chain
  pts = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const p of pts) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
  for (const p of pts.reverse()) { while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
  return lo.slice(0, -1).concat(up.slice(0, -1));
}
function crownShadow(c, alt, az) {
  if (alt < 5) return null;
  const k = 1 / Math.tan((alt * Math.PI) / 180), a = (az * Math.PI) / 180, ox = -k * Math.sin(a), oy = -k * Math.cos(a);
  const pts = [];
  for (const [z, r] of crownProfile(c.shape, c.crown_base_m, c.height_m, c.crown_radius_m))
    for (let j = 0; j < 16; j++) { const th = (j / 16) * 2 * Math.PI; pts.push([z * ox + r * Math.cos(th), z * oy + r * Math.sin(th)]); }
  const o = state.meta.origin, kx = 111320 * Math.cos((c.lat * Math.PI) / 180);
  const ring = hull(pts).map(([x, y]) => [c.lon + x / kx, c.lat + y / o.ky]);
  ring.push(ring[0]);
  return { polygon: [ring] };
}

/* ---------- map ---------- */
const map = new maplibregl.Map({
  container: "map", style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  center: [-73.9527, 40.8033], zoom: 16.3, pitch: 55, bearing: -28, antialias: true,
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
const overlay = new deck.MapboxOverlay({ interleaved: false, layers: [] });
map.addControl(overlay);

/* ---------- colours ---------- */
function hoursColor(h) { const t = Math.max(0, Math.min(1, (h || 0) / 12));
  return [Math.round(230 - 200 * t), Math.round(230 - 120 * t), Math.round(170 - 120 * t)]; }
const summerHours = (t) => t.days?.["2026-06-21"]?.h ?? 0;
function crownColor(t) {
  if (state.colorMode === "hours") return [...hoursColor(summerHours(t)), 235];
  return [...(COLORS[t.source] || COLORS.allometric), 225];
}
function pitColor(p) {
  if (p.rank <= state.topN) return [224, 123, 38, 245];
  return p.new_shade_m2h > 0 ? [240, 190, 140, 200] : [170, 170, 170, 170];
}

/* ---------- layers ---------- */
function crownLayer(id, data, meshShape, extra = {}) {
  return new deck.SimpleMeshLayer({
    id, data: data.filter((t) => (meshShape === "cone") === (t.shape === "cone")),
    mesh: meshShape === "cone" ? CONE : SPHERE, sizeScale: 1, pickable: true,
    getPosition: (t) => [t.lon, t.lat, (t.height_m + t.crown_base_m) / 2],
    getScale: (t) => [t.crown_radius_m, t.crown_radius_m, (t.height_m - t.crown_base_m) / 2],
    getColor: crownColor, material: { ambient: 0.45, diffuse: 0.65, shininess: 8, specularColor: [40, 40, 40] },
    updateTriggers: { getColor: [state.colorMode] }, ...extra,
  });
}
const trunkLayer = (id, data) => new deck.ColumnLayer({
  id, data, diskResolution: 6, radius: 0.25, extruded: true, getPosition: (t) => [t.lon, t.lat],
  getElevation: (t) => t.crown_base_m + 0.3, getFillColor: [110, 84, 60], material: false });

function render() {
  const L = [], ground = { depthTest: false };
  if (state.show.hvi && state.hvi) L.push(new deck.GeoJsonLayer({ id: "hvi", data: state.hvi, pickable: true,
    getFillColor: (f) => [...(HVI_COLORS[f.properties.hvi_quintile] || [200, 200, 200]), 70],
    getLineColor: [180, 30, 30, 160], lineWidthMinPixels: 1.5 }));
  if (state.show.bshadow) L.push(new deck.SolidPolygonLayer({ id: "bshadow", data: state.bShadows,
    getPolygon: (d) => d, getFillColor: [40, 48, 60, 95], parameters: ground }));
  if (state.show.tshadow) L.push(new deck.SolidPolygonLayer({ id: "tshadow", data: state.tShadows,
    getPolygon: (d) => d.polygon, getFillColor: (d) => d.leaf ? [36, 71, 107, 120] : [120, 120, 140, 45], parameters: ground }));
  if (state.planted) {
    const sh = crownShadow(state.planted.crown, ...state.meta.sun[state.dayIdx[state.idx]]);
    if (sh) L.push(new deck.SolidPolygonLayer({ id: "planted-shadow", data: [sh], getPolygon: (d) => d.polygon,
      getFillColor: [224, 123, 38, 120], parameters: ground }));
  }
  if (state.buildings) L.push(new deck.GeoJsonLayer({ id: "buildings", data: state.buildings, extruded: true,
    getElevation: (f) => f.properties.height_m, getFillColor: [222, 224, 230, 235], material: { ambient: 0.55, diffuse: 0.55, shininess: 4 } }));
  L.push(trunkLayer("trunks", state.trees), crownLayer("crowns", state.trees, "sphere"), crownLayer("crowns-cone", state.trees, "cone"));
  if (state.planted) {
    const c = [{ ...state.planted.crown, source: "predicted" }];
    L.push(trunkLayer("planted-trunk", c), crownLayer("planted-crown", c, c[0].shape === "cone" ? "cone" : "sphere", { pickable: false }));
  }
  if (state.show.sites && state.sites) L.push(new deck.ScatterplotLayer({ id: "sites", data: state.sites.features, pickable: true,
    radiusUnits: "meters", getRadius: (f) => (f.properties.rank <= state.topN ? 2.6 : 1.8), radiusMinPixels: 3,
    getPosition: (f) => f.geometry.coordinates, getFillColor: (f) => pitColor(f.properties), stroked: true,
    getLineColor: [255, 255, 255], lineWidthMinPixels: 1, updateTriggers: { getFillColor: [state.topN], getRadius: [state.topN] } }));
  if (state.meta?.focus) L.push(new deck.ScatterplotLayer({ id: "focus", data: [state.meta.focus], radiusUnits: "pixels",
    getRadius: 9, getPosition: (d) => [d.lon, d.lat], filled: true, getFillColor: [200, 30, 60, 230], stroked: true,
    getLineColor: [255, 255, 255], lineWidthMinPixels: 3, pickable: true, parameters: ground }));
  if (state.selected) L.push(new deck.ScatterplotLayer({ id: "sel", data: [state.selected], radiusUnits: "meters",
    getRadius: (d) => d.r, filled: false, stroked: true, getPosition: (d) => d.pos, getLineColor: [20, 20, 20],
    lineWidthMinPixels: 2, parameters: ground }));
  overlay.setProps({ layers: L, onClick, getTooltip });
}

function getTooltip({ object, layer }) {
  if (!object || !layer) return null;
  if (layer.id.startsWith("crowns")) return { text: `${object.species_label || object.species || "Unknown"}\n${object.height_m.toFixed(1)} m tall · ${object.source}\nsummer sidewalk shade: ${summerHours(object)} h` };
  if (layer.id === "sites") { const p = object.properties;
    return { text: `Empty pit #${p.rank} · ${p.address || p.streetname}\n${p.new_shade_m2h} m²·h new shade · click to plant` }; }
  if (layer.id === "hvi") return { text: `${object.properties.ntaname}\nHeat vulnerability ${object.properties.hvi_quintile} of 5` };
  if (layer.id === "focus") return { text: object.label };
  return null;
}

/* ---------- time ---------- */
const fmtTime = (ts) => ts.slice(11, 16);
async function setDay(day) {
  state.dayIdx = state.meta.timestamps.map((t, i) => [t, i]).filter(([t]) => t.startsWith(day)).map(([, i]) => i);
  const s = $("hour"); s.max = state.dayIdx.length - 1;
  const two = state.dayIdx.findIndex((i) => state.meta.timestamps[i].slice(11, 13) === "15");
  s.value = two >= 0 ? two : Math.floor(state.dayIdx.length / 2);
  await setHour(+s.value);
  if (state.selected?.treeId) openTree(state.selected.treeId);
}
const shadowCache = new Map();
async function setHour(i) {
  state.idx = i;
  const gi = state.dayIdx[i], ts = state.meta.timestamps[gi], key = state.aoi + gi;
  $("time-label").textContent = fmtTime(ts);
  if (!shadowCache.has(key)) shadowCache.set(key, getJSON(dataUrl(`shadows/${gi}.json`)).then((d) => ({
    t: d.t.map((s) => ({ polygon: decodeRings(s.r), leaf: !!s.l })), b: decodeRings(d.b) })));
  const d = await shadowCache.get(key);
  if (state.dayIdx[state.idx] !== gi) return;
  state.tShadows = d.t; state.bShadows = d.b;
  const day = ts.slice(0, 10);
  let n = 0, shade = 0;
  for (const t of state.trees) { const h = t.hourly?.[day]; const dd = t.days?.[day];
    if (h && dd?.leaf) { n++; shade += h[state.idx] || 0; } }
  $("stats").textContent = n ? `${n.toLocaleString()} trees in leaf · ${Math.round(shade).toLocaleString()} m² of sidewalk shaded by trees right now (net of building shade)`
    : "Leaf-off: deciduous crowns are bare, so their shadows are drawn faint and not counted as shade.";
  render();
}

/* ---------- planting queue ---------- */
function queueStats() {
  const pits = state.sites.features.map((f) => f.properties);
  const total = pits.reduce((a, p) => a + p.new_shade_m2h, 0), n = Math.min(state.topN, pits.length);
  const top = pits.filter((p) => p.rank <= n).reduce((a, p) => a + p.new_shade_m2h, 0);
  const unranked = (total / pits.length) * n;
  const s = state.meta.sites_summary;
  $("topn").max = Math.max(10, Math.min(200, pits.length));
  $("topn-label").textContent = n;
  $("queue-stats").innerHTML = `
    <div><span class="big">${Math.round((top / total) * 100)}%</span> of the area's possible new sidewalk shade
    from ${n} of ${pits.length} empty pits</div>
    <div><b>${(top / unranked).toFixed(1)}×</b> the shade per tree vs. planting ${n} pits in no particular order ·
    ${Math.round(top).toLocaleString()} m²·h per July afternoon</div>
    <div class="muted">${s.zero_pits} pits would add no new shade (already shaded or no sidewalk in reach).
    ${s.geocoded ? `${s.geocoded} pits recovered from placeholder coordinates.` : ""}</div>`;
  render();
}

/* ---------- panels ---------- */
function barChart(values, labels, color, unit, win) {
  const w = 330, h = 120, pad = 22, n = values.length, max = Math.max(1, ...values), bw = (w - pad) / n;
  const bars = values.map((v, i) => {
    const bh = (v / max) * (h - 30), x = pad + i * bw;
    const bg = win && win(labels[i]) ? `<rect class="win" x="${x}" y="8" width="${bw}" height="${h - 24}"/>` : "";
    return `${bg}<rect x="${x + 1}" y="${h - 16 - bh}" width="${bw - 2}" height="${bh}" rx="2" fill="${color}"><title>${labels[i]}: ${v.toFixed(1)} ${unit}</title></rect>`
      + (i % Math.max(1, Math.ceil(n / 7)) === 0 ? `<text x="${x + bw / 2}" y="${h - 3}" text-anchor="middle">${labels[i]}</text>` : "");
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img"><text x="0" y="10">${max.toFixed(0)} ${unit}</text><line x1="${pad}" x2="${w}" y1="${h - 16}" y2="${h - 16}" stroke="#ccc"/>${bars}</svg>`;
}
function showPanel(html) { $("panel-body").innerHTML = html; $("panel").classList.remove("hidden"); }
$("close").onclick = () => { $("panel").classList.add("hidden"); state.selected = null; state.planted = null; render(); };

function openTree(id) {
  const t = state.trees.find((x) => x.tree_id === id); if (!t) return;
  const day = $("day").value, s = t.days?.[day] || {}, H = t.hourly?.[day] || [];
  const labels = state.dayIdx.map((i) => fmtTime(state.meta.timestamps[i]));
  state.selected = { treeId: id, pos: [t.lon, t.lat], r: t.crown_radius_m + 0.5 }; state.planted = null;
  showPanel(`
    <h2>${t.species_label || t.species || "Unknown species"}</h2>
    <span class="badge" style="background:rgb(${COLORS[t.source].join(",")})">${t.source}</span>
    <span class="muted">confidence ${Math.round(t.confidence * 100)}% · crown as of ${t.as_of_year}</span>
    <dl>
      <dt>Height</dt><dd>${t.height_m.toFixed(1)} m</dd>
      <dt>Crown radius</dt><dd>${t.crown_radius_m.toFixed(1)} m (base ${t.crown_base_m.toFixed(1)} m)</dd>
      <dt>Trunk DBH</dt><dd>${t.dbh_cm ? (t.dbh_cm / 2.54).toFixed(0) + " in" : "–"}</dd>
      <dt>Condition</dt><dd>${t.tpcondition || "–"}</dd>
      <dt>Usable sidewalk shade</dt><dd><b>${s.h ?? 0} h</b> on ${day}${s.leaf === false ? " (leaf-off)" : ""}</dd>
      <dt>Shadow on public ground</dt><dd>${s.pub != null ? Math.round(s.pub * 100) + "%" : "–"}</dd>
      <dt>Already in building shade</dt><dd>${s.self != null ? Math.round(s.self * 100) + "%" : "–"}</dd>
    </dl>
    <div class="muted">Sidewalk shade by hour (m², net of building shade)</div>
    ${barChart(H, labels.slice(0, H.length), "#24476b", "m²")}
    <p class="note">ForMS tree <code>${id.slice(0, 8)}…</code>. <i>lidar</i> crowns are measured from the 2021 NYC LiDAR; <i>allometric</i> crowns are estimated from trunk diameter (USFS Urban Tree Database, Queens).</p>`);
  render();
}

function plantAt(site, years) {
  const p = site.properties, sc = state.scen[p.site_id];
  if (!sc) return;
  const species = state.species || Object.keys(state.meta.species)[0];
  state.plantedYear = years; state.species = species;
  const pick = (sp, y) => { const a = sc[sp][String(y)];
    return { height_m: a[0], crown_radius_m: a[1], crown_base_m: a[2], shape: a[3], m2h: a[4], yld: a[5], prof: a[6] }; };
  const cur = pick(species, years);
  const [lon, lat] = site.geometry.coordinates;
  state.planted = { site, crown: { ...cur, lon, lat } };
  state.selected = { pos: [lon, lat], r: 3 };
  const times = state.meta.sites_summary.profile_times;
  const row = (y) => { const r = pick(species, y);
    return `<tr><td>${y} yr</td><td>${r.height_m.toFixed(1)} m</td><td>${r.crown_radius_m.toFixed(1)} m</td><td><b>${r.m2h}</b></td><td>${Math.round(r.yld * 100)}%</td></tr>`; };
  showPanel(`
    <h2>Pit #${p.rank} of ${state.sites.features.length} <span class="muted">${p.address || p.streetname}</span></h2>
    <span class="badge" style="background:rgb(${COLORS.predicted.join(",")})">predicted</span>
    <span class="muted">HVI ${p.hvi_quintile ?? "–"}/5 · ${p.ntaname || ""}${p.geocoded ? " · location recovered from address" : ""}</span>
    <label class="muted" style="display:block;margin-top:8px">Species
      <select id="species">${Object.entries(state.meta.species).map(([k, v]) => `<option ${k === species ? "selected" : ""} value="${k}">${v}</option>`).join("")}</select></label>
    <div class="yrs">${[5, 10, 15].map((y) => `<button type="button" data-y="${y}" class="${y === years ? "on" : ""}">${y} years</button>`).join("")}</div>
    <table class="note" style="width:100%"><tr><th></th><th>height</th><th>radius</th><th>new shade m²·h</th><th>yield</th></tr>${row(5)}${row(10)}${row(15)}</table>
    <div class="muted" style="margin-top:6px">New sidewalk shade on July 15 at ${years} yrs (m²; scoring window shaded)</div>
    ${barChart(cur.prof, times, "#e07b26", "m²", (t) => t >= "14:00" && t <= "16:00")}
    <p class="note">"New" = on sidewalk that is sunny today: not in building shadow and not under an existing tree.
    Street ${p.street_width_m ?? "–"} m wide · nearby buildings ${(p.nearby_building_heights || []).map((h) => h.toFixed(0) + " m").join(", ") || "none"}${p.overheadutilities === "Yes" ? " · overhead wires" : ""}.
    The orange shadow on the map follows the time slider.</p>`);
  $("species").onchange = (e) => { state.species = e.target.value; plantAt(site, state.plantedYear); };
  document.querySelectorAll(".yrs button").forEach((b) => (b.onclick = () => plantAt(site, +b.dataset.y)));
  render();
}

function onClick({ object, layer }) {
  if (!object || !layer) return;
  if (layer.id.startsWith("crowns")) openTree(object.tree_id);
  else if (layer.id === "sites") plantAt(object, state.plantedYear);
}

/* ---------- legend + controls ---------- */
function legend() {
  const items = state.colorMode === "source"
    ? [["LiDAR crown", COLORS.lidar], ["Allometric (from DBH)", COLORS.allometric], ["Predicted", COLORS.predicted]]
    : [["0 h", hoursColor(0)], ["6 h", hoursColor(6)], ["12 h usable shade", hoursColor(12)]];
  $("legend").innerHTML = items.map(([l, c]) => `<span><span class="sw" style="background:rgb(${c.join(",")})"></span>${l}</span>`).join("")
    + `<span><span class="sw" style="background:#24476b"></span>tree shadow</span><span><span class="sw" style="background:#e07b26"></span>top pits</span>`;
}
$("day").onchange = (e) => setDay(e.target.value);
$("hour").oninput = (e) => setHour(+e.target.value);
$("color-mode").onchange = (e) => { state.colorMode = e.target.value; legend(); render(); };
$("topn").oninput = (e) => { state.topN = +e.target.value; queueStats(); };
$("aoi").onchange = (e) => { const u = new URL(location); u.searchParams.set("aoi", e.target.value); location.href = u; };
for (const k of ["bshadow", "tshadow", "sites", "hvi"]) $("t-" + k).onchange = (e) => { state.show[k] = e.target.checked; render(); };
$("play").onclick = () => {
  if (state.playing) { clearInterval(state.playing); state.playing = null; $("play").textContent = "▶ Play"; return; }
  $("play").textContent = "❚❚ Pause";
  state.playing = setInterval(() => { const s = $("hour"); s.value = (+s.value + 1) % (+s.max + 1); setHour(+s.value); }, 900);
};

/* ---------- boot ---------- */
(async function boot() {
  legend();
  const aois = await getJSON("data/aois.json");
  const want = new URL(location).searchParams.get("aoi");
  state.aoi = aois.some((a) => a.name === want) ? want : aois[0].name;
  $("aoi").innerHTML = aois.map((a) => `<option value="${a.name}" ${a.name === state.aoi ? "selected" : ""}>${a.label}</option>`).join("");
  const [meta, trees, buildings, sites, hvi, scen] = await Promise.all(
    ["meta.json", "trees.json", "buildings.json", "sites.json", "hvi.json", "scenarios.json"].map((f) => getJSON(dataUrl(f))));
  Object.assign(state, { meta, trees, buildings, sites, hvi, scen });
  const c = meta.focus ? [meta.focus.lon, meta.focus.lat] : meta.center;
  map.jumpTo({ center: c });
  const n = meta.counts;
  $("subtitle").innerHTML = `${meta.focus ? `<b>Heat impact around ${meta.focus.label}.</b> ` : ""}${n.trees.toLocaleString()} street trees (${n.lidar.toLocaleString()} measured by LiDAR) and ${n.pits} empty pits, ranked by the new sidewalk shade a tree would add. Click a tree, or an orange pit to plant one.`;
  document.title = `Shade Queue · ${meta.label}`;
  queueStats();
  await setDay($("day").value);
})().catch((e) => { $("subtitle").textContent = "Failed to load data: " + e.message; console.error(e); });

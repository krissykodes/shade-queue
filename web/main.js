/* Shade Queue web map: MapLibre basemap (no token) + deck.gl layers, all data from the FastAPI. */
const API = "";  // same origin (served by api/main.py)
const COLORS = { lidar: [47, 125, 79], allometric: [138, 166, 91], predicted: [224, 123, 38] };
const state = {
  trees: null, buildings: null, sites: null, hvi: null,
  timestamps: [], dayStamps: [], idx: 0,
  tShadows: null, bShadows: null,
  colorMode: "source", show: { bshadow: true, tshadow: true, sites: true, hvi: false },
  selected: null, planted: null, plantedYear: 10, playing: null,
};
const $ = (id) => document.getElementById(id);
const fetchJSON = (u, opt) => fetch(API + u, opt).then((r) => { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); });

/* ---------- unit sphere / cone meshes (loaders.gl Mesh format, non-indexed triangles) ---------- */
function meshFrom(tris) {
  const pos = new Float32Array(tris.flatMap((t) => t.p));
  const nor = new Float32Array(tris.flatMap((t) => t.n));
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
function coneMesh(seg = 18) {  // base at z=-1, tip at z=+1, radius 1
  const tris = [];
  for (let j = 0; j < seg; j++) {
    const a0 = (j / seg) * 2 * Math.PI, a1 = ((j + 1) / seg) * 2 * Math.PI;
    const p0 = [Math.cos(a0), Math.sin(a0), -1], p1 = [Math.cos(a1), Math.sin(a1), -1], tip = [0, 0, 1];
    const n0 = [Math.cos(a0), Math.sin(a0), 0.5], n1 = [Math.cos(a1), Math.sin(a1), 0.5];
    tris.push({ p: [...p0, ...p1, ...tip], n: [...n0, ...n1, 0, 0, 1] });
    tris.push({ p: [...p1, ...p0, 0, 0, -1], n: [0, 0, -1, 0, 0, -1, 0, 0, -1] });
  }
  return meshFrom(tris);
}
const SPHERE = sphereMesh(), CONE = coneMesh();

/* ---------- map ---------- */
const map = new maplibregl.Map({
  container: "map",
  style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  center: [-73.9225, 40.8095], zoom: 16.3, pitch: 55, bearing: -28, antialias: true,
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
const overlay = new deck.MapboxOverlay({ interleaved: false, layers: [] });
map.addControl(overlay);

/* ---------- colours ---------- */
function hoursColor(h) {  // 0 → pale, 12 → deep green
  const t = Math.max(0, Math.min(1, (h || 0) / 12));
  return [Math.round(230 - 200 * t), Math.round(230 - 120 * t), Math.round(170 - 120 * t)];
}
function crownColor(p) {
  if (state.colorMode === "hours") return [...hoursColor(p.summer_shade_hours), 235];
  return [...(COLORS[p.source] || COLORS.allometric), 225];
}
const HVI_COLORS = { 1: [255, 255, 204], 2: [255, 217, 142], 3: [254, 178, 76], 4: [253, 141, 60], 5: [227, 26, 28] };

/* ---------- layers ---------- */
function crownLayer(id, feats, meshShape, extra = {}) {
  return new deck.SimpleMeshLayer({
    id, data: feats.filter((f) => (meshShape === "cone") === (f.properties.shape === "cone")),
    mesh: meshShape === "cone" ? CONE : SPHERE, sizeScale: 1, pickable: true,
    getPosition: (f) => [f.properties.lon, f.properties.lat, (f.properties.height_m + f.properties.crown_base_m) / 2],
    getScale: (f) => [f.properties.crown_radius_m, f.properties.crown_radius_m, (f.properties.height_m - f.properties.crown_base_m) / 2],
    getColor: (f) => crownColor(f.properties),
    material: { ambient: 0.45, diffuse: 0.65, shininess: 8, specularColor: [40, 40, 40] },
    updateTriggers: { getColor: [state.colorMode] },
    ...extra,
  });
}
function trunkLayer(id, feats) {
  return new deck.ColumnLayer({
    id, data: feats, diskResolution: 6, radius: 0.25, extruded: true,
    getPosition: (f) => [f.properties.lon, f.properties.lat], getElevation: (f) => f.properties.crown_base_m + 0.3,
    getFillColor: [110, 84, 60], material: false,
  });
}

function render() {
  const L = [];
  if (state.show.hvi && state.hvi) L.push(new deck.GeoJsonLayer({
    id: "hvi", data: state.hvi, stroked: true, filled: true, getFillColor: (f) => [...(HVI_COLORS[f.properties.hvi_quintile] || [200, 200, 200]), 70],
    getLineColor: [180, 30, 30, 160], lineWidthMinPixels: 1.5, pickable: true }));
  const ground = { depthTest: false };
  if (state.show.bshadow && state.bShadows) L.push(new deck.GeoJsonLayer({
    id: "bshadow", data: state.bShadows, filled: true, stroked: false, getFillColor: [40, 48, 60, 95], parameters: ground }));
  if (state.show.tshadow && state.tShadows) L.push(new deck.GeoJsonLayer({
    id: "tshadow", data: state.tShadows, filled: true, stroked: false, parameters: ground,
    getFillColor: (f) => f.properties.leaf_on ? [36, 71, 107, 120] : [120, 120, 140, 45] }));
  if (state.planted?.shadow) L.push(new deck.GeoJsonLayer({
    id: "planted-shadow", data: state.planted.shadow, filled: true, stroked: true, parameters: ground,
    getFillColor: [224, 123, 38, 110], getLineColor: [224, 123, 38, 230], lineWidthMinPixels: 1.5 }));
  if (state.buildings) L.push(new deck.GeoJsonLayer({
    id: "buildings", data: state.buildings, extruded: true, filled: true, stroked: false, wireframe: false,
    getElevation: (f) => f.properties.height_m, getFillColor: [222, 224, 230, 235],
    material: { ambient: 0.55, diffuse: 0.55, shininess: 4 } }));
  if (state.trees) {
    const feats = state.trees.features;
    L.push(trunkLayer("trunks", feats), crownLayer("crowns", feats, "sphere"), crownLayer("crowns-cone", feats, "cone"));
  }
  if (state.planted?.crown) {
    const f = [{ properties: { ...state.planted.crown, summer_shade_hours: 0 } }];
    L.push(trunkLayer("planted-trunk", f), crownLayer("planted-crown", f, f[0].properties.shape === "cone" ? "cone" : "sphere",
      { getColor: [...COLORS.predicted, 245], pickable: false }));
  }
  if (state.show.sites && state.sites) L.push(new deck.ScatterplotLayer({
    id: "sites", data: state.sites.features, pickable: true, radiusUnits: "meters", getRadius: 2.2, radiusMinPixels: 3,
    getPosition: (f) => f.geometry.coordinates, getFillColor: [224, 123, 38, 230], getLineColor: [255, 255, 255],
    stroked: true, lineWidthMinPixels: 1 }));
  if (state.selected) L.push(new deck.ScatterplotLayer({
    id: "sel", data: [state.selected], radiusUnits: "meters", getRadius: (d) => d.r, filled: false, stroked: true,
    getPosition: (d) => d.pos, getLineColor: [20, 20, 20], lineWidthMinPixels: 2, parameters: ground }));
  overlay.setProps({ layers: L, onClick, getTooltip });
}

function getTooltip({ object, layer }) {
  if (!object || !layer) return null;
  if (layer.id.startsWith("crowns")) {
    const p = object.properties;
    return { text: `${p.species_label || p.species || "Unknown"}\n${p.height_m.toFixed(1)} m tall · ${p.source}\nsummer sidewalk shade: ${p.summer_shade_hours ?? "–"} h` };
  }
  if (layer.id === "sites") return { text: `Empty pit · ${object.properties.streetname}\nclick to plant` };
  if (layer.id === "hvi") return { text: `${object.properties.ntaname}\nHVI quintile ${object.properties.hvi_quintile} of 5` };
  return null;
}

/* ---------- time ---------- */
function fmtTime(ts) { return ts.slice(11, 16); }
async function setDay(day) {
  state.dayStamps = state.timestamps.filter((t) => t.startsWith(day));
  const s = $("hour"); s.max = state.dayStamps.length - 1;
  const noon = state.dayStamps.findIndex((t) => t.slice(11, 13) === "14");
  s.value = noon >= 0 ? noon : Math.floor(state.dayStamps.length / 2);
  await setHour(+s.value);
  if (state.planted) plantAt(state.planted.site, state.plantedYear);
  if (state.selected?.treeId) openTree(state.selected.treeId);
}
const cache = new Map();
async function setHour(i) {
  state.idx = i;
  const ts = state.dayStamps[i];
  $("time-label").textContent = fmtTime(ts);
  const q = encodeURIComponent(ts);
  if (!cache.has(ts)) cache.set(ts, Promise.all([fetchJSON(`/shadows?timestamp=${q}`), fetchJSON(`/building-shadows?timestamp=${q}`)]));
  const [t, b] = await cache.get(ts);
  if (state.dayStamps[state.idx] !== ts) return;  // user moved on
  state.tShadows = t; state.bShadows = b;
  if (state.planted?.byTs) state.planted.shadow = state.planted.byTs[ts] || null;
  const shade = t.features.reduce((a, f) => a + f.properties.sidewalk_shade_m2, 0);
  $("stats").textContent = `${t.features.length} tree shadows · ${Math.round(shade).toLocaleString()} m² of sidewalk shaded by trees (net of building shade)`;
  render();
}

/* ---------- panels ---------- */
function barChart(values, labels, color, unit) {
  const w = 330, h = 120, pad = 22, n = values.length, max = Math.max(1, ...values);
  const bw = (w - pad) / n;
  const bars = values.map((v, i) => {
    const bh = (v / max) * (h - 30);
    return `<rect x="${pad + i * bw + 1}" y="${h - 16 - bh}" width="${bw - 2}" height="${bh}" rx="2" fill="${color}"><title>${labels[i]}: ${v.toFixed(1)} ${unit}</title></rect>`
      + (i % 2 === 0 ? `<text x="${pad + i * bw + bw / 2}" y="${h - 3}" text-anchor="middle">${labels[i]}</text>` : "");
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img"><text x="0" y="10">${max.toFixed(0)} ${unit}</text><line x1="${pad}" x2="${w}" y1="${h - 16}" y2="${h - 16}" stroke="#ccc"/>${bars}</svg>`;
}
function showPanel(html) { $("panel-body").innerHTML = html; $("panel").classList.remove("hidden"); }
$("close").onclick = () => { $("panel").classList.add("hidden"); state.selected = null; state.planted = null; render(); };

async function openTree(id) {
  const day = $("day").value;
  const [t, hourly] = await Promise.all([fetchJSON(`/trees/${id}`), fetchJSON(`/trees/${id}/shade?date=${day}`)]);
  const p = t.crown.properties;
  state.selected = { treeId: id, pos: [p.lon, p.lat], r: p.crown_radius_m + 0.5 };
  state.planted = null;
  const s = t.summary.find((r) => r.day === day) || {};
  const H = hourly.features.map((f) => f.properties);
  const srcColor = `rgb(${COLORS[p.source].join(",")})`;
  showPanel(`
    <h2>${p.species_label || p.species || "Unknown species"}</h2>
    <span class="badge" style="background:${srcColor}">${p.source}</span>
    <span class="muted">confidence ${(p.confidence * 100).toFixed(0)}% · crown as of ${p.as_of_year}</span>
    <dl>
      <dt>Height</dt><dd>${p.height_m.toFixed(1)} m</dd>
      <dt>Crown radius</dt><dd>${p.crown_radius_m.toFixed(1)} m (base ${p.crown_base_m.toFixed(1)} m)</dd>
      <dt>Trunk DBH</dt><dd>${p.dbh_cm ? (p.dbh_cm / 2.54).toFixed(0) + " in" : "–"}</dd>
      <dt>Condition</dt><dd>${p.tpcondition || "–"}</dd>
      <dt>Usable sidewalk shade</dt><dd><b>${s.usable_sidewalk_shade_hours ?? 0} h</b> on ${day}${s.leaf_on === false ? " (leaf-off)" : ""}</dd>
      <dt>Shadow on public ground</dt><dd>${s.public_ground_fraction != null ? Math.round(s.public_ground_fraction * 100) + "%" : "–"}</dd>
      <dt>Already in building shade</dt><dd>${s.mean_self_shaded_fraction != null ? Math.round(s.mean_self_shaded_fraction * 100) + "%" : "–"}</dd>
    </dl>
    <div class="muted">Sidewalk shade by hour (m², net of building shade)</div>
    ${barChart(H.map((h) => h.sidewalk_shade_m2), H.map((h) => fmtTime(h.timestamp)), "#24476b", "m²")}
    <p class="note">ForMS tree <code>${id.slice(0, 8)}…</code>. Crowns marked <i>allometric</i> are estimated from trunk diameter with USFS Urban Tree Database equations (Queens reference city).</p>`);
  render();
}

async function plantAt(site, years) {
  state.plantedYear = years;
  const [lon, lat] = site.geometry.coordinates;
  const species = $("species")?.value || "Platanus x acerifolia";
  state.selected = { pos: [lon, lat], r: 3 };
  const r = await fetchJSON("/simulate", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ species, lon, lat, years: [5, 10, 15], day: $("day").value }) });
  const byYear = Object.fromEntries(r.scenarios.map((s) => [s.years, s]));
  const sc = byYear[years];
  const byTs = Object.fromEntries(sc.shadows.map((s) => [s.timestamp, { type: "Feature", geometry: s.geometry, properties: {} }]));
  state.planted = { site, crown: sc.crown, byTs, shadow: byTs[state.dayStamps[state.idx]] || null };
  const p = site.properties;
  const row = (y) => `<tr><td>${y} yr</td><td>${byYear[y].crown.height_m.toFixed(1)} m</td><td>${byYear[y].crown.crown_radius_m.toFixed(1)} m</td><td><b>${byYear[y].summary.usable_sidewalk_shade_hours} h</b></td><td>${byYear[y].summary.mean_sidewalk_shade_m2.toFixed(0)} m²</td></tr>`;
  const H = sc.hourly;
  showPanel(`
    <h2>Plant here? <span class="muted">${p.streetname}</span></h2>
    <span class="badge" style="background:rgb(${COLORS.predicted.join(",")})">predicted</span>
    <span class="muted">HVI ${p.hvi_quintile ?? "–"}/5 · street ${p.street_width_m ?? "–"} m · bearing ${p.orientation_deg ?? "–"}°</span>
    <label class="muted" style="display:block;margin-top:8px">Species
      <select id="species">${SPECIES.map((s) => `<option ${s[0] === species ? "selected" : ""} value="${s[0]}">${s[1]}</option>`).join("")}</select></label>
    <div class="yrs">${[5, 10, 15].map((y) => `<button type="button" data-y="${y}" class="${y === years ? "on" : ""}">${y} years</button>`).join("")}</div>
    <table class="note" style="width:100%"><tr><th></th><th>height</th><th>radius</th><th>usable shade</th><th>mean sidewalk</th></tr>${row(5)}${row(10)}${row(15)}</table>
    <div class="muted" style="margin-top:6px">Sidewalk shade by hour at ${years} yrs (m²)</div>
    ${barChart(H.map((h) => h.sidewalk_shade_m2), H.map((h) => fmtTime(h.timestamp)), "#e07b26", "m²")}
    <p class="note">Nearby buildings: ${(p.nearby_building_heights || []).map((h) => h.toFixed(0) + " m").join(", ") || "none"}.
    Growth from a ${2.5}" caliper using UTD age→DBH→crown equations; the shadow comes from the <i>same</i> simulator as existing trees.</p>`);
  $("species").onchange = () => plantAt(site, state.plantedYear);
  document.querySelectorAll(".yrs button").forEach((b) => (b.onclick = () => plantAt(site, +b.dataset.y)));
  render();
}
const SPECIES = [
  ["Platanus x acerifolia", "London planetree"], ["Gleditsia triacanthos", "Thornless honeylocust"],
  ["Quercus palustris", "Pin oak"], ["Quercus rubra", "Northern red oak"], ["Zelkova serrata", "Japanese zelkova"],
  ["Tilia cordata", "Littleleaf linden"], ["Ginkgo biloba", "Ginkgo"], ["Ulmus americana", "American elm"],
  ["Acer rubrum", "Red maple"], ["Liquidambar styraciflua", "Sweetgum"],
];

function onClick({ object, layer }) {
  if (!object || !layer) return;
  if (layer.id.startsWith("crowns")) openTree(object.properties.tree_id);
  else if (layer.id === "sites") plantAt(object, state.plantedYear);
}

/* ---------- legend + controls ---------- */
function legend() {
  const items = state.colorMode === "source"
    ? [["LiDAR crown", COLORS.lidar], ["Allometric (from DBH)", COLORS.allometric], ["Predicted (planting)", COLORS.predicted]]
    : [["0 h", hoursColor(0)], ["6 h", hoursColor(6)], ["12 h usable shade", hoursColor(12)]];
  $("legend").innerHTML = items.map(([l, c]) => `<span><span class="sw" style="background:rgb(${c.join(",")})"></span>${l}</span>`).join("")
    + `<span><span class="sw" style="background:#24476b"></span>tree shadow</span>`;
}
$("day").onchange = (e) => setDay(e.target.value);
$("hour").oninput = (e) => setHour(+e.target.value);
$("color-mode").onchange = (e) => { state.colorMode = e.target.value; legend(); render(); };
for (const k of ["bshadow", "tshadow", "sites", "hvi"]) $("t-" + k).onchange = (e) => { state.show[k] = e.target.checked; render(); };
$("play").onclick = () => {
  if (state.playing) { clearInterval(state.playing); state.playing = null; $("play").textContent = "▶ Play"; return; }
  $("play").textContent = "❚❚ Pause";
  state.playing = setInterval(() => { const s = $("hour"); s.value = (+s.value + 1) % (+s.max + 1); setHour(+s.value); }, 900);
};

/* ---------- boot ---------- */
(async function boot() {
  legend();
  const [trees, buildings, sites, hvi, ts] = await Promise.all(
    ["/trees", "/buildings", "/sites", "/hvi", "/timestamps"].map((u) => fetchJSON(u)));
  Object.assign(state, { trees, buildings, sites, hvi, timestamps: ts });
  const n = trees.features.length, nl = trees.features.filter((f) => f.properties.source === "lidar").length;
  $("title").querySelector("p").textContent =
    `${n.toLocaleString()} street trees (${nl ? nl + " from LiDAR, " : ""}${n - nl} allometric) · ${sites.features.length} empty pits. Click a tree, or an orange pit to plant one.`;
  await setDay($("day").value);
})().catch((e) => { $("stats").textContent = "Failed to load: " + e.message + " (is the API running and the pipeline built?)"; console.error(e); });

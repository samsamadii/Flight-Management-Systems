const byId = id => document.getElementById(id);
const styles = new Set(["dark", "positron", "bright"]);
const styleURL = name => "https://tiles.openfreemap.org/styles/" + name;
const actions = [];
const shapes = new Set();
const pendingShapes = new Set();
let shapeRedraw = 0;
let snapshot = {flights: [], servers: []};
let style = "dark";
let previousFollowPosition = "";
let requestedCenter = "";
let photoPath = "";
let searchIndex = new Map();

const cameraKey = "fms.live.camera";
function lastCamera() {
  try {
    const saved = JSON.parse(localStorage.getItem(cameraKey));
    if (saved && Array.isArray(saved.center) && saved.center.length === 2 &&
        [...saved.center, saved.zoom, saved.bearing, saved.pitch].every(Number.isFinite) &&
        Math.abs(saved.center[1]) <= 90) return saved;
  } catch {}
  return {center: [10, 25], zoom: 2.6};
}

maplibregl.setRTLTextPlugin(mapRTLPluginUrl, false)
  .catch(error => console.warn("Could not load right-to-left map labels", error));
const map = new maplibregl.Map({
  container: "map", style: styleURL(style), ...lastCamera(),
  minZoom: 1.5, maxZoom: 19, pitchWithRotate: false, dragRotate: false,
  attributionControl: false,
});
map.on("move", () => {
  try {
    localStorage.setItem(cameraKey, JSON.stringify({
      center: map.getCenter().toArray(), zoom: map.getZoom(),
      bearing: map.getBearing(), pitch: map.getPitch(),
    }));
  } catch {}
});
const mapSizeObserver = new ResizeObserver(() => map.resize());
mapSizeObserver.observe(byId("map"));
map.addControl(new maplibregl.NavigationControl({showCompass: false}), "bottom-right");
map.addControl(new maplibregl.AttributionControl({compact: true}), "bottom-right");
map.on("error", event => {
  if (!map.getSource("fms-traffic") && event.error) byId("map-error").hidden = false;
});

const collection = features => ({type: "FeatureCollection", features});
const point = (position, properties) => ({type: "Feature", geometry: {type: "Point", coordinates: position}, properties});

function loadShape(id) {
  if (!/^[a-z0-9-]+$/i.test(id) || shapes.has(id) || pendingShapes.has(id)) return;
  pendingShapes.add(id);
  const image = new Image();
  image.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 64;
    const context = canvas.getContext("2d");
    const ratio = 58 / Math.max(image.naturalWidth, image.naturalHeight);
    const width = image.naturalWidth * ratio, height = image.naturalHeight * ratio;
    context.drawImage(image, (64 - width) / 2, (64 - height) / 2, width, height);
    pendingShapes.delete(id);
    if (!map.hasImage(id)) map.addImage(id, context.getImageData(0, 0, 64, 64), {pixelRatio: 2});
    shapes.add(id);
    if (!shapeRedraw) shapeRedraw = requestAnimationFrame(() => {
      shapeRedraw = 0;
      renderMap();
    });
  };
  image.onerror = () => pendingShapes.delete(id);
  image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(aircraftSVG[id]);
}

function renderMap() {
  const source = map.getSource("fms-traffic");
  if (!source) return;
  const selected = snapshot.selected;
  const traffic = snapshot.flights;
  for (const flight of traffic) loadShape(flight.shape);
  if (selected) loadShape(selected.shape + "-selected");
  const name = flight => shapes.has(flight.shape) ? flight.shape : "Unidentified";
  source.setData(collection(traffic.filter(f => f.id !== selected?.id).map(f =>
    point(f.position, {id: f.id, callsign: f.callsign || "", heading: f.heading, image: name(f)}))));
  const selectedShape = selected && selected.shape + "-selected";
  map.getSource("fms-selected").setData(collection(selected ?
    [point(selected.position, {callsign: selected.callsign || "", heading: selected.heading, image: shapes.has(selectedShape) ? selectedShape : "Unidentified-selected"})] : []));
  map.getSource("fms-atc").setData(collection((snapshot.atc || []).map(a => point(a.position, {label: a.label}))));
  const route = selected?.route ?? [];
  map.getSource("fms-route").setData(collection(route.length >= 2 ?
    [{type: "Feature", geometry: {type: "LineString", coordinates: route}, properties: {}}] : []));
  map.getSource("fms-airports").setData(collection(selected ?
    [selected.departure, selected.arrival].filter(a => a.position).map(a => point(a.position, {code: a.code})) : []));
  if (selected && (snapshot.following || requestedCenter === selected.id)) {
    const position = JSON.stringify(selected.position);
    if (position !== previousFollowPosition || requestedCenter) {
      map.easeTo({center: selected.position, zoom: requestedCenter ? Math.max(5, map.getZoom()) : map.getZoom(), duration: 280});
      previousFollowPosition = position;
    }
    requestedCenter = "";
  } else {
    previousFollowPosition = "";
  }
}

map.on("style.load", () => {
  byId("map-error").hidden = true;
  for (const name of [...shapes]) {
    if (!map.hasImage(name)) {
      shapes.delete(name);
      loadShape(name);
    }
  }
  loadShape("Unidentified");
  loadShape("Unidentified-selected");
  for (const id of ["fms-route", "fms-airports", "fms-atc", "fms-traffic", "fms-selected"]) {
    map.addSource(id, {type: "geojson", data: collection([])});
  }
  map.addLayer({id: "fms-atc", type: "circle", source: "fms-atc", paint: {
    "circle-radius": 4.5, "circle-color": "#35df8b", "circle-stroke-width": 1,
    "circle-stroke-color": "#103a2a",
  }});
  map.addLayer({id: "fms-route", type: "line", source: "fms-route", paint: {"line-color": "#36c0ff", "line-width": 2.5}});
  map.addLayer({id: "fms-airports", type: "symbol", source: "fms-airports",
    layout: {"text-field": ["get", "code"], "text-font": ["Noto Sans Bold"], "text-size": 12, "text-offset": [0, 1.6]},
    paint: {"text-color": "#fff", "text-halo-color": "#172637", "text-halo-width": 2}});
  for (const id of ["fms-traffic", "fms-selected"]) {
    map.addLayer({id, type: "symbol", source: id, layout: {
      "icon-image": ["get", "image"], "icon-rotate": ["get", "heading"], "icon-rotation-alignment": "map",
      "icon-size": id === "fms-selected" ? 1 : 0.73, "icon-allow-overlap": true, "icon-ignore-placement": true,
    }});
  }
  renderMap();
});

function send(type, value = null) {
  actions.push({type, value});
}
window.takeLiveMapActions = () => actions.splice(0);
map.on("click", event => {
  if (!map.getLayer("fms-traffic")) return;
  const feature = map.queryRenderedFeatures(event.point, {layers: ["fms-traffic"]})[0];
  if (feature) send("select", feature.properties.id);
});
map.on("movestart", event => {
  if (event.originalEvent) send("activity");
});
map.on("mousemove", event => {
  const layers = ["fms-selected", "fms-traffic", "fms-atc"].filter(id => map.getLayer(id));
  const hits = layers.length ? map.queryRenderedFeatures(event.point, {layers}) : [];
  const aircraft = hits.find(hit => hit.layer.id !== "fms-atc");
  const atc = hits.find(hit => hit.layer.id === "fms-atc");
  const label = aircraft?.properties.callsign || atc?.properties.label;
  const tooltip = byId("map-tooltip");
  tooltip.hidden = !label;
  if (label) {
    tooltip.textContent = label;
    tooltip.style.left = Math.min(event.point.x + 12, window.innerWidth - tooltip.offsetWidth - 6) + "px";
    tooltip.style.top = Math.min(event.point.y + 12, window.innerHeight - tooltip.offsetHeight - 6) + "px";
  }
  map.getCanvas().style.cursor = aircraft ? "pointer" : "";
});
map.getCanvas().addEventListener("mouseleave", () => { byId("map-tooltip").hidden = true; });
function selectStyle(value) {
  if (styles.has(value) && style !== value) {
    style = value;
    byId("map-error").hidden = true;
    map.setStyle(styleURL(style), {diff: false});
  }
}
byId("style").onchange = event => {
  selectStyle(event.target.value);
  send("style", event.target.value);
};
for (const id of ["refresh", "settings", "close", "follow"]) byId(id).onclick = () => send(id);
byId("server").onchange = event => send("server", event.target.value);

function renderSearch() {
  const term = byId("search").value.trim().toLowerCase();
  const results = byId("results");
  results.replaceChildren();
  results.hidden = !term;
  if (!term) return;
  const matches = [...searchIndex.values()].filter(f => f.name.toLowerCase().includes(term)).slice(0, 6);
  if (!matches.length) results.textContent = "No matching aircraft";
  for (const flight of matches) {
    const button = document.createElement("button");
    button.dir = "auto";
    button.textContent = flight.name;
    button.onclick = () => {
      requestedCenter = flight.id;
      byId("search").value = "";
      renderSearch();
      send("select", flight.id);
    };
    results.append(button);
  }
}
byId("search").oninput = renderSearch;
const text = (id, value) => { byId(id).textContent = value || "—"; };
const measurement = (value, unit) => value && value !== "—" ? value + " " + unit : "—";

function renderFlight(flight) {
  byId("flight").hidden = !flight;
  if (!flight) return;
  text("callsign", flight.callsign || flight.name);
  byId("subtitle").textContent = flight.pilot || "";
  for (const [prefix, airport] of [["dep", flight.departure], ["arr", flight.arrival]]) {
    text(prefix + "-code", airport.code);
    text(prefix + "-name", airport.name);
  }
  text("etd", flight.timing[0]); text("eta", flight.timing[1]); text("duration", flight.timing[2]);
  text("ete", flight.timing[3]);
  text("eta-label", flight.timing[4] ? "ETA · Estimate" : "ETA");
  text("ete-label", flight.timing[5] ? "ETE · Estimate" : "ETE");
  text("model", flight.model);
  text("altitude", measurement(flight.altitude, "ft"));
  text("speed", measurement(flight.speed, "kt"));
  text("vertical", measurement(flight.vertical, "fpm"));
  text("heading", Math.round(flight.heading) + "°");
  text("follow", snapshot.following ? "Stop following" : "Follow");
  const photo = byId("photo");
  if (photoPath !== flight.photo) {
    photoPath = flight.photo;
    photo.hidden = !photoPath;
    if (photoPath) photo.src = "../" + photoPath;
    else photo.removeAttribute("src");
  }
}
byId("photo").onerror = event => { event.target.hidden = true; };

window.updateLiveMap = value => {
  snapshot = value;
  const selectedStyle = byId("style");
  if (selectedStyle.value !== value.style) selectedStyle.value = value.style;
  selectStyle(value.style);
  const server = byId("server");
  const encoded = JSON.stringify(value.servers);
  if (server.dataset.options !== encoded) {
    server.replaceChildren(...value.servers.map(item => new Option(item.name, item.id)));
    server.dataset.options = encoded;
    server.disabled = !value.servers.length;
  }
  server.value = value.session;
  byId("settings").hidden = !value.needsKey;
  text("status", value.status);
  searchIndex = new Map(value.flights.map(f => [f.id, f]));
  if (byId("search").value) renderSearch();
  renderFlight(value.selected);
  renderMap();
};

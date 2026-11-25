"use strict";

const $ = (id) => document.getElementById(id);
const ICONS = {
  left: '<path d="m15 5-7 7 7 7"/>',
  right: '<path d="m9 5 7 7-7 7"/>',
  moon: '<path d="M20.8 14.2A9 9 0 0 1 9.9 3.1a9.1 9.1 0 1 0 10.9 11.1Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 1.5v2M12 20.5v2M1.5 12h2M20.5 12h2M4.5 4.5 6 6m12 12 1.5 1.5m0-15L18 6M6 18l-1.5 1.5"/>',
  "cloud-sun": '<path d="M8 9a4 4 0 1 1 6.6-3M9 1v1m-7 7h1m1.5-5.5.8.8M18 5l-1 1m-10 14a3.8 3.8 0 1 1 .7-7.5 5 5 0 0 1 9.4-1.4 4.5 4.5 0 1 1 .5 8.9Z"/>',
  cloud: '<path d="M6 19a4.2 4.2 0 1 1 1-8.3 5.4 5.4 0 0 1 10.1-1.4 4.9 4.9 0 1 1 .3 9.7Z"/>',
  rain: '<path d="M6 15a3.8 3.8 0 1 1 .8-7.5A5 5 0 0 1 16 6a4.5 4.5 0 1 1 .9 9M9 17l-2 4m6-4-2 4m6-4-2 4"/>',
  snow: '<path d="M6 15a3.8 3.8 0 1 1 .8-7.5A5 5 0 0 1 16 6a4.5 4.5 0 1 1 .9 9M8 19h.1m4 3h.1m4-3h.1"/>',
  fog: '<path d="M5 12a3.5 3.5 0 0 1 2-6 4.5 4.5 0 0 1 8-1 4 4 0 0 1 4 7M4 15h15M7 19h14M2 22h11"/>',
  thunder: '<path d="M6 15a3.8 3.8 0 1 1 .8-7.5A5 5 0 0 1 16 6a4.5 4.5 0 1 1 .9 9m-5-2-3 5h5l-3 5"/>',
  wind: '<path d="M2 8h12a2.5 2.5 0 1 0-2.5-2.5M2 12h17a2.5 2.5 0 1 1-2.5 2.5M5 16h5a2 2 0 1 1-2 2"/>',
  sunrise: '<path d="M2 19h20M5 22h14m-12-6a5 5 0 0 1 10 0m-5-9V3m-2 2 2-2 2 2M4 11l1 1m14 0 1-1"/>',
  drop: '<path d="M12 2.5S5.5 10 5.5 15.1a6.5 6.5 0 1 0 13 0C18.5 10 12 2.5 12 2.5Z"/><path d="M9 15a3 3 0 0 0 3 3"/>',
  thermometer: '<path d="M10 14.5V5a2 2 0 1 1 4 0v9.5a4 4 0 1 1-4 0Z"/><path d="M12 11v7m4-11h2m-2 4h2"/>',
  home: '<path d="m3 11 9-8 9 8m-3-2v11H6V9m4 11v-6h4v6"/>',
  download: '<path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4"/>',
};
const paintIcon = (el, name) => {
  el.dataset.icon = name;
  el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || ICONS.cloud) + '</svg>';
};
const numberFormats = [0, 1, 2].map(digits =>
  new Intl.NumberFormat("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
const fmt = (value, digits = 1, unit = "") => Number.isFinite(value)
  ? numberFormats[digits].format(value) + unit : "–";
const clock = (value) => new Date(value).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
const timestamp = (value) => new Date(value).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
const isToday = (value) => new Date(value).toDateString() === new Date().toDateString();
const readStored = (key) => { try { return localStorage.getItem(key); } catch { return null; } };
const writeStored = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
const state = { range: "24h", start: "", end: "", series: null, request: null };
let excluded = new Set();
try {
  const saved = JSON.parse(readStored("wetter-hidden-indoor-devices"));
  if (Array.isArray(saved)) excluded = new Set(saved);
} catch {}

async function json(path, signal) {
  const response = await fetch(path, { cache: "no-store", signal });
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
}

function periodParams() {
  const p = new URLSearchParams({ range: state.range });
  if (state.range === "custom") {
    p.set("start", state.start);
    p.set("end", state.end);
  }
  return p;
}

function setPetal(id, value, angle) {
  const path = $(id);
  if (!Number.isFinite(value)) { path.setAttribute("d", ""); return; }
  const radius = Math.max(4, Math.min(1, value / 150) * 42);
  const coord = (deg) => {
    const rad = deg * Math.PI / 180;
    return (66 + radius * Math.cos(rad)).toFixed(1) + " " + (62 + radius * Math.sin(rad)).toFixed(1);
  };
  path.setAttribute("d", "M66 62 L" + coord(angle - 25) + " A" + radius + " " + radius + " 0 0 1 " + coord(angle + 25) + " Z");
}

async function loadLatest() {
  try {
    const { latest } = await json("/api/latest");
    if (!latest) { $("measuredAt").textContent = "Noch keine Messung"; return; }
    $("temperatureNow").textContent = fmt(latest.temperature_c);
    $("windNow").textContent = fmt(latest.wind_ms, 1, " m/s");
    $("duskNow").textContent = fmt(latest.twilight_lux, 0, " lx");
    $("lightNow").textContent = fmt(latest.south_klux, 1, " kLux");
    $("measuredAt").textContent = isToday(latest.t) ? "Messung um " + clock(latest.t) : timestamp(latest.t);
    setPetal("lightSouth", latest.south_klux, -90);
    setPetal("lightWest", latest.west_klux, 180);
    setPetal("lightEast", latest.east_klux, 0);
  } catch { $("measuredAt").textContent = "Messung nicht abrufbar"; }
}
async function loadHealth() {
  const status = $("stationStatus"), label = $("stationStatusText");
  try {
    const health = await json("/api/health?details=false");
    status.dataset.status = health.status;
    label.textContent = { ok: "Station empfängt", stale: "Messung verzögert", down: "Kein aktueller Empfang" }[health.status] || "Empfang unbekannt";
    status.title = health.last_t ? "Letzte Messung " + timestamp(health.last_t) : "Keine Stationsdaten";
  } catch {
    status.dataset.status = "unknown";
    label.textContent = "Stationsstatus unbekannt";
  }
}

function duration(seconds) {
  if (!Number.isFinite(seconds)) return "–";
  if (seconds < 60) return "< 1 Min.";
  const minutes = Math.floor(seconds / 60);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor(minutes / 60) % 24;
  if (days) return days + " T." + (hours ? " " + hours + " Std." : "");
  return hours ? hours + " Std." + (minutes % 60 ? " " + minutes % 60 + " Min." : "") : minutes + " Min.";
}

async function loadRain() {
  try {
    const rain = await json("/api/rain");
    const active = rain.status === "raining";
    $("rainStatus").textContent = active ? "Es regnet laut Sensor."
      : rain.status === "dry" ? "Aktuell trocken." : "Kein aktuelles Regensignal.";
    $("rainSinceLabel").textContent = active ? "Ereignis erkannt seit" : "Letzte Regenmessung";
    const since = $("rainSince");
    since.textContent = active ? (isToday(rain.first_wet_at) ? clock(rain.first_wet_at) : timestamp(rain.first_wet_at))
      : rain.last_wet_at ? (rain.since_last_wet_seconds < 60 ? "Gerade eben" : "vor " + duration(rain.since_last_wet_seconds)) : "Noch keine";
    since.title = rain.last_wet_at ? timestamp(rain.last_wet_at) : "";
    $("rainDuration").textContent = !rain.start_bounded && rain.duration_seconds >= 60
      ? "≥ " + duration(rain.duration_seconds) : duration(rain.duration_seconds);
    $("rainDuration").title = rain.start_bounded
      ? "Zeit zwischen erster und letzter nasser Messung"
      : "Beobachtete Dauer. Der Beginn kann wegen einer Datenlücke früher liegen.";
  } catch {
    $("rainStatus").textContent = "Regenstatus derzeit nicht abrufbar.";
  }
}

function weather(code, day) {
  if (code === 0) return day === false ? ["moon", "Klar"] : ["sun", "Sonnig"];
  if (code === 1 || code === 2) return day === false ? ["cloud", "Teilweise bewölkt"] : ["cloud-sun", "Teilweise bewölkt"];
  if (code === 3) return ["cloud", "Bedeckt"];
  if ([45, 48].includes(code)) return ["fog", "Nebel"];
  if ([71, 73, 75, 77, 85, 86].includes(code)) return ["snow", "Schnee"];
  if ([95, 96, 99].includes(code)) return ["thunder", "Gewitter"];
  if ([51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82].includes(code)) return ["rain", "Regen oder Schauer"];
  return ["cloud", "Wetterzustand unbekannt"];
}

const forecastTrack = $("forecastHours");
function syncForecastButtons() {
  $("forecastBack").disabled = forecastTrack.scrollLeft <= 1;
  $("forecastNext").disabled = forecastTrack.scrollLeft + forecastTrack.clientWidth >= forecastTrack.scrollWidth - 1;
}
forecastTrack.addEventListener("scroll", syncForecastButtons, { passive: true });
new ResizeObserver(syncForecastButtons).observe(forecastTrack);
function scrollForecast(direction) {
  const behavior = matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
  forecastTrack.scrollBy({ left: direction * Math.round(forecastTrack.clientWidth * .65), behavior });
}
$("forecastBack").addEventListener("click", () => scrollForecast(-1));
$("forecastNext").addEventListener("click", () => scrollForecast(1));

let renderedForecast = "";
async function loadForecast() {
  const wrap = forecastTrack, caption = $("forecastCaption");
  try {
    const forecast = await json("/api/forecast");
    if (!forecast.hours.length) {
      caption.textContent = forecast.status === "disabled" ? "In der Konfiguration deaktiviert." : "Derzeit keine Prognose verfügbar.";
      wrap.replaceChildren();
      renderedForecast = "";
      syncForecastButtons();
      return;
    }
    const hours = forecast.hours;
    caption.textContent = (forecast.status === "stale" ? "Letzter verfügbarer Abruf " : "Stand ")
      + (isToday(forecast.updated_at) ? clock(forecast.updated_at) : timestamp(forecast.updated_at))
      + " · bis " + (isToday(hours.at(-1).t) ? clock(hours.at(-1).t) : timestamp(hours.at(-1).t));
    const revision = [forecast.updated_at, hours[0].t, hours.at(-1).t].join("/");
    if (revision === renderedForecast) return;
    const left = wrap.scrollLeft;
    const fragment = document.createDocumentFragment();
    for (const hour of hours) {
      const [icon, condition] = weather(hour.weather_code, hour.is_day);
      const card = document.createElement("div");
      const title = (isToday(hour.t) ? "Heute, " + clock(hour.t) : timestamp(hour.t)) + " · " + condition;
      const amount = fmt(hour.precipitation_mm, 1, " mm");
      card.className = "forecast-hour";
      card.dataset.weather = icon;
      card.title = title + " · Niederschlagsmenge " + amount;
      const time = document.createElement("time");
      time.dateTime = new Date(hour.t).toISOString();
      time.textContent = clock(hour.t);
      time.setAttribute("aria-label", title);
      const symbol = document.createElement("span");
      symbol.setAttribute("aria-hidden", "true");
      paintIcon(symbol, icon);
      const temp = document.createElement("strong");
      temp.textContent = fmt(hour.temperature_c, 0, "°");
      temp.setAttribute("aria-label", fmt(hour.temperature_c, 0, " Grad Celsius"));
      const probability = document.createElement("span");
      probability.className = "hour-probability";
      probability.textContent = fmt(hour.precipitation_probability_pct, 0, " %");
      probability.setAttribute("aria-label", "Niederschlagschance " + probability.textContent);
      const track = document.createElement("span");
      track.className = "probability-track";
      track.setAttribute("aria-hidden", "true");
      const bar = document.createElement("i");
      bar.style.width = Math.min(100, Math.max(0, hour.precipitation_probability_pct ?? 0)) + "%";
      track.append(bar);
      card.append(time, symbol, temp, probability, track);
      fragment.append(card);
    }
    wrap.replaceChildren(fragment);
    renderedForecast = revision;
    wrap.scrollLeft = left;
    syncForecastButtons();
  } catch {
    caption.textContent = "Prognose derzeit nicht abrufbar.";
  }
}

async function loadComfort() {
  try {
    const data = await json("/api/analysis/comfort");
    $("comfortStrip").hidden = !data.ok || data.age_seconds > 1800;
    if ($("comfortStrip").hidden) return;
    $("comfortDevice").textContent = (data.device || "Innen") + " · " + fmt(data.temperature_c, 1, " °C");
    $("comfortHint").textContent = data.hint || "";
    $("comfortHum").textContent = fmt(data.humidity_pct, 0, " %");
    $("comfortDew").textContent = fmt(data.dew_point_c, 1, " °C");
    $("comfortFeelsWrap").hidden = Math.abs(data.feels_like_c - data.temperature_c) < 0.5;
    $("comfortFeels").textContent = fmt(data.feels_like_c, 1, " °C");
  } catch { $("comfortStrip").hidden = true; }
}

async function loadTrends() {
  state.request?.abort();
  const controller = new AbortController();
  state.request = controller;
  const params = periodParams();
  const settled = await Promise.allSettled(["series", "sun", "dwd", "indoor"].map(path => json("/api/" + path + "?" + params, controller.signal)));
  if (controller.signal.aborted) return;
  const [out, sun, dwd, inside] = settled.map(r => r.status === "fulfilled" ? r.value : null);
  const warnings = [];
  if (!out) warnings.push("Außenmessungen");
  if (!dwd) warnings.push("DWD-Vergleich");
  if (!inside) warnings.push("Innenmessungen");
  const status = $("trendStatus");
  status.hidden = !warnings.length && !!window.echarts;
  status.textContent = window.echarts ? "Derzeit nicht abrufbar: " + warnings.join(", ") + "." : "Diagramme konnten nicht geladen werden.";
  state.series = { out, sun, dwd, inside };
  drawTrends(state.series);
}

const buttons = [...$("rangePicker").querySelectorAll("button")];
function selectRange(range) {
  for (const button of buttons) button.setAttribute("aria-pressed", button.dataset.range === range);
  $("customRange").hidden = range !== "custom";
}
for (const button of buttons) button.addEventListener("click", () => {
  const range = button.dataset.range;
  selectRange(range);
  if (range === "custom") return;
  Object.assign(state, { range, start: "", end: "" });
  $("rangeError").textContent = "";
  loadTrends();
});
$("customRange").addEventListener("submit", (event) => {
  event.preventDefault();
  const start = event.currentTarget.elements.start.value, end = event.currentTarget.elements.end.value;
  if (end < start) { $("rangeError").textContent = "Das Enddatum muss ab dem Startdatum liegen."; return; }
  $("rangeError").textContent = "";
  Object.assign(state, { range: "custom", start, end });
  loadTrends();
});
$("csvBtn").addEventListener("click", () => { location.href = "/api/export.csv?" + periodParams(); });
document.querySelectorAll("[data-icon]").forEach(el => paintIcon(el, el.dataset.icon));
document.addEventListener("theme-changed", () => { if (state.series) drawTrends(state.series); });

function loadLive() {
  $("todayLabel").textContent = new Date().toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  loadLatest();
  loadRain();
  loadComfort();
}
loadLive();
loadHealth();
loadForecast();
loadTrends();
setInterval(() => { loadLive(); if (state.range === "24h") loadTrends(); }, 60000);
setInterval(loadHealth, 30000);
setInterval(loadForecast, 120000);

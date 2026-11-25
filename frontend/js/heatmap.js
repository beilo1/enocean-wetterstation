"use strict";

const byId = (id) => document.getElementById(id);
const calendarMetrics = {
  temp_max: ["Höchsttemperatur", "°C", 1, "temperature"],
  temp_min: ["Tiefsttemperatur", "°C", 1, "temperature"],
  temp_avg: ["Mittlere Temperatur", "°C", 1, "temperature"],
  wind_max: ["Maximale Windgeschwindigkeit", "m/s", 1, "wind"],
  south_max: ["Maximale Helligkeit Süd", "kLux", 0, "light"],
  rain_any: ["Regentage", "", 0, "rain"],
};
const palette = {
  temperature: ["#6eabd8", "#e9d8a9", "#c75637"],
  wind: ["#d8eae1", "#78ac9f", "#2c695f"],
  light: ["#f2e9ce", "#e9b85e", "#ad641e"],
  rain: ["#dce8db", "#4b85b1"],
};
const dayMs = 86400000;
const now = new Date();
const currentYear = now.getFullYear();
const calendar = { year: currentYear, metric: "temp_max", request: null };
const yearInput = byId("calendarYear");
const shortDate = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "short", timeZone: "UTC" });

function todayUTC() {
  const day = new Date();
  return Date.UTC(day.getFullYear(), day.getMonth(), day.getDate());
}

function number(value, digits, unit) {
  return Number.isFinite(value)
    ? value.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits }) + (unit ? " " + unit : "")
    : "–";
}

function formatValue(value, meta) {
  if (!Number.isFinite(value)) return "kein Messwert";
  if (meta[3] === "rain") return value ? "Regen" : "Trocken";
  return number(value, meta[2], meta[1]);
}

function heatColor(value, min, max, scale) {
  if (value == null) return "var(--panel-2)";
  const [low, middle, high] = palette[scale];
  if (scale === "rain") return value ? middle : low;
  const ratio = max > min ? (value - min) / (max - min) : .5;
  const [from, to] = ratio < .5 ? [low, middle] : [middle, high];
  const percent = Math.round((ratio < .5 ? ratio : ratio - .5) * 200);
  return "color-mix(in srgb," + to + " " + percent + "%," + from + ")";
}

function renderCalendar(payload, year, metric) {
  const meta = calendarMetrics[metric];
  const values = payload.values || {};
  const valid = Object.values(values).filter(Number.isFinite);
  const min = valid.length ? Math.min(...valid) : 0, max = valid.length ? Math.max(...valid) : 1;
  const start = Date.UTC(year, 0, 1), end = Date.UTC(year + 1, 0, 1);
  const today = todayUTC();
  const firstRow = (new Date(start).getUTCDay() + 6) % 7;
  const col = (t) => Math.floor(((t - start) / dayMs + firstRow) / 7);
  const step = 19, size = 15, left = 26, top = 22;
  const width = left + (col(end - dayMs) + 1) * step + 2;
  const height = top + 7 * step;

  let svg = '<svg viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="Jahresübersicht ' + year + '">';
  ["Mo", "", "Mi", "", "Fr", "", "So"].forEach((label, row) => {
    if (label) svg += '<text x="0" y="' + (top + row * step + 12) + '">' + label + "</text>";
  });
  ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"].forEach((label, month) => {
    svg += '<text x="' + (left + col(Date.UTC(year, month, 1)) * step) + '" y="13">' + label + "</text>";
  });
  for (let t = start; t < end; t += dayMs) {
    const day = new Date(t), key = day.toISOString().slice(0, 10);
    const value = values[key];
    const y = top + ((day.getUTCDay() + 6) % 7) * step;
    const x = left + col(t) * step;
    const future = t > today;
    const description = shortDate.format(day) + " · " + (future ? "zukünftiger Tag" : formatValue(value, meta));
    svg += '<rect x="' + x + '" y="' + y + '" width="' + size + '" height="' + size
      + '" rx="3" data-day="' + key + '" class="' + (future ? "future-day" : "calendar-day")
      + '" fill="' + heatColor(value, min, max, meta[3]) + '"><title>' + description + '</title></rect>';
  }
  byId("heatmap").innerHTML = svg + "</svg>";
  byId("metricLabel").textContent = meta[0];
  byId("calendarDetail").textContent = "Wähle einen Tag für Details.";
  const legend = byId("legend");
  legend.replaceChildren();
  const labels = meta[3] === "rain" ? [[0, "Trocken"], [1, "Regen"]] : [
    [min, number(min, meta[2], meta[1])], [(min + max) / 2, ""], [max, number(max, meta[2], meta[1])],
  ];
  for (const [value, label] of [...(valid.length ? labels : []), [null, "Ohne Messwert"]]) {
    const entry = document.createElement("span");
    const color = document.createElement("i");
    color.style.background = heatColor(value, min, max, meta[3]);
    entry.append(color, document.createTextNode(label));
    legend.append(entry);
  }
  const reached = Math.max(0, (Math.min(end - dayMs, today) - start) / dayMs + 1);
  byId("hmDays").textContent = valid.length;
  byId("hmGaps").textContent = Math.max(0, reached - valid.length);
  byId("calendarValueLabel").textContent = meta[3] === "rain" ? "Tage mit Regen" : "Durchschnitt";
  byId("calendarValue").textContent = meta[3] === "rain" ? valid.filter(v => v === 1).length :
    number(valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null, meta[2], meta[1]);
  byId("calendarMin").hidden = byId("calendarMax").hidden = meta[3] === "rain";
  byId("calendarMinValue").textContent = number(valid.length ? min : null, meta[2], meta[1]);
  byId("calendarMaxValue").textContent = number(valid.length ? max : null, meta[2], meta[1]);
  byId("calendarSummary").hidden = false;
  byId("calendarStatus").textContent = valid.length ? "" : "Für diese Messgröße sind keine Tageswerte vorhanden.";
}

function renderYearStats(data) {
  const panel = byId("yearStatsPanel");
  panel.hidden = !data?.ok;
  if (panel.hidden) return;
  byId("calendarStatsSubtitle").textContent = data.year + " · " + data.days_with_data + " Tage mit Stationsdaten";
  const counts = [
    ["Sommertage", "sommertage"], ["Hitzetage", "hitzetage"], ["Frosttage", "frosttage"],
    ["Eistage", "eistage"], ["Tropennächte", "tropennaechte"], ["Regentage", "regentage"],
  ];
  const fill = (el, entries) => {
    el.replaceChildren();
    for (const [label, value] of entries) {
      const box = document.createElement("div"), title = document.createElement("dt"), detail = document.createElement("dd");
      title.textContent = label;
      detail.textContent = value;
      box.append(title, detail);
      el.append(box);
    }
  };
  fill(byId("ysCounts"), counts.map(([label, key]) => [label, data.counts[key] ?? "–"]));
  const extremes = [["Wärmster Tag", "waermster_tag", "°C"], ["Kältester Tag", "kaeltester_tag", "°C"], ["Windigster Tag", "windigster_tag", "m/s"]];
  const highlights = extremes.flatMap(([label, key, unit]) => {
    const reading = data.extremes[key];
    return reading?.datum ? [[label, shortDate.format(new Date(reading.datum)) + " · " + number(reading.wert, 1, unit)]] : [];
  });
  for (const [label, key] of [["Erster Sommertag", "erster_sommertag"], ["Erster Hitzetag", "erster_hitzetag"], ["Letzter Frosttag", "letzter_frosttag"]]) {
    if (data.first?.[key]) highlights.push([label, shortDate.format(new Date(data.first[key]))]);
  }
  fill(byId("ysHighlights"), highlights);
}

async function calendarJSON(path, signal) {
  const response = await fetch(path, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

async function loadCalendar() {
  calendar.request?.abort();
  const controller = new AbortController();
  calendar.request = controller;
  const { year, metric } = calendar;
  const yearChanged = calendar.lastStatsYear !== year;
  byId("calendarStatus").textContent = "Tageswerte werden geladen …";
  const [data, stats] = await Promise.allSettled([
    calendarJSON("/api/calendar?" + new URLSearchParams({year, metric}), controller.signal),
    yearChanged ? calendarJSON("/api/analysis/calendar-stats?year=" + year, controller.signal) : Promise.resolve(null),
  ]);
  if (controller.signal.aborted) return;
  if (data.status === "fulfilled") renderCalendar(data.value, year, metric);
  else {
    byId("heatmap").replaceChildren();
    byId("legend").replaceChildren();
    byId("calendarSummary").hidden = true;
    byId("calendarStatus").textContent = "Die Tageswerte konnten nicht geladen werden.";
  }
  if (yearChanged) {
    renderYearStats(stats.status === "fulfilled" ? stats.value : null);
    calendar.lastStatsYear = stats.status === "fulfilled" ? year : null;
  }
}

byId("heatmap").addEventListener("click", (event) => {
  const entry = event.target.closest("[data-day]");
  if (!entry) return;
  byId("heatmap").querySelector(".chosen-day")?.classList.remove("chosen-day");
  entry.classList.add("chosen-day");
  byId("calendarDetail").textContent = entry.querySelector("title").textContent;
});
for (const btn of byId("calendarMetrics").querySelectorAll("button")) {
  btn.addEventListener("click", () => {
    calendar.metric = btn.dataset.metric;
    for (const control of byId("calendarMetrics").querySelectorAll("button")) control.setAttribute("aria-pressed", control === btn);
    loadCalendar();
  });
}
yearInput.addEventListener("change", () => {
  calendar.year = Number(yearInput.value);
  loadCalendar();
});

(async () => {
  let years = [];
  try { years = (await calendarJSON("/api/calendar/years")).years; } catch {}
  const options = [...new Set([currentYear, ...years])].filter(year => Number.isInteger(year) && year >= 1900 && year <= 9998)
    .sort((a, b) => b - a);
  calendar.year = years.includes(currentYear) || !years.length ? currentYear : options.find(y => y !== currentYear) || currentYear;
  for (const year of options) yearInput.append(new Option(String(year), String(year), false, year === calendar.year));
  loadCalendar();
})();

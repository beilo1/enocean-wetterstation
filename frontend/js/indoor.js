"use strict";

const roomMetrics = [
  { field: "temperature_c", label: "Temperatur", color: "--temp", unit: "°C" },
  { field: "humidity_pct", label: "Relative Luftfeuchte", color: "--wind", unit: "%" },
  { field: "dew_point_c", label: "Taupunkt", color: "--dusk", unit: "°C", dashed: true },
];
const indoorColors = ["--dusk", "--wind", "--temp", "--dwd", "--sun", "#9b477a", "#687c2c", "#ad6449"];
const numberLabel = new Intl.NumberFormat("de-DE");
const initialPeriod = { range: "24h", start: "", end: "" };
const indoor = {
  period: initialPeriod, displayedPeriod: initialPeriod, request: null, comfortRequest: null,
  series: null, catalog: null, selected: null, devices: [],
};

const hiddenKey = "wetter-hidden-indoor-devices";
const hiddenDevices = new Set();
try {
  const saved = JSON.parse(localStorage.getItem(hiddenKey));
  if (Array.isArray(saved)) saved.forEach(id => hiddenDevices.add(id));
} catch {}

function indoorChartOptions() {
  const period = indoor.displayedPeriod;
  const withZero = $("indoorScale").value === "zero";
  return {
    timeFormat: period.range === "24h" ? clock : periodDays(period) <= 2 ? timestamp : undefined,
    yAxis: { scale: !withZero },
  };
}

function deviceButton(device, label) {
  const button = document.createElement("button");
  button.className = "device-button";
  button.type = "button";
  button.dataset.device = device.device_id;
  button.setAttribute("aria-pressed", "false");
  button.textContent = label;
  return button;
}

function renderHouse() {
  const devices = indoor.devices.filter(device => device.in_house && device.temperatureCount);
  const container = $("houseDevices");
  const revision = JSON.stringify(devices.map(d => [d.device_id, d.name, d.temperatureCount]));
  if (container.dataset.revision !== revision) {
    const focused = container.contains(document.activeElement) ? document.activeElement.dataset.device : null;
    container.replaceChildren(...devices.map(device => {
      const button = deviceButton(device, device.name);
      const dot = document.createElement("i");
      dot.className = "device-key";
      dot.setAttribute("aria-hidden", "true");
      const count = document.createElement("small");
      count.textContent = numberLabel.format(device.temperatureCount);
      count.setAttribute("aria-label", pointCountText(device.temperatureCount));
      button.prepend(dot);
      button.append(count);
      return button;
    }));
    if (focused) {
      [...container.children].find(button => button.dataset.device === focused)?.focus({ preventScroll: true });
    }
    container.dataset.revision = revision;
  }
  let total = 0;
  const step = indoor.series?.bucket_seconds;
  const lines = [];
  devices.forEach((device, index) => {
    const tint = color(indoorColors[index % indoorColors.length]);
    const visible = !hiddenDevices.has(device.device_id);
    const button = container.children[index];
    button.setAttribute("aria-pressed", visible);
    button.firstElementChild.style.background = tint;
    if (!visible) return;
    total += device.temperatureCount;
    lines.push(line(device.name, visibleSamples(pairs(device.t, device.temperature_c, step * 1000)), tint, {
      id: device.device_id, showSymbol: true, symbol: "none",
    }));
  });
  showPointCount("chartIndoor", indoor.series && devices.length ? pointCountText(total, step) : "");
  drawChart("chartIndoor", "°C", lines, {
    ...indoorChartOptions(),
    empty: devices.length ? "Wähle eine Temperaturkurve." : "Keine Hausmessungen in diesem Zeitraum.",
  });
}

function renderRoom() {
  const selected = indoor.devices.find(device => device.device_id === indoor.selected);
  const container = $("roomDevices");
  const revision = JSON.stringify(indoor.devices.map(d => [d.device_id, d.name]));
  if (container.dataset.revision !== revision) {
    const focused = container.contains(document.activeElement) ? document.activeElement.dataset.device : null;
    container.replaceChildren(...indoor.devices.map(device => deviceButton(device, device.name)));
    if (focused) {
      [...container.children].find(button => button.dataset.device === focused)?.focus({ preventScroll: true });
    }
    container.dataset.revision = revision;
  }
  for (const button of container.children) button.setAttribute("aria-pressed", button.dataset.device === indoor.selected);
  $("roomCaption").textContent = selected?.name || "Keine Govee-Sensoren verfügbar.";
  const step = indoor.series?.bucket_seconds;
  const lines = selected?.t ? roomMetrics.flatMap(({ field, label, color: tint, unit, dashed }) => {
    if (!numericCount(selected[field])) return [];
    const data = visibleSamples(pairs(selected.t, selected[field], step * 1000));
    return [line(label, data, css(tint), {
      yAxisIndex: unit === "%" ? 1 : 0, showSymbol: true, symbol: "none",
      lineStyle: { width: 2.1, type: dashed ? "dashed" : "solid" },
      tooltip: { valueFormatter: value => fmt(value, 1, " " + unit) },
    })];
  }) : [];
  showPointCount("chartRoom", selected?.t && lines.length ? pointCountText(selected.t.length, step) : "");
  const options = indoorChartOptions();
  const hasCelsius = lines.some(series => !series.yAxisIndex);
  const hasHumidity = lines.some(series => series.yAxisIndex === 1);
  drawChart("chartRoom", "°C", lines, {
    ...options,
    yAxis: { ...options.yAxis, show: hasCelsius },
    rightAxis: hasHumidity ? (options.yAxis.scale ? {} : { min: 0, max: 100 }) : null,
    empty: "Keine Messwerte in diesem Zeitraum.",
  });
}

async function loadComfort(device) {
  indoor.comfortRequest?.abort();
  $("comfortStrip").hidden = true;
  if (!device) return;
  const controller = new AbortController();
  indoor.comfortRequest = controller;
  try {
    const data = await json("/api/analysis/comfort?" + new URLSearchParams({ device }), controller.signal);
    if (controller.signal.aborted || !data.ok || data.age_seconds > 1800) return;
    $("comfortDevice").textContent = "Aktuell · " + fmt(data.temperature_c, 1, " °C");
    $("comfortHint").textContent = data.hint || "";
    $("comfortHum").textContent = fmt(data.humidity_pct, 0, " %");
    $("comfortDew").textContent = fmt(data.dew_point_c, 1, " °C");
    $("comfortFeelsWrap").hidden = Math.abs(data.feels_like_c - data.temperature_c) < 0.5;
    $("comfortFeels").textContent = fmt(data.feels_like_c, 1, " °C");
    $("comfortStrip").hidden = false;
  } catch {}
}

async function loadIndoor() {
  indoor.request?.abort();
  const controller = new AbortController();
  indoor.request = controller;
  const period = indoor.period;
  const params = periodParams(period);
  params.set("resolution", $("indoorResolution").value);
  const [series, catalog] = await Promise.allSettled([
    json("/api/indoor?" + params, controller.signal),
    indoor.catalog || json("/api/indoor/devices", controller.signal),
  ]);
  if (controller.signal.aborted) return;
  indoor.request = null;
  indoor.series = series.status === "fulfilled" ? series.value : null;
  if (catalog.status === "fulfilled") indoor.catalog = catalog.value;
  const seriesById = new Map(indoor.series?.devices.map(device => [device.device_id, device]));
  for (const device of indoor.catalog?.devices || []) {
    const current = seriesById.get(device.device_id);
    seriesById.set(device.device_id, { ...current, ...device, name: device.name || current?.name || device.device_id });
  }
  indoor.devices = [...seriesById.values()].map(device => ({
    ...device, temperatureCount: numericCount(device.temperature_c),
  })).sort((a, b) => a.name.localeCompare(b.name, "de") || a.device_id.localeCompare(b.device_id));
  const active = indoor.devices.find(device => device.device_id === indoor.selected)
    || indoor.devices.find(device => device.in_house && device.t?.length)
    || indoor.devices.find(device => device.t?.length)
    || indoor.devices[0];
  if (active?.device_id !== indoor.selected) loadComfort(active?.device_id);
  indoor.selected = active?.device_id ?? null;
  indoor.displayedPeriod = period;

  const status = $("trendStatus");
  status.textContent = !window.echarts ? "Die Diagrammbibliothek konnte nicht geladen werden."
    : !indoor.series ? "Govee-Messungen derzeit nicht abrufbar."
    : !indoor.devices.length ? "Es sind noch keine Govee-Messungen gespeichert." : "";
  status.hidden = !status.textContent;
  renderHouse();
  renderRoom();
}

$("houseDevices").addEventListener("click", event => {
  const button = event.target.closest("button[data-device]");
  if (!button) return;
  const device = button.dataset.device;
  if (hiddenDevices.has(device)) hiddenDevices.delete(device);
  else hiddenDevices.add(device);
  try { localStorage.setItem(hiddenKey, JSON.stringify([...hiddenDevices])); } catch {}
  renderHouse();
});
$("roomDevices").addEventListener("click", event => {
  const button = event.target.closest("button[data-device]");
  if (!button || button.dataset.device === indoor.selected) return;
  indoor.selected = button.dataset.device;
  renderRoom();
  loadComfort(indoor.selected);
});

const resolution = $("indoorResolution");
bindPeriodControls(period => {
  indoor.period = period;
  for (const [value, maxDays] of [["5m", 7], ["1h", 45]]) {
    const option = resolution.querySelector('option[value="' + value + '"]');
    option.disabled = periodDays(period) > maxDays;
    if (option.disabled && resolution.value === value) resolution.value = "auto";
  }
  loadIndoor();
});
resolution.addEventListener("change", loadIndoor);
$("indoorScale").addEventListener("change", () => { renderHouse(); renderRoom(); });
document.addEventListener("theme-changed", () => { renderHouse(); renderRoom(); });
loadIndoor();
setInterval(() => {
  if (indoor.period.range === "24h" && !indoor.request) loadIndoor();
  if (indoor.selected) loadComfort(indoor.selected);
}, 60000);

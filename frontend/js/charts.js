"use strict";

const chartInstances = new Map();
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const color = (name) => name.startsWith("--") ? css(name) : name;

function pairs(times, values, step = 0) {
  const result = [];
  for (let i = 0; i < times.length; i++) {
    if (i && step && times[i] - times[i - 1] > step * 1.5) result.push([times[i - 1] + step, null]);
    result.push([times[i], values[i] ?? null]);
  }
  return result;
}

function line(name, data, tint, options = {}) {
  return {
    name, type: "line", data, color: tint, showSymbol: false, connectNulls: false,
    lineStyle: { width: 2.1 }, emphasis: { focus: "series" }, ...options,
  };
}

function chart(id) {
  if (!chartInstances.has(id)) {
    const element = $(id);
    const instance = echarts.init(element, null, { renderer: "canvas" });
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(element);
    chartInstances.set(id, { instance, observer });
  }
  return chartInstances.get(id).instance;
}

function drawChart(id, unit, lines, options = {}) {
  if (!window.echarts) return;
  const instance = chart(id);
  const narrow = $(id).clientWidth < 470;
  const labels = { color: css("--muted"), fontSize: narrow ? 11 : 13, hideOverlap: true };
  const family = "Plus Jakarta Sans, system-ui, sans-serif";
  const axis = (axisUnit, overrides) => ({
    type: "value", scale: true, minInterval: axisUnit === "°C" ? 0.1 : 0.01, splitNumber: 5, ...overrides,
    axisLabel: { ...labels, formatter: value => fmt(value, Number.isInteger(value) ? 0 : 1, " " + axisUnit) },
    splitLine: { lineStyle: { color: css("--grid"), type: "dashed" } },
  });
  const yAxis = axis(unit, options.yAxis);
  const rightAxis = options.rightAxis
    ? { ...axis("%", options.rightAxis), splitLine: { show: false }, position: "right" }
    : null;
  const visible = lines.some(series => !series.silent && series.data.some(point => Number.isFinite((point.value || point)[1])));
  if (!visible) {
    instance.setOption({
      graphic: [{ type: "text", left: "center", top: "middle", style: {
        text: options.empty || "Keine Messungen in diesem Zeitraum", fill: css("--muted"), fontFamily: family, fontSize: narrow ? 12 : 15,
      }}],
    }, true);
    return;
  }
  instance.setOption({
    animation: false,
    textStyle: { fontFamily: family },
    grid: { left: 5, right: narrow ? 14 : 24, top: options.legend ? 43 : 19, bottom: 15, containLabel: true },
    xAxis: {
      type: "time",
      splitNumber: narrow ? 3 : 8,
      axisLabel: { ...labels, formatter: options.timeFormat || (value =>
        new Date(value).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })) },
      axisLine: { lineStyle: { color: css("--line-2") } },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    yAxis: rightAxis ? [yAxis, rightAxis] : yAxis,
    tooltip: {
      trigger: "axis", confine: true, renderMode: "richText",
      backgroundColor: css("--panel"), borderColor: css("--line-2"),
      textStyle: { color: css("--text"), fontFamily: family, fontSize: 13 },
      valueFormatter: value => fmt(value, 1, " " + unit),
    },
    legend: options.legend ? { data: options.legend, right: 8, top: 5, textStyle: { color: css("--muted"), fontSize: 13, fontFamily: family } } : undefined,
    series: lines,
  }, true);
}

function nightArea(sun) {
  if (!sun?.nights?.length || sun.nights.length > 7) return undefined;
  return { silent: true, itemStyle: { color: css("--dwd"), opacity: 0.065 },
    data: sun.nights.map(([start, end]) => [{ xAxis: start }, { xAxis: end }]) };
}

function outdoorChart(out, sun, dwd, timeFormat) {
  const lines = [];
  const n = nightArea(sun);
  if (out?.t?.length) {
    const temp = out.temperature_c, times = out.t, step = out.bucket_seconds * 1000;
    const span = temp.min.map((v, i) => v == null || temp.max[i] == null ? null : temp.max[i] - v);
    const band = {
      stack: "measured-range", stackStrategy: "all", silent: true, symbol: "none",
      lineStyle: { opacity: 0 }, tooltip: { show: false },
    };
    lines.push(line("Minimum", pairs(times, temp.min, step), css("--temp"), { ...band, areaStyle: { opacity: 0 } }));
    lines.push(line("Messspanne", pairs(times, span, step), css("--temp"), { ...band, areaStyle: { opacity: 0.13 } }));
    lines.push(line("Dachstation", pairs(times, temp.avg, step), css("--temp"), { markArea: n, lineStyle: { width: 2.6 } }));
  }
  const dwdPresent = dwd?.temperature_c?.some(Number.isFinite);
  if (dwdPresent) lines.push(line("DWD", pairs(dwd.t, dwd.temperature_c), css("--dwd"), { lineStyle: { width: 2, type: "dashed" } }));
  $("dwdLegend").hidden = !dwdPresent;
  $("dwdName").textContent = dwd?.station ? "DWD · " + dwd.station : "DWD";
  const stats = out?.stats?.temperature_c;
  $("tempStats").textContent = stats?.min != null && stats?.max != null
    ? "Dachstation: " + fmt(stats.min, 1, " °C") + " bis " + fmt(stats.max, 1, " °C") : "";
  const counts = [];
  if (out) counts.push("Dachstation: " + pointCountText(numericCount(out.temperature_c?.avg), out.bucket_seconds));
  if (dwdPresent) counts.push("DWD: " + pointCountText(numericCount(dwd.temperature_c), dwd.bucket_seconds));
  showPointCount("chartTemp", counts.join(" / "));
  drawChart("chartTemp", "°C", lines, { timeFormat, empty: out ? undefined : "Außenmessungen derzeit nicht abrufbar" });
}

function pointCountText(count, seconds) {
  const points = new Intl.NumberFormat("de-DE").format(count) + (count === 1 ? " Messpunkt" : " Messpunkte");
  if (!seconds) return points;
  const interval = seconds >= 86400 ? "1 Tag" : seconds >= 3600 ? "1 Std." : Math.round(seconds / 60) + " Min.";
  return points + " · " + interval;
}

function showPointCount(id, text) {
  const label = $(id + "Count");
  label.textContent = text;
  label.hidden = !text;
}

function numericCount(values) {
  return (values || []).filter(Number.isFinite).length;
}

function visibleSamples(data) {
  return data.map((point, index) => {
    if (!Number.isFinite(point[1])) return point;
    const before = data[index - 1], after = data[index + 1];
    return !Number.isFinite(before?.[1]) && !Number.isFinite(after?.[1])
      ? { value: point, symbol: "circle", symbolSize: 8 } : point;
  });
}

function remainingCharts(out, sun, timeFormat) {
  const times = out?.t || [];
  const p = values => pairs(times, values || [], out?.bucket_seconds * 1000);
  const shade = nightArea(sun);
  const lightCount = times.reduce((count, _, i) => count + Number(
    [out.west_klux?.avg[i], out.south_klux?.avg[i], out.east_klux?.avg[i]].some(Number.isFinite)
  ), 0);
  showPointCount("chartWind", out ? pointCountText(numericCount(out.wind_ms?.avg), out.bucket_seconds) : "");
  showPointCount("chartLight", out ? pointCountText(lightCount, out.bucket_seconds) : "");
  showPointCount("chartDusk", out ? pointCountText(numericCount(out.twilight_lux?.avg), out.bucket_seconds) : "");
  drawChart("chartWind", "m/s", [
    line("Höchste Messung", p(out?.wind_ms?.max), css("--dwd"), { lineStyle: { width: 1.5, type: "dashed" } }),
    line("Mittelwert", p(out?.wind_ms?.avg), css("--wind"), { areaStyle: { opacity: 0.10 } }),
  ], { timeFormat, yAxis: { min: 0 }, legend: ["Mittelwert", "Höchste Messung"] });
  drawChart("chartLight", "kLux", [
    line("West", p(out?.west_klux?.avg), css("--temp"), { markArea: shade }),
    line("Süd", p(out?.south_klux?.avg), css("--sun")),
    line("Ost", p(out?.east_klux?.avg), css("--rain")),
  ], { timeFormat, yAxis: { min: 0 }, legend: ["West", "Süd", "Ost"] });
  drawChart("chartDusk", "lx", [
    line("Dämmerung", p(out?.twilight_lux?.avg), css("--dusk"), { areaStyle: { opacity: 0.12 } }),
  ], { timeFormat, yAxis: { min: 0, max: 1000 } });
}

function drawTrends({ out, sun, dwd, timeFormat }) {
  outdoorChart(out, sun, dwd, timeFormat);
  remainingCharts(out, sun, timeFormat);
}

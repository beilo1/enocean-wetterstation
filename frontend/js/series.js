"use strict";

const $ = id => document.getElementById(id);
const numberFormats = [0, 1, 2].map(digits =>
  new Intl.NumberFormat("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
const fmt = (value, digits = 1, unit = "") => Number.isFinite(value)
  ? numberFormats[digits].format(value) + unit : "–";
const clock = (value) => new Date(value).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
const timestamp = (value) => new Date(value).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });

async function json(path, signal) {
  const response = await fetch(path, { cache: "no-store", signal });
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
}

function periodParams(period) {
  const p = new URLSearchParams({ range: period.range });
  if (period.range === "custom") {
    p.set("start", period.start);
    p.set("end", period.end);
  }
  return p;
}

function periodDays({ range, start, end }) {
  if (range === "custom") return (Date.parse(end) - Date.parse(start)) / 86400000 + 1;
  return { "24h": 1, "7d": 7, "30d": 30, "365d": 365 }[range];
}

function bindPeriodControls(onChange) {
  const buttons = [...$("rangePicker").querySelectorAll("button")];
  const form = $("customRange");
  const error = $("rangeError");
  for (const button of buttons) button.addEventListener("click", () => {
    const range = button.dataset.range;
    for (const choice of buttons) choice.setAttribute("aria-pressed", choice === button);
    form.hidden = range !== "custom";
    error.textContent = "";
    if (range !== "custom") onChange({ range, start: "", end: "" });
  });
  form.addEventListener("submit", event => {
    event.preventDefault();
    const { start, end } = form.elements;
    if (end.valueAsNumber < start.valueAsNumber) {
      error.textContent = "Das Enddatum muss ab dem Startdatum liegen.";
      return;
    }
    error.textContent = "";
    onChange({ range: "custom", start: start.value, end: end.value });
  });
}

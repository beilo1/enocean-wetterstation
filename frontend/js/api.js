"use strict";

const list = document.getElementById("apiEndpoints");
const search = document.getElementById("apiSearch");
const apiMessage = document.getElementById("apiMessage");
const limit = 24 * 1024;
const sectionOrder = ["System", "Daten", "Analyse"];

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function previewBody(response) {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let size = 0, body = "", truncated = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      const remaining = limit - size;
      const visible = value.subarray(0, remaining);
      body += decoder.decode(visible, { stream: true });
      size += visible.byteLength;
      if (value.byteLength > remaining) { truncated = true; break; }
    }
    body += decoder.decode();
  } finally {
    if (truncated) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  if (truncated) return body + "\n… Vorschau gekürzt.";
  if (response.headers.get("content-type")?.includes("json")) {
    try { return JSON.stringify(JSON.parse(body), null, 2); } catch {}
  }
  return body;
}

function requestPanel(path, spec) {
  const form = el("form", null, "api-form");
  const query = document.createElement("div");
  query.className = "api-fields";
  const controls = new Map();
  for (const parameter of spec.parameters || []) {
    if (parameter.in !== "query") continue;
    const label = el("label", parameter.name, "control-label");
    const types = parameter.schema?.anyOf || [parameter.schema || {}];
    const schema = types.find(property => property.type !== "null") || {};
    const input = document.createElement("input");
    input.className = "field";
    input.type = schema.type === "integer" ? "number" : "text";
    if (schema.minimum != null) input.min = schema.minimum;
    if (schema.maximum != null) input.max = schema.maximum;
    input.required = !!parameter.required;
    input.placeholder = parameter.schema?.default == null ? "" : String(parameter.schema.default);
    label.append(input);
    controls.set(parameter.name, input);
    query.append(label);
  }
  if (query.children.length) form.append(query);
  const controlsRow = el("div", null, "api-actions");
  const send = el("button", "Anfrage senden", "outline-button");
  send.type = "submit";
  const status = el("span", "", "page-message");
  status.setAttribute("role", "status");
  controlsRow.append(send, status);
  form.append(controlsRow);
  const output = el("pre", null, "console-block");
  output.hidden = true;
  output.tabIndex = 0;
  form.append(output);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const target = new URL(path, location.origin);
    for (const [key, input] of controls) if (input.value.trim()) target.searchParams.set(key, input.value.trim());
    send.disabled = true;
    output.hidden = true;
    status.textContent = "Anfrage läuft …";
    try {
      const response = await fetch(target, { cache: "no-store" });
      output.textContent = await previewBody(response);
      status.textContent = "HTTP " + response.status;
      output.hidden = !output.textContent;
    } catch {
      status.textContent = "Die Anfrage ist fehlgeschlagen.";
    } finally {
      send.disabled = false;
    }
  });
  return form;
}

function renderAPI(schema) {
  const groups = new Map();
  for (const [path, operations] of Object.entries(schema.paths || {})) {
    if (!path.startsWith("/") || path.startsWith("//") || path.includes("{")) continue;
    const spec = operations.get;
    if (!spec) continue;
    const group = spec.tags?.[0] || "Weitere Endpunkte";
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push([path, spec]);
  }
  list.replaceChildren();
  for (const group of [...new Set([...sectionOrder, ...groups.keys()])]) {
    if (!groups.has(group)) continue;
    const section = el("section", null, "card content-card api-group");
    section.append(el("h2", group));
    for (const [path, spec] of groups.get(group)) {
      const entry = el("details", null, "api-endpoint");
      entry.dataset.search = [path, spec.summary, spec.description, group].join(" ").toLocaleLowerCase("de");
      const summary = el("summary");
      const title = el("span", null, "api-route");
      title.append(el("span", "GET", "api-method"), el("code", path));
      summary.append(title, el("span", spec.summary || "", "api-summary"));
      entry.append(summary);
      if (spec.description) entry.append(el("p", spec.description, "api-description"));
      entry.append(requestPanel(path, spec));
      section.append(entry);
    }
    list.append(section);
  }
  search.disabled = false;
  filterAPI();
}

function filterAPI() {
  const term = search.value.trim().toLocaleLowerCase("de");
  let visible = 0;
  for (const group of list.querySelectorAll(".api-group")) {
    let count = 0;
    for (const entry of group.querySelectorAll("details")) {
      entry.hidden = !entry.dataset.search.includes(term);
      if (!entry.hidden) count++;
    }
    group.hidden = !count;
    visible += count;
  }
  apiMessage.textContent = visible ? "" : "Keine passenden Endpunkte gefunden.";
}
search.addEventListener("input", filterAPI);
(async () => {
  try {
    const response = await fetch("/openapi.json", { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    renderAPI(await response.json());
  } catch {
    apiMessage.textContent = "Das OpenAPI-Schema konnte nicht geladen werden.";
  }
})();
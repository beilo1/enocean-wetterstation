"use strict";

const feedback = document.getElementById("copyFeedback");

async function copySnippet(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Auch die lokale HTTP-Installation ohne Clipboard API unterstützen.
    const field = document.createElement("textarea");
    field.className = "visually-hidden";
    field.value = text;
    document.body.append(field);
    field.select();
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    } finally {
      field.remove();
    }
  }
}

function setCopyState(button, state) {
  const labels = {
    ready: "Code kopieren",
    copied: "Kopiert",
    error: "Kopieren fehlgeschlagen. Bitte manuell kopieren.",
  };
  const label = labels[state];
  button.dataset.copyState = state;
  button.setAttribute("aria-label", label);
  button.title = label;
  button.querySelector("use").setAttribute("href", "/icons.svg#" + (state === "copied" ? "check" : "copy"));
}

for (const button of document.querySelectorAll(".snippet-copy")) {
  let reset;
  button.addEventListener("click", async () => {
    clearTimeout(reset);
    const text = button.closest(".snippet").querySelector("code").textContent;
    const copied = await copySnippet(text);
    setCopyState(button, copied ? "copied" : "error");
    feedback.textContent = button.title;
    if (document.activeElement === document.body) button.focus({ preventScroll: true });
    reset = setTimeout(() => {
      setCopyState(button, "ready");
      feedback.textContent = "";
    }, 1800);
  });
}

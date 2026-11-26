"use strict";

const themeSwitch = document.getElementById("themeBtn");
const moonPath = '<path d="M20.8 14.2A9 9 0 0 1 9.9 3.1a9.1 9.1 0 1 0 10.9 11.1Z"/>';
const sunPath = '<circle cx="12" cy="12" r="4"/><path d="M12 1.5v2M12 20.5v2M1.5 12h2M20.5 12h2M4.5 4.5 6 6m12 12 1.5 1.5m0-15L18 6M6 18l-1.5 1.5"/>';

function setSiteTheme(dark) {
  document.documentElement.classList.toggle("dark", dark);
  const label = dark ? "Helle Ansicht einschalten" : "Dunkle Ansicht einschalten";
  themeSwitch.setAttribute("aria-label", label);
  themeSwitch.title = label;
  themeSwitch.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + (dark ? sunPath : moonPath) + "</svg>";
  document.querySelector('meta[name="theme-color"]').content = dark ? "#17221d" : "#f7f6f0";
}

let themeMode = "light";
try { themeMode = localStorage.getItem("theme") || "light"; } catch {}
setSiteTheme(themeMode === "dark");
themeSwitch.addEventListener("click", () => {
  const dark = !document.documentElement.classList.contains("dark");
  try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch {}
  setSiteTheme(dark);
  document.dispatchEvent(new Event("theme-changed"));
});

if (document.getElementById("innen")) {
  function showCurrentPage() {
    const indoor = location.hash === "#innen";
    document.title = "Wetterstation • " + (indoor ? "Raumklima" : "Übersicht");
    for (const link of document.querySelectorAll('.main-nav a[href="/"], .main-nav a[href="/#innen"]')) {
      const active = (link.hash === "#innen") === indoor;
      link.classList.toggle("current", active);
      if (active) link.setAttribute("aria-current", indoor ? "location" : "page");
      else link.removeAttribute("aria-current");
    }
  }
  showCurrentPage();
  window.addEventListener("hashchange", showCurrentPage);
}

function mountProjectFooter(footer) {
  const repository = "beilo1/enocean-wetterstation";
  const repositoryUrl = "https://github.com/" + repository;
  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "project-footer-link";
  trigger.setAttribute("aria-haspopup", "dialog");
  trigger.setAttribute("aria-controls", "project-dialog");
  trigger.innerHTML = `<span data-copyright-year></span> <span aria-hidden="true">|</span>
    <span class="project-repository">${repository}</span>`;
  footer.append(trigger);

  const firstYear = 2026;
  const yearFormat = new Intl.DateTimeFormat("de-DE", { year: "numeric", timeZone: "Europe/Berlin" });
  const yearLabel = trigger.querySelector("[data-copyright-year]");
  function updateYear() {
    const year = Number(yearFormat.format(new Date()));
    yearLabel.textContent = "© " + (year > firstYear ? firstYear + "-" + year : firstYear);
  }
  updateYear();
  setInterval(updateYear, 60_000);

  const dialog = document.createElement("dialog");
  dialog.id = "project-dialog";
  dialog.className = "project-dialog";
  dialog.setAttribute("aria-labelledby", "project-title");
  dialog.innerHTML = `<header class="project-dialog-header">
      <h2 id="project-title">Projekt und Lizenz</h2>
      <button type="button" class="icon-button" aria-label="Fenster schließen" autofocus>
        <svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>
      </button>
    </header>
    <div class="project-dialog-content">
      <div class="project-notice">
        <div>
          <p>EnOcean Wetterstation steht unter der <strong>MIT-Lizenz</strong>. Der Quellcode ist im öffentlichen GitHub-Repository von <strong>beilo1</strong> verfügbar.</p>
          <p><a href="${repositoryUrl}" target="_blank" rel="noopener noreferrer">github.com/${repository}</a></p>
        </div>
        <img class="project-qr" src="/project-qr.svg" alt="QR-Code zum EnOcean-Wetterstation-Repository auf GitHub" width="132" height="132">
      </div>
      <details class="project-license">
        <summary>MIT-Lizenz lokal lesen</summary>
        <div class="project-license-content" aria-live="polite"></div>
      </details>
    </div>`;
  document.body.append(dialog);

  const license = dialog.querySelector(".project-license");
  const content = license.querySelector(".project-license-content");
  let licenseLoading = false;
  let licenseLoaded = false;
  license.addEventListener("toggle", async () => {
    if (!license.open || licenseLoading || licenseLoaded) return;
    licenseLoading = true;
    content.textContent = "Lizenztext wird geladen …";
    try {
      const response = await fetch("/license", { signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const text = await response.text();
      const paragraphs = text.trim().split(/\r?\n(?:[^\S\r\n]*\r?\n)+/);
      content.replaceChildren(...paragraphs.map(paragraph => {
        const node = document.createElement("p");
        node.textContent = paragraph.replace(/\s+/g, " ");
        return node;
      }));
      licenseLoaded = true;
    } catch {
      content.textContent = "Lizenztext konnte nicht geladen werden. Schließe und öffne den Abschnitt erneut.";
    } finally {
      licenseLoading = false;
    }
  });

  trigger.addEventListener("click", () => {
    updateYear();
    dialog.showModal();
  });
  dialog.querySelector("button").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => trigger.focus());
}

mountProjectFooter(document.querySelector(".site-footer"));

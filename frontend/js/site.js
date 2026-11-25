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

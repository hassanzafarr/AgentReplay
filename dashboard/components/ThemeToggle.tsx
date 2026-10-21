"use client";

import { useSyncExternalStore } from "react";
import { MoonIcon, SunIcon } from "./Icons";

// The theme lives on <html class="dark"> (set pre-paint in layout.tsx), so read
// it as an external store instead of mirroring it into state via an effect.
function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

const isDark = () => document.documentElement.classList.contains("dark");

function toggleTheme() {
  const next = !isDark();
  document.documentElement.classList.toggle("dark", next);
  try {
    localStorage.setItem("ar-theme", next ? "dark" : "light");
  } catch {}
}

export default function ThemeToggle() {
  const dark = useSyncExternalStore(subscribe, isDark, () => false);
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Switch to light theme" : "Switch to dark theme"}
      className="grid h-8 w-8 shrink-0 place-items-center border border-desk-line text-on-desk-muted transition-colors hover:bg-desk-2 hover:text-on-desk"
    >
      {dark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

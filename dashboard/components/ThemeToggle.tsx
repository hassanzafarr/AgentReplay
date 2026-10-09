"use client";

import { useSyncExternalStore } from "react";

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
      onClick={toggleTheme}
      aria-label="Toggle theme"
      className="grid h-8 w-8 place-items-center rounded-lg border border-border text-fg-muted transition-colors hover:bg-surface-3 hover:text-fg"
    >
      {dark ? "☀️" : "🌙"}
    </button>
  );
}

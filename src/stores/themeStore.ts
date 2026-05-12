/**
 * themeStore — manages light/dark mode preference.
 * Persists to localStorage and applies "dark" class to <html>.
 */

import { create } from "zustand";

function getInitial(): boolean {
  try {
    const stored = localStorage.getItem("vanilla:dark");
    if (stored !== null) return stored === "true";
  } catch {}
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

function applyDark(dark: boolean) {
  if (dark) {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

interface ThemeState {
  isDark: boolean;
  toggle: () => void;
  setDark: (dark: boolean) => void;
}

export const useThemeStore = create<ThemeState>((set, get) => {
  // Apply immediately on module load
  const initial = getInitial();
  applyDark(initial);

  return {
    isDark: initial,
    toggle: () => {
      const next = !get().isDark;
      applyDark(next);
      localStorage.setItem("vanilla:dark", String(next));
      set({ isDark: next });
    },
    setDark: (dark: boolean) => {
      applyDark(dark);
      localStorage.setItem("vanilla:dark", String(dark));
      set({ isDark: dark });
    },
  };
});

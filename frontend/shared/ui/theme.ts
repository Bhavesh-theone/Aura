"use client";

import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

/** Inline in <head> to set data-theme before paint (no flash). */
export const themeInitScript = `try{var t=localStorage.getItem("aura_theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}`;

function current(): Theme {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "light" || attr === "dark") return attr;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const EVT = "aura:theme";

export function useTheme() {
  const [theme, setTheme] = useState<Theme>("light");
  useEffect(() => {
    setTheme(current());
    const on = () => setTheme(current());
    window.addEventListener(EVT, on);
    return () => window.removeEventListener(EVT, on);
  }, []);
  const toggle = () => {
    const next: Theme = current() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("aura_theme", next);
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new Event(EVT));
  };
  return { theme, toggle };
}

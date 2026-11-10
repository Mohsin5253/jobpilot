"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Toaster } from "sonner";

import { useMediaQuery } from "@/lib/use-media";

type Theme = "light" | "dark" | "system";
const ThemeCtx = createContext<{ theme: Theme; setTheme: (t: Theme) => void }>({ theme: "dark", setTheme: () => {} });
export const useTheme = () => useContext(ThemeCtx);

function apply(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: true } },
      }),
  );
  // Agent toasts stack bottom-right on desktop and drop from the top on phones (clear of the tab bar).
  const phone = useMediaQuery("(max-width: 767px)");
  // Graphite is the house look; the switch in the sidebar offers light and "follow my system".
  const [theme, setThemeState] = useState<Theme>("dark");

  useEffect(() => {
    let saved: Theme = "dark";
    try {
      saved = (localStorage.getItem("jp-theme") as Theme) || "dark";
    } catch {}
    setThemeState(saved);
    apply(saved);
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply((localStorage.getItem("jp-theme") as Theme) || "dark");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const setTheme = (t: Theme) => {
    setThemeState(t);
    try {
      localStorage.setItem("jp-theme", t);
    } catch {}
    apply(t);
  };

  return (
    <ThemeCtx.Provider value={{ theme, setTheme }}>
      <QueryClientProvider client={client}>
        {children}
        <Toaster
          position={phone ? "top-center" : "bottom-right"}
          offset={phone ? undefined : 20}
          mobileOffset={{ top: "calc(12px + env(safe-area-inset-top))", left: 12, right: 12 }}
          gap={10}
          visibleToasts={4}
        />
      </QueryClientProvider>
    </ThemeCtx.Provider>
  );
}

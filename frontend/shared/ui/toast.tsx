"use client";

import { CheckCircle2, Info, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useState } from "react";
import { cx } from "@/shared/lib/format";

type Tone = "success" | "error" | "info";
type Toast = { id: number; tone: Tone; message: string };
const Ctx = createContext<(message: string, tone?: Tone) => void>(() => {});

export const useToast = () => useContext(Ctx);

const icon: Record<Tone, React.ReactNode> = {
  success: <CheckCircle2 className="h-4 w-4 text-success" />,
  error: <XCircle className="h-4 w-4 text-danger" />,
  info: <Info className="h-4 w-4 text-info" />,
};

/** Bottom-right toasts: neutral raised surface, tone carried by the icon only. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((message: string, tone: Tone = "success") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-2), { id, tone, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div role="status" aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[80] flex w-[340px] flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cx(
              "a-pop pointer-events-auto flex items-start gap-2.5 rounded-md bg-raised px-3.5 py-3 text-[13px] text-fg shadow-overlay",
            )}
          >
            <span className="mt-px">{icon[t.tone]}</span>
            <span className="leading-snug">{t.message}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

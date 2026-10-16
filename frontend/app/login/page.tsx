import { LoginForm } from "@/features/auth/components/LoginForm";
import { FIRM_NAME } from "@/shared/config";
import { AuraMark } from "@/shared/ui/Mark";

/**
 * A neutral picture of the product: twelve stage cells with gates between
 * them, a guard checklist and a hash chain. Placeholder bars only — no deal
 * names, figures or claims.
 */
function SpineIllustration() {
  const reached = 7;
  return (
    <div className="max-w-md rounded-md border border-line bg-raised p-5 shadow-overlay">
      {/* header placeholders */}
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-40 rounded-full bg-control-active" />
        <span className="ml-auto h-4 w-14 rounded-xs border border-line bg-well" />
      </div>
      <div className="mt-2 h-2 w-24 rounded-full bg-control-active/70" />

      {/* twelve-stage spine with gates */}
      <div className="mt-6 flex items-center">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="flex flex-1 items-center">
            <span
              className={
                i < reached
                  ? "h-2 flex-1 rounded-[2px] bg-accent"
                  : i === reached
                    ? "h-2 flex-1 rounded-[2px] bg-accent shadow-[0_0_0_3px_var(--accent-soft)]"
                    : "h-2 flex-1 rounded-[2px] bg-control-active"
              }
            />
            {i < 11 ? (
              <span className={i < reached ? "mx-[2px] h-3 w-[2px] rounded-full bg-accent/50" : "mx-[2px] h-3 w-[2px] rounded-full bg-line-strong"} />
            ) : null}
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between font-mono text-[11px] text-muted">
        <span>01</span>
        <span>12</span>
      </div>

      {/* guard checklist */}
      <ul className="mt-5 space-y-2.5 border-t border-line-subtle pt-4">
        {[
          ["bg-success", "w-44"],
          ["bg-success", "w-36"],
          ["bg-warning", "w-48"],
        ].map(([dot, w], i) => (
          <li key={i} className="flex items-center gap-2.5">
            <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
            <span className={`h-2 rounded-full bg-control-active ${w}`} />
            <span className="ml-auto h-2 w-10 rounded-full bg-control-active/70" />
          </li>
        ))}
      </ul>

      {/* hash chain */}
      <div className="mt-5 flex items-center gap-1.5 border-t border-line-subtle pt-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <span className="flex h-6 items-center rounded-xs border border-line bg-well px-1.5">
              <span className="h-1.5 w-7 rounded-full bg-line-strong" />
            </span>
            {i < 4 ? <span className="h-px w-2.5 bg-line-strong" /> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="grid min-h-screen bg-canvas lg:grid-cols-[1fr_minmax(480px,44%)]">
      {/* Sign-in */}
      <div className="flex flex-col px-8 py-8 sm:px-14">
        <div className="flex items-center gap-2.5">
          <AuraMark size={24} />
          <span className="text-[14px] font-semibold tracking-tight text-fg">{FIRM_NAME}</span>
        </div>

        <div className="mx-auto flex w-full max-w-[360px] flex-1 flex-col justify-center py-16">
          <h1 className="font-serif text-[36px] leading-[1.1] text-fg">Sign in to the desk</h1>
          <p className="mt-3 text-[14px] leading-relaxed text-muted">
            Use the account your administrator gave you. Everything you decide here is recorded in your name.
          </p>
          <div className="mt-9">
            <LoginForm />
          </div>
          <p className="mt-8 text-[12px] leading-relaxed text-muted">
            Runs entirely on this machine. No deal data, documents or model calls leave the network.
          </p>
        </div>

        <p className="text-[12px] text-muted">{FIRM_NAME === "Aura" ? "Aura" : `${FIRM_NAME} · Aura`} · Internal use only</p>
      </div>

      {/* Product panel */}
      <aside aria-hidden className="relative hidden overflow-hidden border-l border-line bg-surface lg:block dark:bg-[#0e1013]">
        <div className="absolute inset-0 bg-[radial-gradient(80%_60%_at_70%_0%,var(--accent-soft),transparent_70%)] opacity-80" />
        <div className="relative flex h-full flex-col justify-between p-12">
          <div className="text-[12px] font-medium uppercase tracking-[0.08em] text-muted">Deal execution, with a human hand on every gate</div>

          <div>
            <p className="max-w-md font-serif text-[28px] leading-[1.25] text-fg">
              Twelve stages. Every move guarded, every decision on the record.
            </p>
            <div className="mt-10">
              <SpineIllustration />
            </div>
          </div>

          <div className="flex gap-8 text-[12px] text-muted">
            <span><span className="font-mono text-fg-2">SHA-256</span> hash-chained audit</span>
            <span><span className="font-mono text-fg-2">Local</span> inference only</span>
          </div>
        </div>
      </aside>
    </div>
  );
}

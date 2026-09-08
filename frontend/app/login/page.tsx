import { LoginForm } from "@/features/auth/components/LoginForm";
import { YukiMark } from "@/shared/ui/icons";

export default function LoginPage() {
  return (
    <div className="flex min-h-screen">
      {/* Brand panel */}
      <div className="relative hidden w-[46%] flex-col justify-between bg-navy p-10 lg:flex">
        <div className="flex items-center gap-2.5">
          <YukiMark className="h-6 w-6 text-amber" />
          <span className="text-[13px] font-bold tracking-[0.2em] text-white">YUKI OS</span>
        </div>

        <div className="max-w-md">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber">
            Agent orchestration portal
          </p>
          <h1 className="mt-4 text-3xl font-semibold leading-snug text-white">
            Every rupee, every document, every message — cleared by a human first.
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-white/60">
            Yuki OS runs the desk&apos;s agent crew end to end, and holds anything that touches money,
            legal execution or outbound communication until you approve it.
          </p>
        </div>

        <p className="text-[11px] text-white/40">
          Opulence Business Solutions Pvt. Ltd. · Internal use only
        </p>
      </div>

      {/* Sign-in panel */}
      <div className="flex flex-1 items-center justify-center bg-appbg px-6 py-12">
        <div className="w-full max-w-[360px]">
          <div className="mb-7 lg:hidden">
            <YukiMark className="h-7 w-7 text-amber" />
          </div>
          <h2 className="text-xl font-semibold text-ink">Sign in</h2>
          <p className="mt-1.5 text-[13px] text-muted">
            Use your Opulence directory credentials to open the portal.
          </p>

          <div className="mt-7 rounded-xl border border-line bg-surface p-6 shadow-[0_1px_2px_rgba(27,36,54,0.04)]">
            <LoginForm />
          </div>

          <p className="mt-5 text-center text-[11px] leading-relaxed text-muted">
            Access is logged. Approvals you record here are auditable actions taken in your name.
          </p>
        </div>
      </div>
    </div>
  );
}

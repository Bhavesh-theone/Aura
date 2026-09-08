"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/hooks";
import { Button } from "@/shared/ui/Button";
import { AlertIcon } from "@/shared/ui/icons";

export function LoginForm() {
  const { signIn, user, ready } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && user) router.replace("/");
  }, [ready, user, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label htmlFor="username" className="mb-1.5 block text-[12px] font-medium text-ink">
          Username
        </label>
        <input
          id="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
          placeholder="bhavesh"
          className="w-full rounded-md border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none transition-colors placeholder:text-muted/70 focus:border-navy focus:ring-2 focus:ring-navy/10"
        />
      </div>

      <div>
        <label htmlFor="password" className="mb-1.5 block text-[12px] font-medium text-ink">
          Password
        </label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
          placeholder="••••••••"
          className="w-full rounded-md border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none transition-colors placeholder:text-muted/70 focus:border-navy focus:ring-2 focus:ring-navy/10"
        />
      </div>

      {error ? (
        <div className="flex items-start gap-2 rounded-md border border-[#f6c9c9] bg-cat-outbound-bg px-3 py-2.5 text-[12px] leading-relaxed text-cat-outbound-fg">
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}

      <Button type="submit" loading={busy} className="w-full py-2.5">
        {busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}

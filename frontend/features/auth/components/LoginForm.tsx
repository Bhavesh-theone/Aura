"use client";

import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/hooks";
import { ApiError } from "@/shared/api/client";
import { Button, inputCls, labelCls } from "@/shared/ui/primitives";
import { Notice } from "@/shared/ui/States";
import { cx } from "@/shared/lib/format";

export function LoginForm() {
  const { signIn, user, ready } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [down, setDown] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && user) router.replace("/");
  }, [ready, user, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDown(false);
    try {
      await signIn(username.trim(), password);
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError && (err.isUnreachable || err.kind === "timeout")) setDown(true);
      else setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label htmlFor="username" className={labelCls}>Username</label>
        <input
          id="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          autoFocus
          required
          className={cx(inputCls, "h-9 text-[14px]")}
        />
      </div>
      <div>
        <label htmlFor="password" className={labelCls}>Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
          className={cx(inputCls, "h-9 text-[14px]")}
        />
      </div>
      {down ? (
        <Notice tone="error" title="Can’t reach the Aura server">
          Sign-in needs the live server — there is no offline mode. Check that the API is running, then try again.
        </Notice>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}
      <Button type="submit" size="lg" loading={busy} className="w-full">
        {busy ? "Signing in…" : "Continue"}
        {!busy ? <ArrowRight className="h-3.5 w-3.5" /> : null}
      </Button>
    </form>
  );
}

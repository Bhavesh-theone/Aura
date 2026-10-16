# Aura — frontend

Next.js portal for Aura. See the [root README](../README.md) for the product overview and [RUNNING.md](../RUNNING.md) for setup.

```bash
npm install
npm run dev     # http://localhost:3000 — needs the backend on :8000
npm run build   # must pass with no type errors
```

Design tokens (colour, spacing, type, motion, light and dark themes) live in `app/globals.css`. Set the firm name shown in the sidebar and login with `NEXT_PUBLIC_FIRM_NAME` (see `.env.example`). Read `AGENTS.md` before changing code: this Next.js version has rules that differ from older releases.

import type { Metadata } from "next";
import { AuthProvider } from "@/features/auth/hooks";
import "./globals.css";

export const metadata: Metadata = {
  title: "Yuki OS Portal",
  description: "Agent orchestration and approvals — Opulence Business Solutions Pvt. Ltd.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}

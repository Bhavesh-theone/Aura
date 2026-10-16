import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource/newsreader/500.css";
import { AuthProvider } from "@/features/auth/hooks";
import { FIRM_NAME } from "@/shared/config";
import { themeInitScript } from "@/shared/ui/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: FIRM_NAME === "Aura" ? "Aura — Deal desk" : `Aura — ${FIRM_NAME} deal desk`,
  description: FIRM_NAME === "Aura" ? "Deal execution workspace" : `Deal execution workspace — ${FIRM_NAME}`,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className="h-full" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-full">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}

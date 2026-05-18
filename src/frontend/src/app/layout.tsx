import type { Metadata } from "next";
import "./globals.css";

/** Prefix for static assets when ``NEXT_PUBLIC_BASE_PATH`` is set (manual CM bundle). */
function staticAsset(path: string): string {
  const base = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
}

export const metadata: Metadata = {
  title: "Arango Workflow",
  description: "Unified Databricks workflow dashboard — OntoExtract + platform shell",
  icons: {
    icon: staticAsset("/favicon.svg"),
    shortcut: staticAsset("/favicon.svg"),
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}

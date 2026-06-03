import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Autopsy Memory | Local-first graph memory for coding agents",
  description:
    "Autopsy Memory gives coding agents durable local graph memory, relation-aware context packs, governed writes, and a native macOS companion.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

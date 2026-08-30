import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Forge AI",
  description: "Durable workflow and agent control plane"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html className="dark" lang="en">
      <body className="min-h-screen bg-[#050505] text-zinc-100 antialiased">{children}</body>
    </html>
  );
}

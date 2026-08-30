import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Forge AI",
  description: "Durable workflow and agent control plane"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

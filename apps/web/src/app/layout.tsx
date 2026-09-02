import "./globals.css";
import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap"
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap"
});

export const metadata: Metadata = {
  title: "Forge AI",
  description: "A precision control room for durable AI agent and workflow execution"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html className={`dark ${inter.variable} ${jetbrainsMono.variable}`} lang="en">
      <body className="min-h-screen bg-surface-0 font-sans text-ink antialiased">{children}</body>
    </html>
  );
}

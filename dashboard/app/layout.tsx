import type { Metadata } from "next";
import { Archivo, Fragment_Mono } from "next/font/google";
import "./globals.css";

// Archivo's width axis gives both voices of a punch card: condensed caps for card print,
// normal width for the interface. Fragment Mono carries data: hashes, seq, prompts.
const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  axes: ["wdth"],
});

const fragmentMono = Fragment_Mono({
  variable: "--font-fragment-mono",
  subsets: ["latin"],
  weight: "400",
});

export const metadata: Metadata = {
  title: "AgentReplay — Trace Viewer & Diff",
  description:
    "Inspect and diff deterministic LangGraph agent traces. Record every impure input, replay offline at ~$0, and diff a new prompt/model against a baseline.",
};

// Run before paint to set the theme class — avoids a light/dark flash on load.
const themeScript = `
(function () {
  try {
    var t = localStorage.getItem('ar-theme');
    var dark = t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.classList.toggle('dark', dark);
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${archivo.variable} ${fragmentMono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}

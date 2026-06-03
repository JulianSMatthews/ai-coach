import type { Metadata } from "next";
import { Fraunces, Source_Sans_3 } from "next/font/google";
import "./globals.css";
import { themeBootstrapScript } from "@/lib/theme";
import AppSplash from "@/components/AppSplash";

const headingFont = Fraunces({
  variable: "--font-heading",
  subsets: ["latin"],
});

const bodyFont = Source_Sans_3({
  variable: "--font-body",
  subsets: ["latin"],
});

const appTitle = process.env.NODE_ENV === "development" ? "HealthSense App (Develop)" : "HealthSense App";

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover" as const,
};

export const metadata: Metadata = {
  title: appTitle,
  description: "HealthSense coaching and assessment app",
  icons: {
    icon: "/healthsense-mark.svg",
    shortcut: "/healthsense-mark.svg",
    apple: "/apple-touch-icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      data-theme="light"
      data-theme-preference="light"
      style={{ colorScheme: "light", backgroundColor: "var(--background)" }}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrapScript() }} />
      </head>
      <body
        className={`${headingFont.variable} ${bodyFont.variable} antialiased`}
        style={{ backgroundColor: "var(--background)" }}
      >
        <AppSplash />
        {children}
      </body>
    </html>
  );
}

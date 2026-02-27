import type { Metadata } from "next";
import { Fraunces, Source_Sans_3 } from "next/font/google";
import "./globals.css";

const headingFont = Fraunces({
  variable: "--font-heading",
  subsets: ["latin"],
});

const bodyFont = Source_Sans_3({
  variable: "--font-body",
  subsets: ["latin"],
});

const appTitle = process.env.NODE_ENV === "development" ? "HealthSense App (Develop)" : "HealthSense App";

export const metadata: Metadata = {
  title: appTitle,
  description: "HealthSense assessment and progress dashboards",
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
    <html lang="en">
      <body className={`${headingFont.variable} ${bodyFont.variable} antialiased`}>{children}</body>
    </html>
  );
}

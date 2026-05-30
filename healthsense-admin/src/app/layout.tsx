import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import SessionBootstrap from "@/components/SessionBootstrap";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const adminTitle = process.env.NODE_ENV === "development" ? "HealthSense Admin (Develop)" : "HealthSense Admin";

export const metadata: Metadata = {
  title: adminTitle,
  description: "HealthSense administration console",
  icons: {
    icon: "/healthsense-mark.svg",
    shortcut: "/healthsense-mark.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <SessionBootstrap />
        {children}
      </body>
    </html>
  );
}

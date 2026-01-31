import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: [
    "https://healthsense.ngrok.app",
    "http://healthsense.ngrok.app",
    "https://healthsenseapi.ngrok.app",
    "http://healthsenseapi.ngrok.app",
  ],
};

export default nextConfig;

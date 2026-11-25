import type { NextConfig } from "next";

// The FastAPI backend runs on localhost:8000 (scripts/run_api.py). Proxying /api keeps
// the browser on one origin, so no CORS and no backend URL in client code.
const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
  },
};

export default nextConfig;

import type { NextConfig } from "next";

// Two builds from one codebase:
// - local app: the FastAPI backend on localhost:8000 (scripts/run_api.py), proxied as /api so the
//   browser stays on one origin (no CORS, no backend URL in client code);
// - hosted site (NEXT_PUBLIC_STATIC=1): plain files for Cloudflare Pages, reading the data the
//   daily scan exports to public/data.
const isStatic = process.env.NEXT_PUBLIC_STATIC === "1";

const nextConfig: NextConfig = isStatic
  ? { output: "export", images: { unoptimized: true } }
  : {
      async rewrites() {
        return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
      },
    };

export default nextConfig;

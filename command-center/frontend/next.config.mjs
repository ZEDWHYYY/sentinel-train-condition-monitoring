/** @type {import('next').NextConfig} */
const apiOrigin = process.env.SENTINEL_API_ORIGIN || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // NEXT_DIST_DIR lets a production build run while `next dev` holds .next
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Include multipart overhead above the API's 128 MiB per-file limit.
  experimental: { proxyTimeout: 300_000, middlewareClientMaxBodySize: "136mb", cpus: 2 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;

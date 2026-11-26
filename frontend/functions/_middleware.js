// Hosted site (Cloudflare Pages): fully public, no sign-in. Every response asks search engines
// not to index the site, so it is reachable only by its link.
export async function onRequest({ request, next }) {
  const res = await next();
  const copy = new Response(res.body, res);
  copy.headers.set("X-Robots-Tag", "noindex, nofollow");
  if (new URL(request.url).pathname.startsWith("/data/")) {
    copy.headers.set("cache-control", "public, max-age=300"); // updated daily
  }
  return copy;
}

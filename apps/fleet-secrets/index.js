// Serves super.env, rebuilt from Secrets Store bindings, to one Cloudflare Access service
// token. Access guards the hostname; this code re-verifies the Access JWT so a misconfigured
// Access app still fails closed. Never log request data or secret values here.
// Plain-text bindings team_domain (<team>.cloudflareaccess.com) and aud (the Access app AUD
// tag) come from the Access API at push time. Secret bindings, written by
// scripts/stow-secrets.sh: super_env_0, super_env_1, ... hold the file's base64 in order, and
// FLEET_SECRETS_ACCESS_CLIENT_ID names the one service token allowed in. GET /NAME serves one
// secret only when it is bound as read_NAME (the name in FLEET_SECRETS_READABLE).
const headers = { "Cache-Control": "no-store" };
const deny = (status = 403) => new Response(null, { status, headers });
const bytes = (s) =>
  Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
const json = (s) => JSON.parse(new TextDecoder().decode(bytes(s)));

async function authorized(request, env) {
  const parts = (request.headers.get("Cf-Access-Jwt-Assertion") ?? "").split(".");
  if (parts.length !== 3) return false;
  const [head, body, sig] = parts;
  const { alg, kid } = json(head);
  if (alg !== "RS256") return false;
  // Fetched per request so Access key rotation needs no redeploy.
  const certs = await fetch(`https://${env.team_domain}/cdn-cgi/access/certs`);
  const jwk = (await certs.json()).keys.find((k) => k.kid === kid);
  if (!jwk) return false;
  const algo = { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" };
  const key = await crypto.subtle.importKey("jwk", jwk, algo, false, ["verify"]);
  const signed = new TextEncoder().encode(`${head}.${body}`);
  if (!(await crypto.subtle.verify(algo, key, bytes(sig), signed))) return false;
  const claims = json(body);
  const now = Date.now() / 1000;
  return (
    claims.iss === `https://${env.team_domain}` &&
    Boolean(env.aud) &&
    [claims.aud].flat().includes(env.aud) &&
    claims.exp > now &&
    (claims.nbf ?? 0) <= now &&
    claims.common_name === (await env.FLEET_SECRETS_ACCESS_CLIENT_ID.get())
  );
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET") return deny();
    if (!(await authorized(request, env).catch(() => false))) return deny();
    const name = new URL(request.url).pathname.slice(1);
    const text = { ...headers, "Content-Type": "text/plain; charset=utf-8" };
    try {
      if (name) {
        const secret = env[`read_${name}`];
        return secret ? new Response(await secret.get(), { headers: text }) : deny(404);
      }
      let b64 = "";
      for (let i = 0; env[`super_env_${i}`]; i++) b64 += await env[`super_env_${i}`].get();
      return new Response(bytes(b64), { headers: text });
    } catch {
      // Error text can quote secret material; answer without it.
      return deny(500);
    }
  },
};

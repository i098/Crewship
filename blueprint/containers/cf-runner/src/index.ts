import { Container, getContainer } from "@cloudflare/containers";

// One container per job. The entrypoint runs the JIT runner once, so the container stops
// when the job ends; sleepAfter only bounds a container whose runner never got a job.
export class Runner extends Container {
  sleepAfter = "3h";
  async launch(jit: string) {
    await this.start({ envVars: { JITCONFIG: jit } });
  }
}

interface Env {
  RUNNER: DurableObjectNamespace<Runner>;
  DISPATCH_TOKEN: string;
}

export default {
  async fetch(req: Request, env: Env) {
    if (!env.DISPATCH_TOKEN) return new Response("not configured", { status: 503 });
    if (req.headers.get("authorization") !== `Bearer ${env.DISPATCH_TOKEN}`) {
      return new Response("unauthorized", { status: 401 });
    }
    const url = new URL(req.url);
    const id = url.searchParams.get("id");
    if (!id) return new Response("id required", { status: 400 });
    const box = getContainer(env.RUNNER, id);
    if (url.pathname === "/start" && req.method === "POST") {
      await box.launch((await req.json<{ jit: string }>()).jit);
      return Response.json({ started: id });
    }
    return new Response("not found", { status: 404 });
  },
};

interface CapApi {
	on(event: "before_provider_request", handler: (event: { payload: unknown }) => unknown): void;
}

export default function (pi: CapApi) {
	const env = process.env;
	if (env.FM_OMP_HARNESS !== "omp" || env.OMP_SKIP_SETUP !== "1" || env.FM_OPUS_EFFORT_UNCAPPED === "1") return;
	pi.on("before_provider_request", (event) => {
		const payload = event.payload as { model?: unknown; output_config?: { effort?: unknown } } | null;
		if (typeof payload?.model !== "string" || !payload.model.includes("claude-opus-5-5")) return undefined;
		const effort = payload.output_config?.effort;
		if (effort !== "xhigh" && effort !== "max") return undefined;
		return { ...payload, output_config: { ...payload.output_config, effort: "high" } };
	});
}

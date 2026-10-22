interface CapApi {
	on(event: "before_provider_request", handler: (event: { payload: unknown }) => unknown): void;
}

interface EffortControl {
	output_config?: { effort?: unknown };
}

function exceedsCap(control: EffortControl) {
	return control.output_config?.effort === "xhigh" || control.output_config?.effort === "max";
}

export default function (pi: CapApi) {
	const env = process.env;
	if (env.FM_OMP_HARNESS !== "omp" || env.OMP_SKIP_SETUP !== "1" || env.FM_OPUS_EFFORT_UNCAPPED === "1") return;
	pi.on("before_provider_request", (event) => {
		const payload = event.payload as (EffortControl & {
			model?: unknown;
			messages?: EffortControl[];
		}) | null;
		if (typeof payload?.model !== "string" || !payload.model.includes("claude-opus-5-5")) return undefined;
		let result = payload;
		if (exceedsCap(payload)) {
			result = { ...result, output_config: { ...payload.output_config, effort: "high" } };
		}
		if (payload.messages?.some(exceedsCap)) {
			result = {
				...result,
				messages: payload.messages.map((message) => exceedsCap(message)
					? { ...message, output_config: { ...message.output_config, effort: "high" } }
					: message),
			};
		}
		return result === payload ? undefined : result;
	});
}

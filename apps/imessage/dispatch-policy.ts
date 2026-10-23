import { JSONC, YAML } from "bun";
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

export type DispatchModel = { id: string; provider: "omp" | "inception"; model: string; reasoning: string[]; apiKeyEnv: string | null };
export type DispatchSelection = { provider: "omp" | "inception"; model: string; reasoning: string; apiKeyEnv: string | null };
export type DispatchCatalogEntry = { provider: string; id: string; reasoning: readonly string[]; apiKeyEnv: string | null };
export type DispatchPurpose = "general" | "simple-coding";

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function permitsPurpose(id: string, purpose: DispatchPurpose): boolean {
  if (/(?:^|\/)claude-fable(?:-|$)/.test(id)) return false;
  if (id === "inception/mercury-3") return purpose === "simple-coding";
  return /^(?:anthropic|openai|openai-codex)\//.test(id);
}

// Mirror pi-ai/registry/hooks/env.ts; its computed Anthropic resolver exposes no single environment variable name.
function anthropicApiKeyEnv(environment: Record<string, string | undefined>, foundry: boolean): string | null {
  const names = foundry
    ? ["ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_API_KEY"]
    : ["ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_API_KEY"];
  return names.find((name) => environment[name]?.trim()) ?? null;
}

function dispatchProfiles(policy: unknown): unknown[] {
  if (!record(policy) || !Array.isArray(policy.rules)) throw new Error("Invalid crew dispatch policy");
  const profiles: unknown[] = [];
  for (const rule of policy.rules) {
    if (!record(rule)) throw new Error("Invalid crew dispatch rule");
    profiles.push(...(Array.isArray(rule.use) ? rule.use : [rule.use]));
  }
  if (policy.default !== undefined) profiles.push(...(Array.isArray(policy.default) ? policy.default : [policy.default]));
  return profiles;
}

function primaryProfile(value: unknown): { model: string; effort?: string } | undefined {
  if (!record(value) || typeof value.harness !== "string" || typeof value.model !== "string"
    || (value.effort !== undefined && typeof value.effort !== "string")) throw new Error("Invalid crew dispatch profile");
  if (value.harness !== "omp" || /(?:^|\/)claude-fable(?:-|$)/.test(value.model)) return;
  return value as { model: string; effort?: string };
}

function profileEfforts(policy: unknown): Map<string, Set<string>> {
  const fixedEfforts = new Map<string, Set<string>>();
  for (const value of dispatchProfiles(policy)) {
    const profile = primaryProfile(value);
    if (profile?.effort === undefined) continue;
    const efforts = fixedEfforts.get(profile.model) ?? new Set<string>();
    efforts.add(profile.effort);
    fixedEfforts.set(profile.model, efforts);
  }
  return fixedEfforts;
}

export function dispatchModels(catalog: readonly DispatchCatalogEntry[], policy: unknown, purpose: DispatchPurpose = "general"): DispatchModel[] {
  const fixedEfforts = profileEfforts(policy);
  const choices = new Map<string, DispatchModel>();
  for (const entry of catalog) {
    const id = `${entry.provider}/${entry.id}`;
    if (!permitsPurpose(id, purpose)) continue;
    const fixed = fixedEfforts.get(id);
    const reasoning = entry.reasoning.filter((level) => (!fixed || fixed.has(level))
      && (!entry.id.startsWith("claude-opus-") || ["minimal", "low", "medium", "high"].includes(level))
      && (id !== "inception/mercury-3" || level === "high"));
    if (!reasoning.length) continue;
    const prior = choices.get(id);
    if (prior) {
      for (const level of reasoning) if (!prior.reasoning.includes(level)) prior.reasoning.push(level);
    } else choices.set(id, {
      id, provider: entry.provider === "inception" ? "inception" : "omp",
      model: entry.provider === "inception" ? entry.id : id, reasoning: [...new Set(reasoning)], apiKeyEnv: entry.apiKeyEnv,
    });
  }
  return [...choices.values()];
}

export function dispatchSelection(value: unknown, models: readonly DispatchModel[], purpose: DispatchPurpose = "general"): DispatchSelection | undefined {
  if (!record(value) || typeof value.model !== "string" || typeof value.reasoning !== "string" || !permitsPurpose(value.model, purpose)) return;
  const selected = models.find((model) => model.id === value.model && model.reasoning.includes(value.reasoning as string));
  if (!selected) return;
  return { provider: selected.provider, model: selected.model, reasoning: value.reasoning, apiKeyEnv: selected.apiKeyEnv };
}

type CatalogModel = { provider: string; id: string; api?: unknown; baseUrl?: unknown };
type ConfigurationTools = {
  custom: {
    buildCustomModelOverlay(...args: unknown[]): CatalogModel | undefined;
    finalizeCustomModel(model: CatalogModel, options: { useDefaults: boolean }): CatalogModel;
  };
  patches: {
    applyModelPatch(model: CatalogModel, patch: CatalogModel, transport: "replace"): CatalogModel;
    applyModelOverride(model: CatalogModel, override: Record<string, unknown>): CatalogModel;
  };
  validation: {
    validateProviderConfiguration(provider: string, config: Record<string, unknown>, mode: "models-config"): void;
  };
};

function credentialName(provider: string, sources: {
  environment: Record<string, string | undefined>;
  isFoundryEnabled(): boolean;
  getEnvApiKeyName(provider: string): string | undefined;
}): string | null {
  if (provider === "inception") return "INCEPTION_API_KEY";
  if (provider === "anthropic") return anthropicApiKeyEnv(sources.environment, sources.isFoundryEnabled());
  return sources.getEnvApiKeyName(provider) ?? null;
}

function applyProvider(models: CatalogModel[], provider: string, value: unknown, tools: ConfigurationTools): CatalogModel[] {
  if (!record(value)) throw new Error("Invalid host model provider");
  const definitions = value.models ?? [];
  if (!Array.isArray(definitions)) throw new Error("Invalid host model definitions");
  tools.validation.validateProviderConfiguration(provider, { ...value, models: definitions }, "models-config");
  for (const definition of definitions) {
    const overlay = tools.custom.buildCustomModelOverlay(provider, value.baseUrl, value.api, undefined, undefined,
      value.authHeader, value.compat, value.auth, value.remoteCompaction, definition);
    if (!overlay) throw new Error("Invalid custom dispatch model");
    const index = models.findIndex((model) => model.provider === provider && model.id === overlay.id);
    const model = index < 0 ? tools.custom.finalizeCustomModel(overlay, { useDefaults: true })
      : tools.patches.applyModelPatch({ ...models[index], api: overlay.api, baseUrl: overlay.baseUrl }, overlay, "replace");
    if (index < 0) models.push(model);
    else models[index] = model;
  }
  if (value.modelOverrides !== undefined) {
    if (!record(value.modelOverrides)) throw new Error("Invalid host model overrides");
    models = models.map((model) => model.provider === provider && record(value.modelOverrides)
      && record(value.modelOverrides[model.id]) ? tools.patches.applyModelOverride(model, value.modelOverrides[model.id]) : model);
  }
  return models;
}

function configuredCatalog(models: CatalogModel[], agentDir: string, tools: ConfigurationTools): CatalogModel[] {
  const path = ["models.yml", "models.yaml", "models.json"].map((name) => join(agentDir, name)).find(existsSync);
  if (path) {
    const source = readFileSync(path, "utf8");
    const config = path.endsWith(".json") ? JSONC.parse(source) : YAML.parse(source);
    if (!record(config) || !record(config.providers)) throw new Error("Invalid host model configuration");
    for (const [provider, value] of Object.entries(config.providers)) models = applyProvider(models, provider, value, tools);
  }
  return models;
}

export async function loadDispatchModels(home: string, agentDir: string, cwd = home, purpose: DispatchPurpose = "general"): Promise<DispatchModel[]> {
  const executable = Bun.which("omp");
  if (!executable) throw new Error("The installed omp catalog is unavailable");
  const base = dirname(realpathSync(executable));
  const load = (name: string) => import(pathToFileURL(Bun.resolveSync(name, base)).href);
  const [catalog, thinking, settingsApi, modelSettings, resolver, custom, patches, validation, credentials, runtimeEnvironment, foundry] = await Promise.all([
    load("@oh-my-pi/pi-catalog/models"), load("@oh-my-pi/pi-catalog/model-thinking"),
    load("@oh-my-pi/pi-coding-agent/config/settings"), load("@oh-my-pi/pi-coding-agent/config/model-settings"),
    load("@oh-my-pi/pi-coding-agent/config/model-resolver"), load("@oh-my-pi/pi-coding-agent/config/custom-models"),
    load("@oh-my-pi/pi-coding-agent/config/model-patch"), load("@oh-my-pi/pi-coding-agent/config/models-config"),
    load("@oh-my-pi/pi-ai/env-api-key"),
    load("@oh-my-pi/pi-utils"), load("@oh-my-pi/pi-ai/utils/foundry"),
  ]);
  const credentialSources = {
    environment: runtimeEnvironment.$env,
    isFoundryEnabled: foundry.isFoundryEnabled,
    getEnvApiKeyName: credentials.getEnvApiKeyName,
  };
  const settings = await settingsApi.Settings.loadReadOnly({ agentDir, cwd });
  const models = configuredCatalog(catalog.getBundledProviders().flatMap((provider: string) => catalog.getBundledModels(provider)),
    agentDir, { custom, patches, validation });
  const disabled = new Set(modelSettings.cfgDisabledProviders.get(settings));
  const enabled = resolver.filterAvailableModelsByEnabledPatterns(models, modelSettings.cfgEnabledModels.get(settings), settings);
  const entries = enabled.filter((model: { provider: string }) => !disabled.has(model.provider)).map((model: { provider: string; id: string }) => ({
    provider: model.provider, id: model.id, reasoning: thinking.getSupportedEfforts(model),
    apiKeyEnv: credentialName(model.provider, credentialSources),
  }));
  return dispatchModels(entries, JSON.parse(readFileSync(join(home, "config", "crew-dispatch.json"), "utf8")), purpose);
}

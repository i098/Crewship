import { type Secondmate, supervisorOnly } from "./desk.ts";

export type RelayRequest = Readonly<{
  requestId: string;
  text: string;
  authored?: string;
  mateEligible?: boolean;
  firstmate: boolean;
  mutationPath?: string;
}>;

export function relayTarget(requests: readonly RelayRequest[], metadata: unknown, mates: Secondmate[]): Secondmate | undefined {
  if (!requests.length || requests.some((request) => request.firstmate || !request.mateEligible || request.mutationPath
    || supervisorOnly(request.authored ?? request.text))) return;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return;
  const value = metadata as Record<string, unknown>;
  if (value.category !== "work" || typeof value.target !== "string" || !Array.isArray(value.domains)
    || value.domains.length !== 1 || value.domains[0] !== value.target) return;
  return mates.find((mate) => mate.id === value.target);
}

export function relayTargetCurrent(mate: Secondmate, mates: readonly Secondmate[]): boolean {
  return mates.some((entry) => entry.id === mate.id && entry.home === mate.home && entry.scope === mate.scope);
}

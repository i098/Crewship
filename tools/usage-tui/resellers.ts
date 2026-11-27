// Reseller plan-quota sources for usage-tui. One entry here is the whole cost of a new reseller:
// quota.ts and detect.ts read every entry through the same code, with no per-reseller branch.
// A reseller answers one api-anything operation with a list of plans; each plan holds named credit windows.

export type ResellerConfig = {
  id: string // QuotaSource value for the provider list, and the key of QuotaInput.resellers
  providerId: string // omp auth provider id the detected provider is filed under
  label: string // provider label; also the prefix of each plan row ("deepseek max")
  account: string // row name for a note that covers the whole source ("deepseek (reseller)")
  noPlansAccount: string // row name when the account is signed in with no plan
  planWords: string[] // words every plan name shares; dropped from the row name
  site: string // api-anything site; its cookies in the fleet jar mark the reseller as present
  operation: string // api-anything operation that returns the plan list
  clerk: { host: string; apiVersion: string } // the site's sign-in service, used to renew the 60 s session
  windows: [key: string, label: string][] // quota.<key> -> row window label
  fields: { // names in the operation's answer
    plan: string
    planStatus: string
    planStatusOk: string
    quota: string
    quotaStatus: string
    quotaStatusOk: string
    used: string
    limit: string
    resetAt: string // ISO time
  }
}

export const RESELLERS: ResellerConfig[] = [
  {
    id: "deepseek",
    providerId: "deepseek",
    label: "deepseek",
    account: "deepseek (reseller)",
    noPlansAccount: "deepseek plans",
    planWords: ["deepseek", "coding", "plan"],
    site: "deepseekv4pro.com",
    operation: "quotaMe",
    clerk: { host: "clerk.deepseekv4pro.com", apiVersion: "2026-08-20" },
    windows: [["fiveHour", "5h"], ["sevenDay", "7d"]],
    fields: { plan: "planName", planStatus: "quotaStatus", planStatusOk: "available", quota: "quota", quotaStatus: "status", quotaStatusOk: "active", used: "usedCredits", limit: "limitCredits", resetAt: "resetAt" },
  },
]

// True for the site's own domain and its subdomains, as a cookie `domain` value.
export const onSite = (cfg: ResellerConfig, domain: unknown) =>
  new RegExp(`^\\.?([a-z0-9-]+\\.)*${cfg.site.replace(/\./g, "\\.")}$`).test(String(domain ?? ""))

---
name: open-seo
description: Use when building, launching, redesigning or auditing a website, or when the operator asks for an SEO audit, SEO fixes or keyword research. Run the OpenSEO site audit and give a short report of findings with fixes.
---

# SEO for websites with OpenSEO

OpenSEO (https://openseo.so, MIT) gives an agent real SEO data: site audit, keyword research, competitor and backlink research, rank tracking. It is an official plugin of 12 skills plus a hosted MCP server. This skill is the pointer: it says when to use OpenSEO and how to run the audit. Do not copy, fork or rebuild its skills.

## When to use it

- Building a website: before launch, audit the staging or live URL. Fix title, meta description, canonical, headings, status codes, redirects, sitemap, `robots.txt` and internal links in the code.
- Launching or redesigning: audit the old site first, so the new one keeps what ranks.
- Any request for an SEO check: audit first, then fix.

Do not use it for page speed alone or for accessibility; use the browser tools for those.

## Install

Docs: https://openseo.so/docs/claude-code-plugin and https://openseo.so/docs/skills/setup. Install as published, per agent:

- omp: `omp plugin marketplace add every-app/open-seo && omp plugin install openseo@openseo`
- Claude Code: `npx skills add every-app/open-seo --skill '*' --agent claude-code -g -y` (the skills), then `claude mcp add --transport http --scope user openseo https://app.openseo.so/mcp --header "Authorization: Bearer $OPENSEO_API_KEY"` (the MCP server). Where `claude` is not installed, the skills alone are present.

The install runs no hooks and no scripts. The plugin is markdown plus a `.mcp.json` that points to `https://app.openseo.so/mcp`. Skills write nothing on the host; they save reports and project context to the OpenSEO account.

## Key

The audit runs on the hosted MCP server, so it needs an OpenSEO account. Sign in once (OAuth), or for a headless agent create an API key (`oseo_...`) in https://app.openseo.so/settings and keep it in the host secret store as `OPENSEO_API_KEY`. Never print it and never write it into a repository.

The account has a free trial of $0.50 of credits, then $10 a month (https://openseo.so/pricing). Keyword, SERP and backlink calls and Lighthouse use credits. Do not subscribe and do not add a card. If the account or the key is missing, say so and stop; do not guess an audit from memory.

Self-hosting is free of subscription but needs a paid DataForSEO key. Do not set it up unless the operator asks.

## Run an audit

1. Check the MCP server is connected. In the agent, call the `whoami` tool. On a 401, the key or sign-in is missing.
2. Run the `/seo-audit` skill for the domain. It starts `run_site_audit` (leave Lighthouse off), polls `get_audit_status`, reads `get_audit_issues` and `get_audit_pages`, and checks live rankings.
3. For a short fix list without research, ask only for the crawl issues and pages.
4. Never change the audited site because of the audit alone. Fix the code only when the task is to build or fix that site.

## Output

The `seo-audit` skill delivers an HTML report through `seo-report`, saved on the OpenSEO project (private until the operator asks to publish it). It has: the next SEO move, one to three data-backed recommendations with the pages and the change to make, a table of what else it checked, and an evidence appendix.

For chat, give the operator a short markdown report: the top findings by impact and one concrete fix for each. Save it where the task says.

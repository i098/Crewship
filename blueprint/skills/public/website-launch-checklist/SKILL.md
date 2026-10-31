---
name: website-launch-checklist
description: 'Use before launching a website or reviewing a page for launch; not for production infrastructure readiness or general SEO strategy.'
---

# Website launch checklist

Source: [Instagram reel](https://www.instagram.com/reel/DcWbryWNs0q/).

Run all 20 checks against the launch candidate.
For each item, record `pass`, `fail`, or `not applicable`, with evidence.
Mark an item `fail` when evidence is missing or the check is not run.
Use `not applicable` only when the item does not apply, and record why.

1. Privacy policy: Verify that a privacy policy page is available.
2. Terms page: Verify that a terms page is available.
3. Clear CTA: Verify that the page has a clear call to action.
4. FAQ: Verify that the page has an FAQ when needed; otherwise record why it is not needed.
5. `robots.txt`: Request `/robots.txt` and inspect its contents.
6. `sitemap.xml`: Request `/sitemap.xml` and inspect its contents.
7. Custom 404 page: Request a nonexistent URL and inspect the response page.
8. Image alt text: Inspect image markup for suitable alt text.
9. Analytics: Verify analytics configuration and confirm a test visit appears in its report.
10. Meta titles: Inspect page source for a suitable title on each page.
11. Meta descriptions: Inspect page source for a suitable description on each page.
12. Social share previews: Inspect the social sharing metadata and preview for a page.
13. Favicon: Request the configured favicon and confirm it loads.
14. Canonical URLs: Inspect page source for the intended canonical URL.
15. Cookie consent: Verify consent behavior when required; otherwise record why it is not needed.
16. Mobile behavior: Inspect key pages and interactions at mobile viewport sizes.
17. Basic accessibility: Check key pages with keyboard navigation and an accessibility checker.
18. Forms: Submit each form with valid and invalid test data and inspect its results.
19. Broken links: Crawl internal and external links and inspect failures.
20. Performance: Measure page load performance with a browser performance tool.

Return a table with all 20 items in order.
Use `pass`, `fail`, or `not applicable`; include evidence or the reason in each row.

| Item | Verdict | Evidence |
| --- | --- | --- |

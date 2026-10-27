---
name: repo-readme
description: Use when writing, polishing or launching a repository README, including one like similar repos. Gives section order, rules, and a polish checklist.
---

# Write a README that sells and explains

A README answers three questions in order: what is this, does it work, how do I start. Use `README.template.md` beside this file as the starting point. Replace every `{{placeholder}}`. Delete a section only when it has no content for this repository.

## Study peers first

Find 3-5 popular OSS repositories for the same kind of product. Use `gh api search/repositories` or the project's topics, and prefer repositories with many stars and recent activity.
Read their READMEs and compare repo, section order, hero, badges, screenshot, and quick start length in a small table.
Keep the sections most peers share and take the best idea from each. Then apply the GitHub README practices below.
Keep the README short: link to docs instead of copying them.

## Sections, in this order

1. **Hero.** A centered block: title with one emoji, a one-line pitch, `for-the-badge` badges, and a nav row. Use CI, Release, License, Stars, and Sponsor when the repository has a sponsor page. Do not use Last commit or Updated badges. Nav: Try it or Install, Docs, Changelog, Contribute.
2. **Screenshot.** One real screenshot of the live product at desktop size, with real data and an italic caption. Commit an optimized PNG under 300 KB (for example `docs/images/<name>.png`). Never use a mock-up.
3. **Features.** A bullet list in the present tense. Each line: a bold name that links to its doc, then one short sentence. Say what the product does now. Never write "will" or "in progress".
4. **Quick start.** Numbered steps that a reader can copy and paste. Give the shortest path first (try it hosted), then self-hosting.
5. **How it works.** One diagram with a light and a dark variant (`<picture>`), and alt text that says the flow in words. Link the architecture doc.
6. **Repository layout.** One bullet per top-level folder, each linked, with one line of purpose.
7. **License.** The license name, a link to the file, and one plain-words line. Use the exact name of the license. Do not call a source-available license "open source".

Put the key search terms (what the product is, who it is for, the main nouns) in the first paragraph. Keep the whole README short: link to docs instead of copying them.

## Polish checklist

Do the README first, then the repository around it. See `checklist.md` for the full list.

- **Community files:** LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, SUPPORT, CHANGELOG.
- **Templates:** issue forms for a bug and a feature, and a pull request template.
- **Topics and SEO:** the repository description, 5 to 10 topics, the homepage URL.
- **Social preview:** a 1280x640 image made from the hero and the screenshot. Put no subtitle text on it.

## Verify before you ship

Render the README the way GitHub does (`gh api -X POST markdown -f mode=gfm -f context=<owner>/<repo> -f text=@README.md`), look at it at 1280 px wide in light and dark, and open every link.

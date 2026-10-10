# harbor

`harbor/` is the website for [crewship.si](https://crewship.si): a full-screen, first-person walk around the ship, dock, island, and house, drawn as text.
Each object shows an ASCII sign anchored to its surface.
The sign uses the scene's character grid, font and colors, with clickable links.
Selecting a destination on the ASCII mini map walks you there around obstacles; with reduced motion, you jump there instead.
See [how.html](public/how.html) for the renderer and controls.
The off-screen HTML list and current sign keep links available to screen readers and keyboard users.
An uncaught error or rejected promise in `harbor.js`, or a failure to load it, hides the scene and shows the plain page.
Errors and rejected promises from other scripts or resources, such as browser add-ons, do not.
JavaScript hides the plain page before the first paint; visitors without JavaScript still see it.
The scene starts with a 1.2-second glyph-noise sweep that fades in from black without moving the camera or resizing the grid.
Any key, click, touch, or mouse wheel input skips the animation.
Reduced-motion visitors get the scene immediately.
Waves, the fountain, and boats keep moving during the intro.
See [how.html](public/how.html) for the canvas limits and intro rendering details.

The island has staggered plaza paving, scattered stones and grass tufts, varied tree canopies, textured bark, and foam along the shore.

Walk into the framed house door to enter a warm room with a lamp, table, bed, and a starry night window.
The blue bed faces the door; darker walls and floor keep the furniture, lamp, and window clear.
Walk back through the inside door to return just outside, facing the island.
Keyboard and touch movement share the door transition; walls and furniture block walking, and the map stays hidden inside.
Release the movement keys and touch pad after a door crossing to move again.
See [the frame loop](public/how.html#frame-loop) for adaptive detail and display timing.

The pirate ship has a 28 m tapered hull, a raised stern castle, and two square-rigged masts.
Its gun ports, railings, figurehead, and warm lanterns follow the hull and deck.
Walking bounds and the map use the hull's tapered stations; the gangway joins the deck to the dock.
Steps connect the main deck to the stern castle's roof.
Map walks connect the dock through the gangway and reach the stern roof through the supported stairs.
Ship approaches avoid deck obstacles and reject unsupported floors or height changes larger than the manual walking limit.
The sails keep a pale canvas tone at night.
Outboard lanterns make the gun ports visible.

The plaza fountain has an octagonal stone rim, a central spout, and water that uses the existing animation clock.
Its basin blocks walking, and a blue `O` marks it on the mini map.
The fountain marker leaves map labels and selected point markers clear.
Map walks check each road and approach segment against the walking collision bounds at the local floor height and require continuous ground coverage.
Detour corners come from every walking obstacle, including trees, hedges, the basin, the house, dock cargo, and ship fixtures.
The page builds the corner graph once before animation starts.
Ship bob and roll do not rebuild the graph during a map click.
If no free viewing spot exists, the map selection stops without moving the player.
Without reduced motion, a missing clear route also stops the map walk without moving the player.

The page uses plain HTML, CSS and JavaScript in `public/`, with no runtime dependencies.
Nothing here reaches a Crewship host or worker image: `.dockerignore` excludes `harbor/`, and the playbook never copies it.
`tests/test_harbor_isolation.py` checks both.

## Content from the repository

`build.py` (Python standard library) copies `public/` to `dist/` and fills the points of interest from the README's Features list and More docs row.
It also adds the quick start, the repository, the latest release from `CHANGELOG.md`, and how.html.
A link with an object in the scene (mapped in `build.py`'s `SCENE`) opens on that object.
A link with no mapping prints a warning but never blocks the build.
The docs board shows on the mini map like the other points.
Add an object and a `SCENE` entry to give the link its own place.
The build limits each sign to a title, a short description and one link.
Unmapped pages share a short summary with a count and one link to the README feature index.
The welcome sign has three project links.
Signs first reflow below or beside the map, clear of the move pad and safe-area edges.
If space is limited, signs remove spacing and shorten the visible copy.
If no clear rectangle fits, compact signs can cover the map but keep their links clear of the move pad.
Signs remain within the safe area.
Touch links share one row when they fit; otherwise, each link has its own row.
Inline touch links keep hit regions at least 44 CSS pixels tall without increasing the frame height.
Stacked links have one blank link row between them and separate hit regions at least 24 CSS pixels tall.
Each stacked link row is at least 12 CSS pixels tall.
The invisible hit padding can extend beyond the sign frame, but stays clear of the move pad.
Touch frames fit the text, with one blank row before the links.
Desktop signs keep their original layout.
Click or tap a sign link to open it.
Focus a feature-list link to show its sign.
The sign highlights the focused link without scrolling the scene.
Link focus closes the map and cancels pending automatic walking.
See [how.html](public/how.html) for the movement and Enter controls.

## Preview

```bash
python3 harbor/build.py
python3 -m http.server --directory harbor/dist 8000
```

Then open <http://localhost:8000>.

## Link preview

`index.html` sets the Open Graph and Twitter card tags, with absolute https://crewship.si URLs.
The preview image `public/og.png` (1200x630) is committed, so the build and the deploy need no browser.
`og-image.mjs` draws it with the real renderer from a fixed camera, without the sign or the mini map, and sets the title and the tagline over the scene.
It also draws `public/apple-touch-icon.png` (180x180) from `public/favicon.svg`.
After a scene, preview layout, metadata tagline, or favicon change, regenerate both PNGs in the Playwright container and commit them:

```bash
python3 harbor/build.py
npm install --no-save --no-package-lock --prefix harbor playwright@1.64.0
docker run --rm --ipc=host --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/harbor:/harbor" -w /harbor \
  mcr.microsoft.com/playwright:v1.64.0-noble node og-image.mjs
```

The Playwright package version must match the container version.
Rebuild `dist/` after regeneration to preview or deploy the new images.
`tests/test_harbor_build.py` checks the tags, the URLs, and the image sizes.

## Browser checks

The check loads the built page in Playwright WebKit at desktop and iPhone portrait and landscape sizes.
The check fails on a crash, an uncaught error, a console error, a fallback to the plain page, or a multi-glyph `fillText` call on touch.
The check also fails if the first 30 slow exterior frames change the grid, cell size, field of view, or canvas layout.
The check walks through the house door and back with the touch pad.
It also checks that the first intro frame is black and that the scene keeps moving during the intro.
Inside the house, it checks that manifest focus keeps the player in place and draws a sign with hit-testable links.
It checks every sign against safe-area edges and checks map and move pad clearance before the final overlay placement.
It includes 320×568 phones in both orientations and landscape heights of 256 and 192 pixels.
It checks measured safe insets, visible signs, link hit regions, and keyboard focus without stage scrolling.
On iPhone 15 Pro, it limits the welcome sign to six scene rows, including the frame, and checks the canvas DPR limit.
It also taps six pixels above and below each stacked link center to check the separate hit regions.
It also checks feature-link focus with the full map open and an arrival selection pending.
It fails if rendering stalls.
It taps or clicks every link and opens the docs index with the keyboard.
See [how.html](public/how.html) for the rendering limits on touch devices.

CI also loads the page in Playwright Chromium in a 3651x2160 window at DPR 2, with `chromium-check.mjs`.
It adds a failing image and a rejected promise, as a browser add-on can.
It fails on the plain-page fallback, a black canvas 3 s after load, or a console error.
It also fails if the backing-store area exceeds the [canvas limit](public/how.html).
To run the checks locally:

```bash
python3 harbor/build.py
cd harbor
npm install --no-save --no-package-lock --prefix . playwright
npx playwright install --with-deps webkit chromium
node webkit-check.mjs
node chromium-check.mjs
```

## Deploy

Cloudflare Workers serves `dist/` as static assets; `wrangler.jsonc` is the configuration. The [harbor workflow](../.github/workflows/harbor.yml) builds and deploys on every push to `main`, on each published release, and on a manual run. Each run is a GitHub deployment in the `crewship.si` environment, which accepts only `main` and `v*` tags and holds the deploy token as its `CLOUDFLARE_API_TOKEN` secret and the account id as its `CLOUDFLARE_ACCOUNT_ID` variable.

To deploy by hand with a token that can edit the `crewship` Worker:

```bash
python3 harbor/build.py
cd harbor
CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... npx wrangler@latest deploy
```

The site serves on https://crewship.si, a custom domain attached to the Worker outside `wrangler.jsonc`, and each deploy records that URL under Deployments.

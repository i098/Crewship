# Generative UI: card views

`apps/genui-web/src/views/` draws one card from the spec. It ports the card part of the approved design (`docs/genui/design/index.html`): the chrome, the Geist Mono font, every card kind and the build-in motion. `src/cards.css` holds the styles. `public/fonts/geist-mono.woff2` holds the font.

## API (`src/views/index.ts`)

| Export | What it does |
|---|---|
| `renderCard(spec, component, widthTier)` | Returns the inner HTML of a tile: `.core` (the view), `.tgrip` (resize corner), `.ago` (live stamp) and `.tools` (pin, link). `widthTier` is `"narrow"` (tile up to 500 px), `"wide"` or `"full"` (full view). Wider tiers show more detail. |
| `mountCard(el, html, booted)` | Paints `html` into a tile element and adds the `tile` class. After boot, a new card shows a dithered skeleton, opens out and decodes its text from glyphs. A changed card morphs in place. The world you open with is drawn at once. |
| `tickStamps(root)` | Updates every live stamp ("now", "7s ago"). Call it once a second. |
| `dropCard(el)` | Shrinks, blurs and fades a removed card, then removes it. |
| `bindCards(root, repaint)` | Runs the draw-only events: hovering a decision option previews its outcome on other cards, and media report their shape for the Auto ratio. |
| `morph`, `reveal` | The motion primitives, for the full view. |

Buttons carry `data-act` and `data-id`, and `data-k` when there is a choice: `full`, `drop`, `pin`, `link`, `resize` (grip), `pick` (decision option), `merge` (`ai`, `theirs`, `mine`), `act` (compare actions), `ar` (ratio preset) and `send` (the plan form). The canvas turns them into intents.

## Card kinds

`props.kind` picks the view. A component with no known kind gets a plain note: `title`, `body` and `items`. Every string is escaped. A colour must be plain `hsl(...)` or it is replaced. Media load only from http(s), blob or same-origin paths, and sites run in a sandboxed iframe.

| Kind | Props |
|---|---|
| `decision` | `q` (short: who and the ask), `why` (one line on why it matters now), `body` (the detail), `url` (drawn as a link icon), `opts [{ k, b, rec, preview }]`, `free` (an answer box for free text), `pick`, `done`. `preview` is `{ [cardId]: props }`: hovering the option shows those props on those cards. With no options it draws no fork. |
| `conflict` | `title`, `doneTitle`, `files[]`, `branch`, `done` |
| `pipeline` | `title`, `stages[]`, `at`, `kpi { value, unit }`, `done` |
| `timeline` | `subject`, `ship`, `days[]`, `rows [{ name, hsl, from, len }]` (days from `days[0]`), `now`, `shipAt`, `shipRow` |
| `crew` | `title`, `body`, `members [{ name, hsl, doing }]` |
| `shipped` | `total`, `bars[]` (PRs per day, oldest first) |
| `plan` | `title`, `kpi`, `fields [{ name, label, opts [[value, label]] }]`, `done` |
| `embed` | `type` (`site`, `board`, `pdf`, `image`, `diagram`, `video`, `audio`, `text`, `file`), `title`, `src`, `nat` (`"W/H"`), `ar`, `text`, `size` |
| `incident` | `title`, `doneTitle`, `claim`, `att` (1-3), `fix { from, to }`, `done` |
| `compare` | `a`, `b`, `subject`, `metrics [[label, a, b]]`, `verdict`, `acts [{ k, b, pri }]` |
| `ask` | `q`, `about[]`, `ready` |
| `sys` | `series { cpu, mem, disk, net: number[] }` (0-100) |
| `tui` | `agent`, `lines[]` |

Every kind also reads `need`, `pinned` (shows the project pill from `spec.projects`) and `kpi` where the design shows a big number.

## Chrome

Cards have no border, a 22 px radius and a solid fill that lightens on hover. A thin light runs round the edge on hover. The title (20 px) shares the top row with the flag, the KPI and the bare ⤢ and ✕ glyphs. On a narrow card (500 px or less) the header takes the top row alone and the title uses the full width under it. The live stamp sits bottom left, and the L-shaped resize corner bottom right. Pin and link sit beside it and show on hover; a pinned card always shows its pin.

## Fit

Text never runs out of its card. A title shows two lines at most and a `body` four, with an ellipsis; the full view shows all of it. Long words and URLs break anywhere. After each layout, and once a second, `fitCards` (`src/fit.ts`) checks every card:

1. It measures the title with [pretext](https://github.com/chenglou/pretext) and steps its size down (20, 18, 16, 14 px) until it fits two lines.
2. It finds each element wider than its box (`scrollWidth > clientWidth + 1`) or outside the card's rect, and lets that text wrap anywhere (`.ovf`).
3. It cuts what still runs out with an ellipsis (`.cut`) and logs the card ids as `card fit:` warnings.

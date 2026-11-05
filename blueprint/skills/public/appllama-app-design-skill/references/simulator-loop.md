# The device loop — verification checklist & device matrix

A screen is finished when it survives this checklist on a real device in vphone-linux, not
when the code compiles. Budget as many loop iterations as it takes; the goal
is "cannot find a flaw", not "looks fine".

## Loop mechanics

1. Launch on vphone-linux (primary), the virtual iPhone on the host from the
   `vphone` profile. Boot it with `tools/boot-test.sh` or `setup/start-vm.sh`
   from `~/.local/share/crewship/vphone-linux`, then install your dev build
   with `tools/install-ipa.py APP.ipa --launch BUNDLE_ID`. Android emulator
   second.
2. Screenshot the screen with `tools/qmp.py SOCK shot s.png` (SOCK is the
   QMP socket in `runs/RUN/qmp.sock`; see the vphone-linux `docs/TOOLS.md`).
   **Open the screenshot and study it** — do not trust memory of what you
   wrote.
3. Interact: tap (`tools/qmp.py SOCK tap X Y`) and swipe every control, type
   overlong text, background/foreground the app, rotate if supported.
4. For motion: film the ENTIRE flow, not just the hero transition. Run
   `tools/swipe-film.py SOCK OUTDIR X0 Y0 X1 Y1` for a gesture, or take
   `tools/qmp.py SOCK shot` frames while you drive the flow. Scrub the frames
   one by one. Stills cannot catch a one-frame flash, a dropped spring, or a
   keyboard jump-cut; only dense frames can.
5. Fix → relaunch → re-verify. Never batch more than a few fixes between
   looks; regressions hide in batches.

If a UI-testing tool (e.g. Maestro) is available, script the flow's happy
path once it stabilizes — taps, assertions, screenshots — so later changes
re-verify for free.

## Per-screen checklist

**Layout**
- [ ] Nothing clipped by the Dynamic Island / status bar; scrolled content
      passes *under* it with the intended fade/blur, not a hard edge
- [ ] Bottom CTA clears the home indicator (safe-area inset respected)
- [ ] Optical alignment: icons vs text baselines, centered things actually
      look centered (check at 2× zoom)
- [ ] Spacing rhythm consistent (no rogue 13px gaps in an 8pt system)
- [ ] Long text: 2× length titles truncate/wrap by design, not by accident
- [ ] Empty state, loading state, error state each verified by forcing them

**Theming & type**
- [ ] Dark mode AND light mode screenshots taken and inspected
- [ ] Dynamic Type at XL: no overlap, no clipped labels
- [ ] Contrast: secondary text still readable in both themes

**Motion (evaluated on the full-flow recording, never on stills)**
- [ ] Entrance plays once, correctly, on first mount (and NOT again on
      back-navigation)
- [ ] Gesture follows the finger 1:1; release springs with velocity;
      cancelling mid-gesture settles cleanly
- [ ] Frame-by-frame: no pop at animation start/end, no double-render flash,
      no one-frame white/wrong-theme/wrong-color frames during transitions
- [ ] Every modal/sheet cycle recorded: present, drag, dismiss, cancel —
      smooth in both directions
- [ ] Keyboard appear AND dismiss recorded: layout glides with it, focused
      input stays visible, nothing jump-cuts or reflows after settling
- [ ] Sustained 60 fps through every transition of the flow (measure with
      the perf monitor / Instruments, don't eyeball)
- [ ] Reduce Motion enabled → spatial animations become fades

**Interaction**
- [ ] Every tappable ≥ 44pt; press states visible; haptics where native
      controls would have them
- [ ] Keyboard: appears with the right type, doesn't cover the focused input,
      dismisses sensibly
- [ ] Back gesture (iOS edge swipe) works everywhere it should
- [ ] Rapid double-taps don't double-navigate or double-submit

**State**
- [ ] Background the app mid-flow → return: state intact
- [ ] Kill and relaunch: persisted state restores, ephemeral state resets
- [ ] Offline: actions queue or fail loudly — never silently

## Device matrix (minimum)

| Profile | Why |
|---|---|
| Latest iPhone Pro (Dynamic Island) | Primary design target |
| iPhone SE-class (small, no island) | Layout compression + button reachability |
| Latest Pixel (Android) | Material behaviors, back gesture, font metrics |
| One tablet/iPad IF the app claims support | Otherwise explicitly letterbox |

Run the full checklist on the primary; on the others, verify layout,
safe areas, and the hero flow.

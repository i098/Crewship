---
name: board-phone-fit
description: "Check that a Lavish, diagram or PR-preview board fits a phone before you open or send it"
condition: ["lavish-axi\\s+(?:open\\s+)?[^\\s|;&]+\\.html?\\b"]
scope: "tool:bash"
---
## Fit the board to a phone before you send it

The reader often opens a board link on a phone, 390 px wide.

1. Paste the output of `board-phone-fit --css` at the end of the board's `<style>`.
   Give the board `<meta name="viewport" content="width=device-width, initial-scale=1">`.
2. Run `board-phone-fit <board.html>`. It renders the board at 390x844 in headless Chrome.
3. Fix each failure it prints, then run it again until it prints `fits 390x844`.
   - `overflow`: the element named is wider than the phone. Let it wrap or stack its columns.
     For a wide diagram (`diagram-design` and others), make it fit the phone width: use a narrower `viewBox` or stack its parts. Do not shrink its text under 14 px.
   - `text`: the element named shows text under 14 px. Make it 14 px or larger.
4. Send the link only after the check passes.

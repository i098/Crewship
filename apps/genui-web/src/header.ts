export type HeaderState = { title: unknown; wins: "agent" | "user"; live: boolean; seq: number; busy: boolean; notice?: string };

/** Header nodes. Every dynamic value goes in through textContent or setAttribute, never as markup. */
export function buildHeader(doc: Document, o: HeaderState): Node[] {
  const el = (tag: string, cls?: string, text?: string) => {
    const n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const orb = el("i", `orb${o.busy ? " busy" : ""}`);
  const h1 = el("h1", "line", String(o.title ?? ""));
  const st = el("span", `st${o.live ? " on" : ""}`);
  st.setAttribute("role", "status");
  if (o.live) st.append("live · seq ", el("b", "num", String(o.seq)));
  else st.append("reconnecting");
  if (o.notice) st.append(` · ${o.notice}`);
  const seg = el("div", "seg");
  seg.setAttribute("role", "group");
  seg.setAttribute("aria-label", "When you and the agent both move a card");
  for (const w of ["agent", "user"] as const) {
    const b = el("button", undefined, `${w} wins`);
    b.setAttribute("type", "button");
    b.dataset.wins = w;
    b.setAttribute("aria-pressed", String(o.wins === w));
    seg.append(b);
  }
  return [orb, h1, st, seg];
}

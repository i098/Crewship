// Mermaid text to an SVG picture, drawn by the local `ondine` renderer: no network, no browser.
// The board shows it as an image from a data URL, so the picture can never run a script.
const DARK = [[/(--ondine-bg,)#fff/, "$1#10101a"], [/(--ondine-fg,)#000/, "$1#e8e8f2"]] as const;

/** The SVG of a Mermaid source as a data URL; throws with the renderer's own message when the source does not parse. */
export async function mermaidSrc(source: string): Promise<string> {
  const p = Bun.spawn(["ondine"], { stdin: new Blob([source.slice(0, 4000)]), stdout: "pipe", stderr: "pipe" });
  const timer = setTimeout(() => p.kill(), 15_000);
  try {
    const [out, err, code] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text(), p.exited]);
    if (code !== 0 || !out.includes("<svg")) throw new Error((err || out).trim().split("\n")[0].slice(0, 200) || `ondine exited ${code}`);
    const svg = DARK.reduce((s, [re, to]) => s.replace(re, to), out);
    return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
  } finally {
    clearTimeout(timer);
  }
}

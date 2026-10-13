// Spring and beat sample: a card springs in on every beat of a fixed BPM, and the colour cuts on beat 4.
// Every move is spring(), a closed-form damped spring, never CSS easing. Cut frame = round(beat * 60 / BPM * fps).
import React from "react";
import { AbsoluteFill, Composition, registerRoot, spring, useCurrentFrame, useVideoConfig } from "remotion";

const BPM = 120;
const beatFrame = (beat: number, fps: number) => Math.round((beat * 60) / BPM * fps);

const Scene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const beat = Math.max(0, Math.floor((frame / fps) * (BPM / 60) + 1e-9)); // beat number now
  const since = frame - beatFrame(beat, fps); // frames since the last beat
  const pop = spring({ frame: since, fps, config: { damping: 8, stiffness: 180 } }); // overshoots, settles
  const cut = frame >= beatFrame(4, fps); // the cut sits on a beat frame
  return (
    <AbsoluteFill style={{ background: cut ? "#f5d76e" : "#0e1830", justifyContent: "center", alignItems: "center" }}>
      <div style={{ width: 300, height: 300, borderRadius: 40, background: cut ? "#0e1830" : "#8fa3d0", transform: `scale(${0.6 + 0.4 * pop}) rotate(${(beat % 2 ? 1 : -1) * 12 * (1 - pop)}deg)` }} />
    </AbsoluteFill>
  );
};

registerRoot(() => (
  <Composition id="Scene" component={Scene} durationInFrames={120} fps={30} width={1280} height={720} />
));

// Three.js scene, frame-exact through Remotion: a rotating moon and a passing eclipse disc at night.
// Self-contained: render.py copies it into the install and renders composition "Scene".
import React from "react";
import { AbsoluteFill, Composition, registerRoot, useCurrentFrame, useVideoConfig } from "remotion";
import { ThreeCanvas } from "@remotion/three";

const Moon: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = frame / durationInFrames; // 0..1; every motion is a function of the frame
  return (
    <>
      <ambientLight intensity={0.12} />
      <directionalLight position={[4, 2, 5]} intensity={2.2} color="#dfe8ff" />
      <mesh rotation={[0.25, t * Math.PI * 2, 0]}>
        <sphereGeometry args={[1.5, 96, 96]} />
        <meshStandardMaterial color="#c9cdd6" roughness={1} flatShading />
      </mesh>
      {/* the eclipse: a dark disc in front of the moon, sliding across */}
      <mesh position={[(t - 0.5) * 6, 0.1, 2.2]}>
        <circleGeometry args={[0.98, 64]} />
        <meshBasicMaterial color="#05070f" />
      </mesh>
    </>
  );
};

const Scene: React.FC = () => {
  const { width, height } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: "radial-gradient(circle at 50% 40%, #0e1830, #05070f 70%)" }}>
      <ThreeCanvas width={width} height={height} camera={{ position: [0, 0, 6], fov: 40 }}>
        <Moon />
      </ThreeCanvas>
      <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 70 }}>
        <div style={{ fontFamily: "monospace", color: "#8fa3d0", fontSize: 34, letterSpacing: 6 }}>CREWSHIP</div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

registerRoot(() => (
  <Composition id="Scene" component={Scene} durationInFrames={120} fps={30} width={1280} height={720} />
));

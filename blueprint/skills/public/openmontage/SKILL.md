---
name: openmontage
description: Use when the operator asks for a video, a reel, an explainer clip or a short animated piece. Make it with OpenMontage, the agentic video production system, and send the result.
---

# Make a video with OpenMontage

OpenMontage (https://openmontage.video) turns a plain request into a finished video: research, script, assets, narration, captions and a Remotion or HyperFrames render. For a math or algorithm animation, use the `manim` skill. For a still chart, do not make a video.

## Install

Follow the README on https://openmontage.video exactly. Do not fork or rebuild it. It needs Python 3.10+, Node.js 18+ and `ffmpeg`.

`gh repo clone calesthio/OpenMontage ~/.local/share/openmontage && cd ~/.local/share/openmontage && make setup`

Keep it outside any worktree. `render.py` reads `OPENMONTAGE_DIR` when it lives elsewhere. Check the install with `make demo-list` in that directory.

## Keys

Every key is optional. With none, you get Piper narration, free open footage, Remotion, HyperFrames and FFmpeg. OpenMontage reads keys from `.env` in its own directory. Copy each one there by name from the operator's secret store; never print a value and never write one into a repository.

It reads these names: `FAL_KEY`, `ATLASCLOUD_API_KEY`, `KLING_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `UNSPLASH_ACCESS_KEY`, `SUNO_API_KEY`, `ELEVENLABS_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `GOOGLE_API_KEY`, `ARK_API_KEY`, `HEYGEN_API_KEY`, `RUNWAY_API_KEY`. The full list with prices is in `docs/PROVIDERS.md` of the install.

Do not sign up for a service or buy credits. If a request needs a missing key, say which key and what it unlocks (`FAL_KEY` AI images and video clips, `ELEVENLABS_API_KEY` premium voice, `PEXELS_API_KEY` stock footage), and offer the zero-key path.

## Make the video

For an open-ended request ("a 30 s explainer about X"), open the install directory in your session and follow its `AGENT_GUIDE.md`. It is a pipeline: pick the pipeline, read its manifest, then run the stages. Show the operator the script and the cost before you spend on paid keys.

For a short zero-key clip, write a props file like those in `remotion-composer/public/demo-props/` and render it:

`render.py code-to-screen --seconds 3` renders the first 3 s of a checked-in demo.
`render.py /tmp/props.json` renders your own props in full.

## Web and three.js scenes, and recording a live site

Web and three.js scenes render through Remotion, which draws every frame from the frame number, so a render is frame-exact and never drops frames. Add three.js once in the install:

`cd ~/.local/share/openmontage/remotion-composer && npm install --save-exact @remotion/three@$(node -p "require('remotion/package.json').version") three@0.170.0 @react-three/fiber@8.17.10`

Then `render.py <skill dir>/scenes/moon.tsx` renders the sample scene (a rotating moon and an eclipse, 4 s). A scene is one file with `registerRoot` and a composition with id `Scene`; copy `scenes/moon.tsx` and change it. A host with no GPU has no WebGL, so `render.py` passes `--gl=swangle` (software GL) for scenes.

To record a real live site, use `screencast.mjs`, next to this file:

`screencast.mjs https://example.com ~/.cache/crewship/videos/site.mp4 5` records 5 s (width and height are optional: `1280 720`).

It uses CDP `Page.startScreencast` on a running Chrome, by default the shared `chrome` tier of `fleet-browser` (`CDP_URL` overrides), then encodes the frames with `ffmpeg`. It opens its own tab and closes it. It needs a page that changes while it records, and it fails when the page stays still. A recording is real time, so a heavy page can drop frames; for a frame-exact result, build the scene in Remotion.

## Motion and sound

Move every element with Remotion `spring({frame, fps, config})`, a closed-form damped spring, or the same formula by hand. Never use CSS easing, transitions or keyframes: they run on the wall clock, not the frame number, so a render drifts. Start each spring at the frame of its trigger (`frame - startFrame`). A low `damping` (8 to 12) overshoots and settles; a high one (20+) does not.

Synthesize sound in code and fix one BPM. Put every cut and every spring trigger on a beat frame: `frame = round(beat * 60 / BPM * fps)`. A 4 s click track at 120 BPM, then mux it:

`ffmpeg -f lavfi -i "aevalsrc='sin(2*PI*1000*t)*exp(-40*mod(t,0.5))':d=4:s=44100" beat.wav`
`ffmpeg -i video.mp4 -i beat.wav -c:v copy -c:a aac -shortest out.mp4`

`mod(t,0.5)` is the beat period, 60 / BPM. For more than a click, write samples with numpy and `wave`. `scenes/beat.tsx` shows the spring and the beat-frame cut together.

## Self-review

Do this before you send a video. Render with `--frames-every N` (N = fps / 2 gives 2 frames per second); `render.py` prints the folder of png frames. For one segment, use `ffmpeg -ss S -t D -i out.mp4 -vf "select=not(mod(n\,N))" -fps_mode vfr seg%03d.png`. Look at each frame. Score each segment 1 to 10 against the brief: layout, text legibility, motion, and cut on beat. Re-render every segment that scores under 8 with a fix for the stated fault, then review it again. Repeat once, then send the best result and say which segments stayed under 8.

## Output

It writes to one cache dir, `~/.cache/crewship/videos/` (`XDG_CACHE_HOME` moves it), prunes anything older than 1 day on each run, and prints the mp4 path. A systemd user tmpfiles rule (`d %C/crewship/videos 0755 - - 1d`) prunes it too. Do not keep renders anywhere else, and delete large intermediate files.

## Send

iMessage takes png, jpg or webp, not mp4. `render.py PROPS --send "caption"` also extracts a poster frame and runs `fm-imessage --image`. It stops with a message when `fm-imessage` does not exist. Always give the mp4 path as well: other chats and tools take the video by path.

## Install of this skill

Crewship installs this skill with every other public skill: `~/.omp/agent/skills/openmontage/` for omp and `~/.claude/skills/openmontage/` for Claude Code (see [Skills](../../../../docs/omp.md#skills)). To install it by hand, copy this folder to both paths.

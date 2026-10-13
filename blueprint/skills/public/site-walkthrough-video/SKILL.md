---
name: site-walkthrough-video
description: Use when asked for a walk-through or fly-through video of a 3D or WebGL site. Drive the camera yourself with real keyboard and mouse-look input, look where it goes, never clip, and cover every area; frame-exact 1080p60 with sound.
---

# Site walk-through video

The result: a smooth walk that faces its direction of travel, eases every turn, slows near geometry, stops at each area to look at it, and never passes through walls. It is framed as a browser window on a desktop wallpaper and has synthesized ambient sound. Never use the site's own auto-walk, map jumps, teleports or preset views: they snap the camera and do not look where they go.

## 1. Read the site first

Read the site's movement and camera code before you plan anything:

- **Input:** the key bindings and their speed (m/s, rad/s), and the mouse-look gain (rad per pixel of `movementX`/`movementY`). Note the pitch clamp and what starts pointer lock (usually a click on the canvas).
- **Collision:** the floor height function, the blocked test, and the step height.
- **Rooms:** the door, hatch and ladder triggers, and where they put you.
- **Clicks to avoid:** a click on a sign or object that opens a link or jumps the camera.
- **Areas:** every one, from the site code (spot or anchor ids, rooms, signs). Check the list against the live page, then plan to stop at each one.

## 2. Hook and dump

Write an adapter module (below). Its `patch` appends a few lines to the site's own script, so the controller can read the real state:

- `window.__pose()` returns `{ x, z, yaw, pitch, eye, room }`.
- `window.__move(dt)` runs the site's own key step for part of a frame. This gives walking speeds below the full key speed with the key really held. Without it, the forward key is held for the whole frame or not at all.

Then dump a walkable grid per scene (outdoors and each room) from the site's own floor and blocked functions, every 0.1 m: `{ x0, z0, R, nx, nz, fy, bl, soft }`. Set `soft` to 1 under small things the camera must not enter but the site lets you walk through: tree crowns, rails, posts, lamps. These are non-solid boxes about 1.5 m wide or less that reach eye height. Large non-solid boxes (hull sides, sails, rigging) enclose walkable space, so route around them by hand. Dump every scene box too, for the review.

## 3. Plan the route

`walk.mjs` holds the planner and the camera controller, with no browser. A leg is `{ name, scene, via, end, looks }`:

- `via` points through open space, joined by A*. Its cost rises below 1.6 m of clearance. Then a shortcut pass and corner smoothing.
- `end: "stop"` brakes to a halt and runs `looks`: `{ at: [x, y, z], hold }` turns to that point, or `{ yaw, pitch, hold }` gives an absolute view.
- `end: "cross"` walks at pace through a door, hatch or ladder; `push` adds the run past the trigger.
- Options: `narrow` keeps a speed floor between close rails, `lapse` speeds the page clock on long open ground, `crossPitch` sets the view up a ladder.

Each frame the controller does this:

- It aims at a look-ahead point 0.9-1.9 m along the path, so it always faces where it goes.
- Yaw and pitch are critically damped springs on slew-limited targets, so there are no snaps.
- Speed is the lowest of four limits: clearance ahead, curvature ahead, heading error and stopping distance.

Run the controller offline against the grid before the browser, like the test does. Look for 0 bumps and for clearance on every leg. End on a wide view, held about 3 s.

## 4. Capture

```bash
bunx playwright install chromium                       # once; bun installs playwright-core on first import
pids=(); for s in "0 4000" "4000 8000" "8000 12000" "12000 Infinity"; do set -- $s
  CAPFROM=$1 CAPTO=$2 bun capture.mjs adapter.mjs frames > seg.$1.log 2>&1 & pids+=($!)
done
for p in "${pids[@]}"; do wait "$p" || { echo "a capture segment failed: see seg.*.log"; exit 1; }; done
mv frames/log.12000-Infinity.json frames/log.json
```

`capture.mjs` puts the page on a virtual clock: `requestAnimationFrame` and `performance.now` advance 1/60 s per frame, so the capture is frame-exact. Make rendering deterministic in `init` (for example, single-threaded workers). Each segment replays the walk from frame 0 and saves only its own range of frames, so the segments run in parallel. Check that their logs agree, then take the last segment's `log.json`.

It needs new-headless Chromium (`channel: "chromium"`); the old headless shell reports `movementX = 0` under pointer lock. All input goes through CDP:

- clicks: `start()` does the intro, such as the sound button, then one click on a plain canvas cell to lock the pointer
- `mouseMoved` deltas for mouse-look
- the forward key

A drawn cursor glides on a spring for the clicks and hides under pointer lock.

Adapter:

```js
export default {
  url: "https://example.com", // the page renders at 1700x920, the area compose.mjs frames
  init: "/* runs before the page, after the virtual clock */",
  patch: { match: "**/app.js", append: "window.__pose = () => ({ x: me.x, z: me.z, yaw: me.yaw, pitch: me.pitch, eye: me.eye, room: me.room });" },
  pose: "window.__pose()", move: "__move", radPerPx: 0.0022, keySpeed: 3.4, forwardKey: "w",
  async start({ page, glide, click, sleep, W, H, log }) { await glide(W * 0.5, H * 0.2); await click(); },
  legs: () => LEGS.map((l) => ({ ...l, grid: G[l.scene], path: l.via && path(G[l.scene], l.via, l.push) })), // no via: a stand-and-look leg
};
```

## 5. Review, then re-render

```bash
python3 review.py frames review boxes.json
```

The tool prints per leg the peak yaw rate and the facing error, which is the angle between movement and view. It writes contact sheets: a tile every 0.5 s, dense around door crossings and the fastest turn. With `boxes.json`, it lists every run of frames where the eye comes within 0.45 m of an object. Look at every sheet and score each leg 1 to 10 for clipping, jerks and wrong facing. Fix each leg under 8 in the route, then re-render. Rendering is deterministic, so re-render from the first changed frame only and keep the frames before it. Repeat until no leg is under 8. Some legs stay low for reasons a camera cannot fix, such as a dark scene. Name those in the report, with the reason.

## 6. Sound and compose

```bash
uv run --with numpy python3 synth.py frames/log.json frames/audio.wav
bun compose.mjs frames out.mp4 frames/audio.wav example.com
```

`synth.py` makes a sound bed (low swell, wind, faint drone) from noise and sines. On top: a footstep per 0.75 m walked, a blip per click, a thud per door, and a muffled bed inside rooms. The sound stays silent until the first click, as a browser's does.

`compose.mjs` writes 1920x1080 at 60 fps. It converts sRGB to BT.709 limited-range YUV explicitly and tags the file; an untagged or implicit conversion looks washed out, most of all on an HDR display. Keep the page's own colours: do not brighten a dark scene with curves, because a shadow lift flattens contrast and looks washed out. To check, compare one frame with the raw capture: `ffmpeg -i out.mp4 -vf signalstats,metadata=mode=print -frames:v 1 -f null -`. The video's luma must match the raw frame's (`YMIN` at 16 for true black, the peak at 235 or less).

## 7. Deliver

Read the credentials by name from the operator's secret store, and never print one. Upload with an unguessable key and check the public link:

```bash
key="walkthrough-$(openssl rand -hex 16).mp4"
uv run --with boto3 python3 -c 'import boto3, os, sys; boto3.client("s3", endpoint_url=os.environ["R2_S3_ENDPOINT"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto").upload_file(sys.argv[1], os.environ["R2_BUCKET"], sys.argv[2], ExtraArgs={"ContentType": "video/mp4"})' out.mp4 "$key"
curl -sI "$R2_PUBLIC_URL/$key" | head -1                  # HTTP/1.1 200 OK (curl, not Python's urllib: it gets 403)
ssh "$MAC_HOST" open -g -a Dia "$R2_PUBLIC_URL/$key"   # open the link in the background; never copy files to the Mac
```

Deliver the video as the link only. Do not copy it to the operator's Mac or open it there from disk, unless they ask for that exact file. Give the link and the length, and give the per-leg scores in the report.

---
name: downloads
description: Use for fast, resumable file downloads with aria2c or for video and audio with yt-dlp.
---

# Download files and media

Download only content you have permission to save. Check for the tool you need before you use it.
If a prerequisite is missing, stop the affected action and tell the user which install command they can run.
Do not run install commands.
Do not use stored credentials.

Do not use this skill for private, signed, or credential-bearing links.

## Direct file URL: aria2c

Pass one direct HTTP or HTTPS URL per call and use only trusted origins.
aria2 can follow mirrors from HTTP `Link` headers on new downloads and resumes.
Run `command -v aria2c`. Install commands for the user: `sudo apt install aria2` (Debian/Ubuntu) or `brew install aria2` (macOS).
Set `DOWNLOAD_DIR` to an unused directory for each new download.

```bash
aria2c --no-conf --no-netrc=true --follow-torrent=false --follow-metalink=false \
  --auto-file-renaming=false -x 4 -s 4 -d "$DOWNLOAD_DIR" -o download -- "$FILE_URL"
```

`-x` limits connections per server. `-s` sets the number of connections for the file.
The server must support range requests for parallel HTTP downloads.
Add `-c` before `--` only if the known partial file and its matching `.aria2` control file exist.
Resume only from the same URL and only if the version is unchanged or the publisher's checksum verifies the result.
Otherwise, start at a new destination.

If the publisher supplies a SHA-256 or SHA-512 digest, add `--checksum=ALGO=DIGEST` before `--`.
Use the publisher's algorithm (`sha-256` or `sha-512`) and hex digest, for example `--checksum="sha-256=$SHA256"`.
Treat a mismatch as a failed download.
Without a checksum, parallel requests can mix versions if the file changes during transfer.
If the file looks corrupt, use a new destination and replace `-x 4 -s 4` with `-x 1 -s 1`.

## Video or audio page: yt-dlp

Use an HTTP or HTTPS URL for one video, not a playlist-only URL.
Run `command -v yt-dlp`.
Install commands for the user: `pipx install 'yt-dlp[default]'` (requires pipx) or `brew install yt-dlp` (macOS).

For YouTube, check for compatible `yt-dlp-ejs` scripts and Deno before any command below.
Check `deno --version` for Deno 2.3.0 or later, which yt-dlp enables by default.
Refer the user to the upstream yt-dlp EJS setup guide if any YouTube prerequisite is missing.

Run this check before any media action. The empty playlist range prevents the check from processing collection entries.

```bash
yt-dlp --ignore-config --no-cache-dir --no-playlist --playlist-items 1:0 --simulate \
  --print '%(_type|video)s %(live_status)s' -- "$VIDEO_URL" 2>/dev/null
```

Continue only if the check succeeds and prints one line with type `video`. This also covers audio-only items.
Refuse items with status `is_live` or `is_upcoming`. Do not download live HLS. Finished public HLS recordings are allowed.
For a collection, use the requested item's individual URL and repeat the check.
Set `DOWNLOAD_DIR` to an unused directory for each download, including a new format of the same resource.
Check the exit status and confirm the requested output; a skipped collection can exit without an error or output.

```bash
yt-dlp --ignore-config --no-cache-dir --quiet --no-playlist --playlist-items 1:0 -F -- "$VIDEO_URL"
yt-dlp --ignore-config --no-cache-dir --no-playlist --playlist-items 1:0 \
  --match-filters 'live_status !=? is_live & live_status !=? is_upcoming' \
  -P "$DOWNLOAD_DIR" -o 'video.%(ext)s' -- "$VIDEO_URL"
yt-dlp --ignore-config --no-cache-dir --no-playlist --playlist-items 1:0 \
  --match-filters 'live_status !=? is_live & live_status !=? is_upcoming' \
  -P "$DOWNLOAD_DIR" -x -o 'audio.%(ext)s' -- "$VIDEO_URL"
```

Use the default format selection unless the user requests a specific quality or format.
Add `-f FORMAT_ID` before `--` to select a format from the list.
For video with sound, select a combined format or pair separate streams with `-f VIDEO_ID+AUDIO_ID`.
For audio extraction, select a format that contains audio.
Check `command -v ffmpeg` before merging streams or extracting audio.
Install commands for the user: `sudo apt install ffmpeg` (Debian/Ubuntu) or `brew install ffmpeg` (macOS).

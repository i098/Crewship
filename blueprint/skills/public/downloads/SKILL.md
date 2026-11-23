---
name: downloads
description: Use for fast, resumable file downloads with aria2c or for video, audio, and clips with yt-dlp.
---

# Download files and media

Download only content you have permission to save. Check for the tool you need before you use it.
If a prerequisite is missing, stop the affected action and tell the user which install command they can run.
Do not run install commands.
Do not use stored credentials.

Create a temporary input file with `mktemp` and mode `0600`. Set `URL_FILE` to its path.
Put one URL on the first line without tabs or other whitespace.
For signed links, populate the file from a private source or through a non-recorded terminal with echo off.
Do not paste signed links into chat or tool calls, type them as shell commands, or print the file.
Delete the file after the last command, including on failure.

## Direct file URL: aria2c

Pass one direct HTTP, HTTPS, or FTP URL per call and use only trusted origins.
aria2 can follow mirrors from HTTP `Link` headers on new downloads and resumes.
Run `command -v aria2c`. Install commands for the user: `sudo apt install aria2` (Debian/Ubuntu) or `brew install aria2` (macOS).
Set `DOWNLOAD_DIR` and `FILE_NAME` to an unused destination for each new resource.
In the input file, add `  out=FILE_NAME` on the line below the URL, with the actual basename.

```bash
aria2c --no-conf --no-netrc=true --follow-torrent=false --follow-metalink=false \
  --auto-file-renaming=false -x 4 -s 4 -d "$DOWNLOAD_DIR" -i "$URL_FILE" >/dev/null 2>&1
```

`-x` limits connections per server. `-s` sets the number of connections for the file.
The server must support range requests for parallel HTTP downloads.
Add `-c` only if the known partial file and its matching `.aria2` control file exist at the same destination.
Resume only from the same URL and only if the version is unchanged or the publisher's checksum verifies the result.
Otherwise, start at a new destination.

If the publisher supplies a SHA-256 or SHA-512 digest, add `--checksum=ALGO=DIGEST`.
Use the publisher's algorithm (`sha-256` or `sha-512`) and hex digest, for example `--checksum="sha-256=$SHA256"`.
Treat a mismatch as a failed download.
Without a checksum, parallel requests can mix versions if the file changes during transfer.
If the file looks corrupt, download to a new destination with `-x 1 -s 1`.

## Video or audio page: yt-dlp

Use a URL for one video, not a playlist-only URL.
Run `command -v yt-dlp`.
Install commands for the user: `pipx install 'yt-dlp[default]'` (requires pipx) or `brew install yt-dlp` (macOS).

For YouTube, check for compatible `yt-dlp-ejs` scripts and a supported runtime before any command below.
Check `deno --version` for Deno 2.3.0 or later, which yt-dlp enables by default.
For Node 22 or later, check `node --version` and add `--js-runtimes node` to the yt-dlp command.
Refer the user to the upstream yt-dlp EJS setup guide if any YouTube prerequisite is missing.

Run this check before any media action. The empty playlist range prevents the check from processing collection entries.

```bash
yt-dlp --ignore-config --no-playlist --playlist-items 1:0 --simulate \
  --print '%(_type|video)s' -a "$URL_FILE" 2>/dev/null
```

Continue only if the check succeeds and prints exactly `video`. This also covers audio-only items.
For a collection, use the requested item's individual URL and repeat the check.
Set `DOWNLOAD_DIR` to an unused output directory for each distinct media resource.
Use a URL-only input file for yt-dlp.
Check the exit status and confirm the requested output; a skipped collection can exit without an error or output.

```bash
yt-dlp --ignore-config --quiet --no-playlist --playlist-items 1:0 -F -a "$URL_FILE" 2>/dev/null
yt-dlp --ignore-config --no-playlist --playlist-items 1:0 -P "$DOWNLOAD_DIR" \
  -o '%(title)s [%(id)s] [%(format_id)s].%(ext)s' -a "$URL_FILE" >/dev/null 2>&1
yt-dlp --ignore-config --no-playlist --playlist-items 1:0 -P "$DOWNLOAD_DIR" -x \
  -o '%(title)s [%(id)s] [%(format_id)s] audio.%(ext)s' -a "$URL_FILE" >/dev/null 2>&1
yt-dlp --ignore-config --no-playlist --playlist-items 1:0 -P "$DOWNLOAD_DIR" \
  --download-sections '*00:01:10-00:01:30' \
  -o '%(title)s [%(id)s] [%(format_id)s] %(section_start)s-%(section_end)s.%(ext)s' \
  -a "$URL_FILE" >/dev/null 2>&1
```

Use the default format selection unless the user requests a specific quality or format.
Add `-f FORMAT_ID` to select a format from the list.
For a video or clip with sound, select a combined format or pair separate streams with `-f VIDEO_ID+AUDIO_ID`.
For audio extraction, select a format that contains audio.
Check `command -v ffmpeg` before merging streams, extracting audio, or cutting a clip.
Install commands for the user: `sudo apt install ffmpeg` (Debian/Ubuntu) or `brew install ffmpeg` (macOS).

The default cut is approximate because it can start before the requested time.
For accurate cuts, add `--force-keyframes-at-cuts` and add `-accurate` before `.%(ext)s` in the output template.

For signed links, use `--downloader native` and only direct HTTP(S) media formats for video or audio downloads.
Stop if the selected streams require an external downloader.
For a signed clip, download the video first and cut the local file with FFmpeg.
Use `ffmpeg -n -ss "$START" -i "$LOCAL_VIDEO" -t "$DURATION" -c copy "$CLIP_FILE"` for an approximate cut.
Omit `-c copy` to re-encode for an accurate cut. Include both time bounds and, for accurate cuts, `-accurate` in the filename.

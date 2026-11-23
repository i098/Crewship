---
name: downloads
description: Use for fast, resumable file downloads with aria2c or for video, audio, and clips with yt-dlp.
---

# Download files and media

Download only content you have permission to save. Check for the tool you need before you use it.
If a prerequisite is missing, stop the affected action and tell the user which install command they can run.
Do not run install commands.
Do not use stored credentials.

## Direct file URL: aria2c

Use only direct HTTP, HTTPS, or FTP URLs.
Run `command -v aria2c`. Install commands for the user: `sudo apt install aria2` (Debian/Ubuntu) or `brew install aria2` (macOS).
Set `DOWNLOAD_DIR` and `FILE_NAME` to an unused destination for each new resource.

```bash
aria2c --no-conf --no-netrc=true --follow-torrent=false --follow-metalink=false \
  --auto-file-renaming=false -x 4 -s 4 -d "$DOWNLOAD_DIR" -o "$FILE_NAME" -- "$FILE_URL"
```

`-x` limits connections per server. `-s` sets the number of connections for the file.
The server must support range requests for parallel HTTP downloads.
Add `-c` only for a known partial download from the same URL at the same destination.
Resume only if you know the remote version has not changed or you can verify the result with the publisher's checksum.
Otherwise, start at a new destination.
Keep the partial file and its `.aria2` control file together.

If the publisher supplies a SHA-256 or SHA-512 digest, add `--checksum=ALGO=DIGEST` before `--`.
Use the publisher's algorithm (`sha-256` or `sha-512`) and hex digest, for example `--checksum="sha-256=$SHA256"`.
Treat a mismatch as a failed download.

## Video or audio page: yt-dlp

Use a URL for one video, not a playlist-only URL.
Run `command -v yt-dlp`.
Install commands for the user: `pipx install 'yt-dlp[default]'` (requires pipx) or `brew install yt-dlp` (macOS).

For YouTube, check for compatible `yt-dlp-ejs` scripts and a supported runtime before any command below.
Check `deno --version` for Deno 2.3.0 or later, which yt-dlp enables by default.
For Node 22 or later, check `node --version` and add `--js-runtimes node` before `--`.
Refer the user to the [yt-dlp EJS setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS) if any YouTube prerequisite is missing.

```bash
yt-dlp --ignore-config --no-playlist -F -- "$VIDEO_URL"  # List formats
yt-dlp --ignore-config --no-playlist \
  -o '%(title)s [%(id)s] [%(format_id)s].%(ext)s' -- "$VIDEO_URL"
yt-dlp --ignore-config --no-playlist -x \
  -o '%(title)s [%(id)s] [%(format_id)s] audio.%(ext)s' -- "$VIDEO_URL"
yt-dlp --ignore-config --no-playlist --download-sections '*00:01:10-00:01:30' \
  -o '%(title)s [%(id)s] [%(format_id)s] %(section_start)s-%(section_end)s.%(ext)s' -- "$VIDEO_URL"
```

Use the default format selection unless the user requests a specific quality or format.
Add `-f FORMAT_ID` before `--` to select a format from the list.
Check `command -v ffmpeg && command -v ffprobe` before merging streams, extracting audio, or cutting a clip.
Install commands for the user: `sudo apt install ffmpeg` (Debian/Ubuntu) or `brew install ffmpeg` (macOS).

The default cut is approximate because it can start before the requested time.
For accurate cuts, add `--force-keyframes-at-cuts` before `--` and add `-accurate` before `.%(ext)s` in the output template.

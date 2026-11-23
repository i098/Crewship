---
name: downloads
description: Use for fast, resumable file downloads with aria2c or for video, audio, and clips with yt-dlp.
---

# Download files and media

Download only content you have permission to save. Check for the tool you need before you use it.
If a prerequisite is missing, stop the affected action and tell the user which install command they can run.
Do not run install commands.

## Direct file URL: aria2c

Use only direct HTTP, HTTPS, or FTP URLs.
Run `command -v aria2c`. Install commands for the user: `sudo apt install aria2` (Debian/Ubuntu) or `brew install aria2` (macOS).
Set `DOWNLOAD_DIR` and `FILE_NAME` to an unused destination for each new resource.

```bash
aria2c --no-conf --follow-torrent=false --follow-metalink=false \
  --auto-file-renaming=false -x 4 -s 4 -d "$DOWNLOAD_DIR" -o "$FILE_NAME" -- "$FILE_URL"
```

`-x` limits connections per server. `-s` sets the number of connections for the file.
The server must support range requests for parallel HTTP downloads.
Add `-c` only to resume a known partial download from the same URL at the same destination.
Keep the partial file and its `.aria2` control file together.

If the publisher supplies a SHA-256 digest, add `--checksum="sha-256=$SHA256"` before `--`. Treat a mismatch as a failed download.

## Video or audio page: yt-dlp

Use a URL for one video, not a playlist-only URL.
Run `command -v yt-dlp`. Install commands for the user: `pipx install yt-dlp` (requires pipx) or `brew install yt-dlp` (macOS).

```bash
yt-dlp --ignore-config --no-playlist -F -- "$VIDEO_URL"  # List formats
yt-dlp --ignore-config --no-playlist -- "$VIDEO_URL"
yt-dlp --ignore-config --no-playlist -x \
  -o '%(title)s [%(id)s] audio.%(ext)s' -- "$VIDEO_URL"
yt-dlp --ignore-config --no-playlist --download-sections '*00:01:10-00:01:30' \
  -o '%(title)s [%(id)s] %(section_start)s-%(section_end)s.%(ext)s' -- "$VIDEO_URL"
```

Use the default format selection unless the user requests a specific quality or format.
Add `-f FORMAT_ID` before `--` to select a format from the list.
Check `command -v ffmpeg && command -v ffprobe` before merging streams, extracting audio, or cutting a clip.
Install commands for the user: `sudo apt install ffmpeg` (Debian/Ubuntu) or `brew install ffmpeg` (macOS).

The default cut is approximate because it can start before the requested time.
For accurate cuts, add `--force-keyframes-at-cuts` before `--` and add `-accurate` before `.%(ext)s` in the output template.

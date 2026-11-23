---
name: downloads
description: Use for fast, resumable file downloads with aria2c or for video, audio, and clips with yt-dlp.
---

# Download files and media

Download only content you have permission to save. Check for the tool you need before you use it.

## Direct file URL: aria2c

Run `command -v aria2c`. If it is missing, use `sudo apt install aria2` (Debian/Ubuntu) or `brew install aria2` (macOS).

```bash
aria2c -c -x 4 -s 4 -- "$FILE_URL"
```

`-x` limits connections per server. `-s` sets the number of connections for the file. The server must support range requests for parallel HTTP downloads. Run the same command in the same directory to resume with `-c`. Keep the partial file and its `.aria2` control file.

If the publisher supplies a SHA-256 digest, add `--checksum="sha-256=$SHA256"` before `--`. Treat a mismatch as a failed download.

## Video or audio page: yt-dlp

Run `command -v yt-dlp`. If it is missing, use `pipx install yt-dlp` (with pipx installed) or `brew install yt-dlp` (macOS).

```bash
yt-dlp -F -- "$VIDEO_URL"                              # List formats
yt-dlp -f 'bv[height<=1080]+ba/b[height<=1080]' -- "$VIDEO_URL"
yt-dlp -x -- "$VIDEO_URL"                              # Save audio only
yt-dlp --download-sections '*00:01:10-00:01:30' -- "$VIDEO_URL"
```

The second command selects video at 1080p or less and its audio. Use `-f FORMAT_ID` to select a specific format from the list. Check `command -v ffmpeg` before merging streams, extracting audio, or cutting a clip. If it is missing, use `sudo apt install ffmpeg` or `brew install ffmpeg`.

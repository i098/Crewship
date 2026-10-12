// Outbound photos (fm-imessage --image): the checks and the downscale, with Bun's built-in Bun.Image, so the bridge
// needs no image dependency. Free of spectrum-ts, so tests run without it.

export const IMAGE_IN_MAX = 25 * 1024 * 1024; // bytes accepted from the command
export const IMAGE_OUT_MAX = 10 * 1024 * 1024; // bytes sent, after the downscale
export const IMAGE_EDGE_MAX = 2048; // pixels on the longest side; a larger photo (a 4K screenshot) is downscaled

// A photo ready to send: a file in the bridge's state directory, kept until every bubble of its item is out.
export type Picture = { path: string; name: string; mimeType: string };

const FORMATS: Record<string, { ext: string; mimeType: string }> = {
  png: { ext: "png", mimeType: "image/png" },
  jpeg: { ext: "jpg", mimeType: "image/jpeg" },
  webp: { ext: "webp", mimeType: "image/webp" },
};

// A photo that cannot be sent: the message says why, for the command's stderr.
export class ImageError extends Error {}

export type PreparedImage = { bytes: Uint8Array; name: string; mimeType: string; resized: boolean };

// Checks `bytes` by content, not by name, and downscales a photo with a side over IMAGE_EDGE_MAX (same format and
// aspect ratio; Bun.Image applies the EXIF orientation). The name gets the extension of the real format.
export async function prepareImage(bytes: Uint8Array, name: string): Promise<PreparedImage> {
  if (bytes.length > IMAGE_IN_MAX) throw new ImageError(`image is ${mb(bytes.length)} MB; the limit is ${mb(IMAGE_IN_MAX)} MB`);
  const info = await new Bun.Image(bytes).metadata().catch(() => undefined);
  const format = info && FORMATS[info.format];
  if (!info || !format) throw new ImageError(`${info ? info.format : "this file"} is not a png, jpg or webp image`);
  let out = bytes;
  const resized = Math.max(info.width, info.height) > IMAGE_EDGE_MAX;
  if (resized) {
    const image = new Bun.Image(bytes).resize(IMAGE_EDGE_MAX, IMAGE_EDGE_MAX, { fit: "inside" });
    out = await (info.format === "png" ? image.png() : info.format === "webp" ? image.webp({ quality: 85 }) : image.jpeg({ quality: 85 })).bytes();
  }
  if (out.length > IMAGE_OUT_MAX) throw new ImageError(`image is still ${mb(out.length)} MB after the downscale; the limit is ${mb(IMAGE_OUT_MAX)} MB`);
  const stem = name.replace(/\.[^.]*$/, "").replace(/[^\w.-]/g, "_") || "image";
  return { bytes: out, name: `${stem}.${format.ext}`, mimeType: format.mimeType, resized };
}

const mb = (n: number) => (n / 1024 / 1024).toFixed(1);

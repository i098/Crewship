import { expect, test } from "bun:test";
import { uploadType } from "../src/overlays";

test("uploads play media, show text and HTML escaped, frame only PDFs", () => {
  expect(uploadType({ type: "image/png", name: "a.png" })).toBe("image");
  expect(uploadType({ type: "video/mp4", name: "a.mp4" })).toBe("video");
  expect(uploadType({ type: "audio/mpeg", name: "a.mp3" })).toBe("audio");
  // an HTML file in a blob frame would run on this origin, so it shows as text
  expect(uploadType({ type: "text/html", name: "x.html" })).toBe("text");
  expect(uploadType({ type: "", name: "x.htm" })).toBe("text");
  expect(uploadType({ type: "application/json", name: "a.json" })).toBe("text");
  expect(uploadType({ type: "", name: "notes.md" })).toBe("text");
  expect(uploadType({ type: "application/pdf", name: "a.pdf" })).toBe("pdf");
  expect(uploadType({ type: "application/zip", name: "a.zip" })).toBe("file");
});

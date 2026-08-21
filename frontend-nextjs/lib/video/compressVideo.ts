// Client-side video compression before upload, using the browser's own
// hardware-accelerated codecs (WebCodecs, via the `mediabunny` package).
//
// The ingestion pipeline only needs: (1) clear audio for Whisper
// transcription, and (2) frames good enough for scene detection / rough
// visual analysis — neither needs full source resolution or bitrate. Capping
// to 480p before upload cuts both upload time and what the backend has to
// download+process, without touching audio quality.
//
// Skips files that are too small to be worth the encode time, and falls
// back to the original file untouched if WebCodecs isn't supported or the
// conversion fails for any reason — compression is a nice-to-have, never a
// blocker for getting the file uploaded.

const SKIP_BELOW_MB = 15;
const TARGET_HEIGHT = 480;
// Encoding time is bound by frame COUNT, not resolution. The ingestion
// pipeline only uses frames for scene detection + rough visual context (the
// real content is the audio → Whisper, which stays full quality), so we
// don't need 30fps. Capping to 10fps means ~3x fewer frames to encode → a
// much faster encode AND a smaller file. Only applied when the source is
// higher than this; never upsamples.
const TARGET_FPS = 10;

function hasWebCodecsSupport(): boolean {
  return typeof window !== "undefined" && "VideoEncoder" in window && "VideoDecoder" in window;
}

export async function compressVideoForUpload(
  file: File,
  onProgress?: (fraction: number) => void
): Promise<File> {
  if (!file.type.startsWith("video/")) return file;
  if (file.size / (1024 * 1024) < SKIP_BELOW_MB) return file;
  if (!hasWebCodecsSupport()) return file;

  console.log(`[compressVideo] starting: ${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)`);
  const startedAt = Date.now();

  try {
    const { Input, Output, Mp4OutputFormat, BufferTarget, Conversion, Quality, ALL_FORMATS, BlobSource } =
      await import("mediabunny");
    console.log("[compressVideo] mediabunny loaded");

    const input = new Input({
      formats: ALL_FORMATS,
      source: new BlobSource(file),
    });

    const videoTrack = await input.getPrimaryVideoTrack();
    console.log("[compressVideo] primary video track:", videoTrack ? "found" : "none (audio-only or unreadable)");
    // Already small enough (or audio-only) — don't re-encode for nothing.
    if (videoTrack) {
      const displayHeight = await videoTrack.getDisplayHeight();
      console.log(`[compressVideo] source height: ${displayHeight}px`);
      if (displayHeight <= TARGET_HEIGHT) {
        console.log("[compressVideo] already <= target height, skipping compression");
        return file;
      }
    }

    const output = new Output({
      format: new Mp4OutputFormat(),
      target: new BufferTarget(),
    });

    console.log("[compressVideo] initializing conversion...");
    const conversion = await Conversion.init({
      input,
      output,
      video: {
        height: TARGET_HEIGHT,
        frameRate: TARGET_FPS,
        quality: new Quality("low"),
      },
    });

    if (!conversion.isValid) {
      console.warn("[compressVideo] Conversion not valid for this file, uploading original", conversion.discardedTracks);
      return file;
    }

    conversion.onProgress = (fraction: number) => {
      console.log(`[compressVideo] progress: ${(fraction * 100).toFixed(1)}% (${((Date.now() - startedAt) / 1000).toFixed(0)}s elapsed)`);
      onProgress?.(fraction);
    };

    console.log("[compressVideo] executing conversion...");

    // Safety net: if the encode genuinely hangs (not just slow) rather than
    // erroring, don't block the upload forever — cancel it cleanly and fall
    // back to the original file.
    const TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes
    let timedOut = false;
    const timeoutId = setTimeout(() => {
      timedOut = true;
      console.warn(`[compressVideo] exceeded ${TIMEOUT_MS / 1000}s, canceling and uploading original`);
      conversion.cancel().catch(() => {});
    }, TIMEOUT_MS);

    try {
      await conversion.execute();
    } finally {
      clearTimeout(timeoutId);
    }

    if (timedOut) return file;
    console.log(`[compressVideo] execute() resolved after ${((Date.now() - startedAt) / 1000).toFixed(0)}s`);

    const buffer = output.target.buffer;
    if (!buffer) return file;

    const blob = new Blob([buffer], { type: "video/mp4" });
    const compressedName = file.name.replace(/\.[^./\\]+$/, "") + ".mp4";
    const compressed = new File([blob], compressedName, { type: "video/mp4" });

    // Only use it if it's actually smaller — never upload a bigger "compressed" file.
    return compressed.size < file.size ? compressed : file;
  } catch (e) {
    console.warn("[compressVideo] Compression failed, uploading original file", e);
    return file;
  }
}

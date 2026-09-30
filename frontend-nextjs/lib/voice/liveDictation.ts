/**
 * Near-live dictation: transcribes while the user speaks.
 *
 * OpenRouter's speech-to-text is request/response only (no streaming), so we
 * make it feel live in the browser:
 *   - Capture mic audio as 16 kHz mono PCM (AudioWorklet).
 *   - A simple energy VAD with an adaptive noise floor splits speech into
 *     segments at pauses (~700 ms of silence, or a 20 s cap).
 *   - While a segment is in progress it's re-sent about once a second, so its
 *     text updates as the user talks ("interim").
 *   - When the segment ends it's sent once more and that text is final.
 * Each request is a short WAV clip → POST /api/voice/transcribe (Deepgram
 * Nova-3 via OpenRouter).
 */

import { voiceApi } from "@/lib/api/voice";

const TARGET_RATE = 16000;
const FRAME_MS = 20;
const END_SILENCE_MS = 700; // pause that ends a segment
const MIN_SPEECH_MS = 250; // ignore clicks/pops
const MAX_SEGMENT_MS = 20000; // force a cut on long unbroken speech
const PRE_ROLL_MS = 300; // keep audio just before speech starts (first syllable)
const INTERIM_EVERY_MS = 900;
const MIN_THRESHOLD = 0.012;

export interface DictationCallbacks {
  /** Full text so far: finalised segments + the in-progress one. */
  onText: (text: string) => void;
  /** 0..1 input level for a meter. */
  onLevel?: (level: number) => void;
  onError?: (message: string) => void;
}

interface Segment {
  text: string;
  final: boolean;
}

// Tiny worklet that forwards raw input samples to the main thread.
const WORKLET_SRC = `
class Tap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("dictation-tap", Tap);
`;

function encodeWav(samples: Int16Array, rate: number): Blob {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const w = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); w(8, "WAVE");
  w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, samples.length * 2, true);
  new Int16Array(buf, 44).set(samples);
  return new Blob([buf], { type: "audio/wav" });
}

function concat(chunks: Int16Array[]): Int16Array {
  const out = new Int16Array(chunks.reduce((n, c) => n + c.length, 0));
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}

export class LiveDictation {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private cb: DictationCallbacks;

  private resampleBuf: number[] = [];
  private frameBuf: number[] = [];
  private preRoll: Int16Array[] = [];

  private segments: Segment[] = [];
  private current: Int16Array[] | null = null; // frames of the segment in progress
  private currentIndex = -1;
  private speechMs = 0;
  private silenceMs = 0;
  private segmentMs = 0;
  private noiseFloor = 0.005;

  private interimTimer: ReturnType<typeof setInterval> | null = null;
  private interimInFlight = false;
  private pending = new Set<Promise<void>>();
  private stopped = false;

  constructor(callbacks: DictationCallbacks) {
    this.cb = callbacks;
  }

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    this.ctx = new AudioContext();
    const url = URL.createObjectURL(new Blob([WORKLET_SRC], { type: "application/javascript" }));
    try {
      await this.ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const source = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "dictation-tap");
    this.node.port.onmessage = (e: MessageEvent<Float32Array>) => this.onSamples(e.data);
    source.connect(this.node);
    this.interimTimer = setInterval(() => this.sendInterim(), INTERIM_EVERY_MS);
  }

  /** Stop listening, finish the last segment, wait for all text. */
  async stop(): Promise<string> {
    if (this.stopped) return this.text();
    this.stopped = true;
    this.teardownAudio();
    if (this.current && this.speechMs >= MIN_SPEECH_MS) this.finalizeSegment();
    else this.current = null;
    while (this.pending.size) await Promise.allSettled([...this.pending]);
    return this.text();
  }

  /** Stop without waiting for results. */
  cancel(): void {
    this.stopped = true;
    this.teardownAudio();
  }

  // ---- audio -------------------------------------------------------------

  private teardownAudio() {
    if (this.interimTimer) clearInterval(this.interimTimer);
    this.interimTimer = null;
    // Best-effort: a failure here must never block stop() from finishing.
    try {
      this.node?.port.close();
      this.node?.disconnect();
      this.stream?.getTracks().forEach((t) => t.stop());
      void this.ctx?.close()?.catch(() => {});
    } catch {
      /* ignore */
    }
    this.node = null;
    this.stream = null;
    this.ctx = null;
  }

  private onSamples(input: Float32Array) {
    if (this.stopped || !this.ctx) return;
    // Downsample to 16 kHz by averaging (cheap anti-aliasing for speech).
    const ratio = this.ctx.sampleRate / TARGET_RATE;
    for (let i = 0; i < input.length; i++) {
      this.resampleBuf.push(input[i]);
      if (this.resampleBuf.length >= ratio) {
        let s = 0;
        for (const x of this.resampleBuf) s += x;
        this.frameBuf.push(s / this.resampleBuf.length);
        this.resampleBuf = [];
      }
    }
    const frameLen = (TARGET_RATE * FRAME_MS) / 1000;
    while (this.frameBuf.length >= frameLen) {
      this.onFrame(this.frameBuf.splice(0, frameLen));
    }
  }

  private onFrame(frame: number[]) {
    let sum = 0;
    const pcm = new Int16Array(frame.length);
    for (let i = 0; i < frame.length; i++) {
      const s = Math.max(-1, Math.min(1, frame[i]));
      sum += s * s;
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    const rms = Math.sqrt(sum / frame.length);
    this.cb.onLevel?.(Math.min(1, rms * 8));

    const threshold = Math.max(MIN_THRESHOLD, this.noiseFloor * 2.5);
    const isSpeech = rms > threshold;
    if (!isSpeech) this.noiseFloor = this.noiseFloor * 0.95 + rms * 0.05; // adapt to the room

    if (!this.current) {
      this.preRoll.push(pcm);
      if (this.preRoll.length > PRE_ROLL_MS / FRAME_MS) this.preRoll.shift();
      if (isSpeech) this.beginSegment();
      return;
    }

    this.current.push(pcm);
    this.segmentMs += FRAME_MS;
    if (isSpeech) {
      this.speechMs += FRAME_MS;
      this.silenceMs = 0;
    } else {
      this.silenceMs += FRAME_MS;
    }

    if (this.silenceMs >= END_SILENCE_MS || this.segmentMs >= MAX_SEGMENT_MS) {
      if (this.speechMs >= MIN_SPEECH_MS) this.finalizeSegment();
      else this.discardSegment();
    }
  }

  // ---- segments ----------------------------------------------------------

  private beginSegment() {
    this.current = [...this.preRoll];
    this.preRoll = [];
    this.currentIndex = this.segments.length;
    this.segments.push({ text: "", final: false });
    this.speechMs = FRAME_MS;
    this.silenceMs = 0;
    this.segmentMs = this.current.length * FRAME_MS;
  }

  private discardSegment() {
    this.segments.splice(this.currentIndex, 1);
    this.current = null;
    this.currentIndex = -1;
    this.emit();
  }

  private finalizeSegment() {
    const index = this.currentIndex;
    const audio = concat(this.current!);
    this.current = null;
    this.currentIndex = -1;
    this.track(
      this.transcribe(audio).then((text) => {
        this.segments[index] = { text, final: true };
        this.emit();
      })
    );
  }

  private sendInterim() {
    if (!this.current || this.interimInFlight || this.speechMs < MIN_SPEECH_MS) return;
    const index = this.currentIndex;
    const audio = concat(this.current);
    this.interimInFlight = true;
    this.track(
      this.transcribe(audio)
        .then((text) => {
          // Ignore if the final result for this segment already landed.
          const seg = this.segments[index];
          if (seg && !seg.final && text) {
            seg.text = text;
            this.emit();
          }
        })
        .finally(() => {
          this.interimInFlight = false;
        })
    );
  }

  private async transcribe(audio: Int16Array): Promise<string> {
    try {
      return await voiceApi.transcribe(encodeWav(audio, TARGET_RATE), "wav");
    } catch (e: any) {
      this.cb.onError?.(e?.response?.data?.detail || e?.message || "Transcription failed");
      return "";
    }
  }

  private track(p: Promise<void>) {
    const tracked = p.catch(() => {}).finally(() => this.pending.delete(tracked));
    this.pending.add(tracked);
  }

  private text(): string {
    return this.segments.map((s) => s.text).filter(Boolean).join(" ");
  }

  private emit() {
    this.cb.onText(this.text());
  }
}

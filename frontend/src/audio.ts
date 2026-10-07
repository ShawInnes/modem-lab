/** Native PCM monitoring. Presentation queues never feed back into the modem. */
export type AudioStats = {
  status: string;
  underruns: number;
  bufferMs: number;
  sourceSample: number;
};

const SOURCE_RATE = 48_000;

export class AudioMonitor {
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private generation = 0;
  private epoch = 0;
  private stream = 0;
  private initializing: Promise<void> | null = null;
  private closed = false;
  private current: AudioStats = {
    status: "disabled",
    underruns: 0,
    bufferMs: 0,
    sourceSample: 0,
  };

  get stats(): AudioStats {
    return { ...this.current };
  }

  constructor() {
    document.addEventListener("visibilitychange", this.visibilityChanged);
  }

  /** Must be called from a click: browser audio permissions require a gesture. */
  async enable(): Promise<void> {
    if (this.closed) throw new Error("Audio monitor is closed");
    if (!this.context) {
      this.context = new AudioContext();
      this.context.addEventListener("statechange", this.contextChanged);
      this.initializing = this.initialize(this.context);
    }
    await this.initializing;
    if (this.context.state !== "running") await this.context.resume();
    this.flush(
      document.hidden
        ? "hidden — audio paused"
        : this.stream === 0
          ? "muted"
          : "rebuffering",
    );
  }

  private async initialize(context: AudioContext): Promise<void> {
    try {
      await context.audioWorklet.addModule("/audio-worklet.js");
      if (this.closed) return;
      this.node = new AudioWorkletNode(context, "modem-monitor", {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: { sourceRate: SOURCE_RATE },
      });
      this.node.port.onmessage = ({ data }) => {
        if (data.generation !== this.generation || data.epoch !== this.epoch)
          return;
        this.current = {
          status: data.status,
          underruns: data.underruns,
          bufferMs: data.bufferMs,
          sourceSample:
            this.stream === 0 ? this.current.sourceSample : data.sourceSample,
        };
      };
      this.node.connect(context.destination);
    } catch (error) {
      this.current.status = "audio unavailable";
      context.removeEventListener("statechange", this.contextChanged);
      await context.close();
      this.context = null;
      throw error;
    }
  }

  setStream(stream: number): void {
    if (!Number.isInteger(stream) || stream < 0 || stream > 5)
      throw new Error("Unknown monitor stream");
    if (stream === this.stream) return;
    this.stream = stream;
    this.flush(
      this.context?.state === "running"
        ? stream === 0
          ? "muted"
          : "rebuffering"
        : "disabled",
    );
  }

  push(streams: Float32Array[], startSample: number, generation: number): void {
    if (generation !== this.generation || this.closed) return;
    const count = streams[0]?.length ?? 0;
    if (this.stream === 0) {
      this.current.sourceSample = startSample + count;
      return;
    }
    if (!this.node || this.context?.state !== "running" || document.hidden)
      return;
    let pcm: Float32Array;
    if (this.stream === 3) {
      if (!streams[1] || streams[1].length !== count) return;
      pcm = new Float32Array(count);
      for (let i = 0; i < count; i++)
        pcm[i] = (streams[0][i] + streams[1][i]) * 0.5;
    } else {
      const index =
        this.stream === 1
          ? 0
          : this.stream === 2
            ? 1
            : this.stream === 4
              ? 2
              : 3;
      if (!streams[index]) return;
      // Transfer our own copy; plots retain ownership of their input arrays.
      pcm = streams[index].slice();
    }
    this.node.port.postMessage(
      { type: "pcm", pcm, startSample, generation, epoch: this.epoch },
      [pcm.buffer],
    );
  }

  reset(generation: number): void {
    this.generation = generation;
    this.current.sourceSample = 0;
    this.current.underruns = 0;
    this.flush(
      this.context?.state === "running"
        ? this.stream === 0
          ? "muted"
          : "rebuffering"
        : "disabled",
    );
  }

  stop(): void {
    this.flush("stopped");
  }

  private flush(status: string): void {
    this.epoch++;
    this.current = { ...this.current, status, bufferMs: 0 };
    this.node?.port.postMessage({
      type: "reset",
      generation: this.generation,
      epoch: this.epoch,
      status,
      sourceSample: this.current.sourceSample,
      underruns: this.current.underruns,
    });
  }

  private visibilityChanged = (): void => {
    this.flush(
      document.hidden
        ? "hidden — audio paused"
        : this.context?.state === "running"
          ? this.stream === 0
            ? "muted"
            : "rebuffering"
          : "suspended",
    );
  };

  private contextChanged = (): void => {
    if (this.closed || !this.context) return;
    this.flush(
      this.context.state === "running"
        ? this.stream === 0
          ? "muted"
          : "rebuffering"
        : "suspended",
    );
  };

  async close(): Promise<void> {
    this.closed = true;
    document.removeEventListener("visibilitychange", this.visibilityChanged);
    this.context?.removeEventListener("statechange", this.contextChanged);
    this.node?.disconnect();
    this.node?.port.close();
    await this.context?.close();
    this.node = null;
    this.context = null;
    this.current.status = "closed";
  }
}

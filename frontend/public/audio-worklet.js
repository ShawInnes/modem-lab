/* Source-rate ring and interpolation live on the render thread, outside UI timing.
 * Keep one source sample for interpolation across engine block boundaries.
 * A queue gap/overflow discards pending presentation and explicitly re-buffers.
 */
class ModemMonitorProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.sourceRate = options.processorOptions?.sourceRate || 48000;
    this.ratio = this.sourceRate / sampleRate;
    this.capacity = Math.ceil(this.sourceRate * 0.5);
    this.threshold = Math.ceil(this.sourceRate * 0.12);
    this.ring = new Float32Array(this.capacity);
    this.read = 0;
    this.count = 0;
    this.fraction = 0;
    this.sourceSample = 0;
    this.expectedSample = null;
    this.generation = 0;
    this.epoch = 0;
    this.underruns = 0;
    this.buffering = true;
    this.status = "stopped";
    this.gain = 0;
    this.lastOutput = 0;
    this.tailOutput = 0;
    this.tailGain = 0;
    this.fadeStep = 1 / (sampleRate * 0.005);
    this.reportFrames = 0;
    this.port.onmessage = ({ data }) => this.message(data);
  }

  clear(status) {
    this.tailOutput = this.lastOutput;
    this.tailGain = 1;
    this.gain = 0;
    this.read = 0;
    this.count = 0;
    this.fraction = 0;
    this.expectedSample = null;
    this.buffering = true;
    this.status = status;
    // The previous output fades independently, even if a burst fills the new ring.
  }

  message(data) {
    if (data.type === "reset") {
      this.generation = data.generation;
      this.epoch = data.epoch;
      this.sourceSample = data.sourceSample;
      this.underruns = data.underruns;
      this.clear(data.status);
      this.report();
      return;
    }
    if (
      data.type !== "pcm" ||
      data.generation !== this.generation ||
      data.epoch !== this.epoch
    )
      return;
    const pcm = data.pcm;
    if (
      !(pcm instanceof Float32Array) ||
      !pcm.length ||
      !Number.isSafeInteger(data.startSample)
    )
      return;
    if (
      this.expectedSample !== null &&
      data.startSample !== this.expectedSample
    ) {
      this.clear("rebuffering — sample gap");
    }
    if (this.count + pcm.length > this.capacity)
      this.clear("rebuffering — backlog cleared");
    const skip = Math.max(0, pcm.length - this.capacity);
    if (this.count === 0) this.sourceSample = data.startSample + skip;
    for (let i = skip; i < pcm.length; i++) {
      const value = pcm[i];
      this.ring[(this.read + this.count) % this.capacity] = Number.isFinite(
        value,
      )
        ? value
        : 0;
      this.count++;
    }
    this.expectedSample = data.startSample + pcm.length;
    if (
      this.status === "stopped" ||
      this.status === "suspended" ||
      this.status === "muted"
    )
      this.status = "rebuffering";
  }

  report() {
    this.port.postMessage({
      generation: this.generation,
      epoch: this.epoch,
      status: this.status,
      underruns: this.underruns,
      bufferMs:
        (Math.max(0, this.count - this.fraction) / this.sourceRate) * 1000,
      sourceSample: this.sourceSample + this.fraction,
    });
  }

  process(_inputs, outputs) {
    const output = outputs[0][0];
    if (this.buffering && this.count >= this.threshold) {
      this.buffering = false;
      this.status = "playing";
    }
    for (let i = 0; i < output.length; i++) {
      // Require sufficient input for both interpolation and the next cursor step.
      const step = Math.floor(this.fraction + this.ratio);
      if (!this.buffering && this.count > Math.max(1, step)) {
        this.gain = Math.min(1, this.gain + this.fadeStep);
        const a = this.ring[this.read];
        const b = this.ring[(this.read + 1) % this.capacity];
        output[i] =
          Math.max(-1, Math.min(1, a + (b - a) * this.fraction)) * this.gain;
        this.fraction += this.ratio;
        const consumed = Math.floor(this.fraction);
        this.fraction -= consumed;
        this.read = (this.read + consumed) % this.capacity;
        this.count -= consumed;
        this.sourceSample += consumed;
      } else {
        if (!this.buffering) {
          this.tailOutput = this.lastOutput;
          this.tailGain = 1;
          this.gain = 0;
          this.buffering = true;
          this.underruns++;
          this.status = "rebuffering — underrun";
        }
        output[i] = 0;
      }
      this.tailGain = Math.max(0, this.tailGain - this.fadeStep);
      output[i] = Math.max(
        -1,
        Math.min(1, output[i] + this.tailOutput * this.tailGain),
      );
      this.lastOutput = output[i];
    }
    this.reportFrames += output.length;
    if (this.reportFrames >= sampleRate * 0.02) {
      this.reportFrames = 0;
      this.report();
    }
    return true;
  }
}

registerProcessor("modem-monitor", ModemMonitorProcessor);

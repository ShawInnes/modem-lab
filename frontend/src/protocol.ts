export type Endpoint = "caller" | "answerer";
export interface Config {
  profile?: string;
  call_setup?: boolean;
  snr_db: number;
  delay_ms: number;
  echo_attenuation_db: number;
  bandpass: string;
  seed: number;
}
export interface ReceiverDiagnostics {
  mode: "fsk" | "dqpsk" | "qam16";
  constellation?: [number, number, string][];
  symbol_samples: number;
  carrier_hz?: number;
  sample_index: number;
  trace: [number, number][];
  symbols: [number, number, number, number, number][];
  timing_locked: boolean;
  timing_note: string;
}
export interface EndpointState {
  state: string;
  call_stage?: string;
  transmit_ready?: boolean;
  carrier_lock: boolean;
  confidence: number;
  framing_errors: number;
  queued: number;
}
export interface SessionState {
  type: "state";
  generation: number;
  sample_index: number;
  active: boolean;
  auto_chat_enabled?: boolean;
  auto_chat_status?: string;
  actual_seed?: number;
  actual_profile?: string;
  diagnostics?: Record<Endpoint, ReceiverDiagnostics>;
  config: Config;
  endpoints: Record<Endpoint, EndpointState>;
  metrics: { processing_ms: number; overruns: number; display_gaps: number };
}
export interface LabEvent {
  type: "event";
  generation: number;
  sample_index: number;
  endpoint: Endpoint;
  event_type: string;
  detail: string;
}
export interface Packet {
  generation: number;
  sequence: number;
  startSample: number;
  sampleRate: number;
  frames: number;
  columns: number;
  bins: number;
  streams: Float32Array[];
  timestamps: number[];
  spectra: Uint8Array[];
}
export function decodePacket(buffer: ArrayBuffer): Packet {
  if (buffer.byteLength < 40) throw new Error("Truncated signal header");
  const v = new DataView(buffer);
  if (
    v.getUint32(0, true) !== 0x42414c4d ||
    v.getUint16(4, true) !== 1 ||
    v.getUint16(6, true) !== 1
  )
    throw new Error("Unsupported signal packet");
  const generation = v.getUint32(8, true),
    sequence = v.getUint32(12, true),
    startSample = Number(v.getBigUint64(16, true)),
    sampleRate = v.getUint32(24, true),
    frames = v.getUint32(28, true),
    columns = v.getUint32(32, true),
    bins = v.getUint32(36, true);
  const expected = 40 + frames * 16 + columns * 8 + 4 * columns * bins;
  if (
    !Number.isSafeInteger(startSample) ||
    sampleRate !== 48000 ||
    frames > 48000 ||
    columns > 2000 ||
    bins !== 171 ||
    expected !== buffer.byteLength
  )
    throw new Error("Invalid signal dimensions");
  let offset = 40;
  const streams = Array.from({ length: 4 }, () => {
    const a = new Float32Array(buffer, offset, frames);
    offset += frames * 4;
    return a;
  });
  const timestamps = Array.from({ length: columns }, (_, i) =>
    Number(v.getBigUint64(offset + i * 8, true)),
  );
  offset += columns * 8;
  if (timestamps.some((t) => !Number.isSafeInteger(t)))
    throw new Error("Unsafe sample timestamp");
  const spectra = Array.from({ length: 4 }, () => {
    const a = new Uint8Array(buffer, offset, columns * bins);
    offset += columns * bins;
    return a;
  });
  return {
    generation,
    sequence,
    startSample,
    sampleRate,
    frames,
    columns,
    bins,
    streams,
    timestamps,
    spectra,
  };
}

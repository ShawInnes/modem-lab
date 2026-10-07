import type { Endpoint, LabEvent } from "./protocol";

export interface PhaseInterval {
  sample: number;
  end: number;
  label: string;
  detail: string;
}

/** Semantic history is independent of the rolling decoded-byte event inspector. */
export class PhaseStore {
  generation = 0;
  events: LabEvent[] = [];

  reset(generation: number) {
    this.generation = generation;
    this.events = [];
  }

  append(event: LabEvent) {
    if (event.generation !== this.generation ||
      !["call_stage_changed", "negotiation_message", "disconnected"].includes(event.event_type)) return;
    if (this.events.some((old) => old.sample_index === event.sample_index &&
      old.endpoint === event.endpoint && old.event_type === event.event_type &&
      old.detail === event.detail && old.negotiation?.direction === event.negotiation?.direction)) return;
    this.events.push(event);
    this.events.sort((a, b) => a.sample_index - b.sample_index);
  }

  prune(earliest: number) {
    const carry = new Map<Endpoint, LabEvent>();
    for (const event of this.events) {
      if (event.sample_index >= earliest) break;
      if (event.event_type !== "negotiation_message") carry.set(event.endpoint, event);
    }
    this.events = this.events.filter((event) => event.sample_index >= earliest || carry.get(event.endpoint) === event);
  }

  intervals(endpoint: Endpoint, latest: number): PhaseInterval[] {
    const stages = this.events.filter((event) => event.endpoint === endpoint && event.event_type !== "negotiation_message");
    return stages.map((event, i) => ({
      sample: event.sample_index,
      end: Math.min(latest, stages[i + 1]?.sample_index ?? latest),
      label: event.event_type === "disconnected" ? "Disconnected" : phaseLabel(event.detail.split(":", 1)[0]),
      detail: event.detail,
    }));
  }

  messages(endpoint: Endpoint, direction: "tx" | "rx") {
    return this.events.filter((event) => event.endpoint === endpoint &&
      event.event_type === "negotiation_message" && event.negotiation?.direction === direction);
  }
}

function phaseLabel(stage: string) {
  const labels: Record<string, string> = {
    dialing: "Dialing", ringing: "Ringing", pickup: "Pickup",
    waiting_for_ansam: "Wait for ANSam", v8_answer_wait: "Answer wait",
    sending_ansam: "ANSam", ansam_detected: "ANSam detected",
    sending_cm: "CM", sending_jm: "JM", sending_cj: "CJ",
    negotiation_complete: "Negotiated", v8bis_discovery: "V.8bis discovery",
    v8bis_selecting: "V.8bis selection", v8bis_accepted: "V.8bis accepted",
    v8bis_rejected: "V.8bis rejected", v8bis_complete: "V.8bis complete",
    training: "Training", connected: "Data", failed: "Failed",
  };
  return labels[stage] ?? stage.replaceAll("_", " ");
}

import type { Config, Endpoint, LabEvent, NegotiationMessage, NegotiationState } from './protocol';

const endpoints: Endpoint[] = ['caller', 'answerer'];
const names = { caller: 'Caller', answerer: 'Answerer' };
const modes = [
  { id: 'dqpsk1200', name: 'V.22-style · 1200 bit/s' },
  { id: 'qam2400', name: 'V.22bis-style · 2400 bit/s' },
];
const all = ['v22'];
export function modeName(mode: string) {
  return mode === 'v22' ? 'V.22 / V.22bis family' : modes.find(item => item.id === mode)?.name ?? mode;
}
const explanations: Record<string, string> = {
  CI: 'Caller identifies a data-modem call.',
  ANSam: 'Answerer announces V.8 support with a modulated answer tone.',
  CM: 'Caller advertises the modulation families it supports.',
  JM: 'Answerer returns the compatible modulation families.',
  CJ: 'Caller ends the menu exchange and confirms the transition to modem training.',
  CR: "Request the other device's capabilities.",
  CL: 'Send a capabilities list.',
  CLR: 'Send a capabilities list and request one in return.',
  MS: 'Propose a common operating mode.',
  ACK: 'Accept the capabilities transaction.',
  NAK: 'Reject the proposed transaction.',
};

export function NegotiationControls({config, disabled, configure}: {
  config: Config; disabled: boolean; configure: (patch: Partial<Config>) => unknown;
}) {
  const setup = config.call_setup_mode ?? 'direct';
  return <section className="setup-controls" aria-label="Call setup controls">
    <div className="setup-heading">
      <label>Call setup <select aria-label="Call setup procedure" value={setup} disabled={disabled}
        onChange={event => configure({call_setup_mode: event.target.value as Config['call_setup_mode'],
          ...(event.target.value !== 'direct' && (!config.profile || config.profile === 'bell103') ? {profile: 'qam2400'} : {})})}>
        <option value="direct">Direct · selected modem startup</option>
        <option value="v8">V.8 · menu negotiation</option>
        <option value="v8bis">V.8bis → V.8 · capabilities then menus</option>
      </select></label>
      {setup !== 'direct' && <span className="small">Experimental audio negotiation · payload training follows separately</span>}
      {setup === 'v8bis' && <label>Request initiated by <select aria-label="V.8bis initiator" value={config.bis_initiator ?? 'caller'} disabled={disabled}
        onChange={event => configure({bis_initiator: event.target.value as Endpoint})}>
        <option value="caller">Caller</option><option value="answerer">Answerer</option>
      </select></label>}
    </div>
    {setup !== 'direct' && <details className="capability-options">
      <summary>Device capabilities and examples</summary>
      <div className="capability-presets">
        <span className="small">Try:</span>
        <button disabled={disabled} onClick={() => configure({caller_capabilities: all, answerer_capabilities: all, caller_v8bis: true, answerer_v8bis: true})}>Both support V.22 family</button>
        <button disabled={disabled} onClick={() => configure({caller_capabilities: all, answerer_capabilities: []})}>Answerer offers no common family</button>
        <button disabled={disabled} onClick={() => configure({caller_capabilities: [], answerer_capabilities: all})}>Caller offers no common family</button>
        {setup === 'v8bis' && <button disabled={disabled} onClick={() => configure({caller_capabilities: all, answerer_capabilities: all, caller_v8bis: true, answerer_v8bis: false})}>Answerer without V.8bis</button>}
      </div>
      <div className="pair capability-pair">
        {endpoints.map(endpoint => {
          const key = `${endpoint}_capabilities` as 'caller_capabilities' | 'answerer_capabilities';
          const capabilities = config[key] ?? all;
          const support = `${endpoint}_v8bis` as 'caller_v8bis' | 'answerer_v8bis';
          return <fieldset key={endpoint} className={endpoint}>
            <legend>{names[endpoint]} offers</legend>
            <label><input type="checkbox" disabled={disabled}
              aria-label={`${names[endpoint]} supports V.22 family`}
              checked={capabilities.includes('v22')} onChange={event => configure({[key]: event.target.checked ? ['v22'] : []})} />V.22 / V.22bis family</label>
            {setup === 'v8bis' && <label><input type="checkbox" disabled={disabled}
              aria-label={`${names[endpoint]} supports V.8bis`} checked={config[support] ?? true}
              onChange={event => configure({[support]: event.target.checked})} />V.8bis capabilities exchange</label>}
          </fieldset>;
        })}
      </div>
      <p className="small">V.8 agrees a modem family; the 1200/2400 payload rate is preconfigured in this experimental lab. V.8bis proposes that payload mode before V.8. Changing setup clears the current call.</p>
      {setup === 'v8bis' && <p className="small">Implemented V.8bis subset: a post-pickup capabilities request (CRd), capability list, mode selection and ACK(1), followed by full V.8. Initiator and responder are separate from telephone caller and answerer.</p>}
    </details>}
  </section>;
}

function Message({message}: {message: NegotiationMessage}) {
  const signal = message.signal === 'CRd' ? 'CR' : message.signal?.replace(/\(.*\)$/, '') ?? '';
  return <div className="negotiation-message">
    <strong>{message.protocol} {message.signal} · {message.direction === 'tx' ? 'Transmitted' : 'Received'}</strong>
    {explanations[signal] && <p>{explanations[signal]}</p>}
    {message.validation && <p>Validation: {message.validation}{message.protocol === 'V.8' && ['CM', 'JM'].includes(message.signal ?? '') && message.repetitions !== undefined ? ` · ${message.repetitions} consistent repetitions` : ''}</p>}
    {message.reason && <p>{message.reason}</p>}
    {message.raw_hex && <div className="menu-bytes"><span className="small">Raw octets · hex</span><code>{message.raw_hex}</code></div>}
    {message.fields && <pre className="menu-fields">{JSON.stringify(message.fields, null, 2)}</pre>}
  </div>;
}

export function NegotiationInspector({config, negotiation, events, selected, selectEvent}: {
  config: Config; negotiation?: NegotiationState; events: LabEvent[]; selected: LabEvent | null; selectEvent: (event: LabEvent) => void;
}) {
  if ((config.call_setup_mode ?? 'direct') === 'direct') return null;
  const negotiationEvents = events.filter(event => event.negotiation || /negotiation|v8|menu|ansam|capabilit/.test(event.event_type));
  return <section className="panel negotiation-inspector" aria-label="Negotiation inspector">
    <div className="panel-head"><h2>Negotiation · capabilities → selection → training</h2><span className="small">Decoded from received audio</span></div>
    <div className="negotiation-result" role="status">
      <strong>{negotiation?.stage?.replaceAll('_', ' ') ?? 'Waiting for a call'}</strong>
      <span>{negotiation?.selected_profile ? `Selected: ${modeName(negotiation.selected_profile)}` : 'No payload mode selected yet'}</span>
      {negotiation?.outcome && <p>{negotiation.outcome}</p>}
    </div>
    <div className="pair negotiation-pair">
      {endpoints.map(endpoint => {
        const status = negotiation?.endpoints?.[endpoint];
        return <article key={endpoint} aria-label={`${names[endpoint]} negotiation`}>
          <h3>{names[endpoint]}</h3>
          <p>Local enabled families: {(config[`${endpoint}_capabilities`] ?? all).map(modeName).join(', ') || 'none'}</p>
          <p>Stage: {status?.stage?.replaceAll('_', ' ') ?? 'waiting'}</p>
          <p>Transmitting: {status?.tx_signal?.replaceAll('_', ' ') ?? '—'} · Last decoded control: {status?.rx_state ?? 'waiting for audio evidence'}</p>
          {status?.received && <p>Decoded remote offer: {status.received.map(modeName).join(', ') || 'none'}</p>}
          {status?.selected && <p>Selection: {modeName(status.selected)}</p>}
          {status?.v8bis_selected_profile && <p>V.8bis selected mode: {modeName(status.v8bis_selected_profile)}</p>}
          {status?.selected_family && <p>V.8 agreed family: {modeName(status.selected_family)}</p>}
          {status?.menu_hex && <div className="menu-bytes"><span className="small">Received menu · hex</span><code>{status.menu_hex}</code></div>}
          {status?.validation && <p>{status.validation} · repetitions {status.repetitions ?? 0}</p>}
        </article>;
      })}
    </div>
    {selected?.negotiation && <div className="selected-negotiation" aria-label="Selected negotiation message"><Message message={selected.negotiation} /></div>}
    <div className="negotiation-timeline" aria-label="Negotiation events">
      {negotiationEvents.length === 0 ? <p className="empty">Start a call to hear and inspect the capability exchange. Terminal traffic waits for modem training.</p> : negotiationEvents.slice().reverse().map((event, index) =>
        <button key={`${event.sample_index}-${index}`} className={`event ${event.endpoint} ${selected === event ? 'selected' : ''}`} onClick={() => selectEvent(event)}>
          <time>{(event.sample_index / 48000).toFixed(3)} s</time><span>{names[event.endpoint] ?? 'Line'}</span>
          <span>{event.negotiation ? `${event.negotiation.protocol ?? ''} ${event.negotiation.signal ?? ''} ${event.negotiation.direction ?? ''}` : event.event_type.replaceAll('_', ' ')}</span>
          <span className="event-detail">{event.detail}</span>
        </button>)}
    </div>
    <p className="negotiation-footnote">A completed menu exchange is separate from receiver lock and readiness for text. Select an event to align both graphs with its audio.</p>
  </section>;
}

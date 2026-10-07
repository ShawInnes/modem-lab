const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const code = fs.readFileSync(require('node:path').join(__dirname, '../public/audio-worklet.js'), 'utf8');
for (const rate of [44100, 48000, 96000]) {
  let Processor;
  class Base { constructor() { this.port = { onmessage: null, postMessage: () => {} }; } }
  vm.runInNewContext(code, { AudioWorkletProcessor: Base, sampleRate: rate, Float32Array,
    registerProcessor: (_, p) => { Processor = p; } });
  const p = new Processor({ processorOptions: { sourceRate: 48000 } });
  p.message({ type:'reset', generation:3, epoch:2, sourceSample:0, underruns:0, status:'rebuffering' });
  p.message({ type:'pcm', generation:2, epoch:2, startSample:0, pcm:new Float32Array(10000) });
  assert.equal(p.count, 0, 'stale generation ignored');
  p.message({ type:'pcm', generation:3, epoch:2, startSample:5000, pcm:new Float32Array(10000).fill(.25) });
  for (let n=0;n<20;n++) p.process([], [[new Float32Array(128)]]);
  assert.equal(p.status, 'playing');
  assert.ok(Math.abs(p.sourceSample + p.fraction - (5000 + 2560 * 48000 / rate)) < 1e-7, 'resampling cursor');
  for (let n=0;n<300;n++) p.process([], [[new Float32Array(128)]]);
  assert.equal(p.underruns,1);
  const silence = new Float32Array(128); p.process([], [[silence]]);
  assert.ok(silence.every(x => x === 0), 'underrun silence');
  p.message({ type:'pcm', generation:3, epoch:2, startSample:15000, pcm:new Float32Array(20000) });
  p.message({ type:'pcm', generation:3, epoch:2, startSample:35000, pcm:new Float32Array(10000) });
  assert.equal(p.status,'rebuffering — backlog cleared');
  assert.equal(p.count,10000);
  assert.equal(p.sourceSample,35000);
}
console.log('AudioWorklet checks pass at 44.1, 48 and 96 kHz: source position, stale frames, underrun silence, bounded backlog.');

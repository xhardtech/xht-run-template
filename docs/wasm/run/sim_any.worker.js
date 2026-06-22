// Generic config-driven Web Worker for the port-aware WASM pipeline.
// Reads ?top=<top>, fetches <top>.config.json, imports V<top>.mjs, wires up
// sim_reset/sim_step + every get_<out>/set_<in> by name, free-runs the clock,
// and streams {values, cycles, cycles_per_sec} per tick. No server compute.
const params = new URLSearchParams(self.location.search);
const top = params.get('top') || 'counter_en';
// ?base=/wasm/<jobId> lets one shared worker serve any published artifact dir;
// defaults to '.' so the in-tree poc_any.html still works unchanged.
const base = (params.get('base') || '.').replace(/\/$/, '');

const cfg = await (await fetch(`${base}/${top}.config.json`)).json();
const createModule = (await import(`${base}/V${top}.mjs`)).default;
const Mod = await createModule();

const sim_reset = Mod.cwrap('sim_reset', null, []);
const sim_step  = Mod.cwrap('sim_step', null, ['number']);
const getters = {};
for (const o of cfg.outputs) getters[o.name] = Mod.cwrap(o.getter, 'number', []);
const setters = {};
for (const s of (cfg.inputs_settable || [])) setters[s.name] = Mod.cwrap(s.setter, null, ['number']);

// Pick sensible defaults so something visibly runs:
//  - if there's an explicit enable 'en', turn it on; 'up' -> count up.
//  - counter_en has no named reset/enable: io_in[1]=en, so set io_in=2.
function driveDefaults() {
  if (setters.en) setters.en(1);
  if (setters.up) setters.up(1);
  if (setters.io_in && !setters.en) setters.io_in(0x02); // counter_en: rst=0,en=1
}

const BATCH = 20000;
let running = false, cycles = 0, t0 = 0;

function readAll() {
  const v = {};
  for (const o of cfg.outputs) v[o.name] = getters[o.name]() >>> 0;
  return v;
}

function loop() {
  if (!running) return;
  for (let i = 0; i < 50; i++) { sim_step(BATCH); cycles += BATCH; }
  const wall = (performance.now() - t0) / 1000;
  postMessage({ type: 'tick', values: readAll(), cycles,
                cycles_per_sec: wall > 0 ? cycles / wall : 0 });
  setTimeout(loop, 0);
}

onmessage = (e) => {
  const cmd = e.data && e.data.cmd;
  if (cmd === 'start') {
    sim_reset(); driveDefaults();
    cycles = 0; t0 = performance.now(); running = true;
    postMessage({ type: 'started' });
    loop();
  } else if (cmd === 'stop') {
    running = false; postMessage({ type: 'stopped' });
  } else if (cmd === 'reset') {
    sim_reset(); driveDefaults(); cycles = 0; t0 = performance.now();
    postMessage({ type: 'tick', values: readAll(), cycles: 0, cycles_per_sec: 0 });
  }
};

postMessage({ type: 'ready', top, outputs: cfg.outputs });

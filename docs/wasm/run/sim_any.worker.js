// Generic config-driven Web Worker for the port-aware WASM pipeline.
// Reads ?top=<top>, fetches <top>.config.json, imports V<top>.mjs, wires up
// sim_reset/sim_step + every get_<out>/set_<in> by name, free-runs the clock,
// and streams {values, cycles, cycles_per_sec} per tick. No server compute.
//
// Two extra modes (config-driven, additive):
//   * TERMINAL: if cfg.terminal, drain UART TX bytes each tick -> {type:'uart',bytes};
//     accept {cmd:'input',bytes} -> uart_rx_push (keystrokes -> the design's RX).
//   * WAVEFORM: {cmd:'wave',n} -> reset+drive defaults, capture n cycles of EVERY port
//     via wave_run() (one low-32 sample/cycle), and post {type:'wave',signals,...}.
const params = new URLSearchParams(self.location.search);
const top = params.get('top') || 'counter_en';
const base = (params.get('base') || '.').replace(/\/$/, '');

const cfg = await (await fetch(`${base}/${top}.config.json`)).json();
const createModule = (await import(`${base}/V${top}.mjs`)).default;
const Mod = await createModule();

const sim_reset = Mod.cwrap('sim_reset', null, []);
const sim_step  = Mod.cwrap('sim_step', null, ['number']);
// wave_run may be absent in artifacts built before the waveform feature — degrade gracefully.
const HAS_WAVE  = typeof Mod._wave_run === 'function';
const wave_run  = HAS_WAVE ? Mod.cwrap('wave_run', 'number', ['number']) : null;
const TERM = !!cfg.terminal;
const uart_pop = TERM ? Mod.cwrap('uart_pop', 'number', []) : null;
const uart_rx_push = (TERM && cfg.uart && cfg.uart.rx_valid) ? Mod.cwrap('uart_rx_push', null, ['number']) : null;
const getters = {};
for (const o of cfg.outputs) getters[o.name] = Mod.cwrap(o.getter, 'number', []);
const setters = {};
for (const s of (cfg.inputs_settable || [])) setters[s.name] = Mod.cwrap(s.setter, null, ['number']);

// Pick sensible defaults so something visibly runs.
function driveDefaults() {
  if (setters.en) setters.en(1);
  if (setters.up) setters.up(1);
  if (setters.io_in && !setters.en) setters.io_in(0x02); // counter_en: rst=0,en=1
}

const BATCH = 20000;
let running = false, cycles = 0, t0 = 0;
// Keystrokes are queued and fed ONE byte per loop iteration (not all at once): a CPU SoC needs
// many cycles to poll+read each RX byte, so feeding faster would overwrite the holding register.
let rxQueue = [];

function readAll() {
  const v = {};
  for (const o of cfg.outputs) v[o.name] = getters[o.name]() >>> 0;
  return v;
}
function drainUart() {
  if (!uart_pop) return;
  const bytes = []; let b, cap = 8192;
  while (cap-- > 0 && (b = uart_pop()) >= 0) bytes.push(b);
  if (bytes.length) postMessage({ type: 'uart', bytes });
}

function loop() {
  if (!running) return;
  if (uart_rx_push && rxQueue.length) uart_rx_push(rxQueue.shift()); // pace RX: 1 byte per iteration
  for (let i = 0; i < 50; i++) { sim_step(BATCH); cycles += BATCH; }
  drainUart();
  const wall = (performance.now() - t0) / 1000;
  postMessage({ type: 'tick', values: readAll(), cycles, cycles_per_sec: wall > 0 ? cycles / wall : 0 });
  setTimeout(loop, 0);
}

// Cycle-accurate waveform snapshot: reset, drive defaults, run n cycles capturing every
// port's low-32 value each cycle, then hand the per-signal sample arrays to the runner.
function captureWave(n) {
  running = false;                       // pause free-run (a pending loop() will no-op)
  const NP = (cfg.ports || []).length;
  n = Math.max(1, Math.min(n || 128, cfg.wave_max || 512));
  sim_reset(); driveDefaults();
  const ptr = wave_run(n) >>> 0;
  const base32 = ptr >>> 2;
  const H = Mod.HEAPU32;
  const signals = (cfg.ports || []).map((p, j) => {
    const samples = new Array(n);
    for (let i = 0; i < n; i++) samples[i] = H[base32 + i * NP + j] >>> 0;
    return { name: p.name, dir: p.dir, width: p.width, samples };
  });
  postMessage({ type: 'wave', n, clock: cfg.clock, reset: cfg.reset, signals });
  sim_reset(); driveDefaults();          // leave the model clean & ready
  postMessage({ type: 'stopped' });
}

onmessage = (e) => {
  const m = e.data || {}; const cmd = m.cmd;
  if (cmd === 'start') {
    sim_reset(); driveDefaults();
    cycles = 0; t0 = performance.now(); running = true;
    postMessage({ type: 'started' });
    loop();
  } else if (cmd === 'stop') {
    running = false; postMessage({ type: 'stopped' });
  } else if (cmd === 'reset') {
    sim_reset(); driveDefaults(); cycles = 0; t0 = performance.now();
    if (TERM) postMessage({ type: 'uartclear' });
    postMessage({ type: 'tick', values: readAll(), cycles: 0, cycles_per_sec: 0 });
  } else if (cmd === 'input') {
    if (uart_rx_push && Array.isArray(m.bytes)) for (const b of m.bytes) rxQueue.push(b & 0xff);
  } else if (cmd === 'wave') {
    captureWave(m.n);
  }
};

postMessage({ type: 'ready', top, outputs: cfg.outputs, terminal: TERM,
              hasInput: !!uart_rx_push, ports: cfg.ports || [], clock: cfg.clock });

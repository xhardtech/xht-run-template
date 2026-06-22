#!/usr/bin/env python3
"""Port-aware, design-agnostic harness codegen for the Verilator->WASM pipeline.

Reads a Verilator --xml-only XML for a single top module, extracts the top's
ports (name, direction, width), and emits:
  * sim_main_<top>_wasm.cpp : an EMSCRIPTEN harness exposing extern "C":
        void sim_reset();
        void sim_step(int n);
        unsigned get_<outport>();          (one per output port; low 32 bits)
        void set_<inport>(unsigned v);      (one per non-clk/non-reset input)
        unsigned* wave_run(int n);          (cycle-accurate capture of all ports)
        int  uart_pop();                    (terminal designs: drain one TX byte, -1 if none)
        void uart_rx_push(unsigned v);      (terminal designs: queue one RX byte)
  * <top>.config.json        : run-config the frontend uses to render outputs.
  * <top>.exports.txt        : comma list of _-prefixed exported funcs for emcc.

Clock detection : port name in CLK_NAMES.
Reset detection : port name in RESET_NAMES; active level inferred from name.

UART terminal: if the top exposes a byte-level UART (output uart_tx_valid + uart_tx
[+ optional input uart_rx_valid + uart_rx]), the harness captures TX bytes into a ring
buffer (drained by uart_pop) and feeds queued RX bytes one-per-cycle (uart_rx_push),
and config gets "terminal":true so the runner renders an xterm.js terminal.

Waveform: wave_run(n) re-runs n (<=512) cycles FROM RESET, recording every port's low-32
value per cycle into a static buffer, and returns its pointer; the runner reads HEAPU32 and
draws a cycle-accurate timing diagram (FireSim/GTKWave-style, in-browser).

Wide ports (>32 bits): getter returns the LOW 32 bits only ("truncated":true).
"""
import sys, os, json
import xml.etree.ElementTree as ET

CLK_NAMES   = {"clk", "clock", "i_clk", "clk_i", "iclk"}
RESET_NAMES = {"rst", "reset", "rstn", "resetn", "rst_n", "i_rst", "rst_i",
               "reset_n", "i_rstn", "arst", "arstn"}
WAVE_MAX = 512  # cycles captured per waveform snapshot

def active_low(name):
    n = name.lower()
    return n.endswith("n") or "rstn" in n or "resetn" in n or "rst_n" in n or "reset_n" in n

def parse_ports(xml_path, top):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    types = {}
    for tt in root.iter("typetable"):
        for dt in tt:
            tid = dt.get("id")
            if tid is None:
                continue
            ent = {"tag": dt.tag, "left": dt.get("left"), "right": dt.get("right")}
            ent["sub"] = dt.get("sub_dtype_id")
            rng = dt.find("range")
            if rng is not None:
                consts = rng.findall("const")
                ent["range_consts"] = [c.get("name") for c in consts]
            types[tid] = ent

    def const_to_int(s):
        if s is None:
            return None
        try:
            if "'h" in s:
                return int(s.split("'h")[1], 16)
            if "'d" in s:
                return int(s.split("'d")[1], 10)
            if "'b" in s:
                return int(s.split("'b")[1], 2)
            return int(s)
        except Exception:
            return None

    def width_of(tid, _depth=0):
        if tid is None or _depth > 8:
            return 1
        ent = types.get(tid)
        if ent is None:
            return 1
        tag = ent["tag"]
        if tag in ("basicdtype",):
            l, r = ent["left"], ent["right"]
            if l is None or r is None:
                return 1
            return abs(int(l) - int(r)) + 1
        if tag in ("packarraydtype", "unpackarraydtype"):
            sub_w = width_of(ent.get("sub"), _depth + 1)
            rc = ent.get("range_consts")
            if rc and len(rc) >= 2:
                a = const_to_int(rc[0]); b = const_to_int(rc[1])
                if a is not None and b is not None:
                    return (abs(a - b) + 1) * sub_w
            return sub_w
        if ent.get("sub"):
            return width_of(ent.get("sub"), _depth + 1)
        l, r = ent["left"], ent["right"]
        if l is not None and r is not None:
            return abs(int(l) - int(r)) + 1
        return 1

    mod = None
    for m in root.iter("module"):
        if m.get("name") == top or m.get("topModule") == "1":
            if m.get("name") == top or mod is None:
                mod = m
            if m.get("name") == top:
                break
    if mod is None:
        raise SystemExit(f"top module {top} not found in XML")

    ports = []
    for v in mod.findall("var"):
        d = v.get("dir")
        if d not in ("input", "output", "inout"):
            continue
        ports.append({"name": v.get("name"), "dir": d, "width": width_of(v.get("dtype_id"))})
    return ports

def classify(ports):
    clk = rst = None
    for p in ports:
        if p["dir"] == "input" and p["name"].lower() in CLK_NAMES and clk is None:
            clk = p
    for p in ports:
        if p["dir"] == "input" and p["name"].lower() in RESET_NAMES and rst is None:
            rst = p
    return clk, rst

def find_uart(ports):
    """Detect a byte-level UART by conventional port names. Returns dict or None."""
    out_by = {p["name"]: p for p in ports if p["dir"] in ("output", "inout")}
    in_by  = {p["name"]: p for p in ports if p["dir"] == "input"}
    TXV = ["uart_tx_valid", "tx_valid", "uart_valid", "o_uart_tx_valid", "o_tx_valid"]
    TXD = ["uart_tx", "tx_data", "uart_data", "tx_byte", "o_uart_tx"]
    RXV = ["uart_rx_valid", "rx_valid", "i_uart_rx_valid", "i_rx_valid"]
    RXD = ["uart_rx", "rx_data", "rx_byte", "i_uart_rx"]
    def pick(names, d):
        for n in names:
            if n in d:
                return n
        return None
    txv, txd = pick(TXV, out_by), pick(TXD, out_by)
    if not (txv and txd):
        return None
    rxv, rxd = pick(RXV, in_by), pick(RXD, in_by)
    return {"tx_valid": txv, "tx_data": txd,
            "rx_valid": rxv if (rxv and rxd) else None,
            "rx_data":  rxd if (rxv and rxd) else None}

def _read_low32(name, width):
    if width > 64:
        return f"(unsigned)g_top->{name}[0]"
    return f"(unsigned)(g_top->{name} & 0xffffffffu)"

def emit_cpp(top, ports, clk, rst, uart):
    txv = uart["tx_valid"] if uart else None
    txd = uart["tx_data"] if uart else None
    rxv = uart["rx_valid"] if uart else None
    rxd = uart["rx_data"] if uart else None
    uart_names = set()
    if uart:
        uart_names = {txv, txd}
        if rxv:
            uart_names |= {rxv, rxd}
    outs = [p for p in ports if p["dir"] in ("output", "inout") and p["name"] not in uart_names]
    setters = [p for p in ports if p["dir"] == "input"
               and (clk is None or p["name"] != clk["name"])
               and (rst is None or p["name"] != rst["name"])
               and p["name"] not in uart_names]
    NP = len(ports)
    L = []
    a = L.append
    a(f'// AUTO-GENERATED port-aware WASM harness for top module "{top}".')
    a('// Generated by gen_harness.py -- do not edit by hand.')
    a(f'#include "V{top}.h"')
    a('#include "verilated.h"')
    a('#include <emscripten/emscripten.h>')
    a('')
    a(f'static V{top}* g_top = nullptr;')
    a(f'static unsigned g_wave[{WAVE_MAX} * {NP if NP else 1}];  // [cycle][port] low-32 capture')
    if uart:
        a('// ---- UART terminal byte ring buffers (64 KiB each) ----')
        a('static unsigned char g_tx[1<<16]; static unsigned g_txh=0, g_txt=0;')
        a('static inline void tx_push(unsigned char b){ unsigned nh=(g_txh+1)&0xffffu; if(nh!=g_txt){ g_tx[g_txh]=b; g_txh=nh; } }')
        if rxv:
            a('static unsigned char g_rx[1<<16]; static unsigned g_rxh=0, g_rxt=0;')
    a('')
    # helper that advances one clock cycle (feeds RX, captures TX)
    a('static inline void step_one() {')
    if rxv:
        a(f'    g_top->{rxv} = 0;')
        a('    if (g_rxt != g_rxh) {')
        a(f'        g_top->{rxd} = g_rx[g_rxt]; g_rxt=(g_rxt+1)&0xffffu; g_top->{rxv} = 1;')
        a('    }')
    if clk:
        a(f'    g_top->{clk["name"]} = 0; g_top->eval();')
        a(f'    g_top->{clk["name"]} = 1; g_top->eval();')
    else:
        a('    g_top->eval();')
    if uart:
        a(f'    if (g_top->{txv}) tx_push((unsigned char)(g_top->{txd} & 0xffu));')
    a('}')
    a('')
    a('extern "C" {')
    a('')
    # sim_reset
    a('EMSCRIPTEN_KEEPALIVE')
    a('void sim_reset() {')
    a('    if (g_top) { delete g_top; g_top = nullptr; }')
    a(f'    g_top = new V{top};')
    if uart:
        a('    g_txh = g_txt = 0;')
        if rxv:
            a('    g_rxh = g_rxt = 0;')
    if clk:
        a(f'    g_top->{clk["name"]} = 0;')
    if rst:
        asserted = 0 if active_low(rst["name"]) else 1
        deasserted = 1 - asserted
        a(f'    g_top->{rst["name"]} = {asserted};  // assert reset')
        a('    g_top->eval();')
        if clk:
            a('    for (int i = 0; i < 20; i++) {')
            a(f'        g_top->{clk["name"]} = !g_top->{clk["name"]};')
            a('        g_top->eval();')
            a('    }')
        a(f'    g_top->{rst["name"]} = {deasserted};  // release reset')
        a('    g_top->eval();')
    else:
        a('    g_top->eval();')
    a('}')
    a('')
    # sim_step
    a('EMSCRIPTEN_KEEPALIVE')
    a('void sim_step(int n) {')
    a('    if (!g_top) sim_reset();')
    a('    for (int i = 0; i < n; i++) step_one();')
    a('}')
    a('')
    # wave_run: capture n cycles FROM RESET into g_wave, return pointer
    a('EMSCRIPTEN_KEEPALIVE')
    a('unsigned* wave_run(int n) {')
    a(f'    if (n < 1) n = 1; if (n > {WAVE_MAX}) n = {WAVE_MAX};')
    a('    if (!g_top) sim_reset();  // capture from the CURRENT (caller-driven) state')
    a('    for (int i = 0; i < n; i++) {')
    a('        step_one();')
    a(f'        unsigned* row = &g_wave[i * {NP if NP else 1}];')
    for idx, p in enumerate(ports):
        a(f'        row[{idx}] = {_read_low32(p["name"], p["width"])};')
    a('    }')
    a('    return g_wave;')
    a('}')
    a('')
    # uart drain / push
    if uart:
        a('EMSCRIPTEN_KEEPALIVE')
        a('int uart_pop() {')
        a('    if (g_txt == g_txh) return -1;')
        a('    unsigned char b = g_tx[g_txt]; g_txt=(g_txt+1)&0xffffu; return (int)b;')
        a('}')
        a('')
        if rxv:
            a('EMSCRIPTEN_KEEPALIVE')
            a('void uart_rx_push(unsigned v) {')
            a('    unsigned nh=(g_rxh+1)&0xffffu; if(nh!=g_rxt){ g_rx[g_rxh]=(unsigned char)(v&0xffu); g_rxh=nh; }')
            a('}')
            a('')
    # output getters
    for p in outs:
        a('EMSCRIPTEN_KEEPALIVE')
        a(f'unsigned get_{p["name"]}() {{')
        a('    if (!g_top) return 0u;')
        a(f'    return {_read_low32(p["name"], p["width"])};')
        a('}')
        a('')
    # input setters
    for p in setters:
        a('EMSCRIPTEN_KEEPALIVE')
        a(f'void set_{p["name"]}(unsigned v) {{')
        a('    if (!g_top) sim_reset();')
        if p["width"] > 64:
            a(f'    g_top->{p["name"]}[0] = v;')
        else:
            a(f'    g_top->{p["name"]} = v;')
        a('    g_top->eval();')
        a('}')
        a('')
    a('} // extern "C"')
    a('')
    return "\n".join(L), outs, setters

def main():
    if len(sys.argv) < 4:
        print("usage: gen_harness.py <xml> <top> <outdir>", file=sys.stderr)
        sys.exit(2)
    xml_path, top, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
    ports = parse_ports(xml_path, top)
    clk, rst = classify(ports)
    uart = find_uart(ports)
    cpp, outs, setters = emit_cpp(top, ports, clk, rst, uart)

    with open(os.path.join(outdir, f"sim_main_{top}_wasm.cpp"), "w") as f:
        f.write(cpp)

    cfg = {
        "top": top,
        "clock": clk["name"] if clk else None,
        "reset": rst["name"] if rst else None,
        "reset_active_low": (active_low(rst["name"]) if rst else None),
        "terminal": bool(uart),
        "uart": ({"tx_valid": uart["tx_valid"], "tx_data": uart["tx_data"],
                  "rx_valid": uart["rx_valid"], "rx_data": uart["rx_data"]} if uart else None),
        "outputs": [{"name": p["name"], "width": p["width"],
                     "truncated": p["width"] > 32, "getter": f"get_{p['name']}"} for p in outs],
        "inputs_settable": [{"name": p["name"], "width": p["width"],
                             "setter": f"set_{p['name']}"} for p in setters],
        "ports": ports,
        "wave_max": WAVE_MAX,
    }
    with open(os.path.join(outdir, f"{top}.config.json"), "w") as f:
        json.dump(cfg, f, indent=2)

    exports = ["_sim_reset", "_sim_step", "_wave_run"]
    if uart:
        exports.append("_uart_pop")
        if uart["rx_valid"]:
            exports.append("_uart_rx_push")
    exports += [f"_get_{p['name']}" for p in outs]
    exports += [f"_set_{p['name']}" for p in setters]
    exports += ["_malloc", "_free"]
    with open(os.path.join(outdir, f"{top}.exports.txt"), "w") as f:
        f.write(",".join(exports))

    print(f"top={top} clk={clk['name'] if clk else 'NONE'} "
          f"rst={rst['name'] if rst else 'NONE'} terminal={bool(uart)} "
          f"outputs={[p['name'] for p in outs]} settable_inputs={[p['name'] for p in setters]}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Port-aware, design-agnostic harness codegen for the Verilator->WASM pipeline.

Reads a Verilator --xml-only XML for a single top module, extracts the top's
ports (name, direction, width), and emits:
  * sim_main_<top>_wasm.cpp : an EMSCRIPTEN harness exposing extern "C":
        void sim_reset();
        void sim_step(int n);
        unsigned get_<outport>();          (one per output port; low 32 bits)
        void set_<inport>(unsigned v);      (one per non-clk/non-reset input)
  * <top>.config.json        : run-config the frontend uses to render outputs.
  * <top>.exports.txt        : comma list of _-prefixed exported funcs for emcc.

Clock detection : port name in CLK_NAMES.
Reset detection : port name in RESET_NAMES; active level inferred from name
                  (names ending n / containing 'rstn'/'resetn'/'rst_n' are
                  active-low, asserted = 0; otherwise active-high, asserted = 1).

Wide ports (>32 bits): getter returns the LOW 32 bits only (documented in the
config JSON via "truncated":true). Verilator stores >64b vars as word arrays;
we read element [0] (the least-significant word) for those.
"""
import sys, os, json
import xml.etree.ElementTree as ET

CLK_NAMES   = {"clk", "clock", "i_clk", "clk_i", "iclk"}
RESET_NAMES = {"rst", "reset", "rstn", "resetn", "rst_n", "i_rst", "rst_i",
               "reset_n", "i_rstn", "arst", "arstn"}

def active_low(name):
    n = name.lower()
    return n.endswith("n") or "rstn" in n or "resetn" in n or "rst_n" in n or "reset_n" in n

def parse_ports(xml_path, top):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Build dtype_id -> width(bits) map from the typetable.
    # basicdtype: width = left-right+1 if left present else 1.
    # packarraydtype / unpackarraydtype: range * subdtype width.
    types = {}      # id -> dict(kind, left, right, sub)
    for tt in root.iter("typetable"):
        for dt in tt:
            tid = dt.get("id")
            if tid is None:
                continue
            ent = {"tag": dt.tag, "left": dt.get("left"), "right": dt.get("right")}
            # array types carry a sub-dtype and a range child
            ent["sub"] = dt.get("sub_dtype_id")
            # range may be a child <range><const.../><const.../></range>
            rng = dt.find("range")
            if rng is not None:
                consts = rng.findall("const")
                ent["range_consts"] = [c.get("name") for c in consts]
            types[tid] = ent

    def const_to_int(s):
        # verilator const names like "32'h7" or "6'h1f"
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
        # refdtype or others: try sub
        if ent.get("sub"):
            return width_of(ent.get("sub"), _depth + 1)
        l, r = ent["left"], ent["right"]
        if l is not None and r is not None:
            return abs(int(l) - int(r)) + 1
        return 1

    # find the top module
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
        name = v.get("name")
        w = width_of(v.get("dtype_id"))
        ports.append({"name": name, "dir": d, "width": w})
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

def emit_cpp(top, ports, clk, rst):
    outs = [p for p in ports if p["dir"] in ("output", "inout")]
    # generic input setters: all inputs that are not clk and not reset
    setters = [p for p in ports if p["dir"] == "input"
               and (clk is None or p["name"] != clk["name"])
               and (rst is None or p["name"] != rst["name"])]
    L = []
    a = L.append
    a(f'// AUTO-GENERATED port-aware WASM harness for top module "{top}".')
    a('// Generated by gen_harness.py -- do not edit by hand.')
    a(f'#include "V{top}.h"')
    a('#include "verilated.h"')
    a('#include <emscripten/emscripten.h>')
    a('')
    a(f'static V{top}* g_top = nullptr;')
    a('')
    a('extern "C" {')
    a('')
    # sim_reset
    a('EMSCRIPTEN_KEEPALIVE')
    a('void sim_reset() {')
    a('    if (g_top) { delete g_top; g_top = nullptr; }')
    a(f'    g_top = new V{top};')
    if clk:
        a(f'    g_top->{clk["name"]} = 0;')
    if rst:
        asserted = 0 if active_low(rst["name"]) else 1
        deasserted = 1 - asserted
        a(f'    g_top->{rst["name"]} = {asserted};  // assert reset')
        a('    g_top->eval();')
        if clk:
            a('    for (int i = 0; i < 20; i++) {  // ~10 clocks held in reset')
            a(f'        g_top->{clk["name"]} = !g_top->{clk["name"]};')
            a('        g_top->eval();')
            a('    }')
        a(f'    g_top->{rst["name"]} = {deasserted};  // release reset')
        a('    g_top->eval();')
    else:
        a('    g_top->eval();')
        a('    // No named reset port detected; model starts from Verilator defaults.')
    a('}')
    a('')
    # sim_step
    a('EMSCRIPTEN_KEEPALIVE')
    a('void sim_step(int n) {')
    a('    if (!g_top) sim_reset();')
    if clk:
        a('    for (int i = 0; i < n; i++) {')
        a(f'        g_top->{clk["name"]} = 0; g_top->eval();')
        a(f'        g_top->{clk["name"]} = 1; g_top->eval();')
        a('    }')
    else:
        a('    // No clock port detected: combinational/async design; just eval n times.')
        a('    for (int i = 0; i < n; i++) g_top->eval();')
    a('}')
    a('')
    # output getters
    for p in outs:
        a('EMSCRIPTEN_KEEPALIVE')
        a(f'unsigned get_{p["name"]}() {{')
        a('    if (!g_top) return 0u;')
        if p["width"] > 64:
            # WData array (uint32 words); element [0] is the low word
            a(f'    return (unsigned)g_top->{p["name"]}[0];  // low 32 of {p["width"]}-bit port')
        else:
            a(f'    return (unsigned)(g_top->{p["name"]} & 0xffffffffu);')
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
    cpp, outs, setters = emit_cpp(top, ports, clk, rst)

    cpp_path = os.path.join(outdir, f"sim_main_{top}_wasm.cpp")
    with open(cpp_path, "w") as f:
        f.write(cpp)

    cfg = {
        "top": top,
        "clock": clk["name"] if clk else None,
        "reset": rst["name"] if rst else None,
        "reset_active_low": (active_low(rst["name"]) if rst else None),
        "outputs": [{"name": p["name"], "width": p["width"],
                     "truncated": p["width"] > 32, "getter": f"get_{p['name']}"} for p in outs],
        "inputs_settable": [{"name": p["name"], "width": p["width"],
                             "setter": f"set_{p['name']}"} for p in setters],
        "ports": ports,
    }
    cfg_path = os.path.join(outdir, f"{top}.config.json")
    with open(cfg_path, "w") as f:
        json.dump(cfg, f, indent=2)

    exports = ["_sim_reset", "_sim_step"]
    exports += [f"_get_{p['name']}" for p in outs]
    exports += [f"_set_{p['name']}" for p in setters]
    exports += ["_malloc", "_free"]
    exp_path = os.path.join(outdir, f"{top}.exports.txt")
    with open(exp_path, "w") as f:
        f.write(",".join(exports))

    # status to stdout for the build script / logs
    print(f"top={top} clk={clk['name'] if clk else 'NONE'} "
          f"rst={rst['name'] if rst else 'NONE'} "
          f"outputs={[p['name'] for p in outs]} "
          f"settable_inputs={[p['name'] for p in setters]}")

if __name__ == "__main__":
    main()

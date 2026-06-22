# Run on XhardTech — template

Fork this repo and your Verilog/SystemVerilog design builds to **WebAssembly** and runs
**client-side in your browser** — built by *your own* GitHub Actions, served from *your own*
GitHub Pages. No server, no account on our side runs your code.

[![Run on XhardTech](https://xhardtech.com/run/badge.svg)](https://xhardtech.com/run?template=xhardtech/xht-run-template)

## How it works
1. **Use this template** (or click *Run on XhardTech*) → you get `USER/xht-<name>` in your account.
2. Edit [`xht.json`](xht.json) to point at your design, or leave `"design_repo": "self"` to build
   the bundled [`examples/lfsr8.v`](examples/lfsr8.v) demo.
3. The **build-wasm** Action runs on push → compiles with Verilator → Emscripten and publishes to
   `docs/wasm/run/<top>/`.
4. Enable **Pages** (Settings → Pages → *Deploy from branch*, `main` / `/docs`). Your design is then
   live at `https://<you>.github.io/<repo>/wasm/run/runner.html?top=<top>&base=/<repo>/wasm/run/<top>`.

## xht.json
```json
{ "design_repo": "self", "top": "lfsr8", "rtl": "examples/lfsr8.v" }
```
- `design_repo` — `"self"` (build the RTL in this repo) or a `github.com`/`gitlab.com` https URL.
- `top` — top module name.
- single file: `"rtl": "path/to/top.v"` · multi-file CPU: `"srcdir": "rtl"` or `"filelist": "files.f"`.
- `$readmemh`/`$readmemb` ROM data is auto-detected; override with `"hex": "prog.hex"`.

## What runs where
| Step | Where |
|------|-------|
| Build (Verilator → wasm) | **your** GitHub Actions runner |
| Hosting | **your** GitHub Pages |
| Execution | **your visitors'** browsers (WebAssembly, single-thread) |

XhardTech only orchestrates the one-time setup. The repo, the CI minutes, and the site are yours.

## Constraints
Pure synthesizable RTL. The security scan rejects `$system`/`$fopen`/`$fwrite`/DPI/`$c(...)`/absolute
includes. Single-clock-domain combinational+sequential designs simulate fastest.

---
Tooling under `tools/wasm/` and the runner under `docs/wasm/run/` are MIT-licensed (see `LICENSE`).
Designs you build carry **their own** licenses.

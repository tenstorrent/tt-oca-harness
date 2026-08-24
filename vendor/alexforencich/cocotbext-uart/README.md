# Vendored: cocotbext-uart

UART source/sink models for cocotb (`cocotbext.uart.UartSource` /
`cocotbext.uart.UartSink`), consumed by the shared OCAH UART VIP
(`hw/common/dv/vip/ocah_uart_vip`, classes `OcahUartConsole` /
`OcahUartMonitor`).

## Provenance

| Field    | Value |
|----------|-------|
| Project  | <https://github.com/alexforencich/cocotbext-uart> |
| Version  | 0.1.4 (PyPI sdist) |
| Source   | <https://pypi.org/project/cocotbext-uart/0.1.4/> |
| sha256   | `574643c82067be5e1dd6e2e830f46b8803c07fc1f27b7f75bf25066fd6d06798` (`cocotbext_uart-0.1.4.tar.gz`) |
| License  | MIT (`upstream/LICENSE`) |

The package is vendored rather than pulled from PyPI so that the locked DV
environment resolves entirely from the repository (license review applies to
in-repo sources; the PyPI distribution's license metadata is not
machine-verifiable) and so the cocotb 2.0 compatibility patch below can be
carried until it lands upstream.

## Layout

- `upstream/` — the sdist contents with the patches below applied. Generated
  build metadata (`PKG-INFO`, `*.egg-info/`) and upstream CI configuration
  (`.github/`) are not vendored. Do not hand-edit `upstream/`; record every
  local delta as a patch in `patches/`.
- `patches/` — local deltas versus the pristine sdist, already applied to
  `upstream/`:
  - `0001-cocotb2-handle-path.patch` — cocotb 2.0 removed
    `SimHandleBase._path`, which both `UartSource.__init__` and
    `UartSink.__init__` use for their logger names; fall back to `_name`.

## Consumption

`hw/common/dv/pyproject.toml` declares the `cocotbext-uart` dependency and
resolves it to this directory through a `[tool.uv.sources]` path entry, so
`uv sync --locked --group dv` builds the distribution from `upstream/`
without network access.

## Updating

1. Replace `upstream/` with the new sdist contents, minus the exclusions
   listed above.
2. Re-apply the patches in `patches/` (drop any that landed upstream) and
   regenerate the patch files against the new pristine sdist.
3. Update the provenance table above (version, source URL, sha256).
4. Refresh the lockfile (`uv lock`) and the version references in
   `hw/common/dv/vip/ocah_uart_vip/` and `hw/common/dv/pyproject.toml`.

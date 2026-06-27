# DRBG Wrapper

`hw/comp/drbg` wraps the existing `csrng` and `edn` blocks behind one
single-clock DRBG-oriented interface. The wrapper adds only glue logic:

- producer-driven 32-bit entropy ingress with distribution-first routing
- 32-to-384 CSRNG seed packing with queued `es_fips = 1'b1`
- per-endpoint EDN req/ack to AXI-Stream buffering
- separate 64-bit AXI-Lite control ports for wrapped CSRNG and EDN CSRs

## Parameters

| Parameter | Default | Meaning |
|------|---------|---------|
| `INGRESS_FIFO_DEPTH` | `12` | Shared depth of the distribution and CSRNG-word ingress FIFOs |
| `SEED_FIFO_DEPTH` | `1` | Number of complete CSRNG seeds that can be queued |
| `EDN_ENDPOINT_COUNT` | `1` | Number of exposed EDN endpoint AXI-Stream outputs |
| `ENDPOINT_FIFO_DEPTH` | `8` | FIFO depth per endpoint AXI-Stream output |

## Interfaces

### Entropy ingress

- `entropy_stream_data_i[31:0]`
- `entropy_stream_vld_i`

The wrapper samples `entropy_stream_data_i` only when `entropy_stream_vld_i` is
asserted. There is no ingress backpressure.

Routing policy:

1. Route to the entropy-distribution FIFO if it is not full.
2. Otherwise route to the CSRNG-word FIFO if it is not full.
3. Otherwise drop the word.

### Entropy-distribution AXI-Stream

- `entropy_axis_tvalid_o`
- `entropy_axis_tdata_o[31:0]`
- `entropy_axis_tstrb_o[3:0]`
- `entropy_axis_tready_i`

Transfers use 32-bit full-word beats only, so `tstrb` is always `4'hF`.

### EDN endpoint AXI-Stream outputs

For each endpoint `n` in `0 .. EDN_ENDPOINT_COUNT-1`:

- `edn_axis_tvalid_o[n]`
- `edn_axis_tdata_o[n][31:0]`
- `edn_axis_tstrb_o[n][3:0]`
- `edn_axis_tready_i[n]`

Each endpoint is buffered independently. The current feature release does not
propagate EDN FIPS information onto the external stream contract.

### CSR access

Two separate 64-bit AXI-Lite slave ports are exposed:

- `csrng_axil_*` for the wrapped CSRNG register space
- `edn_axil_*` for the wrapped EDN register space

Supported access scope:

- aligned single-lane 32-bit accesses only
- lower-lane writes use `WSTRB = 8'h0F`
- upper-lane writes use `WSTRB = 8'hF0`
- read responses return the 32-bit CSR data in the addressed lane

Unsupported access scope:

- multi-lane writes
- unaligned reads or writes
- any access that would span more than one 32-bit wrapped register

Unsupported accesses return AXI `SLVERR` and emit no TL-UL request. The wrapper
does not generate autonomous CSRNG or EDN control traffic outside externally
initiated AXI-Lite transactions.

## Reset and clocking

The entire wrapper runs in one `clk_i` / `rst_ni` domain.

- `rst_ni` is active low
- reset may assert asynchronously
- reset must deassert synchronously to `clk_i`
- bring-up should hold `rst_ni` low for at least two rising edges of `clk_i`
- the wrapper adds no internal reset-domain crossings

## CSRNG seed policy

The current feature-release policy drives every queued CSRNG seed with
`es_fips = 1'b1`. This is provisional and is intentionally isolated in
`drbg_pkg.sv`.

## Verification flow

The shared cocotb environment lives in `hw/comp/drbg/tb_vcs/`.

Primary targets:

```bash
make -C hw/comp/drbg/tb_vcs filelist
make -C hw/comp/drbg/tb_vcs sim-vcs
make -C hw/comp/drbg/tb_vcs sim-verilator
make -C hw/comp/drbg/tb_vcs smoke-nondefault-vcs
make -C hw/comp/drbg/tb_vcs smoke-nondefault-verilator
```

Lint targets:

```bash
make -C hw/comp/drbg/tb_vcs lint
make -C hw/comp/drbg/tb_vcs lint-verilator
```

The intended signoff path is `slang-tidy`, Verilator lint, VCS directed tests,
Verilator parity, and one non-default parameter smoke configuration.

# DRBG Wrapper Integration Guide

## Integration Model

The DRBG wrapper is intended to be integrated as one leaf component that owns
the wiring between:

- an upstream entropy producer,
- the wrapped `csrng` and `edn` blocks,
- software-visible CSR access paths, and
- downstream consumers of entropy and EDN output streams.

The wrapper is best used when the subsystem wants a stable external contract for
entropy ingestion and EDN streaming while retaining the existing CSRNG and EDN
register maps internally.

## Clocking and Reset Expectations

The wrapper assumes:

- one clock domain for all wrapper-local logic,
- one active-low reset `rst_ni`,
- asynchronous assertion is allowed, and
- deassertion is synchronous to `clk_i`.

Do not place an independently clocked entropy producer or endpoint consumer on
the wrapper boundary without adding CDC logic outside the wrapper.

## Entropy Producer Requirements

The upstream producer must satisfy the following:

- drive one 32-bit word on `entropy_stream_data_i`,
- assert `entropy_stream_vld_i` for the cycle that word is valid,
- tolerate the absence of a ready signal, and
- tolerate possible word dropping if both wrapper ingress FIFOs are full.

This last point is important. The wrapper prioritizes simplicity of the ingress
contract over lossless flow control. Integrators that require zero loss must
ensure the producer rate is compatible with the configured FIFO depths and the
expected consumer behavior.

## Entropy Routing Policy

Accepted words are routed in the following priority order:

1. entropy-distribution FIFO,
2. CSRNG seed-packing FIFO,
3. drop.

This means:

- the external entropy-distribution stream gets first claim on capacity,
- CSRNG seed formation uses only the overflow path from that first stage, and
- sustained downstream backpressure on the entropy-distribution stream can reduce
  the fraction of ingress words that reach the CSRNG seed path.

If the design intent is to prioritize CSRNG seeding instead, the current wrapper
policy is not the right choice and would need to be changed explicitly.

## CSRNG Integration Notes

The wrapper does not emulate or replace CSRNG internals. It feeds the wrapped
CSRNG through the standard `entropy_src_hw_if` request/ack interface.

Integrator implications:

- complete 384-bit seeds are queued before CSRNG asks for them,
- CSRNG can stall on entropy requests if the seed queue is empty,
- the current wrapper always marks queued seeds as provisional
  `es_fips = 1'b1`, and
- CSRNG command sequencing is still owned by software or another external
  controller.

The sideband inputs `otp_en_csrng_sw_app_read_i` and `lc_hw_debug_en_i` must
still be connected correctly because they affect wrapped CSRNG behavior.

## EDN Integration Notes

The wrapper instantiates EDN with `NumEndPoints = EDN_ENDPOINT_COUNT` and maps
each endpoint onto an independent AXI-Stream channel.

Integrator implications:

- each endpoint stream has its own output FIFO,
- endpoint backpressure is localized to that endpoint FIFO,
- EDN still owns the generation policy and CSR programming semantics, and
- the wrapper does not export EDN's internal FIPS indication on the external
  AXI-Stream interface.

If external consumers need a FIPS sideband, that must be added as a future
interface extension.

## Control-Plane Integration

The wrapper exposes two separate AXI-Lite slave ports:

- one for CSRNG CSRs,
- one for EDN CSRs.

The wrapper does not merge these spaces and does not create any top-level
register file of its own.

When integrating the control plane:

- use aligned 32-bit accesses only,
- drive only one 32-bit lane per transaction on the 64-bit bus,
- expect `SLVERR` for unsupported lane patterns or misaligned accesses, and
- do not rely on the wrapper to generate background register traffic.

This keeps the wrapper transparent to existing CSRNG and EDN software flows.

## Alerts and Interrupts

Alert and interrupt signals are direct pass-throughs from the wrapped blocks.

Integrator implications:

- existing CSRNG and EDN alert handling can be reused,
- existing interrupt software can still reason about CSRNG and EDN events
  independently, and
- the wrapper itself does not add a new interrupt cause or alert category.

## Bender and Filelist Integration

The wrapper depends on:

- the wrapped `csrng` and `edn` source trees,
- the AES dependency chain used by CSRNG,
- TL-UL bridge support,
- AXI typedef packages, and
- the local `prim_assert.sv` shim surface needed by the wrapped RTL.

The expected filelist flow is:

```bash
bender script flist-plus -t drbg
```

This should produce a compile-usable DRBG filelist for the wrapper and its
dependencies.

The critical package-ordering rule is:

1. `entropy_src_pkg`,
2. lifecycle packages,
3. component `csrng` / `edn` packages,
4. `keymgr` and dependent packages.

## Verification Integration

The wrapper's directed verification lives in `hw/comp/drbg/tb_vcs`.

Current regression emphasis:

- parameter smoke coverage,
- routing priority and drop behavior,
- 32-to-384 seed packing,
- end-to-end entropy-to-EDN behavior,
- CSRNG software command path behavior,
- endpoint isolation and buffering, and
- AXI-Lite lane filtering.

Recommended integration validation after any interface or policy change:

1. rerun `make -C hw/comp/drbg/tb_vcs sim-vcs`,
2. rerun a non-default parameter smoke target if parameters changed,
3. confirm the plain Bender-generated filelist still compiles, and
4. review whether the `prim_assert.sv` shim still covers the macro surface used
   by the dependency tree.

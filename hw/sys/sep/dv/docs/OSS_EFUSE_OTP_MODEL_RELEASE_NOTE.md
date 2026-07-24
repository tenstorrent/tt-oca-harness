<!-- SPDX-License-Identifier: Apache-2.0 -->
# OSS eFuse / OTP Behavioral Model Release Note

## Release Summary

This release provides an open-source behavioral eFuse / OTP model for digital
simulation. The responder is a deterministic functional stand-in for an OTP
macro interface and is intended for environments that need an open-source
physical-macro replacement for digital simulation.

## Artifacts

- Specification: `docs/OSS_EFUSE_OTP_MODEL_SPEC.md`
- PDF specification: `docs/OSS_EFUSE_OTP_MODEL_SPEC.pdf`
- Reference SystemVerilog responder: `shims/analog/tb_sep_efuse_responder.sv`

## Key Capabilities

- 8192-bit OTP array modeled as 256 x 32-bit words.
- `$readmemh`-style image preload.
- Multi-beat READ stream for fuse-sense flows.
- Sticky-OR PROGRAM and PROGRAM_READ_BACK.
- Optional program-failure injection for retry testing.
- Reset/resense behavior that reloads the image and overlays successful
  programmed bits.
- Minimal handshake-correct AXI-Lite bank-control responder.

## Implementation Notes

The reference responder supports these runtime knobs:

| Plusarg | Default | Meaning |
|---------|---------|---------|
| `+efuse_prog_fail_count=<n>` or implementation alias | 0 | Fail the first `n` PROGRAM attempts in each reset window. |
| `+efuse_prog_fail_percent=<0..100>` or implementation alias | 0 | Pseudo-random failure probability per PROGRAM attempt. |
| `+efuse_prog_fail_seed=<seed>` or implementation alias | fixed seed | Seed for percent-mode pseudo-random failures. |

Useful waveform signals for bring-up/debug:

- `fuse_command_req_i.valid`
- `fuse_command_req_i.command`
- `fuse_command_req_i.address`
- `fuse_command_req_i.program_data`
- `fuse_command_req_i.access_length_words`
- `fuse_command_resp_o.valid`
- `fuse_command_resp_o.status`
- `fuse_command_resp_o.data`
- `otp_mem[*]`
- `programmed_mem[*]`

## Source Files

- Reference responder: `dv/oss/hw/sys/sep/dv/shims/analog/tb_sep_efuse_responder.sv`
- OTP image helper: `dv/oss/hw/sys/sep/dv/cocotb/env/sep_efuse_image.py`
- Testbench integration: `dv/oss/hw/sys/sep/dv/tb/tb_top.sv`

## Representative Validation

These project validation items are release evidence only. They are not part of
the generic model specification.

- Fuse-sense image load and shadow checking are covered by
  `cocotb/tests/efuse/sep_efuse_sense_test.py`.
- OTP image generation/readback is covered by
  `cocotb/tests/efuse/sep_efuse_image_test.py`.
- OTP program/readback, retry after injected program failure, and resense
  persistence are covered by
  `cocotb/tests/lcc/sep_efuse_lcc_lc_state_stitch_test.py`.
- Representative testlist entries live in `testlists/efuse_lcc.toml`; the
  regression group includes the representative entries through `testlists/all.toml`.
- FSDB waveform inspection was used for bring-up review of request, response,
  storage-update, and failure-injection behavior.

## Scope Notes

- The responder is a faithful **functional stand-in**, not a silicon OTP macro.
- It does not model analog behavior, programming pulse timing, sense margins,
  disturb effects, endurance, aging, or other physical macro effects.
- It does not instantiate or reuse proprietary OTP macro IP.
- Bank-control reads return zero; the bank-control path is a protocol-safe stub,
  not a full OTP-bank register model.
- The model exists to make open-source digital simulation deterministic while
  preserving the contracts needed for fuse sense,
  sticky-OR programming, failure/retry, reset/resense, and readback.

## OCAH SEP OTP Comparison

At a high level, the OCAH SEP environment and the OSS environment use different
OTP models for different purposes:

| Area | OCAH SEP Samsung OTP | OSS OTP behavioral model |
|------|----------------------|--------------------------|
| Purpose | Vendor macro representation used by the internal SEP environment. | Open-source functional replacement for digital simulation. |
| Availability | Not suitable for OSS release. | Included with the OSS simulation environment. |
| Modeled behavior | Tied to the proprietary OTP macro integration. | Models the digital command/response contract: READ, PROGRAM, PROGRAM_READ_BACK, reset/resense, and failure injection. |
| Physical effects | Macro-specific behavior may exist in the proprietary model. | Analog behavior, programming pulse timing, margins, disturb, aging, and endurance are intentionally out of scope. |
| Programming semantics | Macro implementation defines the detailed behavior. | Successful PROGRAM operations update storage with sticky-OR semantics. |
| Failure behavior | Macro-specific error behavior is not carried into OSS. | Deterministic count-based or seeded percent-based program-failure injection is provided for retry testing. |
| Integration goal | Internal fidelity to the SEP vendor OTP integration. | Vendor-clean, deterministic coverage of the digital OTP-facing interface. |

The OSS model is not a drop-in physical macro equivalent. It is intended to
preserve the verification-relevant digital behavior needed by the open-source
testbench without carrying proprietary OTP IP into the release.

## Authoritative Reference

The authoritative reference for this release is:

`docs/OSS_EFUSE_OTP_MODEL_SPEC.md`


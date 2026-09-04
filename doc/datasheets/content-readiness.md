<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# Datasheet content-readiness ledger

This ledger separates evidence needed for accurate beta datasheets from
characterization that can reasonably wait for a more mature release. It is the
working source for refreshing project issues; existing datasheet issues were
not treated as current requirements.

## Evidence standard

A beta sheet may describe behavior visible in checked-in RTL and exercised by
the checked-in verification environment. It must label reference-configuration
values as such. Standards compliance, PPA, maximum frequency, performance,
certification, and silicon claims require evidence specific to those claims;
the existence of RTL or a nominal constraint is not enough.

## Shared decisions needed before all four sheets are final

|Priority |Missing decision or evidence |Why an integrator needs it |
|---|---|---|
|Before publication |Approved product names and one-sentence positioning for SMU, SMC, SEP, and DTP |Prevents the website, PDFs, RTL names, and adopter reviews from using different product identities. |
|Before publication |Release identifier policy: repository tag, commit, date, or a combination |Lets an integrator determine which RTL configuration a downloaded sheet describes. |
|Before publication |Named reference configuration for each sheet |Separates stable architectural range from the particular defaults summarized in a specification table. |
|Before publication |Verification snapshot policy |Defines whether the sheet reports the current branch, a release-tag regression, supported simulators, and any coverage result. |
|Before publication |Public standards-claim wording and evidence owner |“Implements”, “designed to”, “compatible with”, and “compliant” are materially different claims. |
|Before publication |Supported integration and deliverable boundary |Identifies which wrappers, memories, technology macros, firmware, constraints, generated registers, and tests are part of each product. |
|Can follow beta |Technology-specific frequency, area, gate count, power, and implementation conditions |Useful for selection, but not portable across configurations, libraries, memories, process, and physical design. |
|Can follow beta |Silicon characterization and production qualification |Not appropriate to imply for an open-source beta RTL release without corresponding evidence. |

## DTP

The initial sheet uses only claims supportable from the current RTL and DV
tree. The following items remain open or need an explicit owner decision.

|Priority |Missing or conflicting detail |Current evidence |Required resolution |
|---|---|---|---|
|Before publication |Whether to claim IEEE 1149.1-2013 and IEEE 1687-2014 compliance |`hw/sys/dtp/doc/overview.adoc` says “compliant”; there is no identified certification or compliance report. |Keep “implements” in the beta sheet, or attach an approved compliance matrix and review owner. |
|Before publication |Supported TCK operating range |`doc/integrator/src/index.adoc` says 10–50 MHz. `hw/sys/dtp/synth/constraints.sdc` contains a 10 ns reference period but explicitly says it is documentation-level SDC, not signoff. |Publish one qualified integration limit with STA/test evidence, or retain the current no-frequency-claim wording. |
|Before publication |Authoritative security-control interface name and polarity |Current `hw/sys/dtp/rtl/dtp.sv` exposes active-high `dbg_disable_i`; `hw/sys/dtp/doc/port_table.adoc` still describes the obsolete `feat_ctrl_i` contract and opposite enable-style semantics. |Correct the port documentation and confirm the public lifecycle/CDC contract. |
|Before publication |Release configuration: standalone DTP defaults versus the SMU-instantiated configuration |DTP has local defaults; `hw/sys/smu/rtl/smu.sv` overrides SEP-related slices, extra STAP count, ID/version fields, and other options from the SMU configuration. |Name the configuration summarized by the sheet and provide a generated or reviewed parameter manifest. |
|Before publication |Meaning and supported range of JTAG-to-AXI pipeline-depth fields |Top-level comments call the values pipeline depth; detailed PTAP documentation describes pending requests/responses as `pl_depth + 1` and special read marker behavior. |Add an integrator-facing definition and confirm which values are verified for each bridge. |
|Before publication |External protocol name and revision for cross-trigger signaling |The overview names “OCH Cross Trigger v1.0”; no public conformance reference is linked from the DTP source. |Link the governing protocol or describe only the implemented pulse and four-phase signal behavior. |
|Before publication |Verification baseline represented by the beta statement |The PyUVM tree and VPLAN cover all major blocks and include checker-negative modes; SV-UVM coverage is a subset. |Pin the statement to a release regression and publish its pass/skip/known-failure summary. |
|Can follow beta |Maximum JTAG-to-AXI throughput/latency and cross-trigger latency |No portable characterization is identified. |Measure per named configuration and clock assumptions when selection-level performance data is needed. |
|Can follow beta |Frequency, area, power, and silicon results |No implementation-specific signoff package is identified. |Add only with process, libraries, constraints, memories, tool versions, and corner conditions. |

## SEP

Before drafting the SEP sheet, resolve or bound:

- the approved security value proposition and threat-model boundary;
- the authenticated/secure boot claim, boot-stage ownership, trust anchors, and
  rollback policy actually present in the release configuration;
- lifecycle states, transition policy, debug policy, and the authoritative
  terminology for lifecycle-derived controls;
- the precise algorithm/mode set exposed for AES, HMAC/SHA-2, KMAC/SHA-3,
  OTBN, key manager, entropy, DRBG, and sideload paths;
- technology-macro responsibilities for ROM, SRAM, OTP/eFuse, and entropy,
  including integrity/ECC assumptions and initialization artifacts;
- DMA, SPI, watchdog, mailbox, interrupt, and memory-map capacities for the
  named reference configuration;
- which firmware and generated register collateral is delivered and which
  cryptographic/security scenarios are in the release regression; and
- any future throughput, latency, PPA, certification, side-channel, or fault-
  injection claim together with its measurement or assessment conditions.

Also correct the existing expansion of SECDED in `hw/sys/sep/doc/cpu.adoc`
before reusing that wording in public collateral.

## SMC

Before drafting the SMC sheet, resolve or bound:

- reference CPU-cluster configuration, implemented RISC-V ISA/debug profile,
  cache/TCM/ROM/scratch sizes, and which memories are adopter macros;
- supported clock-domain configuration and reset/power sequencing boundary;
- external and internal AXI/AXI-Lite widths, address-map ownership, aperture
  programming, remap/filter behavior, and error response expectations;
- DMA channel/features, GPIO/I2C/UART counts, PVT/PLL/AVSBus shim contracts,
  telemetry format, OCTS role, and interrupt capacities in the named build;
- boot ROM and management firmware deliverables versus examples;
- multi-chiplet management statements that are implemented and simulated
  today versus architectural intent; and
- release-regression scope before making performance, robustness, or protocol-
  compliance claims.

## SMU

The SMU sheet must describe a composed integration product, not repeat the
three component sheets. Before drafting it, resolve or bound:

- the public release configurations, including SEP-present and SEP-absent
  behavior and which configuration is the headline reference;
- the authoritative top-level module/wrapper names and paths—the current
  `hw/sys/smu/doc/SMU_SPEC.md` still contains obsolete `hw/smu/...` paths;
- top-level clock, reset, power, pad, macro, interrupt, SMN-facing AXI, JTAG,
  and adopter-extension boundaries;
- the 3-by-3 crossbar routing model, aperture defaults, fixed alias/remap paths,
  ID conversion, atomic-operation behavior, and unmatched-access responses;
- which SMC, SEP, and DTP parameters the SMU configuration overrides and how an
  adopter records a reproducible configuration;
- wrapper contents that are illustrative shims versus integration-ready logic;
- system-level boot, security handoff, debug authorization, and isolation
  assumptions; and
- the regression evidence that validates interaction among SMC, SEP, DTP, and
  the external interfaces, separately from block-level verification.

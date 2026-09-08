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
|Before publication |Release configuration beyond top-level trigger counts |`dtp_pkg.sv` fixes the DTP boundary at 16 CTPs, 10 internal trigger interfaces, and nine clock-stop inputs. The default SMU uses two internal trigger interfaces and one clock-stop input for SMC, exposing eight of each at its external boundary. SMU also overrides SEP-related slices, extra STAP count, ID/version fields, and other options. |Name the complete configuration summarized by the sheet and provide a generated or reviewed parameter manifest. |
|Before publication |Meaning and supported range of JTAG-to-AXI pipeline-depth fields |Top-level comments call the values pipeline depth; detailed PTAP documentation describes pending requests/responses as `pl_depth + 1` and special read marker behavior. |Add an integrator-facing definition and confirm which values are verified for each bridge. |
|Before publication |External protocol name and revision for cross-trigger signaling |The overview names “OCH Cross Trigger v1.0”; no public conformance reference is linked from the DTP source. |Link the governing protocol or describe only the implemented pulse and four-phase signal behavior. |
|Before publication |Verification baseline represented by the beta statement |The PyUVM tree and VPLAN cover all major blocks and include checker-negative modes; SV-UVM coverage is a subset. |Pin the statement to a release regression and publish its pass/skip/known-failure summary. |
|Can follow beta |Maximum JTAG-to-AXI throughput/latency and cross-trigger latency |No portable characterization is identified. |Measure per named configuration and clock assumptions when selection-level performance data is needed. |
|Can follow beta |Frequency, area, power, and silicon results |No implementation-specific signoff package is identified. |Add only with process, libraries, constraints, memories, tool versions, and corner conditions. |

Resolved during initial review: `hw/sys/dtp/doc/port_table.adoc` now matches the
RTL's active-high `dbg_disable_i` interface and records the TCK-domain
synchronization performed inside DTP.

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

The sheet positions SMU as the composed integration product with a standardized
OCAH chiplet interface. Its main configuration is four-core SMC + SEP + DTP,
corresponding to `DefaultCfg`, `SEP=1`; the alternate omits SEP. The underlying
configuration fields and no-SEP behavior are recorded here and in `smu.sv`.
The architectural positioning does not claim completed standards certification
or product security assessment.

|Priority |Missing or conflicting detail |Current evidence |Required resolution |
|---|---|---|---|
|Before publication |Approved public configuration names and support status |`smu_pkg.sv` defines `DefaultCfg` and `NoSepCfg`, but their struct fields are identical; the separate `SEP` parameter selects presence. `smu.sv` implements both elaboration branches. |Approve customer-facing names, declare whether both are release configurations, and publish one complete generated parameter manifest for each. |
|Before publication |Multi-chiplet SEP placement and security ownership |`smu.sv` selects SEP per instance. `hw/sys/sep/doc/lifecycle_controller.adoc`, Multiple Security Domains and Non-Primary Chiplets, describes primary and secondary chiplets with local SEP/LCC and secondaries without SEP. Forwarding lifecycle/debug controls to chiplets without SEP is an adopter integration responsibility; the SMU's no-SEP tie-offs do not implement it. |Define the SEP placement, SiP-owner and chiplet-owner domains, control propagation and enforcement, and verification plan for the integrated system. Per-instance configurability does not establish verified multi-SEP operation. |
|Before publication |No-SEP security posture |With `SEP=0`, RTL ties `sep_dbg_disable` to zero, reports fixed lifecycle value `8'hf0`, disables SEP endpoints, and returns DECERR on the SEP OTP debug path. DTP and the SMU's primary JTAG interface remain instantiated. No automatic handoff of debug authorization to another chiplet is implemented by this selection. |Define the system JTAG topology and no-SEP debug/security policy, including any alternative enforcement mechanism. Document the meaning of the fixed lifecycle value and all required system enforcement. |
|Before publication |Runtime aperture programming and ownership |The full 3-by-3 crossbar accepts CSR-driven SMC/SEP base and size values. RTL asserts non-overlap in simulation but does not freeze updates while traffic is in flight. Unmatched SMC/SEP egress uses the external output; unmatched external ingress decode-errors. |Assign firmware ownership, reset values, programming order, lock/stability rules, containment checks, and permitted error responses. Publish the chiplet-envelope relationship. |
|Before publication |System boot and handoff contract |SMC owns primary reset and external boot/repair gating; SEP supplies lifecycle, mailbox, watchdog-reset, and debug-disable signals when present. Wrapper smoke observes SMC firmware and real-SEP boot readiness, while broader production boot policy belongs to component firmware owners. |Approve the system sequence from power-good through memory repair, fuse sense, reset release, firmware readiness, lifecycle handoff, failure/recovery, and clock-stop interaction. |
|Before publication |Reference-wrapper boundary |`hw/top/smu_wrapper.sv` attaches open memory/eFuse/pad and termination models through `smc_ip_integration.sv` and `sep_ip_integration.sv`; the Integrator Guide describes these as examples for replacement. |List which wrapper and model files ship as examples, identify non-synthesizable or non-production behavior, and provide an adopter replacement/qualification checklist. |
|Before publication |Adopter extension and macro ownership |The `smu` boundary exposes SMN AXI, adopter AXI/AXI4-Lite extensions, JTAG/scan, triggers, interrupts, resets/isolation, SMC/SEP memories, OTP/eFuse, I3C tables, telemetry, GPIO, PLL/PVT, trace, entropy, and I/O connections. |Approve the supported/tie-off matrix and identify clock domains, CDC assumptions, macro latency/integrity, pad ownership, interrupt aggregation, and security restrictions per interface. |
|Before publication |Verification baseline represented by the beta statement |Hosted `--dut smu` smoke/nightly uses `SEP=0`; `sep0_all` has 53 tests. A distinct `--dut smu_wrapper` catalog has four smoke entries across no-SEP and real-SEP profiles plus separately enrolled real-firmware/lifecycle/entropy/chain groups. Wrapper results are not bare-SMU signoff; some groups remain blocked. |Pin a release-tag regression for each supported configuration and publish pass/skip/known-failure, backend, seed, firmware, force/stub, and coverage information without merging the two evidence surfaces. |
|Before publication |Designer approval and traceability |`SMU_FEATURE_LIST.adoc` labels the v0.5.0 SEP=0 subset candidate/unsigned and records open designer-confirmation and traceability trackers. |Obtain the named design and DV approvals and reconcile the feature list with the current wrapper real-SEP catalog before final publication. |
|Can follow beta |Implementation, performance, certification, and silicon results |No portable frequency, area, power, latency, throughput, standards-certification, system-security-assessment, or silicon signoff package is identified. |Add only with configuration, workloads, firmware, tools, libraries/process, physical conditions, assessment method, and owner. |

Resolved during initial review: `SMU_SPEC.md` now names the current
`hw/sys/smu/rtl/` core paths, `hw/top/smu_wrapper.sv`, the
`tt-oca-harness` repository, and the current `dbg_disable_o` to
`dbg_disable_i` lifecycle handoff.

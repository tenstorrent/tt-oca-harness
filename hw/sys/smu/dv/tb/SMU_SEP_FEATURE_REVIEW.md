# SMU_SEP — Feature Review Packet

> **PROVENANCE CAVEAT:** sealed_derivation is false — pin_file.py validate dumped the pin anchors list into this context before the feature_list freeze. Treat inventory bias risk as elevated; DV owner may require a sealed re-run.

## Open questions (answer before approving features)

- **SF-001** (High): At the SMU integration boundary, must SEP→SMC egress always traverse the SEP outbound filter, or is a dedicated unfiltered alias/egress path architecturally required? What exact response is required when a filtered rule would deny an SMC-egress beat?
- **SF-003** (High): For SMU-level proof, which observation point is authoritative for SEP mailbox IRQ — wrapper-internal smc_mailbox_interrupt_o, SMC sep_mailbox_interrupts_i, or the documented cpu_interrupts_o bit indices — and what are the exact bit indices for 1-core vs 4-core configs?
- **SF-005** (High): What exact digest constant and token presentation path must SMU-level checkers use for SEC_DIS match vs mismatch, and is A0-only metal-strap disable in-scope for this pin?
- **SF-006** (High): Please publish authoritative (non-generated) absolute addresses, field widths, and reset values for SEP/SMC aperture CSRs that SMU xbar decode checkers must use.

## Feature inventory (approve semantics)

| Key | Intent | Spec | Scenarios | Approve |
|---|---|---|---|---|
| `SEP-COMPOSE-ENABLE` | With SEP=1 the real SEP block is instantiated under SMU and participates in SMU composition | hw/sys/smu/doc/SMU_SPEC.md Architecture / Sub-Blocks / Feature 2 | 2 | [ ] |
| `SEP-RESET-CONTROL` | SMC reset logic holds and releases the SEP primary reset at the SMU boundary | hw/sys/smu/doc/SMU_SPEC.md Clock and Reset | 4 | [ ] |
| `SEP-FUSE-SENSE-HANDSHAKE` | SMC fuse-sense completion crosses to SEP and SEP fuse-sense completion is exported at SMU | hw/sys/smu/doc/SMU_SPEC.md Security Considerations | 2 | [ ] |
| `SEP-ROM-BOOT-ENABLE` | After fuse sensing and memory-repair/bypass, SEP CPU is enabled and fetches BL0 from Boot ROM | hw/sys/sep/doc/periphs.adoc Fuse Controller (OTP) | 2 | [ ] |
| `SEP-XBAR-SYSIF` | SEP outbound/inbound AXI participates in the SMU 3x3 crossbar with ID-width conversion | hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing | 3 | [ ] |
| `SEP-XBAR-APERTURE` | SMU crossbar routes using CSR-programmed SEP and SMC apertures including global-base remap | hw/sys/smu/doc/SMU_SPEC.md Feature 4 AXI Crossbar Fabric | 3 | [ ] |
| `SEP-XBAR-CONNECTIVITY` | Crossbar connectivity forbids a master reaching its own inbound port; SEP reaches smc_in and ext_out only | hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing | 3 | [ ] |
| `SEP-SMC-ALIAS-REMAP` | Dedicated SEP-to-SMC path remaps fixed 0x4000_0000/1GB to 0x0, bypassing the crossbar | hw/sys/smu/doc/SMU_SPEC.md Data Paths SEP to SMC alias remap | 3 | [ ] |
| `SEP-MAILBOX-IRQ-TO-SMC` | SEP mailbox events raise smc_mailbox_interrupt_o which SMC maps into CPU interrupt space | hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt 0 | 3 | [ ] |
| `SEP-MAILBOX-DATA-EXCHANGE` | SMC and SEP exchange mailbox payload words as the primary real interoperability path | hw/sys/smu/doc/SMU_SPEC.md Data Paths Mailbox challenge-response | 3 | [ ] |
| `SEP-FEAT-CTRL-EXPORT` | SEP LCC drives feat_ctrl_o into SMC and DTP to gate debug/test/function features | hw/sys/sep/doc/lifecycle_controller.adoc Life Cycle Controller (LCC) | 3 | [ ] |
| `SEP-LC-STATE-EXPORT` | SEP drives differentially encoded lc_state_o and demote state visible at SMU outputs | hw/sys/smu/doc/SMU_SPEC.md Interfaces Lifecycle / feature control | 3 | [ ] |
| `SEP-SECURITY-DISABLE-EXPORT` | SEP security_disable_o is exported to SMC; SMU binds SEP_SEC_DISABLE_TOKEN digest into SEP | hw/sys/sep/doc/security_disable.adoc Security Disable (SEC_DIS) | 3 | [ ] |
| `SEP-TEST-MODE-SECURE-TM` | TEST_EN strap latched at fuse-sense-done or cold-reset if SEC_DIS becomes SECURE_TM qualifying test enables | hw/sys/sep/doc/test_mode.adoc Test Mode Entry | 2 | [ ] |
| `SEP-WDT-RESET-TO-SMC` | SEP WDT second-stage bite asserts reset request that SMC aggregates as SEP watchdog indication | hw/sys/sep/doc/periphs.adoc Watchdog Timer (WDT) | 3 | [ ] |
| `SEP-MEMORY-PORT-OBS` | SEP TCM/SRAM/Boot-ROM request/response ports passthrough the SMU wrapper for integration memories | hw/sys/smu/doc/port_table.adoc sep_cpu_tcm_req_o | 3 | [ ] |
| `SEP-CRYPTO-PORT-OBS` | AES/OTBN/KM memory and CSR paths that appear at SMU integration ports are exercisable | hw/sys/sep/doc/crypto.adoc Cryptographic Subsystem | 3 | [ ] |
| `SEP-DMA-PORT-OBS` | SEP DMA CSR programming moves data on SEP fabric paths visible at SMU-integrated memories | hw/sys/sep/doc/memory_map.adoc DMA CSR 0x1080_0000 | 2 | [ ] |
| `SEP-SPI-PORT-OBS` | SEP SPI host request/response and muxed SPI IRQ are visible at SMU boundary | hw/sys/sep/doc/periphs.adoc Serial Peripheral Interface (SPI) | 2 | [ ] |
| `SEP-EFUSE-PORT-OBS` | SEP eFuse AXI-Lite bank control and fuse command interfaces passthrough SMU to the eFuse shim | hw/sys/sep/doc/periphs.adoc Fuse Controller (OTP) | 3 | [ ] |
| `SEP-INBOUND-FILTER` | Inbound filter is block-by-default after POR; only SEP CPU programs allow rules by addr/NS/source ID | hw/sys/sep/doc/fabric.adoc System Interface initiator / inbound filter | 3 | [ ] |
| `SEP-OUTBOUND-DEMUX` | SEP outbound routing distinguishes SMC-neighbor path vs SMN/NoC path after local/alias decode | hw/sys/sep/doc/fabric.adoc Transaction Routing | 3 | [ ] |
| `SEP-OUTBOUND-FILTER` | Outbound filter enforces address/NS/source-ID rules so source-ID others cannot access M-mode assets | hw/sys/sep/doc/fabric.adoc outbound filter enables filtering based on address NS and source ID | 3 | [ ] |
| `SEP-AP-STEE-REMAP` | Writes to AP/STEE remap windows are routed through the corresponding remappers with programmed attributes | hw/sys/sep/doc/fabric.adoc Address Remapping Sixteen remap regions | 3 | [ ] |
| `SEP-AXI-EXTENSION` | SEP AXI extension region/master port is passthrough at SMU for adopter peripherals | hw/sys/sep/doc/memory_map.adoc AXI Extension Region | 2 | [ ] |
| `SEP-DEBUG-BUS-EXPORT` | SEP ext_debug_bus_o is exported for debug infrastructure observation at SMU | hw/sys/sep/doc/port_table.adoc ext_debug_bus_o | 1 | [ ] |
| `SEP-EXTERNAL-IRQ` | External interrupt sources on extintsrc_req reach SEP PIC at SMU-visible integration | hw/sys/sep/doc/port_table.adoc extintsrc_req | 2 | [ ] |
| `SEP-IC-RESET-EXT-SLICE` | When JTAG IC_RESET is enabled, SMU exports jtag_ic_reset_ext override slice that can override SEP-related resets | hw/sys/smu/doc/port_table.adoc jtag_ic_reset_ext_o | 2 | [ ] |

## Interactions

- `INT-FUSE-AUTH-TO-ROM` features=['SEP-FUSE-SENSE-HANDSHAKE', 'SEP-ROM-BOOT-ENABLE']: SMC fuse-sense authorization precedes SEP fuse completion and first BL0 ROM fetch — Approve [ ]
- `INT-ALIAS-MAILBOX` features=['SEP-SMC-ALIAS-REMAP', 'SEP-MAILBOX-DATA-EXCHANGE']: SEP reaches SMC mailbox region through the alias remap path for interop payload exchange — Approve [ ]
- `INT-FEAT-LC-HANDOFF` features=['SEP-FEAT-CTRL-EXPORT', 'SEP-LC-STATE-EXPORT']: Lifecycle state and feat_ctrl are exported together as the security handoff into SMC/DTP — Approve [ ]

## Appendix

- feature_list content_sha256: `a78ab08448e2271e9a4c9f9b4e85538f40fb53a553b5046d66d42732f8a5dcd4`
- artifact_revision: 1
- pin_revision: 1
- derivation_provenance: `{'sealed_derivation': False, 'anchor_seal_mechanism': 'ordered-single-context', 'fresh_context_route': 'fresh-subagent', 'feature_list_frozen_at': '2026-08-07T17:45:00+08:00'}`

<!-- SPDX-License-Identifier: CC-BY-4.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# TRM diagram index

Source: [Documentation drawings for OCAH](https://docs.google.com/spreadsheets/d/1AwAe141qEmBevViCIS1gMMXXoZ7NUUjRwzD-UeqUxg8/edit),
[shared figure folder](https://drive.google.com/drive/folders/1SqfpLch-jIbCbGwBwpy5FQIc7mydoSVN),
retrieved 2026-09-23. Figure IDs are scoped to their worksheet and document type.
This inventory maps index entries to authored sources; it is not a figure-number
assignment for the generated PDF.

Assets live with their owning hardware documentation. SVG exports are used when
supplied alongside PNGs. SVGs without intrinsic dimensions use their view-box
size for the browser image viewer. Draw.io PNGs retain their embedded editable source.
The GPIO JPEG is the unmodified `preview.jpeg` embedded in its retained
OmniGraffle source. Upstream reference figures retain their licenses and pinned
provenance in [their README](../../../hw/sys/sep/doc/assets/upstream/README.md).

The SMC top-level/reset filenames in the sheet omit `.drawio`; the Drive files
match the repository images. SMU FIG002 repeats the decode filename in the sheet;
both the connectivity and decode files are included. SEP FIG004 links to its PNG
by Drive ID; the companion SVG is used. Entries marked "Needed" in the sheet are
included when an actual asset is present. Existing revised JTAG, DTP, lifecycle,
and token-processing figures remain canonical.

## OCAH Top

| Figure | Description | Authored page | Asset | Notes |
| --- | --- | --- | --- | --- |
| FIG001 | OCAH subsystem / top-level block diagram | [doc/trm/src/overview.adoc](../../../doc/trm/src/overview.adoc) | [doc/trm/assets/ocah_top.svg](../../../doc/trm/assets/ocah_top.svg) | Redrawn as hand-authored SVG from the imported draw.io figure |
| FIG003 | OCAH clock-domain and CDC overlay | [doc/trm/src/clock_domains.adoc](../../../doc/trm/src/clock_domains.adoc) | [doc/trm/assets/ocah_top_clocks.svg](../../../doc/trm/assets/ocah_top_clocks.svg) | Copy of FIG001 with colored clock-domain zones bounded by its CDCs |

## SMU

| Figure | Description | Authored page | Asset | Notes |
| --- | --- | --- | --- | --- |
| FIG001 | SMU core composition: DTP + SMC + optional SEP + AXI crossbar | [hw/sys/smu/doc/index.adoc](../../../hw/sys/smu/doc/index.adoc) | [hw/sys/smu/doc/assets/smu-composition.svg](../../../hw/sys/smu/doc/assets/smu-composition.svg) | Redrawn as hand-authored SVG from the imported draw.io figure |
| FIG002 | SMU 3x3 AXI crossbar connectivity and aperture address-routing flow | [hw/sys/smu/doc/index.adoc](../../../hw/sys/smu/doc/index.adoc) | [hw/sys/smu/doc/assets/smu-crossbar-connectivity.svg](../../../hw/sys/smu/doc/assets/smu-crossbar-connectivity.svg)<br>[hw/sys/smu/doc/assets/smu-aperture-decode.svg](../../../hw/sys/smu/doc/assets/smu-aperture-decode.svg) | Redrawn as hand-authored SVGs from the imported draw.io figures |
| FIG004 | SMU internal clock tree and clock domains | [hw/sys/smu/doc/index.adoc](../../../hw/sys/smu/doc/index.adoc) | [hw/sys/smu/doc/assets/smu-clock-distribution.svg](../../../hw/sys/smu/doc/assets/smu-clock-distribution.svg) | Redrawn as a hand-authored SVG; the sheet notes the imported figure was a mockup with no source |
| FIG005 | SMU reset tree and reset domains | [hw/sys/smu/doc/index.adoc](../../../hw/sys/smu/doc/index.adoc) | [hw/sys/smu/doc/assets/smu-reset-distribution.svg](../../../hw/sys/smu/doc/assets/smu-reset-distribution.svg) | Redrawn as a hand-authored SVG; the sheet notes the imported figure was a mockup with no source |
| FIG006 | SEP lifecycle / feature-control / demotion propagation to SMC and DTP | [hw/sys/smu/doc/index.adoc](../../../hw/sys/smu/doc/index.adoc) | [hw/sys/smu/doc/assets/smu-lifecycle-controls.svg](../../../hw/sys/smu/doc/assets/smu-lifecycle-controls.svg) | Redrawn as a hand-authored SVG from the imported figure |

## SEP

| Figure | Description | Authored page | Asset | Notes |
| --- | --- | --- | --- | --- |
| FIG001 | SEP top-level microarchitecture | [hw/sys/sep/doc/overview.adoc](../../../hw/sys/sep/doc/overview.adoc) | [hw/sys/sep/doc/assets/SEP_TopLevel_FIG001.drawio.png](../../../hw/sys/sep/doc/assets/SEP_TopLevel_FIG001.drawio.png) | Imported |
| FIG002 | SEP clock tree and domains | [hw/sys/sep/doc/overview.adoc](../../../hw/sys/sep/doc/overview.adoc) | [hw/sys/sep/doc/assets/SEP_CLOCKING_FIG002.svg](../../../hw/sys/sep/doc/assets/SEP_CLOCKING_FIG002.svg) | Imported |
| FIG003 | SEP reset tree and domains | [hw/ip/key_manager/doc/architecture.adoc](../../../hw/ip/key_manager/doc/architecture.adoc)<br>[hw/sys/sep/doc/reset_controller.adoc](../../../hw/sys/sep/doc/reset_controller.adoc) | [hw/ip/key_manager/doc/assets/SEP_KMResetDomains_FIG003.2.png](../../../hw/ip/key_manager/doc/assets/SEP_KMResetDomains_FIG003.2.png)<br>[hw/sys/sep/doc/assets/SEP_ResetDomains_FIG003.1.png](../../../hw/sys/sep/doc/assets/SEP_ResetDomains_FIG003.1.png) | Imported |
| FIG004 | SEP host (EL2 CPU subsystem) microarchitecture | [hw/sys/sep/doc/cpu.adoc](../../../hw/sys/sep/doc/cpu.adoc) | [hw/sys/sep/doc/assets/SEP_CPU_FIG004.svg](../../../hw/sys/sep/doc/assets/SEP_CPU_FIG004.svg) | Imported |
| FIG005 | SEP input fabric | [hw/sys/sep/doc/fabric.adoc](../../../hw/sys/sep/doc/fabric.adoc) | [hw/sys/sep/doc/assets/SEP_Input_Fabric_FIG005.svg](../../../hw/sys/sep/doc/assets/SEP_Input_Fabric_FIG005.svg) | Imported |
| FIG006 | SEP local fabric | [hw/sys/sep/doc/fabric.adoc](../../../hw/sys/sep/doc/fabric.adoc) | [hw/sys/sep/doc/assets/SEP_Local_Fabric_FIG006.svg](../../../hw/sys/sep/doc/assets/SEP_Local_Fabric_FIG006.svg) | Imported |
| FIG007 | SEP output fabric | [hw/sys/sep/doc/fabric.adoc](../../../hw/sys/sep/doc/fabric.adoc) | [hw/sys/sep/doc/assets/SEP_Output_Fabric_FIG007.svg](../../../hw/sys/sep/doc/assets/SEP_Output_Fabric_FIG007.svg) | Imported |
| FIG008 | SEP host mailbox block diagram | [hw/sys/sep/doc/fabric.adoc](../../../hw/sys/sep/doc/fabric.adoc) | [hw/sys/sep/doc/assets/SEP_AXILmailbox_FIG008.png](../../../hw/sys/sep/doc/assets/SEP_AXILmailbox_FIG008.png) | Imported |
| FIG009 | SEP DMA architecture and chunked-transfer flow with SHA | [hw/sys/sep/doc/cpu.adoc](../../../hw/sys/sep/doc/cpu.adoc) | [hw/sys/sep/doc/assets/upstream/opentitan_dma.svg](../../../hw/sys/sep/doc/assets/upstream/opentitan_dma.svg) | Imported |
| FIG010 | SEP cryptographic complex overview | [hw/sys/sep/doc/crypto.adoc](../../../hw/sys/sep/doc/crypto.adoc) | [hw/sys/sep/doc/assets/SEP_Crypto_TopLevel_FIG010.drawio.png](../../../hw/sys/sep/doc/assets/SEP_Crypto_TopLevel_FIG010.drawio.png) | Imported |
| FIG011 | TRNG microarchitecture | [hw/sys/sep/doc/trng.adoc](../../../hw/sys/sep/doc/trng.adoc) | [hw/sys/sep/doc/assets/SEP_Trng_TopLevel_FIG011.drawio.png](../../../hw/sys/sep/doc/assets/SEP_Trng_TopLevel_FIG011.drawio.png) | Imported |
| FIG012 | Entropy source microarchitecture | [hw/ip/entropy_source/doc/architecture.adoc](../../../hw/ip/entropy_source/doc/architecture.adoc) | [hw/ip/entropy_source/doc/assets/SEP_Esrc_TopLevel_FIG012.drawio.png](../../../hw/ip/entropy_source/doc/assets/SEP_Esrc_TopLevel_FIG012.drawio.png) | Imported |
| FIG013 | Entropy source ring oscillator complex block diagram | [hw/ip/entropy_source/doc/architecture.adoc](../../../hw/ip/entropy_source/doc/architecture.adoc) | [hw/ip/entropy_source/doc/assets/SEP_Esrc_ROSC_FIG013.drawio.png](../../../hw/ip/entropy_source/doc/assets/SEP_Esrc_ROSC_FIG013.drawio.png) | Imported |
| FIG016 | Key Manager microarchitecture | [hw/ip/key_manager/doc/architecture.adoc](../../../hw/ip/key_manager/doc/architecture.adoc) | [hw/sys/sep/doc/assets/SEP_Key_Manager.png](../../../hw/sys/sep/doc/assets/SEP_Key_Manager.png) | Existing canonical figure |
| FIG017 | Key Manager / SEP host coordination | [hw/ip/key_manager/doc/architecture.adoc](../../../hw/ip/key_manager/doc/architecture.adoc) | [hw/ip/key_manager/doc/assets/SEP_KM_Key_Load_Transfer_FIG017.png](../../../hw/ip/key_manager/doc/assets/SEP_KM_Key_Load_Transfer_FIG017.png) | Imported |
| FIG018 | AES block diagram | [hw/sys/sep/doc/aes.adoc](../../../hw/sys/sep/doc/aes.adoc) | [hw/sys/sep/doc/assets/upstream/opentitan_aes.svg](../../../hw/sys/sep/doc/assets/upstream/opentitan_aes.svg) | Imported |
| FIG019 | HMAC block diagram | [hw/sys/sep/doc/hmac.adoc](../../../hw/sys/sep/doc/hmac.adoc) | [hw/sys/sep/doc/assets/upstream/opentitan_hmac.svg](../../../hw/sys/sep/doc/assets/upstream/opentitan_hmac.svg) | Imported |
| FIG020 | KMAC block diagram | [hw/sys/sep/doc/kmac.adoc](../../../hw/sys/sep/doc/kmac.adoc) | [hw/sys/sep/doc/assets/upstream/opentitan_kmac.svg](../../../hw/sys/sep/doc/assets/upstream/opentitan_kmac.svg) | Imported |
| FIG021 | OTBN block diagram | [hw/sys/sep/doc/otbn.adoc](../../../hw/sys/sep/doc/otbn.adoc) | [hw/sys/sep/doc/assets/upstream/opentitan_otbn.svg](../../../hw/sys/sep/doc/assets/upstream/opentitan_otbn.svg) | Imported |
| FIG022 | Adam's Bridge block diagram | [hw/sys/sep/doc/adams_bridge.adoc](../../../hw/sys/sep/doc/adams_bridge.adoc) | [hw/sys/sep/doc/assets/upstream/adams_bridge_mldsa.png](../../../hw/sys/sep/doc/assets/upstream/adams_bridge_mldsa.png)<br>[hw/sys/sep/doc/assets/upstream/adams_bridge_mlkem.png](../../../hw/sys/sep/doc/assets/upstream/adams_bridge_mlkem.png) | Imported |
| FIG023 | eFuse interface block diagram | [hw/sys/sep/doc/otp_fuse_controller.adoc](../../../hw/sys/sep/doc/otp_fuse_controller.adoc) | [hw/sys/sep/doc/assets/SEP_eFuse_Interface_Block_Diagram_FIG023.png](../../../hw/sys/sep/doc/assets/SEP_eFuse_Interface_Block_Diagram_FIG023.png) | Imported |
| FIG024 | Life Cycle Controller (LCC) FSM | [hw/sys/sep/doc/lifecycle_controller.adoc](../../../hw/sys/sep/doc/lifecycle_controller.adoc) | [hw/sys/sep/doc/assets/SEP_LC_FSM.png](../../../hw/sys/sep/doc/assets/SEP_LC_FSM.png) | Existing canonical figure |
| FIG025 | Life Cycle Controller block diagram | [hw/sys/sep/doc/lifecycle_controller.adoc](../../../hw/sys/sep/doc/lifecycle_controller.adoc) | [hw/sys/sep/doc/assets/SEP_LC_Block.png](../../../hw/sys/sep/doc/assets/SEP_LC_Block.png) | Existing canonical figure |
| FIG026 | Token Processing | [hw/sys/sep/doc/token_processing.adoc](../../../hw/sys/sep/doc/token_processing.adoc) | [hw/sys/sep/doc/assets/SEP_Token_Processing.png](../../../hw/sys/sep/doc/assets/SEP_Token_Processing.png) | Existing canonical figure |
| FIG029 | eFuse Sense FSM | [hw/sys/sep/doc/otp_fuse_controller.adoc](../../../hw/sys/sep/doc/otp_fuse_controller.adoc) | [hw/sys/sep/doc/assets/SEP_eFuse_Sense_FSM_FIG029.png](../../../hw/sys/sep/doc/assets/SEP_eFuse_Sense_FSM_FIG029.png) | Imported |

## SMC

| Figure | Description | Authored page | Asset | Notes |
| --- | --- | --- | --- | --- |
| FIG001 | SMC top-level microarchitecture | [hw/sys/smc/doc/overview.adoc](../../../hw/sys/smc/doc/overview.adoc) | [hw/sys/smc/doc/assets/smc-top-level.svg](../../../hw/sys/smc/doc/assets/smc-top-level.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG004 | Input fabric topology and routing | [hw/sys/smc/doc/fabric.adoc](../../../hw/sys/smc/doc/fabric.adoc) | [hw/sys/smc/doc/assets/smc-input-fabric.svg](../../../hw/sys/smc/doc/assets/smc-input-fabric.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG005 | Local fabric topology and CSR/peripheral islands | [hw/sys/smc/doc/fabric.adoc](../../../hw/sys/smc/doc/fabric.adoc) | [hw/sys/smc/doc/assets/smc-local-fabric.svg](../../../hw/sys/smc/doc/assets/smc-local-fabric.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG006 | Output fabric topology and routing | [hw/sys/smc/doc/fabric.adoc](../../../hw/sys/smc/doc/fabric.adoc) | [hw/sys/smc/doc/assets/smc-output-fabric.svg](../../../hw/sys/smc/doc/assets/smc-output-fabric.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG008 | Inbound/outbound filters and protection flow | [hw/sys/smc/doc/fabric.adoc](../../../hw/sys/smc/doc/fabric.adoc) | [hw/sys/smc/doc/assets/smc-traffic-filters.svg](../../../hw/sys/smc/doc/assets/smc-traffic-filters.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG010 | CPU cluster and TileLink-to-AXI integration | [hw/sys/smc/doc/cpu.adoc](../../../hw/sys/smc/doc/cpu.adoc) | [hw/sys/smc/doc/assets/smc-cpu-cluster.svg](../../../hw/sys/smc/doc/assets/smc-cpu-cluster.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG013 | DMA frontend/backend and fabric path | [hw/sys/smc/doc/dma.adoc](../../../hw/sys/smc/doc/dma.adoc) | [hw/sys/smc/doc/assets/smc-dma.svg](../../../hw/sys/smc/doc/assets/smc-dma.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG014 | Memory zeroer FSM and AXI flow | [hw/sys/smc/doc/zeroer.adoc](../../../hw/sys/smc/doc/zeroer.adoc) | [hw/sys/smc/doc/assets/smc-memory-zeroer.svg](../../../hw/sys/smc/doc/assets/smc-memory-zeroer.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG015 | SMC reset unit architecture | [hw/sys/smc/doc/clk_rst.adoc](../../../hw/sys/smc/doc/clk_rst.adoc) | [hw/sys/smc/doc/assets/smc-reset-unit.svg](../../../hw/sys/smc/doc/assets/smc-reset-unit.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG016 | FLR Isolation Diagram | [hw/sys/smc/doc/clk_rst.adoc](../../../hw/sys/smc/doc/clk_rst.adoc) | [hw/sys/smc/doc/assets/smc-flr-isolation.svg](../../../hw/sys/smc/doc/assets/smc-flr-isolation.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG017 | FLR Isolation Diagram, SMC driven | [hw/sys/smc/doc/clk_rst.adoc](../../../hw/sys/smc/doc/clk_rst.adoc) | [hw/sys/smc/doc/assets/smc-flr-isolation-smc-driven.svg](../../../hw/sys/smc/doc/assets/smc-flr-isolation-smc-driven.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG018 | FLR Isolation Diagram, Tile Request driven | [hw/sys/smc/doc/clk_rst.adoc](../../../hw/sys/smc/doc/clk_rst.adoc) | [hw/sys/smc/doc/assets/smc-flr-isolation-tile-request.svg](../../../hw/sys/smc/doc/assets/smc-flr-isolation-tile-request.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG019 | FLR Isolate Diagram, GPIO driven | [hw/sys/smc/doc/clk_rst.adoc](../../../hw/sys/smc/doc/clk_rst.adoc) | [hw/sys/smc/doc/assets/smc-flr-isolation-gpio.svg](../../../hw/sys/smc/doc/assets/smc-flr-isolation-gpio.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG021 | GPIO controller, shim, LSIO mux, and strap-capture path | [hw/ip/gpio/doc/architecture.adoc](../../../hw/ip/gpio/doc/architecture.adoc) | [hw/ip/gpio/doc/assets/gpio-interface-and-shim.svg](../../../hw/ip/gpio/doc/assets/gpio-interface-and-shim.svg)<br>[hw/ip/gpio/doc/assets/gpio-padring.svg](../../../hw/ip/gpio/doc/assets/gpio-padring.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG022 | System Timer OCTS primary/secondary synchronization and credit CDC | [hw/ip/system_timer_octs/doc/architecture.adoc](../../../hw/ip/system_timer_octs/doc/architecture.adoc) | [hw/ip/system_timer_octs/doc/assets/system-timer-octs.svg](../../../hw/ip/system_timer_octs/doc/assets/system-timer-octs.svg) | Redrawn as hand-authored SVG from the imported figure |
| | OpenTitan I2C core block diagram | [hw/ip/i2c/doc/index.adoc](../../../hw/ip/i2c/doc/index.adoc) | [hw/ip/i2c/doc/assets/upstream/opentitan_i2c.svg](../../../hw/ip/i2c/doc/assets/upstream/opentitan_i2c.svg) | Symlink to the vendored `i2c_block_diagram.svg` |
| FIG023 | OCAH I2C wrapper and generated register interface | [hw/ip/i2c/doc/index.adoc](../../../hw/ip/i2c/doc/index.adoc) | [hw/ip/i2c/doc/assets/i2c-wrapper.svg](../../../hw/ip/i2c/doc/assets/i2c-wrapper.svg) | Redrawn as hand-authored SVG from the imported figure |
| | i3c-core block diagram | [hw/ip/i3ccore_wrap/doc/index.adoc](../../../hw/ip/i3ccore_wrap/doc/index.adoc) | [hw/ip/i3ccore_wrap/doc/assets/upstream/i3c_core_block_diagram.png](../../../hw/ip/i3ccore_wrap/doc/assets/upstream/i3c_core_block_diagram.png) | Symlink to the vendored `hc_top_level_arch.png` |
| FIG024 | OCAH I3C wrapper | [hw/ip/i3ccore_wrap/doc/index.adoc](../../../hw/ip/i3ccore_wrap/doc/index.adoc) | [hw/ip/i3ccore_wrap/doc/assets/i3c-wrapper.svg](../../../hw/ip/i3ccore_wrap/doc/assets/i3c-wrapper.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG025 | SMC UART wrapper | [hw/ip/uart/uart_16550/doc/index.adoc](../../../hw/ip/uart/uart_16550/doc/index.adoc) | [hw/ip/uart/uart_16550/doc/assets/uart-wrapper.svg](../../../hw/ip/uart/uart_16550/doc/assets/uart-wrapper.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG025 | SMC log-engine wrapper | [hw/ip/uart/log_engine/doc/index.adoc](../../../hw/ip/uart/log_engine/doc/index.adoc) | [hw/ip/uart/log_engine/doc/assets/log-engine-wrapper.svg](../../../hw/ip/uart/log_engine/doc/assets/log-engine-wrapper.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG026 | AVSBus block diagram | [hw/ip/avsbus_controller/doc/architecture.adoc](../../../hw/ip/avsbus_controller/doc/architecture.adoc)<br>[hw/ip/avsbus_controller/doc/interface.adoc](../../../hw/ip/avsbus_controller/doc/interface.adoc) | [hw/ip/avsbus_controller/doc/assets/avsbus-controller.svg](../../../hw/ip/avsbus_controller/doc/assets/avsbus-controller.svg)<br>[hw/ip/avsbus_controller/doc/assets/avsbus-protocol-fsm.svg](../../../hw/ip/avsbus_controller/doc/assets/avsbus-protocol-fsm.svg)<br>[hw/ip/avsbus_controller/doc/assets/avsbus-clock-select.svg](../../../hw/ip/avsbus_controller/doc/assets/avsbus-clock-select.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG027 | SMC mailbox wrapper and interrupt routing | [hw/ip/axi_lite_mailbox_unit/doc/index.adoc](../../../hw/ip/axi_lite_mailbox_unit/doc/index.adoc) | [hw/ip/axi_lite_mailbox_unit/doc/assets/smc-mailbox.svg](../../../hw/ip/axi_lite_mailbox_unit/doc/assets/smc-mailbox.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG028 | SMC DFD block diagram | [hw/sys/smc/doc/dfd.adoc](../../../hw/sys/smc/doc/dfd.adoc) | [hw/sys/smc/doc/assets/smc-dfd.svg](../../../hw/sys/smc/doc/assets/smc-dfd.svg) | Redrawn as hand-authored SVG from the imported figure |
| FIG029 | Clock tree and domains | [hw/sys/smc/doc/clk_rst.adoc](../../../hw/sys/smc/doc/clk_rst.adoc) | [hw/sys/smc/doc/assets/smc-clock-distribution.svg](../../../hw/sys/smc/doc/assets/smc-clock-distribution.svg) | Redrawn as hand-authored SVG from the imported figure |

## DTP

| Figure | Description | Authored page | Asset | Notes |
| --- | --- | --- | --- | --- |
| FIG001 | DTP top-level architecture | [hw/sys/dtp/doc/overview.adoc](../../../hw/sys/dtp/doc/overview.adoc) | [hw/sys/dtp/doc/assets/dtp_arch_overview.svg](../../../hw/sys/dtp/doc/assets/dtp_arch_overview.svg) | Retains the revised repository drawing; original Drive SVG is already stored as dtp_arch_diagram.drawio.svg despite its .png filename |
| FIG002 | Full JTAG scan-chain topology | [hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc](../../../hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc) | [hw/ip/jtag/jtag_intf_unit/doc/assets/jtag_scan_chain.drawio.svg](../../../hw/ip/jtag/jtag_intf_unit/doc/assets/jtag_scan_chain.drawio.svg) | Existing source; staged as jtag_scan_chain.svg |
| FIG003 | PTAP architecture and instruction routing | [hw/ip/jtag/jtag_ptap/doc/architecture.adoc](../../../hw/ip/jtag/jtag_ptap/doc/architecture.adoc) | [hw/ip/jtag/jtag_ptap/doc/assets/ptap_module_diagram.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/ptap_module_diagram.svg) | Retains the revised repository drawing |
| FIG004 | STAP architecture and host/lifecycle gating | [hw/ip/jtag/jtag_stap/doc/architecture.adoc](../../../hw/ip/jtag/jtag_stap/doc/architecture.adoc) | [hw/ip/jtag/jtag_stap/doc/assets/stap_module_diagram.svg](../../../hw/ip/jtag/jtag_stap/doc/assets/stap_module_diagram.svg) | Retains the revised repository drawing |
| FIG007 | JTAG2AXI single-operation and protocol waveform suite | [hw/ip/jtag/jtag_ptap/doc/architecture.adoc](../../../hw/ip/jtag/jtag_ptap/doc/architecture.adoc) | [hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_ctrl.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_ctrl.svg)<br>[hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_error0.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_error0.svg)<br>[hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_error1.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_error1.svg)<br>[hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_error2.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_error2.svg)<br>[hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_error3.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_error3.svg)<br>[hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_incr0.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_incr0.svg)<br>[hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_incr1.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_incr1.svg)<br>[hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_incr2.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_incr2.svg)<br>[hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_incr3.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_series_data_incr3.svg)<br>[hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_single_op.svg](../../../hw/ip/jtag/jtag_ptap/doc/assets/jtag2axi_single_op.svg) | Existing byte-identical protocol suite |
| FIG010 | DTP clock-stop aggregation: JTAG DEBUG_CONTROL + CLA/CTN | [hw/sys/dtp/doc/clock_stop.adoc](../../../hw/sys/dtp/doc/clock_stop.adoc) | [hw/sys/dtp/doc/assets/DTP_ClockStopAggregration_FIG010.png](../../../hw/sys/dtp/doc/assets/DTP_ClockStopAggregration_FIG010.png) | Imported |
| FIG011 | Cross Trigger Network architecture and SiP topology | [hw/ip/cross_trigger/cross_trigger_network/doc/architecture.adoc](../../../hw/ip/cross_trigger/cross_trigger_network/doc/architecture.adoc) | [hw/ip/cross_trigger/cross_trigger_network/doc/assets/sip_xtrig_diagram.png](../../../hw/ip/cross_trigger/cross_trigger_network/doc/assets/sip_xtrig_diagram.png) | Existing byte-identical figure |
| FIG012 | Cross Trigger Port module | [hw/ip/cross_trigger/cross_trigger_port/doc/architecture.adoc](../../../hw/ip/cross_trigger/cross_trigger_port/doc/architecture.adoc) | [hw/ip/cross_trigger/cross_trigger_port/doc/assets/ctp_module_diagram.png](../../../hw/ip/cross_trigger/cross_trigger_port/doc/assets/ctp_module_diagram.png) | Existing byte-identical figure |
| FIG013 | Wire-OR CTP and SiP topology suite | [hw/ip/cross_trigger/cross_trigger_port/doc/architecture.adoc](../../../hw/ip/cross_trigger/cross_trigger_port/doc/architecture.adoc) | [hw/ip/cross_trigger/cross_trigger_port/doc/assets/ctp_wireor_diagram.png](../../../hw/ip/cross_trigger/cross_trigger_port/doc/assets/ctp_wireor_diagram.png)<br>[hw/ip/cross_trigger/cross_trigger_port/doc/assets/sip_wireor_diagram.png](../../../hw/ip/cross_trigger/cross_trigger_port/doc/assets/sip_wireor_diagram.png) | Existing byte-identical CTP and SiP suite |
| FIG014 | Point-to-point CTP and SiP topology suite | [hw/ip/cross_trigger/cross_trigger_port/doc/architecture.adoc](../../../hw/ip/cross_trigger/cross_trigger_port/doc/architecture.adoc) | [hw/ip/cross_trigger/cross_trigger_port/doc/assets/ctp_p2p_diagram.png](../../../hw/ip/cross_trigger/cross_trigger_port/doc/assets/ctp_p2p_diagram.png)<br>[hw/ip/cross_trigger/cross_trigger_port/doc/assets/sip_p2p_diagram.png](../../../hw/ip/cross_trigger/cross_trigger_port/doc/assets/sip_p2p_diagram.png) | Existing byte-identical CTP and SiP suite |
| FIG015 | Point-to-point request/ack timing | [hw/ip/cross_trigger/cross_trigger_port/doc/architecture.adoc](../../../hw/ip/cross_trigger/cross_trigger_port/doc/architecture.adoc) | [hw/ip/cross_trigger/cross_trigger_port/doc/assets/p2p_timing_diagram.svg](../../../hw/ip/cross_trigger/cross_trigger_port/doc/assets/p2p_timing_diagram.svg) | Existing timing figure generated from p2p_timing_diagram.json5 |
| FIG016 | Cross Trigger Matrix architecture and routing | [hw/ip/cross_trigger/cross_trigger_matrix/doc/architecture.adoc](../../../hw/ip/cross_trigger/cross_trigger_matrix/doc/architecture.adoc) | [hw/ip/cross_trigger/cross_trigger_matrix/doc/assets/ctm_module_diagram.png](../../../hw/ip/cross_trigger/cross_trigger_matrix/doc/assets/ctm_module_diagram.png) | Existing byte-identical figure |
| FIG021 | DTP clocking architecture | [hw/sys/dtp/doc/clock_stop.adoc](../../../hw/sys/dtp/doc/clock_stop.adoc) | [hw/sys/dtp/doc/assets/DTP_ClockingArchitecture_FIG021.png](../../../hw/sys/dtp/doc/assets/DTP_ClockingArchitecture_FIG021.png) | Imported |
| FIG022 | DTP reset architecture | [hw/sys/dtp/doc/clock_stop.adoc](../../../hw/sys/dtp/doc/clock_stop.adoc) | [hw/sys/dtp/doc/assets/DTP_ResetArchitecture_FIG022.png](../../../hw/sys/dtp/doc/assets/DTP_ResetArchitecture_FIG022.png) | Imported |

## Entries without supplied TRM figures

The FuSa worksheet lists no downloadable assets for the high-level safety
architecture, safety-bus propagation, four self-test diagrams, or the
point-to-point parity/self-test connection. These require source figures.
The SMN topology entry is blocked by its specification in the index and has no
asset. The AoU entry describes an obsolete placeholder; the TRM already includes
the vendored AoU architecture chapter.

The SMU technology-integration figure belongs to the Integrator Guide and the
SEP secure-boot flow belongs to Appnotes. They are outside this TRM import.

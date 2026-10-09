// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Graded-window owner codes of the Phase 2 FCOV sampler (docs/SEP_FCOV.adoc,
// graded window). One table for the sampler and the cocotb leaves:
// cov/sv/sep_fcov.sv includes it, and cocotb/env/sep_fcov_gate.py reads it.
//
// A code names one Phase 3 VPLAN entry: area * 100 + entry number, so 2.25 is
// 225. 0 means "no window open". Each line is
//   localparam int unsigned FcovOwn<TestNameInCamelCase> = <code>;
// and the test name is the testcase module name of the entry, for example
// FcovOwnSepFabricInboundRebaseTest for sep_fabric_inbound_rebase_test. Add a line for a
// new owner; never reuse a code.

localparam int unsigned FcovOwnNone = 0;

// Fabric and remap (VPLAN 2.25 to 2.33).
localparam int unsigned FcovOwnSepFabricInboundRebaseTest = 225;
localparam int unsigned FcovOwnSepFabricFilterMatchPriorityRandTest = 226;
localparam int unsigned FcovOwnSepFabricOutboundRouteAttrTest = 227;
localparam int unsigned FcovOwnSepFabricAliasRemapAttrRandTest = 228;
localparam int unsigned FcovOwnSepFabricSmcRouteTest = 229;
localparam int unsigned FcovOwnSepFabricExtensionPortWindowTest = 230;
localparam int unsigned FcovOwnSepFabricRowResponseMatrixTest = 231;
localparam int unsigned FcovOwnSepCpuLsuAliasWindowTwinTest = 232;
localparam int unsigned FcovOwnSepFabricDmaEndpointMatrixTest = 233;

// SPI and DMA (VPLAN 4.7 to 4.15).
localparam int unsigned FcovOwnSepSpiPadSpeedDirMatrixTest = 407;
localparam int unsigned FcovOwnSepSpiPadTimingCfgRandTest = 408;
localparam int unsigned FcovOwnSepSpiFifoStallWatermarkRandTest = 409;
localparam int unsigned FcovOwnSepSpiOtHostCsrIrqRandTest = 410;
localparam int unsigned FcovOwnSepSpiColdResetValuesRandTest = 411;
localparam int unsigned FcovOwnSepDmaTransferMatrixRandTest = 412;
localparam int unsigned FcovOwnSepDmaIrqErrorLockRandTest = 413;
localparam int unsigned FcovOwnSepDmaAbortRecoveryRandTest = 414;
localparam int unsigned FcovOwnSepSpiDmaHandshakeRandTest = 415;

// Memory, boot, reset (VPLAN 5.25): owner of
// sep_fabric_dedicated_port_cg.cp_tcm_dma_dir_range.
localparam int unsigned FcovOwnSepTcmDmaApertureEccTest = 525;

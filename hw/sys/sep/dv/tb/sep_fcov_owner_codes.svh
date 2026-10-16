// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Graded-window owner codes of the FCOV sampler (docs/SEP_FCOV.adoc, graded
// window). One table for the sampler and the cocotb leaves:
// cov/sv/sep_fcov.sv includes it, and cocotb/env/sep_fcov_gate.py reads it.
//
// A code names one owning test. The values are stable identifiers with no
// ordering meaning. 0 means "no window open". Each line is
//   localparam int unsigned FcovOwn<TestNameInCamelCase> = <code>;
// and the test name is the testcase module name of the entry, for example
// FcovOwnSepFabricInboundRebaseTest for sep_fabric_inbound_rebase_test. Add a line for a
// new owner; never reuse a code.

localparam int unsigned FcovOwnNone = 0;

// Fabric and remap.
localparam int unsigned FcovOwnSepFabricInboundRebaseTest = 225;
localparam int unsigned FcovOwnSepFabricFilterMatchPriorityRandTest = 226;
localparam int unsigned FcovOwnSepFabricOutboundRouteAttrTest = 227;
localparam int unsigned FcovOwnSepFabricAliasRemapAttrRandTest = 228;
localparam int unsigned FcovOwnSepFabricSmcRouteTest = 229;
localparam int unsigned FcovOwnSepFabricExtensionPortWindowTest = 230;
localparam int unsigned FcovOwnSepFabricRowResponseMatrixTest = 231;
localparam int unsigned FcovOwnSepCpuLsuAliasWindowTwinTest = 232;
localparam int unsigned FcovOwnSepFabricDmaEndpointMatrixTest = 233;

// Mailbox, IRQ and PIC.
localparam int unsigned FcovOwnSepMailboxFifoModelRandTest = 313;
localparam int unsigned FcovOwnSepMailboxAccessErrorInjectTest = 314;
localparam int unsigned FcovOwnSepMailboxFilterTypeMatrixTest = 315;
localparam int unsigned FcovOwnSepMailboxDebugBypassTest = 316;
localparam int unsigned FcovOwnSepMailboxResetClearTest = 317;
localparam int unsigned FcovOwnSepPicRegRandTest = 318;
localparam int unsigned FcovOwnSepPicExternalAccessRefuseTest = 319;
localparam int unsigned FcovOwnSepPicPriorityGateRandTest = 320;
localparam int unsigned FcovOwnSepPicPendingMapWalkRandTest = 321;
localparam int unsigned FcovOwnSepCpuBridgeFaultMatrixRandTest = 322;
localparam int unsigned FcovOwnSepCpuCtrlTimeoutInertRandTest = 323;
localparam int unsigned FcovOwnSepNmiVectorBarkRandTest = 324;

// SPI and DMA.
localparam int unsigned FcovOwnSepSpiPadSpeedDirMatrixTest = 407;
localparam int unsigned FcovOwnSepSpiPadTimingCfgRandTest = 408;
localparam int unsigned FcovOwnSepSpiFifoStallWatermarkRandTest = 409;
localparam int unsigned FcovOwnSepSpiOtHostCsrIrqRandTest = 410;
localparam int unsigned FcovOwnSepSpiColdResetValuesRandTest = 411;
localparam int unsigned FcovOwnSepDmaTransferMatrixRandTest = 412;
localparam int unsigned FcovOwnSepDmaIrqErrorLockRandTest = 413;
localparam int unsigned FcovOwnSepDmaAbortRecoveryRandTest = 414;
localparam int unsigned FcovOwnSepSpiDmaHandshakeRandTest = 415;
localparam int unsigned FcovOwnSepDmaZeroFillRandTest = 416;
localparam int unsigned FcovOwnSepSpiOtDmaRxTest = 417;
localparam int unsigned FcovOwnSepSpiPadOeRulesTest = 418;
localparam int unsigned FcovOwnSepSpiOtFlashCmdRandTest = 419;
localparam int unsigned FcovOwnSepSpiOtDmaTxTest = 420;
localparam int unsigned FcovOwnSepDmaZeroFillContinuationTest = 421;
localparam int unsigned FcovOwnSepDmaZeroTest = 422;

// Memory, boot, reset, WDT and clock. SepTcmDmaApertureEccTest also owns
// sep_fabric_dedicated_port_cg.cp_tcm_dma_dir_range.
localparam int unsigned FcovOwnSepBootReleaseTermsTest = 513;
localparam int unsigned FcovOwnSepColdResetPhaseTest = 514;
localparam int unsigned FcovOwnSepCpuResetRetentionTest = 515;
localparam int unsigned FcovOwnSepSwResetIsolationMatrixTest = 516;
localparam int unsigned FcovOwnSepIpResetOverrideMatrixTest = 517;
localparam int unsigned FcovOwnSepScanResetOverrideTest = 518;
localparam int unsigned FcovOwnSepCpuResetEntryTest = 519;
localparam int unsigned FcovOwnSepSecureTmStrapSamplingTest = 520;
localparam int unsigned FcovOwnSepCpuCtrlRegShapeTest = 521;
localparam int unsigned FcovOwnSepTimerClockContractTest = 522;
localparam int unsigned FcovOwnSepBootRomApertureSweepTest = 523;
localparam int unsigned FcovOwnSepSramAxiShapeMatrixTest = 524;
localparam int unsigned FcovOwnSepTcmDmaApertureEccTest = 525;
localparam int unsigned FcovOwnSepTcmEccCpuTrapTest = 526;
localparam int unsigned FcovOwnSepCpuDemuxUnmappedFetchTest = 527;
localparam int unsigned FcovOwnSepDebugMasterTargetMatrixTest = 528;
localparam int unsigned FcovOwnSepCpuIsaPmpCsrTest = 529;

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

// Crypto and entropy.
localparam int unsigned FcovOwnSepIrqIpToAggregatorTest = 125;
localparam int unsigned FcovOwnSepCryptoEdnMultisinkArbitrationTest = 126;
localparam int unsigned FcovOwnSepHmacIllegalCfgStartTest = 127;
localparam int unsigned FcovOwnSepHmacFifoStreamRandTest = 128;
localparam int unsigned FcovOwnSepHmacSwapContextRandTest = 129;
localparam int unsigned FcovOwnSepCryptoDeliveredKeySelectRandTest = 130;
localparam int unsigned FcovOwnSepAesEncodingInjectRandTest = 131;
localparam int unsigned FcovOwnSepAesStreamStatusRandTest = 132;
localparam int unsigned FcovOwnSepAesReseedTriggerRandTest = 133;
localparam int unsigned FcovOwnSepCryptoShadowUpdateErrRandTest = 134;
localparam int unsigned FcovOwnSepKmacUnsupportedCfgInjectTest = 135;
localparam int unsigned FcovOwnSepKmacStreamCfgRandTest = 136;
localparam int unsigned FcovOwnSepKmacEntropyModeRandTest = 137;
localparam int unsigned FcovOwnSepOtbnCmdStatusRandTest = 138;
localparam int unsigned FcovOwnSepAbrCommandMatrixRandTest = 139;
localparam int unsigned FcovOwnSepEsrcCsrRwWalkRandTest = 140;
localparam int unsigned FcovOwnSepEsrcHealthPatternRandTest = 141;
localparam int unsigned FcovOwnSepEsrcPersistentAlertRandTest = 142;
localparam int unsigned FcovOwnSepEsrcAutotuneDetuneTest = 143;
localparam int unsigned FcovOwnSepEsrcStartupGateRandTest = 144;
localparam int unsigned FcovOwnSepEsrcConditioningMatrixRandTest = 145;
localparam int unsigned FcovOwnSepEsrcFifoFlowRandTest = 146;
localparam int unsigned FcovOwnSepEsrcObserveFifoRandTest = 147;
localparam int unsigned FcovOwnSepDrbgFatalErrInjectRandTest = 148;
localparam int unsigned FcovOwnSepDrbgRegwenLockRandTest = 149;
localparam int unsigned FcovOwnSepDrbgCmdSequenceRandTest = 150;
localparam int unsigned FcovOwnSepTrngExtStreamHandshakeRandTest = 151;
localparam int unsigned FcovOwnSepTrngExtSinkResetRandTest = 152;
localparam int unsigned FcovOwnSepDrbgSinkMixRandTest = 153;
localparam int unsigned FcovOwnSepAesCfbOfbGcmRandTest = 154;
localparam int unsigned FcovOwnSepAbrMldsaHintRejectKatTest = 155;
localparam int unsigned FcovOwnSepOtbnComputeRandTest = 738;
localparam int unsigned FcovOwnSepKmIsolateTerminationTest = 739;
localparam int unsigned FcovOwnSepDrbgAxilAdapterRefusalTest = 740;
localparam int unsigned FcovOwnSepCryptoPerIpResetIsolationTest = 741;
localparam int unsigned FcovOwnSepAbrAccessSizeTest = 742;
localparam int unsigned FcovOwnSepEsrcFipsLockTest = 743;
localparam int unsigned FcovOwnSepEsrcHtWatermarkArmingTest = 744;
localparam int unsigned FcovOwnSepEntropyPoolApertureTest = 745;
localparam int unsigned FcovOwnSepTrngResetRecoveryTest = 746;
localparam int unsigned FcovOwnSepEsrcE2eSmokeTest = 747;
localparam int unsigned FcovOwnSepCryptoCsrWideAccessTest = 748;
localparam int unsigned FcovOwnSepAbrConcurrentRwTest = 750;
localparam int unsigned FcovOwnSepDrbgAxilConcurrentCsrngAwThenArTest = 751;
localparam int unsigned FcovOwnSepDrbgAxilConcurrentEdnAwThenArTest = 752;
localparam int unsigned FcovOwnSepAbrMldsaKeygenKatTest = 753;

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
localparam int unsigned FcovOwnSepFabricDeadspaceDecodeTest = 234;
localparam int unsigned FcovOwnSepUnmappedAccessPolicyTest = 755;
localparam int unsigned FcovOwnSepFabricInboundFilterRuleMatrixTest = 757;
localparam int unsigned FcovOwnSepAxiStrobeWindowTest = 758;
localparam int unsigned FcovOwnSepAxiIdRoutingTest = 759;
localparam int unsigned FcovOwnSepFabricOutboundRemapFilterWalkTest = 760;
localparam int unsigned FcovOwnSepFabricInboundFilterWindowWalkTest = 761;
localparam int unsigned FcovOwnSepFabricRemapFilterCsrBankTest = 762;
localparam int unsigned FcovOwnSepFabricSlotCsrStrobeRandTest = 767;

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
localparam int unsigned FcovOwnSepPeriphBusErrMisalignedTest = 763;
localparam int unsigned FcovOwnSepMailboxPlicTest = 780;

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
localparam int unsigned FcovOwnSepDmaBasicTest = 765;

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
localparam int unsigned FcovOwnSepCpuZbeExecTest = 530;
localparam int unsigned FcovOwnSepScanModeStateHoldTest = 531;
localparam int unsigned FcovOwnSepCpuIfuLsuAliasRemapMatrixTest = 764;
localparam int unsigned FcovOwnSepWdtAonTimerInternalsTest = 766;
localparam int unsigned FcovOwnSepClockGateControlTest = 772;
localparam int unsigned FcovOwnSepTestEnPinReachTest = 773;
localparam int unsigned FcovOwnSepAxiPartialLaneReadTest = 774;

// eFuse, lifecycle and SEC_DIS.
localparam int unsigned FcovOwnSepEfuseWindowDecodeResetTest = 618;
localparam int unsigned FcovOwnSepEfuseFieldLayoutRandTest = 619;
localparam int unsigned FcovOwnSepLccStateCodewordRandTest = 620;
localparam int unsigned FcovOwnSepLccFeatCtrlStateMatrixRandTest = 621;
localparam int unsigned FcovOwnSepEfuseTransientRmaRandTest = 622;
localparam int unsigned FcovOwnSepEfuseTokenChannelRandTest = 623;
localparam int unsigned FcovOwnSepEfuseTokenFaultMatrixTest = 624;
localparam int unsigned FcovOwnSepEfuseInterfaceStatusRandTest = 625;
localparam int unsigned FcovOwnSepEfuseLockSlotMatrixRandTest = 626;
localparam int unsigned FcovOwnSepEfuseSecureTmMatrixRandTest = 627;
localparam int unsigned FcovOwnSepEfuseJtagAccessRandTest = 628;
localparam int unsigned FcovOwnSepSecDisTimingRandTest = 629;
localparam int unsigned FcovOwnSepEfuseShimResponseFaultTest = 630;
localparam int unsigned FcovOwnSepLockedFieldAccessIrqPathTest = 754;
localparam int unsigned FcovOwnSepEfuseImageTest = 768;
localparam int unsigned FcovOwnSepLccDemoteFeatCtrlMatrixTest = 769;
localparam int unsigned FcovOwnSepSecDisOverrideTest = 770;
localparam int unsigned FcovOwnSepEfuseLccLcStateStitchTest = 771;

// Key Manager.
localparam int unsigned FcovOwnSepKmCommandProtocolRandTest = 722;
localparam int unsigned FcovOwnSepKmKeyTransferRandTest = 724;
localparam int unsigned FcovOwnSepKmBootResetRandTest = 726;
localparam int unsigned FcovOwnSepKmHandoverRandTest = 727;
localparam int unsigned FcovOwnSepKmFaultInjectRandTest = 728;
localparam int unsigned FcovOwnSepKmKmcsrResetRandTest = 729;
localparam int unsigned FcovOwnSepKmKpvRandTest = 730;
localparam int unsigned FcovOwnSepKmCpuProtectRandTest = 731;
localparam int unsigned FcovOwnSepKmCrossbarEfuseWindowRandTest = 732;
localparam int unsigned FcovOwnSepKmMailboxKmSideRandTest = 733;
localparam int unsigned FcovOwnSepKmDrbgSamplerRandTest = 734;
localparam int unsigned FcovOwnSepKmOtpInterfaceRandTest = 735;
localparam int unsigned FcovOwnSepKmKeyBankRegisterRandTest = 736;
localparam int unsigned FcovOwnSepKmSramScramblerKeyRandTest = 737;
localparam int unsigned FcovOwnSepKmDrbgSamplerTimeoutResetTest = 775;
localparam int unsigned FcovOwnSepKmHandoverTest = 776;
localparam int unsigned FcovOwnSepKmCrcPcpiKatTest = 777;
localparam int unsigned FcovOwnSepKmRomWriteErrTest = 778;
localparam int unsigned FcovOwnSepEfuseKmPublicIdTest = 779;

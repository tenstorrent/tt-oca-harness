// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

 // Trace Sink: Implements the Trace SRAM for the two trace sink modes

module dfd_trace_sink
  import dfd_tn_pkg::*;
  import dfd_tr_csr_pkg::*;
#(
  parameter int unsigned AXI_ADDR_WIDTH = 64,
  parameter int unsigned AXI_DATA_WIDTH = 64,
  parameter NUM_CORES = 8,
  localparam NUM_CORES_IN_PATH = NUM_CORES>>1,

  parameter int MAX_DELAY_IN_PATH = 16,

  parameter DATA_WIDTH_IN_BYTES = 16,
  parameter DATA_WIDTH = DATA_WIDTH_IN_BYTES*8,

  type SinkMemPktIn_s  = logic,
  type SinkMemPktOut_s = logic,
  parameter TRC_RAM_INDEX = 512,
  localparam TRC_RAM_INDEX_WIDTH = $clog2(TRC_RAM_INDEX),

  parameter logic [15:0] TR_SINK_FLUSH_TIMEOUT = 16'hFF,

  /* verilator lint_off REALCVT */
  localparam int INFLIGHT_PKT_CNT = $ceil(2*MAX_DELAY_IN_PATH/4),
  localparam int INFLIGHT_FRAME_CNT_64B = $ceil(INFLIGHT_PKT_CNT/4)+2,
  localparam int INFLIGHT_FRAME_CNT_128B = $ceil(INFLIGHT_PKT_CNT/8)+2,
  localparam int INFLIGHT_FRAME_CNT_256B = $ceil(INFLIGHT_PKT_CNT/16)+2,
  localparam int INFLIGHT_FRAME_CNT_512B = $ceil(INFLIGHT_PKT_CNT/32)+2
  /* verilator lint_off REALCVT */
)(
  input   logic                                                 clk,
  input   logic                                                 reset_n,

  // Trace Funnel Interface
  // North Branch
  input   logic                                                 TR_TS_North_Src,
  input   logic [DATA_WIDTH-1:0]                                TR_TS_North_Data,
  input   logic [NUM_CORES_IN_PATH-1:0]                         TR_TS_North_Vld,
  // South Branch
  input   logic                                                 TR_TS_South_Src,
  input   logic [DATA_WIDTH-1:0]                                TR_TS_South_Data,
  input   logic [NUM_CORES_IN_PATH-1:0]                         TR_TS_South_Vld,
  // Funnel interface for the Backpressure
  output  logic                                                 TS_TR_Ntrace_Bp,
  output  logic                                                 TS_TR_Dst_Bp,
  // Funnel interface for the Flush
  output  logic                                                 TS_TR_Ntrace_Flush,
  output  logic                                                 TS_TR_Dst_Flush,
  // Num Enbled sources
  input  logic [$clog2(8):0]                                    TR_TS_Ntrace_NumEnabled_Srcs,
  input  logic [$clog2(8):0]                                    TR_TS_Dst_NumEnabled_Srcs,

  // Trace Control Interface Signals
  // N-trace
  input   TrTrramcontrolCsr_s                                   TrCsrTrramcontrol,
  input   TrTrramimplCsr_s                                      TrCsrTrramimpl,
  input   TrTrramstartlowCsr_s                                  TrCsrTrramstartlow,
  input   TrTrramstarthighCsr_s                                 TrCsrTrramstarthigh,
  input   TrTrramlimitlowCsr_s                                  TrCsrTrramlimitlow,
  input   TrTrramlimithighCsr_s                                 TrCsrTrramlimithigh,
  input   TrTrramwplowCsr_s                                     TrCsrTrramwplow,
  input   TrTrramwphighCsr_s                                    TrCsrTrramwphigh,
  input   TrTrramrplowCsr_s                                     TrCsrTrramrplow,
  input   logic                                                 trRamDataRdEn_ANY,
  // DST
  input   TrTrdstramcontrolCsr_s                                TrCsrTrdstramcontrol,
  input   TrTrdstramimplCsr_s                                   TrCsrTrdstramimpl,
  input   TrTrdstramstartlowCsr_s                               TrCsrTrdstramstartlow,
  input   TrTrdstramstarthighCsr_s                              TrCsrTrdstramstarthigh,
  input   TrTrdstramlimitlowCsr_s                               TrCsrTrdstramlimitlow,
  input   TrTrdstramlimithighCsr_s                              TrCsrTrdstramlimithigh,
  input   TrTrdstramwplowCsr_s                                  TrCsrTrdstramwplow,
  input   TrTrdstramwphighCsr_s                                 TrCsrTrdstramwphigh,
  input   TrTrdstramrplowCsr_s                                  TrCsrTrdstramrplow,
  input   logic                                                 trdstRamDataRdEn_ANY,

  // Custom
  input   TrTrcustomramsmemlimitlowCsr_s                        TrCsrTrcustomramsmemlimitlow,

  // Trace MMR Write ports
  // N-trace
  output  TrTrramcontrolCsrWr_s                                 TrCsrTrramcontrolWr,
  output  TrTrramwplowCsrWr_s                                   TrCsrTrramwplowWr,
  output  TrTrramwphighCsrWr_s                                  TrCsrTrramwphighWr,
  output  TrTrramrplowCsrWr_s                                   TrCsrTrramrplowWr,
  output  TrTrramrphighCsrWr_s                                  TrCsrTrramrphighWr,
  output  TrTrramdataCsrWr_s                                    TrCsrTrramdataWr,
  
  // DST
  output  TrTrdstramcontrolCsrWr_s                              TrCsrTrdstramcontrolWr,
  output  TrTrdstramwplowCsrWr_s                                TrCsrTrdstramwplowWr,
  output  TrTrdstramwphighCsrWr_s                               TrCsrTrdstramwphighWr,
  output  TrTrdstramrplowCsrWr_s                                TrCsrTrdstramrplowWr,
  output  TrTrdstramrphighCsrWr_s                               TrCsrTrdstramrphighWr,
  output  TrTrdstramdataCsrWr_s                                 TrCsrTrdstramdataWr,

  // Trace SRAM writes
  output  logic                                                 TraceRamWrEn_TS0,

  // Trace SMEM Interface
  output  logic                                                 TrMemAxiWrVld_ANY,   
  output  logic [AXI_ADDR_WIDTH-1:0]                            TrMemAxiWrAddr_ANY,
  output  logic [AXI_DATA_WIDTH-1:0]                            TrMemAxiWrData_ANY,
  input   logic                                                 TrMemAxiWrRdy_ANY,

  // Trace Sink Memory Interface
  output SinkMemPktIn_s  [TRC_RAM_INSTANCES-1:0]                SinkMemPktIn,
  input  SinkMemPktOut_s [TRC_RAM_INSTANCES-1:0]                SinkMemPktOut
);

  // --------------------------------------------------------------------------
  // Internal Signals
  // --------------------------------------------------------------------------

  typedef struct packed {
    logic [$clog2(TRC_RAM_WAYS)-1:0]     TrRamPendWayIdx_ANY;
    logic [TRC_RAM_INDEX_WIDTH-1:0]      TrRamPendAddr_ANY;
    logic [DATA_WIDTH-1:0]               TrRamPendData_ANY;
    logic                                TrRamPendSrc_ANY; //Determine if the packet is Ntrace or DST
  } TrRamPendPkt_s;

  // Timing staging flops
  logic [31:2]                                                                    trnorthcoreRamWpLow_ANY_stg, trsouthcoreRamWpLow_ANY_stg;
  logic [DATA_WIDTH-1:0]                                                          TR_TS_North_Data_stg, TR_TS_South_Data_stg;
  logic                                                                           TR_TS_North_Src_stg, TR_TS_South_Src_stg;
  logic [NUM_CORES_IN_PATH-1:0]                                                   Eff_TR_TS_North_Vld_stg, Eff_TR_TS_South_Vld_stg;
  logic                                                                           trntrnextlocaltoupdateRamWpWrap_ANY_stg, trntrnextlocaltoupdateRamWpWrap_ANY_stg_d1, trntrnextlocaltoupdateRamWpWrap_ANY_stg_d2;
  logic                                                                           trdstnextlocaltoupdateRamWpWrap_ANY_stg, trdstnextlocaltoupdateRamWpWrap_ANY_stg_d1, trdstnextlocaltoupdateRamWpWrap_ANY_stg_d2;

  // Multiple core handling pointers
  logic [9:0]                                                                     trntrFrameLength_ANY, trdstFrameLength_ANY; // Supported frame_lengths are {1-64,2-128,3-256,4-512} bytes
  logic [NUM_CORES-1:0]                                                           trntrcoreNewFrameStart_ANY, trdstcoreNewFrameStart_ANY;
  logic [NUM_CORES-1:0]                                                           trntrfirstcoreNewFrameStart_ANY, trdstfirstcoreNewFrameStart_ANY;
  logic [NUM_CORES-1:0]                                                           trntrcoreFrameFillComplete_ANY, trntrcoreFrameFillComplete_d1_ANY;
  logic [NUM_CORES-1:0]                                                           trdstcoreFrameFillComplete_ANY, trdstcoreFrameFillComplete_d1_ANY;

  logic [8:0]                                                                     trntrNumFramesFilledInSRAM_ANY, trntrNumFramesFilledInSRAM_ANY_d1;
  logic [8:0]                                                                     trntrNumFrameFillComplete_ANY, trntrNumFrameFillComplete_ANY_d1;

  logic [8:0]                                                                     trdstNumFramesFilledInSRAM_ANY, trdstNumFramesFilledInSRAM_ANY_d1;
  logic [8:0]                                                                     trdstNumFrameFillComplete_ANY, trdstNumFrameFillComplete_ANY_d1;

  logic [31:2]                                                                    trnorthcoreRamWpLow_ANY, trsouthcoreRamWpLow_ANY;

  // SRAM write pending flops 
  TrRamPendPkt_s [7:0]                                                            TrRamPendPktWr_ANY;
  TrRamPendPkt_s                                                                  TrRamPendPktNorthWr_TS0, TrRamPendPktSouthWr_TS0;
  logic                                                                           TrRamPendPktNorthWrEn_TS0, TrRamPendPktSouthWrEn_TS0;
  TrRamPendPkt_s [7:0]                                                            TrRamPendPktRd_ANY;
  logic [7:0]                                                                     TrRamPendWrEn_ANY, TrRamPendBufferNorthWrEn_ANY, TrRamPendBufferSouthWrEn_ANY;
  logic [1:0][7:0]                                                                TrRamPendWrEn_Select_ANY;
  logic [7:0]                                                                     TrRamPendRdEn_ANY;
  logic [7:0]                                                                     TrRamPendPktVld_ANY; // Valid vector for the entries stored
  logic [7:0]                                                                     TrRamPendNtracePktVld_ANY, TrRamPendDstPktVld_ANY;
  logic [TRC_RAM_WAYS-1:0]                                                        TrdstRamPendPktInhibitRamRd_ANY, TrdstRamPendPktInhibitRamRd_ANY_stg;
  logic [TRC_RAM_WAYS-1:0]                                                        TrntrRamPendPktInhibitRamRd_ANY, TrntrRamPendPktInhibitRamRd_ANY_stg;
  logic [TRC_RAM_WAYS-1:0][2:0]                                                   TrRamNorthCoreWrWayPendWriteCnt_ANY, TrRamSouthCoreWrWayPendWriteCnt_ANY, TrRamPerWayPendToWriteCnt_TS1, TrRamPerWayNextPendToWriteCnt_TS0;
  logic [TRC_RAM_WAYS-1:0]                                                        TrRamFreeWayMask_ANY, TrRamFreeWayMaskPend_ANY, TrRamFreeWayMaskPend_ANY_stg;

  // Backpressure controls
  logic [7:0]                                                                     TN_TR_InFlight_PktCnt;
  logic [5:0]                                                                     TN_TR_NTrace_NumPkt_PerFrame, TN_TR_Dst_NumPkt_PerFrame;
  logic [3:0]                                                                     InsnTrace_NumSetsPerFrame_ANY, DataTrace_NumSetsPerFrame_ANY;
  logic [3:0]                                                                     InsnTrace_NumInFlightFrame_ANY, DataTrace_NumInFlightFrame_ANY;
  logic [31:0]                                                                    InsnTrace_InFlightData_BackPressure_Threshold_ANY, DataTrace_InFlightData_BackPressure_Threshold_ANY;
  logic [AXI_ADDR_WIDTH-1:0]                                                      trntrMemAvailableSpace_ANY, trdstMemAvailableSpace_ANY;
  logic [AXI_ADDR_WIDTH-1:0]                                                      trntrMemBytestoWrite_ANY, trdstMemBytestoWrite_ANY;
  logic                                                                           trdstRamModeBP_ANY, trdstMemModeBP_ANY;
  logic                                                                           trntrRamModeBP_ANY, trntrMemModeBP_ANY;

  // SMEM mode storage buffer
  logic                                                                           TrMemAxiWrVld_NtraceOrDst_ANY;
  // DST
  logic [TRC_RAM_INSTANCES-1:0][TRC_RAM_DATA_WIDTH-1:0]                           TrdstMemRdBuffer_TS3;
  logic [TRC_RAM_INSTANCES-1:0]                                                   TrdstMemRdBufferVld_TS3, TrdstMemRdBufferVld_TS4, TrdstMemRdBufferVld_TS5;
  logic [TRC_RAM_INDEX_WIDTH:0]                                                   TrdstMemRamRdAddrFlop_ANY;
  logic [TRC_RAM_INDEX_WIDTH-1:0]                                                 TrdstMemRamRdAddr_TS1, TrdstMemRamRdAddr_TS1_stg;
  logic                                                                           TrdstMemRamRdAddrWrap_ANY;
  logic                                                                           TrdstMemRdBufferFull_ANY;
  logic                                                                           TrdstMemAxiWrVld_ANY;
  logic [AXI_ADDR_WIDTH-1:0]                                                      TrdstMemAxiWrAddr_ANY;
  logic                                                                           TrdstMemAxiWrAddrWrap_ANY;
  logic [AXI_ADDR_WIDTH-1:0]                                                      trdstMemSMEMStartAddr_ANY, trdstMemSMEMLimitAddr_ANY;
  logic [AXI_DATA_WIDTH-1:0]                                                      TrdstMemAxiWrData_ANY;
  logic                                                                           TrdstMemRamRdRdy_TS1;
  logic [TRC_RAM_INSTANCES-1:0]                                                   TrdstMemRamRdEn_TS1, TrdstMemRamRdEn_TS1_stg;
  logic [TRC_RAM_INSTANCES-1:0]                                                   TrdstMemRamRdEn_TS2;
  logic                                                                           trdstMemModeEnable_ANY;
  logic                                                                           TrdstMemRamRdRamEn_ANY;
  logic                                                                           TrdstMemModeRamBackPressure_ANY;
  logic [15:0]                                                                    TrdstFlushTimeoutCntr_ANY;
  logic                                                                           TrdstFlushTimeoutStart_ANY, TrdstFlushTimeoutDone_ANY, TrdstFlushTimeoutCntrClr_ANY;
  // N-Trace
  logic [TRC_RAM_INSTANCES-1:0][TRC_RAM_DATA_WIDTH-1:0]                           TrntrMemRdBuffer_TS3;
  logic [TRC_RAM_INSTANCES-1:0]                                                   TrntrMemRdBufferVld_TS3, TrntrMemRdBufferVld_TS4, TrntrMemRdBufferVld_TS5;
  logic [TRC_RAM_INDEX_WIDTH:0]                                                   TrntrMemRamRdAddrFlop_ANY;
  logic [TRC_RAM_INDEX_WIDTH-1:0]                                                 TrntrMemRamRdAddr_TS1, TrntrMemRamRdAddr_TS1_stg;
  logic                                                                           TrntrMemRamRdAddrWrap_ANY;
  logic                                                                           TrntrMemRdBufferFull_ANY;
  logic                                                                           TrntrMemAxiWrVld_ANY;
  logic [AXI_ADDR_WIDTH-1:0]                                                      TrntrMemAxiWrAddr_ANY;
  logic                                                                           TrntrMemAxiWrAddrWrap_ANY;
  logic [AXI_ADDR_WIDTH-1:0]                                                      trntrMemSMEMStartAddr_ANY, trntrMemSMEMLimitAddr_ANY;
  logic [AXI_DATA_WIDTH-1:0]                                                      TrntrMemAxiWrData_ANY;
  logic                                                                           TrntrMemRamRdRdy_TS1;
  logic [TRC_RAM_INSTANCES-1:0]                                                   TrntrMemRamRdEn_TS1, TrntrMemRamRdEn_TS1_stg;
  logic [TRC_RAM_INSTANCES-1:0]                                                   TrntrMemRamRdEn_TS2;
  logic                                                                           trntrMemModeEnable_ANY;
  logic                                                                           TrntrMemRamRdRamEn_ANY;
  logic                                                                           TrntrMemModeRamBackPressure_ANY;
  logic [15:0]                                                                    TrntrFlushTimeoutCntr_ANY;
  logic                                                                           TrntrFlushTimeoutStart_ANY, TrntrFlushTimeoutDone_ANY, TrntrFlushTimeoutCntrClr_ANY;

  // TS0
  logic                                                                           TrRamNorthTraceWrEn_TS0, TrRamSouthTraceWrEn_TS0;
  logic [1:0]                                                                     TrRamNorthTraceWrWay_TS0, TrRamSouthTraceWrWay_TS0;
  logic [TRC_RAM_INDEX_WIDTH-1:0]                                                 TrRamNorthTraceWrAddr_TS0, TrRamSouthTraceWrAddr_TS0;
  logic [DATA_WIDTH-1:0]                                                          TrRamNorthTraceWrData_TS0, TrRamSouthTraceWrData_TS0;
  logic                                                                           TrRamNorthTraceWrSrc_TS0, TrRamSouthTraceWrSrc_TS0;

  logic                                                                           DataTraceWrEn_TS0;
  logic                                                                           InsnTraceWrEn_TS0;
  logic [NUM_CORES-1:0]                                                           InsnTraceWrEnPerCore_TS0;
  logic [NUM_CORES-1:0]                                                           DataTraceWrEnPerCore_TS0;
  logic [1:0]                                                                     DataTraceWrWay_TS0;
  logic [1:0]                                                                     InsnTraceWrWay_TS0;
  logic [TRC_RAM_INDEX_WIDTH-1:0]                                                 InsnTraceWrAddr_TS0;
  logic [TRC_RAM_INDEX_WIDTH-1:0]                                                 DataTraceWrAddr_TS0;
  logic [DATA_WIDTH-1:0]                                                          InsnTraceWrData_TS0;
  logic [DATA_WIDTH-1:0]                                                          DataTraceWrData_TS0;
  
  logic [TRC_RAM_WAYS-1:0][TRC_RAM_INDEX_WIDTH-1:0]                               TraceWrAddr_TS0_stg, TraceWrAddr_TS0_stg_d1, TraceWrAddr_TS0;
  logic [TRC_RAM_INSTANCES-1:0][TRC_RAM_DATA_WIDTH-1:0]                           TraceWrData_TS0_stg, TraceWrData_TS0_stg_d1, TraceWrData_TS0;
  logic [TRC_RAM_WAYS-1:0]                                                        TraceWrEn_TS0_stg, TraceWrEn_TS0_stg_d1, TraceWrEn_TS0;

  // TS1
  logic  [TRC_RAM_INSTANCES-1:0]                                                  InsnTraceRdEn_TS1;
  logic  [TRC_RAM_INSTANCES-1:0]                                                  DataTraceRdEn_TS1;
  logic                                                                           InsnTraceRdEn_TS2;
  logic                                                                           DataTraceRdEn_TS2;
  logic                                                                           InsnTraceRdEn_TS3;
  logic                                                                           DataTraceRdEn_TS3;
  logic  [TRC_RAM_INSTANCES-1:0]                                                  TraceRdEn_TS1;
  logic  [TRC_RAM_INDEX_WIDTH-1:0]                                                TraceRdAddr_TS1;
  logic  [TRC_RAM_INDEX_WIDTH-1:0]                                                TraceMemRdAddr_TS1, TraceMemRdAddr_TS1_stg;
  logic  [TRC_RAM_INSTANCES-1:0]                                                  TraceMemPerWayRdEn_TS1, TraceMemPerWayRdEn_TS1_stg;
  // TS2
  logic  [TRC_RAM_INSTANCES-1:0]                                                  TraceRdEn_TS2;
  logic  [TRC_RAM_INSTANCES-1:0] [TRC_RAM_DATA_WIDTH-1:0]                         TraceRamData_TS2;
  logic  [TRC_RAM_DATA_WIDTH-1:0]                                                 TraceRamData64b_TS2;
  // Misc
  logic [TRC_RAM_WAYS-1:0][TRC_RAM_INDEX_WIDTH-1:0]                               TraceAddr_ANY;
  logic                                                                           TraceMemRdEn_ANY, TraceMemRdEn_ANY_stg;
  logic                                                                           TrMemRamRd_NtraceOrDst_ANY;
  logic                                                                           TraceRamWrEn_TS0_stg, TraceRamWrEn_TS0_stg_d1;
  logic                                                                           trdstRamWrEn_TS0, trdstRamWrEn_TS0_stg, trdstRamWrEn_TS0_stg_d1;
  logic                                                                           trntrRamWrEn_TS0, trntrRamWrEn_TS0_stg, trntrRamWrEn_TS0_stg_d1;

  // N-trace
  logic [31:2]                                                                    trntrRamStartLow_ANY;
  logic [31:0]                                                                    trntrRamStartHigh_ANY;
  logic [31:2]                                                                    trntrRamLimitLow_ANY;
  logic [31:0]                                                                    trntrRamLimitHigh_ANY;
  logic [31:2]                                                                    trntrRamWpLow_ANY; // Software view of the Write pointers
  logic [31:0]                                                                    trntrRamWpHigh_ANY;
  logic [31:2]                                                                    trntrRamRpLow_ANY;
  logic [31:2]                                                                    trntrMemMode_nextlocalWrapCond_WpLow_ANY, trntrRamMode_nextlocalWrapCond_WpLow_ANY;
  logic [31:2]                                                                    trntrramwplowSRAMWrdata, trntrramwplowSMEMWrdata;
  logic [NUM_CORES-1:0][31:2]                                                     trntrcorefullRamWpLow_ANY,trntrcoreRamWpLow_ANY,trntrcorenextRamWpLow_ANY; // Per core Write pointers
  logic [NUM_CORES-1:0][TRC_RAM_INDEX_WIDTH-1:0]                                  trntrcoreRamWpAddr_ANY, trntrcoreRamWpAddr_ANY_d1;
  logic [NUM_CORES-1:0][TRC_RAM_INDEX_WIDTH:0]                                    trntrcoreRamAddrtoNextLocalSetDiff_ANY, trntrcoreRamAddrtoNextLocalSetDiff_ANY_stg;
  logic [TRC_RAM_INDEX_WIDTH:0]                                                   trntrcoretoFlushThreshold_ANY;
  logic [NUM_CORES-1:0]                                                           trntrcoreRamWpWrap_ANY, trntrcoreRamWpWrap_ANY_d1;
  logic [NUM_CORES-1:0][4:0]                                                      trntrcorewritecnt_ANY, trntrcorenextwritecnt_ANY;
  logic [31:2]                                                                    trntrlocalRamWpLow_ANY;
  logic [31:2]                                                                    trntrRamSMEMStartLow_ANY, trntrRamSMEMLimitLow_ANY, trntrRamSMEMSizeLow_ANY;
  logic [TRC_RAM_INDEX_WIDTH:0]                                                   trntrRamSMEMStartAddr_ANY, trntrRamSMEMLimitAddr_ANY, trntrRamSMEMTotalSets_ANY;
  logic [2:0][31:2]                                                               trntrnextlocalRamWpLow_ANY; // Next core Write pointers
  logic                                                                           trntrnextlocaltoupdateRamWpWrap_ANY;
  logic                                                                           trntrnextlocaltoupdateRamWpWrapOneNewFrame_ANY, trntrnextlocaltoupdateRamWpWrapTwoNewFrame_ANY;
  logic [31:2]                                                                    trntrnextlocaltoupdateRamWpLow_ANY, trntrnextlocaltoupdateRamWpLow_ANY_stg;
  logic                                                                           trntrnextlocaltoupdateRamWpLowWrap_ANY;
  logic                                                                           trntrnorthcoresNewFrameStart_ANY, trntrnorthcoresNewFrameStart_ANY_d1, trntrsouthcoresNewFrameStart_ANY, trntrsouthcoresNewFrameStart_ANY_d1;
  logic                                                                           TrntrMemModeRamFlush_ANY;
  logic [NUM_CORES-1:0]                                                           trntrcoretoFlushEnable_ANY, trntrcoretoFlushClear_ANY;
  logic [NUM_CORES-1:0]                                                           trntrMemRamRdEnFromCore_ANY, trntrMemRamRdEnFromCore_ANY_stg;
  // DST
  logic [31:2]                                                                    trdstRamStartLow_ANY;
  logic [31:0]                                                                    trdstRamStartHigh_ANY;
  logic [31:2]                                                                    trdstRamLimitLow_ANY;
  logic [31:0]                                                                    trdstRamLimitHigh_ANY;
  logic [31:2]                                                                    trdstRamWpLow_ANY; // Software view of the Write pointers
  logic [31:0]                                                                    trdstRamWpHigh_ANY;
  logic [31:2]                                                                    trdstRamRpLow_ANY;
  logic [31:2]                                                                    trdstMemMode_nextlocalWrapCond_WpLow_ANY, trdstRamMode_nextlocalWrapCond_WpLow_ANY;
  logic [31:2]                                                                    trdstramwplowSRAMWrdata, trdstramwplowSMEMWrdata;
  logic [NUM_CORES-1:0][31:2]                                                     trdstcorefullRamWpLow_ANY,trdstcoreRamWpLow_ANY,trdstcorenextRamWpLow_ANY; // Per core Write pointers
  logic [NUM_CORES-1:0][TRC_RAM_INDEX_WIDTH-1:0]                                  trdstcoreRamWpAddr_ANY,trdstcoreRamWpAddr_ANY_d1;
  logic [NUM_CORES-1:0][TRC_RAM_INDEX_WIDTH:0]                                    trdstcoreRamAddrtoNextLocalSetDiff_ANY, trdstcoreRamAddrtoNextLocalSetDiff_ANY_stg;
  logic [TRC_RAM_INDEX_WIDTH:0]                                                   trdstcoretoFlushThreshold_ANY;
  logic [NUM_CORES-1:0]                                                           trdstcoreRamWpWrap_ANY, trdstcoreRamWpWrap_ANY_d1;
  logic [NUM_CORES-1:0][4:0]                                                      trdstcorewritecnt_ANY, trdstcorenextwritecnt_ANY;
  logic [31:2]                                                                    trdstlocalRamWpLow_ANY;
  logic [31:2]                                                                    trdstRamSMEMStartLow_ANY, trdstRamSMEMLimitLow_ANY, trdstRamSMEMSizeLow_ANY;
  logic [TRC_RAM_INDEX_WIDTH:0]                                                   trdstRamSMEMStartAddr_ANY, trdstRamSMEMLimitAddr_ANY, trdstRamSMEMTotalSets_ANY;
  logic [2:0][31:2]                                                               trdstnextlocalRamWpLow_ANY; // Next core Write pointers
  logic                                                                           trdstnextlocaltoupdateRamWpWrap_ANY;
  logic [31:2]                                                                    trdstnextlocaltoupdateRamWpLow_ANY, trdstnextlocaltoupdateRamWpLow_ANY_stg;
  logic                                                                           trdstnextlocaltoupdateRamWpWrapOneNewFrame_ANY, trdstnextlocaltoupdateRamWpWrapTwoNewFrame_ANY;
  logic                                                                           trdstnextlocaltoupdateRamWpLowWrap_ANY;
  logic                                                                           trdstnorthcoresNewFrameStart_ANY, trdstnorthcoresNewFrameStart_ANY_d1, trdstsouthcoresNewFrameStart_ANY, trdstsouthcoresNewFrameStart_ANY_d1;
  logic                                                                           TrdstMemModeRamFlush_ANY;
  logic [NUM_CORES-1:0]                                                           trdstcoretoFlushEnable_ANY, trdstcoretoFlushClear_ANY;
  logic [NUM_CORES-1:0]                                                           trdstMemRamRdEnFromCore_ANY, trdstMemRamRdEnFromCore_ANY_stg;
  // MMR signals
  logic                                                                           trntrRamActive_ANY, trntrRamEnable_ANY;
  logic                                                                           trntrRamActiveEnable_ANY, trntrRamActiveEnable_ANY_d1;
  logic                                                                           trntrRamMode_ANY_stg, trntrRamMode_ANY;
  logic                                                                           trntrStoponWrap_ANY;
  logic                                                                           trntrRamEnableStart_ANY, trntrRamEnableStart_ANY_d1;
  logic                                                                           trntrRamEnableStop_ANY;

  logic                                                                           trdstRamActive_ANY, trdstRamEnable_ANY;
  logic                                                                           trdstRamActiveEnable_ANY, trdstRamActiveEnable_ANY_d1;
  logic                                                                           trdstRamMode_ANY_stg, trdstRamMode_ANY;
  logic                                                                           trdstStoponWrap_ANY;
  logic                                                                           trdstRamEnableStart_ANY, trdstRamEnableStart_ANY_d1;
  logic                                                                           trdstRamEnableStop_ANY;

  logic [31:2]                                                                    Trcustomramsmemlimitlow_ANY;
  // Flush and Bp control signals
  logic                                                                           TS_TR_Dst_Bp_int, TS_TR_Ntrace_Bp_int;
  logic                                                                           TS_TR_Dst_Flush_int, TS_TR_Ntrace_Flush_int;

  // SRAM Overflow Mask blocked Frames write
  logic [NUM_CORES-1:0]                                                           Eff_InsnTraceWrEnPerCore_TS0, Eff_DataTraceWrEnPerCore_TS0;
  logic [NUM_CORES_IN_PATH-1:0]                                                   Eff_TR_TS_North_Vld, Eff_TR_TS_South_Vld;
  logic [NUM_CORES-1:0]                                                           trntrcoreframefillpendingwhileoverflow_ANY, trdstcoreframefillpendingwhileoverflow_ANY;
  logic [NUM_CORES-1:0][NUM_CORES-1:0]                                            trntrcoreptrmatchesanypendingframeafteroverflow_ANY, trdstcoreptrmatchesanypendingframeafteroverflow_ANY;

  // --------------------------------------------------------------------------
  //  Misc signals connection (Ntrace/DST)
  // --------------------------------------------------------------------------
  // Complete frame length value in bytes
  dfd_rv_dff #(.WIDTH(10)) trntrFrameLength_ANY_ff (.o_q(trntrFrameLength_ANY), .i_d({TrCsrTrramimpl.Trramvendorframelength[3:0],6'b0}), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(10)) trdstFrameLength_ANY_ff (.o_q(trdstFrameLength_ANY), .i_d({TrCsrTrdstramimpl.Trdstramvendorframelength[3:0],6'b0}), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  
  dfd_rv_dff #(.WIDTH(30)) Trcustomramsmemlimitlow_ANY_ff (.o_q(Trcustomramsmemlimitlow_ANY), .i_d(TrCsrTrcustomramsmemlimitlow.Trcustomramsmemlimitlow), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  assign trdstRamSMEMStartLow_ANY = Trcustomramsmemlimitlow_ANY;
  assign trdstRamSMEMLimitLow_ANY = 30'h2000;
  assign trdstRamSMEMStartAddr_ANY = trdstRamSMEMStartLow_ANY[6+:(TRC_RAM_INDEX_WIDTH+1)];
  assign trdstRamSMEMLimitAddr_ANY = trdstRamSMEMLimitLow_ANY[6+:(TRC_RAM_INDEX_WIDTH+1)]; 

  dfd_rv_dff #(.WIDTH(30)) trdstRamSMEMSizeLow_ANY_ff (.o_q(trdstRamSMEMSizeLow_ANY), .i_d($bits(trdstRamSMEMSizeLow_ANY)'(trdstRamSMEMLimitLow_ANY - TrCsrTrcustomramsmemlimitlow.Trcustomramsmemlimitlow)), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH+1)) trdstRamSMEMTotalSets_ANY_ff (.o_q(trdstRamSMEMTotalSets_ANY), .i_d($bits(trdstRamSMEMTotalSets_ANY)'(trdstRamSMEMLimitAddr_ANY - trdstRamSMEMStartAddr_ANY)), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  assign trntrRamSMEMStartLow_ANY = 30'h0;
  assign trntrRamSMEMLimitLow_ANY = Trcustomramsmemlimitlow_ANY;
  assign trntrRamSMEMStartAddr_ANY = trntrRamSMEMStartLow_ANY[6+:(TRC_RAM_INDEX_WIDTH+1)]; 
  assign trntrRamSMEMLimitAddr_ANY = trntrRamSMEMLimitLow_ANY[6+:(TRC_RAM_INDEX_WIDTH+1)];

  dfd_rv_dff #(.WIDTH(30)) trntrRamSMEMSizeLow_ANY_ff (.o_q(trntrRamSMEMSizeLow_ANY), .i_d($bits(trntrRamSMEMSizeLow_ANY)'(TrCsrTrcustomramsmemlimitlow.Trcustomramsmemlimitlow)), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH+1)) trntrRamSMEMTotalSets_ANY_ff (.o_q(trntrRamSMEMTotalSets_ANY), .i_d($bits(trntrRamSMEMTotalSets_ANY)'(trntrRamSMEMLimitAddr_ANY - trntrRamSMEMStartAddr_ANY)), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  assign Eff_InsnTraceWrEnPerCore_TS0 = trntrRamMode_ANY?InsnTraceWrEnPerCore_TS0:(InsnTraceWrEnPerCore_TS0 & ~trntrcoreframefillpendingwhileoverflow_ANY);
  assign Eff_DataTraceWrEnPerCore_TS0 = trdstRamMode_ANY?DataTraceWrEnPerCore_TS0:(DataTraceWrEnPerCore_TS0 & ~trdstcoreframefillpendingwhileoverflow_ANY);

  for (genvar i=0; i<NUM_CORES_IN_PATH; i++) begin
    assign Eff_TR_TS_North_Vld[i] = ((TR_TS_North_Src & Eff_InsnTraceWrEnPerCore_TS0[i << 1]) | (~TR_TS_North_Src & Eff_DataTraceWrEnPerCore_TS0[i << 1]));
    assign Eff_TR_TS_South_Vld[i] = ((TR_TS_South_Src & Eff_InsnTraceWrEnPerCore_TS0[(i << 1) + 1]) | (~TR_TS_South_Src & Eff_DataTraceWrEnPerCore_TS0[(i << 1) + 1]));
  end

  // --------------------------------------------------------------------------
  // Timing Staging flops
  // -------------------------------------------------------------------------- 
  dfd_rv_dff #(.WIDTH(1)) TR_TS_North_Src_stg_ff (.o_q(TR_TS_North_Src_stg), .i_d(TR_TS_North_Src), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) TR_TS_South_Src_stg_ff (.o_q(TR_TS_South_Src_stg), .i_d(TR_TS_South_Src), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  dfd_rv_dff #(.WIDTH(DATA_WIDTH)) TR_TS_North_Data_stg_ff (.o_q(TR_TS_North_Data_stg), .i_d(TR_TS_North_Data), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(DATA_WIDTH)) TR_TS_South_Data_stg_ff (.o_q(TR_TS_South_Data_stg), .i_d(TR_TS_South_Data), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  
  dfd_rv_dff #(.WIDTH(30)) trnorthcoreRamWpLow_ANY_stg_ff (.o_q(trnorthcoreRamWpLow_ANY_stg), .i_d(trnorthcoreRamWpLow_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(30)) trsouthcoreRamWpLow_ANY_stg_ff (.o_q(trsouthcoreRamWpLow_ANY_stg), .i_d(trsouthcoreRamWpLow_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  dfd_rv_dff #(.WIDTH(NUM_CORES_IN_PATH)) Eff_TR_TS_North_Vld_stg_ff (.o_q(Eff_TR_TS_North_Vld_stg), .i_d(Eff_TR_TS_North_Vld), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(NUM_CORES_IN_PATH)) Eff_TR_TS_South_Vld_stg_ff (.o_q(Eff_TR_TS_South_Vld_stg), .i_d(Eff_TR_TS_South_Vld), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  
  dfd_rv_dff #(.WIDTH(1)) trntrnextlocaltoupdateRamWpWrap_ANY_stg_ff (.o_q(trntrnextlocaltoupdateRamWpWrap_ANY_stg), .i_d(trntrnextlocaltoupdateRamWpWrap_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trntrnextlocaltoupdateRamWpWrap_ANY_stg_d1_ff (.o_q(trntrnextlocaltoupdateRamWpWrap_ANY_stg_d1), .i_d(trntrnextlocaltoupdateRamWpWrap_ANY_stg), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trntrnextlocaltoupdateRamWpWrap_ANY_stg_d2_ff (.o_q(trntrnextlocaltoupdateRamWpWrap_ANY_stg_d2), .i_d(trntrnextlocaltoupdateRamWpWrap_ANY_stg_d1), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  
  dfd_rv_dff #(.WIDTH(1)) trdstnextlocaltoupdateRamWpWrap_ANY_stg_ff (.o_q(trdstnextlocaltoupdateRamWpWrap_ANY_stg), .i_d(trdstnextlocaltoupdateRamWpWrap_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trdstnextlocaltoupdateRamWpWrap_ANY_stg_d1_ff (.o_q(trdstnextlocaltoupdateRamWpWrap_ANY_stg_d1), .i_d(trdstnextlocaltoupdateRamWpWrap_ANY_stg), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trdstnextlocaltoupdateRamWpWrap_ANY_stg_d2_ff (.o_q(trdstnextlocaltoupdateRamWpWrap_ANY_stg_d2), .i_d(trdstnextlocaltoupdateRamWpWrap_ANY_stg_d1), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  // --------------------------------------------------------------------------
  // Incoming Data Capture
  // --------------------------------------------------------------------------
  always_comb begin
    trnorthcoreRamWpLow_ANY = '0;
    trsouthcoreRamWpLow_ANY = '0;

    for (int i=0; i<NUM_CORES_IN_PATH; i++) begin
      trnorthcoreRamWpLow_ANY |= (TR_TS_North_Src?({30{Eff_TR_TS_North_Vld[i]}} & trntrcoreRamWpLow_ANY[i << 1]):({30{Eff_TR_TS_North_Vld[i]}} & trdstcoreRamWpLow_ANY[i << 1]));
      trsouthcoreRamWpLow_ANY |= (TR_TS_South_Src?({30{Eff_TR_TS_South_Vld[i]}} & trntrcoreRamWpLow_ANY[(i << 1) + 1]):({30{Eff_TR_TS_South_Vld[i]}} & trdstcoreRamWpLow_ANY[(i << 1) + 1]));  
    end
  end

  for (genvar i=0; i<NUM_CORES_IN_PATH; i++) begin
    assign DataTraceWrEnPerCore_TS0[i << 1] = (TR_TS_North_Vld[i] & ~TR_TS_North_Src);
    assign DataTraceWrEnPerCore_TS0[(i << 1) + 1] = (TR_TS_South_Vld[i] & ~TR_TS_South_Src);

    assign InsnTraceWrEnPerCore_TS0[i << 1] = (TR_TS_North_Vld[i] & TR_TS_North_Src);
    assign InsnTraceWrEnPerCore_TS0[(i << 1) + 1] = (TR_TS_South_Vld[i] & TR_TS_South_Src);
  end

  assign TrRamNorthTraceWrEn_TS0 = ~TrRamPendPktNorthWrEn_TS0 & |Eff_TR_TS_North_Vld_stg;
  assign TrRamNorthTraceWrWay_TS0 = trnorthcoreRamWpLow_ANY_stg[5:4]; 
  assign TrRamNorthTraceWrAddr_TS0 = trnorthcoreRamWpLow_ANY_stg[6+:TRC_RAM_INDEX_WIDTH];
  assign TrRamNorthTraceWrData_TS0 = TR_TS_North_Data_stg;
  assign TrRamNorthTraceWrSrc_TS0 = TR_TS_North_Src_stg;

  assign TrRamSouthTraceWrEn_TS0 = ~TrRamPendPktSouthWrEn_TS0 & |Eff_TR_TS_South_Vld_stg;
  assign TrRamSouthTraceWrWay_TS0 = trsouthcoreRamWpLow_ANY_stg[5:4];
  assign TrRamSouthTraceWrAddr_TS0 = trsouthcoreRamWpLow_ANY_stg[6+:TRC_RAM_INDEX_WIDTH];
  assign TrRamSouthTraceWrData_TS0 = TR_TS_South_Data_stg;
  assign TrRamSouthTraceWrSrc_TS0 = TR_TS_South_Src_stg;

  assign TrRamPendPktNorthWrEn_TS0 = ((|Eff_TR_TS_North_Vld_stg & |Eff_TR_TS_South_Vld_stg) & (TrRamNorthTraceWrWay_TS0 == TrRamSouthTraceWrWay_TS0) & |TrRamPerWayPendToWriteCnt_TS1[TrRamNorthTraceWrWay_TS0]) | (|Eff_TR_TS_North_Vld_stg & |TrRamPerWayPendToWriteCnt_TS1[TrRamNorthTraceWrWay_TS0]);
  assign TrRamPendPktSouthWrEn_TS0 = ((|Eff_TR_TS_North_Vld_stg & |Eff_TR_TS_South_Vld_stg) & (TrRamNorthTraceWrWay_TS0 == TrRamSouthTraceWrWay_TS0)) | (|Eff_TR_TS_South_Vld_stg & |TrRamPerWayPendToWriteCnt_TS1[TrRamSouthTraceWrWay_TS0]);

  assign TrRamPendPktNorthWr_TS0 = {trnorthcoreRamWpLow_ANY_stg[5:4], trnorthcoreRamWpLow_ANY_stg[6+:TRC_RAM_INDEX_WIDTH], TR_TS_North_Data_stg, TR_TS_North_Src_stg};
  assign TrRamPendPktSouthWr_TS0 = {trsouthcoreRamWpLow_ANY_stg[5:4], trsouthcoreRamWpLow_ANY_stg[6+:TRC_RAM_INDEX_WIDTH], TR_TS_South_Data_stg, TR_TS_South_Src_stg};

  for (genvar i=0; i<TRC_RAM_WAYS; i++) begin
    dfd_rv_dff #(.WIDTH(3)) TrRamPerWayPendToWriteCnt_ff (.o_q(TrRamPerWayPendToWriteCnt_TS1[i]), .i_d(TrRamPerWayNextPendToWriteCnt_TS0[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
    /* verilator lint_off WIDTHEXPAND */
    assign TrRamPerWayNextPendToWriteCnt_TS0[i] = TrRamPerWayPendToWriteCnt_TS1[i] + (TrRamPendPktNorthWrEn_TS0 & (TrRamPendPktNorthWr_TS0.TrRamPendWayIdx_ANY == i[1:0])) + (TrRamPendPktSouthWrEn_TS0 & (TrRamPendPktSouthWr_TS0.TrRamPendWayIdx_ANY == i[1:0])) - |TrRamPerWayPendToWriteCnt_TS1[i];
    /* verilator lint_on WIDTHEXPAND */
    assign TrRamFreeWayMask_ANY[i] = ~((TrRamNorthTraceWrEn_TS0 & (TrRamNorthTraceWrWay_TS0 == i[1:0])) | (TrRamSouthTraceWrEn_TS0 & (TrRamSouthTraceWrWay_TS0 == i[1:0])));
  end

  // --------------------------------------------------------------------------
  // Write Pointer manipulation for Debug Signal Trace (DST)
  // --------------------------------------------------------------------------
  // 1.Out of reset the next_ptr would be set to start_ptr
  // 2.As soon each of the core starts writing the data the next_ptr would be copied into the core_ptr, next_ptr incremented with frame length
  // 3.When new entry keeps on coming for the core, the writes happen based on the core_ptr and gets incremented
  // 4.Once the frame of the core is incremented, then the global write pointer is updated. (Is it possible that, the more recent core is filled than the oldest one, in that use periodic slush request)
  // 5.New entry to RAM is started from the next_ptr and the same steps are repeated.

  // dfd_rv_dff #(.WIDTH(30)) trdstlocalRamWpLow_ANY_ff (
  //   .o_q          (trdstlocalRamWpLow_ANY),
  //   .i_d          (~trdstRamMode_ANY?((trdstRamEnableStart_ANY_d1 | (~trdstStoponWrap_ANY & (trdstnextlocaltoupdateRamWpLow_ANY == trdstRamLimitLow_ANY)))?trdstRamStartLow_ANY:trdstnextlocaltoupdateRamWpLow_ANY):(trdstnextlocaltoupdateRamWpLow_ANY)), // Increment based on the frame_length
  //   .i_en         ((|trdstcoreNewFrameStart_ANY) | trdstRamEnableStart_ANY_d1),
  //   .i_clk        (clk),
  //   .i_reset_n    (reset_n)
  // );

  dfd_rv_dff #(.WIDTH(1)) trdstnextlocaltoupdateRamWpLowWrap_ANY_ff (.o_q(trdstnextlocaltoupdateRamWpLowWrap_ANY), .i_d((trdstnextlocaltoupdateRamWpLow_ANY >= trdstRamLimitLow_ANY)), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  assign trdstlocalRamWpLow_ANY = ~trdstRamMode_ANY?((trdstRamEnableStart_ANY_d1 | (~trdstStoponWrap_ANY & trdstnextlocaltoupdateRamWpLowWrap_ANY))?trdstRamStartLow_ANY:trdstnextlocaltoupdateRamWpLow_ANY_stg)
                                                   :(trdstRamEnableStart_ANY_d1?trdstRamSMEMStartLow_ANY:trdstnextlocaltoupdateRamWpLow_ANY_stg); // Increment based on the frame_length
  
  // assign trdstnextlocalRamWpLow_ANY[0] = trdstlocalRamWpLow_ANY; //(trdstRamMode_ANY & trdstRamEnableStart_ANY_d1)?trdstRamSMEMStartLow_ANY:trdstlocalRamWpLow_ANY;

  dfd_rv_ffs_fast #(
    .DIR_L2H(1),
    .WIDTH(NUM_CORES),
    .DATA_WIDTH(NUM_CORES)
  ) ff_dst_framestart (
      .req_in(trdstcoreNewFrameStart_ANY),
      .data_in('0),
      .req_out(trdstfirstcoreNewFrameStart_ANY),

      .data_out(),
      .enc_req_out(),
      .req_out_therm()
  );

  always_comb begin
    trdstnorthcoresNewFrameStart_ANY = '0;
    trdstsouthcoresNewFrameStart_ANY = '0; 
    for (int i=0; i<NUM_CORES_IN_PATH; i++) begin
      trdstnorthcoresNewFrameStart_ANY |= (trdstcoreNewFrameStart_ANY[i << 1]);
      trdstsouthcoresNewFrameStart_ANY |= (trdstcoreNewFrameStart_ANY[(i << 1) + 1]);
    end
  end

  dfd_rv_dff #(.WIDTH(1)) trdstnorthcoresNewFrameStart_ANY_d1_ff (.o_q(trdstnorthcoresNewFrameStart_ANY_d1), .i_d(trdstnorthcoresNewFrameStart_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trdstsouthcoresNewFrameStart_ANY_d1_ff (.o_q(trdstsouthcoresNewFrameStart_ANY_d1), .i_d(trdstsouthcoresNewFrameStart_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  // assign trdstnextlocaltoupdateRamWpLow_ANY = trdstnextlocalRamWpLow_ANY[3];

  dfd_rv_dff #(.WIDTH(30)) trdstnextlocaltoupdateRamWpLow_ANY_ff (.o_q(trdstnextlocaltoupdateRamWpLow_ANY_stg), .i_d(trdstnextlocaltoupdateRamWpLow_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  dfd_rv_dff #(.WIDTH(1)) trdstnextlocaltoupdateRamWpWrapOneNewFrame_ANY_ff (.o_q(trdstnextlocaltoupdateRamWpWrapOneNewFrame_ANY), .i_d(((trdstlocalRamWpLow_ANY + $bits(trdstlocalRamWpLow_ANY)'(trdstFrameLength_ANY[9:2])) >= trdstRamLimitLow_ANY)), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trdstnextlocaltoupdateRamWpWrapTwoNewFrame_ANY_ff (.o_q(trdstnextlocaltoupdateRamWpWrapTwoNewFrame_ANY), .i_d((trdstlocalRamWpLow_ANY + $bits(trdstlocalRamWpLow_ANY)'(trdstFrameLength_ANY[9:2]*2)) >= trdstRamLimitLow_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  /* verilator lint_off WIDTHEXPAND */
  assign trdstnextlocaltoupdateRamWpWrap_ANY = (trdstnextlocaltoupdateRamWpWrapOneNewFrame_ANY & ((|trdstnorthcoresNewFrameStart_ANY_d1) | (|trdstsouthcoresNewFrameStart_ANY_d1))) | (trdstnextlocaltoupdateRamWpWrapTwoNewFrame_ANY & ((|trdstnorthcoresNewFrameStart_ANY_d1) & (|trdstsouthcoresNewFrameStart_ANY_d1)));
  /* verilator lint_on WIDTHEXPAND */
  
  /* verilator lint_off WIDTHEXPAND */
  assign trdstnextlocaltoupdateRamWpLow_ANY = (trdstnorthcoresNewFrameStart_ANY & trdstsouthcoresNewFrameStart_ANY)?trdstnextlocalRamWpLow_ANY[2]:((trdstnorthcoresNewFrameStart_ANY | trdstsouthcoresNewFrameStart_ANY)?trdstnextlocalRamWpLow_ANY[1]:trdstnextlocalRamWpLow_ANY[0]);
  /* verilator lint_on WIDTHEXPAND */

  always_comb begin
    trdstnextlocalRamWpLow_ANY[0] = trdstlocalRamWpLow_ANY;
    trdstnextlocalRamWpLow_ANY[1] = '0;
    trdstnextlocalRamWpLow_ANY[2] = '0;
    /* verilator lint_off WIDTHEXPAND */
    for (int i=0; i<2; i++) begin
      trdstnextlocalRamWpLow_ANY[i+1] = trdstRamMode_ANY?((trdstnextlocalRamWpLow_ANY[i] >= trdstMemMode_nextlocalWrapCond_WpLow_ANY)?trdstRamSMEMStartLow_ANY:$bits(trdstnextlocalRamWpLow_ANY[i])'(trdstnextlocalRamWpLow_ANY[i] + trdstFrameLength_ANY[9:2]))
                                                             :((trdstnextlocalRamWpLow_ANY[i] > trdstRamMode_nextlocalWrapCond_WpLow_ANY)?trdstRamStartLow_ANY:$bits(trdstnextlocalRamWpLow_ANY[i])'(trdstnextlocalRamWpLow_ANY[i] + trdstFrameLength_ANY[9:2]));
    end
    /* verilator lint_on WIDTHEXPAND */
  end

  // Timing Flops used in comparison maths 
  //Flop-1: (trdstRamSMEMStartLow_ANY + trdstRamSMEMSizeLow_ANY*2) - trdstFrameLength_ANY[9:2] 
  //Flop-2: trdstRamLimitLow_ANY - trdstFrameLength_ANY[9:2] 
  dfd_rv_dff #(.WIDTH(30)) trdstMemMode_nextlocalWrapCond_WpLow_ANY_ff (.o_q(trdstMemMode_nextlocalWrapCond_WpLow_ANY), .i_d($bits(trdstMemMode_nextlocalWrapCond_WpLow_ANY)'($bits(trdstMemMode_nextlocalWrapCond_WpLow_ANY)'(trdstRamSMEMStartLow_ANY) + $bits(trdstMemMode_nextlocalWrapCond_WpLow_ANY)'(trdstRamSMEMSizeLow_ANY*2) - $bits(trdstMemMode_nextlocalWrapCond_WpLow_ANY)'(trdstFrameLength_ANY[9:2]))), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(30)) trdstRamMode_nextlocalWrapCond_WpLow_ANY_ff (.o_q(trdstRamMode_nextlocalWrapCond_WpLow_ANY), .i_d($bits(trdstRamMode_nextlocalWrapCond_WpLow_ANY)'($bits(trdstRamMode_nextlocalWrapCond_WpLow_ANY)'(trdstRamLimitLow_ANY) - $bits(trdstRamMode_nextlocalWrapCond_WpLow_ANY)'(trdstFrameLength_ANY[9:2]))), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  for (genvar i=0; i<NUM_CORES; i++) begin
    /* verilator lint_off WIDTHEXPAND */
    assign trdstcoreNewFrameStart_ANY[i] = ~|(trdstFrameLength_ANY[9]?trdstcorenextwritecnt_ANY[i][4:0]:trdstFrameLength_ANY[8]?trdstcorenextwritecnt_ANY[i][3:0]:trdstFrameLength_ANY[7]?trdstcorenextwritecnt_ANY[i][2:0]:trdstcorenextwritecnt_ANY[i][1:0]) & DataTraceWrEnPerCore_TS0[i]; 
    /* verilator lint_on WIDTHEXPAND */
    assign trdstcorefullRamWpLow_ANY[i] = trdstcoreNewFrameStart_ANY[i]?(trdstfirstcoreNewFrameStart_ANY[i]?trdstnextlocalRamWpLow_ANY[0]:trdstnextlocalRamWpLow_ANY[1]):{trdstcorenextRamWpLow_ANY[i][31:4] + 28'h1 , 2'h0}; 

    assign trdstcoreRamWpLow_ANY[i] = trdstRamMode_ANY?(((trdstcorefullRamWpLow_ANY[i] - trdstRamSMEMStartLow_ANY) & (trdstRamSMEMSizeLow_ANY - 1'b1)) + trdstRamSMEMStartLow_ANY):trdstcorefullRamWpLow_ANY[i];
    assign trdstcoreRamWpAddr_ANY[i] = trdstcoreRamWpLow_ANY[i][6+:TRC_RAM_INDEX_WIDTH];
    assign trdstcoreRamWpWrap_ANY[i] = |((trdstcorefullRamWpLow_ANY[i] - trdstRamSMEMStartLow_ANY) & trdstRamSMEMSizeLow_ANY); // |((trdstcoreRamWpAddr_ANY[i] - trdstMemSMEMStartAddr_ANY) & trdstRamSMEMTotalSets_ANY)

    // Timing flops
    dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH)) trdstcoreRamWpAddr_ANY_d1_ff (.o_q(trdstcoreRamWpAddr_ANY_d1[i]), .i_d(trdstcoreRamWpAddr_ANY[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
    dfd_rv_dff #(.WIDTH(1)) trdstcoreRamWpWrap_ANY_d1_ff (.o_q(trdstcoreRamWpWrap_ANY_d1[i]), .i_d(trdstcoreRamWpWrap_ANY[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

    dfd_rv_dff #(.WIDTH(30), .RESET_VALUE(0)) trdstcorenextRamWpLow_ANY_ff (
        .o_q          (trdstcorenextRamWpLow_ANY[i]),
        .i_d          (trdstRamEnableStart_ANY_d1?(trdstRamMode_ANY?trdstRamSMEMStartLow_ANY:trdstRamStartLow_ANY):trdstcorefullRamWpLow_ANY[i]),
        .i_en         (trdstRamEnableStart_ANY_d1 | Eff_DataTraceWrEnPerCore_TS0[i]),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

    dfd_rv_dff #(.WIDTH(5), .RESET_VALUE(0)) trdstcorenextwritecnt_ANY_ff (
        .o_q          (trdstcorenextwritecnt_ANY[i]),
        .i_d          (trdstcorewritecnt_ANY[i]), 
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

      dfd_rv_dff_clr #(.WIDTH(1), .RESET_VALUE(0)) trdstcoreframefillpendingwhileoverflow_ANY_ff (
        .o_q          (trdstcoreframefillpendingwhileoverflow_ANY[i]),
        .i_d          (1'b1),
        .i_clr        (trdstcoreFrameFillComplete_ANY[i]),
        .i_en         (|trdstcoreptrmatchesanypendingframeafteroverflow_ANY[i] & ~trdstStoponWrap_ANY & TrCsrTrdstramwplow.Trdstramwrap), 
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

    assign trdstcorewritecnt_ANY[i] = trdstRamEnableStart_ANY_d1?(5'b0):(DataTraceWrEnPerCore_TS0[i]?(trdstcorenextwritecnt_ANY[i] + 1'b1):trdstcorenextwritecnt_ANY[i]);  

    assign trdstcoreRamAddrtoNextLocalSetDiff_ANY[i] = (TrdstMemRamRdAddrWrap_ANY^trdstcoreRamWpWrap_ANY_d1[i])
                                                      ?$bits(trdstcoreRamAddrtoNextLocalSetDiff_ANY[i])'(trdstRamSMEMTotalSets_ANY - (TrdstMemRamRdAddr_TS1 - trdstcoreRamWpAddr_ANY_d1[i]))
                                                      :$bits(trdstcoreRamAddrtoNextLocalSetDiff_ANY[i])'(trdstcoreRamWpAddr_ANY_d1[i] - TrdstMemRamRdAddr_TS1);

    dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH+1), .RESET_VALUE(0)) trdstcoreRamAddrtoNextLocalSetDiff_ANY_stg_ff (
        .o_q          (trdstcoreRamAddrtoNextLocalSetDiff_ANY_stg[i]),
        .i_d          (trdstcoreRamAddrtoNextLocalSetDiff_ANY[i]), 
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

    assign trdstcoretoFlushEnable_ANY[i] = (~trdstcoreFrameFillComplete_ANY[i] & (trdstcoreRamAddrtoNextLocalSetDiff_ANY_stg[i] <= (TRC_RAM_INDEX_WIDTH+1)'(trdstcoretoFlushThreshold_ANY))) & |trdstNumFramesFilledInSRAM_ANY;
    assign trdstcoretoFlushClear_ANY[i] =  trdstMemRamRdEnFromCore_ANY[i]; 

    
    assign trdstMemRamRdEnFromCore_ANY_stg[i] = trdstcoreFrameFillComplete_d1_ANY[i] | (~trdstcoreFrameFillComplete_d1_ANY[i] & ((TrdstMemRamRdAddrWrap_ANY^trdstcoreRamWpWrap_ANY_d1[i])?($bits(trdstRamSMEMTotalSets_ANY)'(trdstcoreRamWpAddr_ANY_d1[i] - TrdstMemRamRdAddr_TS1) > trdstRamSMEMTotalSets_ANY):((trdstcoreRamWpAddr_ANY_d1[i] > TrdstMemRamRdAddr_TS1))));
    /* verilator lint_off WIDTHEXPAND */
    assign trdstcoreFrameFillComplete_ANY[i] = ~|(trdstFrameLength_ANY[9]?trdstcorewritecnt_ANY[i][4:0]:trdstFrameLength_ANY[8]?trdstcorewritecnt_ANY[i][3:0]:trdstFrameLength_ANY[7]?trdstcorewritecnt_ANY[i][2:0]:trdstcorewritecnt_ANY[i][1:0]);
    /* verilator lint_on WIDTHEXPAND */

    for (genvar j=0; j<NUM_CORES; j++) begin
      assign trdstcoreptrmatchesanypendingframeafteroverflow_ANY[i][j] = (i == j)?1'b0:(~trdstcoreFrameFillComplete_ANY[i] & ~trdstcoreFrameFillComplete_ANY[j] & trdstcoreFrameFillComplete_d1_ANY[j] & trdstcoreNewFrameStart_ANY[j] & ((trdstcorefullRamWpLow_ANY[i] & (trdstFrameLength_ANY[9]?30'h3fffff10:trdstFrameLength_ANY[8]?30'h3fffffc0:trdstFrameLength_ANY[7]?30'h3fffffe0: 30'h3ffffff0)) == (trdstcorefullRamWpLow_ANY[j])));
    end
  end

  dfd_rv_dff #(.WIDTH(NUM_CORES), .RESET_VALUE(0)) trdstMemRamRdEnFromCore_ANY_ff (
        .o_q          (trdstMemRamRdEnFromCore_ANY),
        .i_d          (trdstMemRamRdEnFromCore_ANY_stg),
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

  dfd_rv_dff_clr #(.WIDTH(1)) TrdstMemModeRamFlush_ANY_ff (
    .o_q          (TrdstMemModeRamFlush_ANY),
    .i_d          (1'b1),
    .i_clr        (&trdstcoretoFlushClear_ANY),
    .i_en         (|trdstcoretoFlushEnable_ANY),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  always_comb begin
    trdstNumFrameFillComplete_ANY = '0;
    for (int i=0; i<NUM_CORES; i++) begin
      /* verilator lint_off WIDTHEXPAND */
      trdstNumFrameFillComplete_ANY = $bits(trdstNumFrameFillComplete_ANY)'(trdstNumFrameFillComplete_ANY + (trdstcoreFrameFillComplete_ANY[i] & ~trdstcoreFrameFillComplete_d1_ANY[i]));
      /* verilator lint_on WIDTHEXPAND */
    end
  end

  dfd_rv_dff #(.WIDTH(NUM_CORES), .RESET_VALUE({NUM_CORES{1'b1}})) trdstcoreFrameFillComplete_d1_ANY_ff (
        .o_q          (trdstcoreFrameFillComplete_d1_ANY),
        .i_d          (trdstcoreFrameFillComplete_ANY),
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

  dfd_rv_dff_clr #(.WIDTH(9)) trdstNumFramesFilledInSRAM_ANY_ff (
        .o_q          (trdstNumFramesFilledInSRAM_ANY),
        .i_d          ($bits(trdstNumFramesFilledInSRAM_ANY)'(trdstNumFramesFilledInSRAM_ANY + trdstNumFrameFillComplete_ANY_d1*DataTrace_NumSetsPerFrame_ANY - $bits(trdstNumFramesFilledInSRAM_ANY)'(TrdstMemAxiWrVld_ANY))),
        .i_clr        (trdstRamEnableStart_ANY_d1),
        .i_en         (trdstRamMode_ANY & (|trdstNumFrameFillComplete_ANY_d1 | (TrdstMemAxiWrVld_ANY))),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

  // Staging Flops
  dfd_rv_dff #(.WIDTH(9)) trdstNumFrameFillComplete_ANY_d1_ff (
        .o_q          (trdstNumFrameFillComplete_ANY_d1),
        .i_d          (trdstNumFrameFillComplete_ANY),
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

  dfd_rv_dff #(.WIDTH(9)) trdstNumFramesFilledInSRAM_ANY_d1_ff (
        .o_q          (trdstNumFramesFilledInSRAM_ANY_d1),
        .i_d          (trdstNumFramesFilledInSRAM_ANY),
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

  // --------------------------------------------------------------------------
  // Write Pointer manipulation for Instruction Trace (N-Trace)
  // --------------------------------------------------------------------------
  // 1.Out of reset the next_ptr would be set to start_ptr
  // 2.As soon each of the core starts writing the data the next_ptr would be copied into the core_ptr, next_ptr incremented with frame length
  // 3.When new entry keeps on coming for the core, the writes happen based on the core_ptr and gets incremented
  // 4.Once the frame of the core is incremented, then the global write pointer is updated. (Is it possible that, the more recent core is filled than the oldest one, in that use periodic slush request)
  // 5.New entry to RAM is started from the next_ptr and the same steps are repeated.

  // dfd_rv_dff #(.WIDTH(30)) trntrlocalRamWpLow_ANY_ff (
  //   .o_q          (trntrlocalRamWpLow_ANY),
  //   .i_d          (~trntrRamMode_ANY?((trntrRamEnableStart_ANY_d1 | (~trntrStoponWrap_ANY & (trntrnextlocaltoupdateRamWpLow_ANY == trntrRamLimitLow_ANY)))?trntrRamStartLow_ANY:trntrnextlocaltoupdateRamWpLow_ANY)
  //                                   :(trntrnextlocaltoupdateRamWpLow_ANY)), // Increment based on the frame_length
  //   .i_en         ((|trntrcoreNewFrameStart_ANY) | trntrRamEnableStart_ANY_d1),
  //   .i_clk        (clk),
  //   .i_reset_n    (reset_n)
  // );

  dfd_rv_dff #(.WIDTH(1)) trntrnextlocaltoupdateRamWpLowWrap_ANY_ff (.o_q(trntrnextlocaltoupdateRamWpLowWrap_ANY), .i_d((trntrnextlocaltoupdateRamWpLow_ANY >= trntrRamLimitLow_ANY)), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  assign trntrlocalRamWpLow_ANY = ~trntrRamMode_ANY?((trntrRamEnableStart_ANY_d1 | (~trntrStoponWrap_ANY & trntrnextlocaltoupdateRamWpLowWrap_ANY))?trntrRamStartLow_ANY:trntrnextlocaltoupdateRamWpLow_ANY_stg)
                                                   :(trntrRamEnableStart_ANY_d1?trntrRamSMEMStartLow_ANY:trntrnextlocaltoupdateRamWpLow_ANY_stg); // Increment based on the frame_length
  
  // assign trntrnextlocalRamWpLow_ANY[0] = trntrlocalRamWpLow_ANY; //(trntrRamMode_ANY & trntrRamEnableStart_ANY_d1)?trntrRamSMEMStartLow_ANY:trntrlocalRamWpLow_ANY;

  dfd_rv_ffs_fast #(
    .DIR_L2H(1),
    .WIDTH(NUM_CORES),
    .DATA_WIDTH(NUM_CORES)
  ) ff_ntr_framestart (
      .req_in(trntrcoreNewFrameStart_ANY),
      .data_in('0),
      .req_out(trntrfirstcoreNewFrameStart_ANY),

      .data_out(),
      .enc_req_out(),
      .req_out_therm()
  );

  always_comb begin
    trntrnorthcoresNewFrameStart_ANY = '0;
    trntrsouthcoresNewFrameStart_ANY = '0; 
    for (int i=0; i<NUM_CORES_IN_PATH; i++) begin
      trntrnorthcoresNewFrameStart_ANY |= (trntrcoreNewFrameStart_ANY[i << 1]);
      trntrsouthcoresNewFrameStart_ANY |= (trntrcoreNewFrameStart_ANY[(i << 1) + 1]);
    end
  end

  dfd_rv_dff #(.WIDTH(1)) trntrnorthcoresNewFrameStart_ANY_d1_ff (.o_q(trntrnorthcoresNewFrameStart_ANY_d1), .i_d(trntrnorthcoresNewFrameStart_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trntrsouthcoresNewFrameStart_ANY_d1_ff (.o_q(trntrsouthcoresNewFrameStart_ANY_d1), .i_d(trntrsouthcoresNewFrameStart_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  // assign trntrnextlocaltoupdateRamWpLow_ANY =  trntrnextlocalRamWpLow_ANY[3];

  dfd_rv_dff #(.WIDTH(30)) trntrnextlocaltoupdateRamWpLow_ANY_ff (.o_q(trntrnextlocaltoupdateRamWpLow_ANY_stg), .i_d(trntrnextlocaltoupdateRamWpLow_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  dfd_rv_dff #(.WIDTH(1)) trntrnextlocaltoupdateRamWpWrapOneNewFrame_ANY_ff (.o_q(trntrnextlocaltoupdateRamWpWrapOneNewFrame_ANY), .i_d(((trntrlocalRamWpLow_ANY + $bits(trntrlocalRamWpLow_ANY)'(trntrFrameLength_ANY[9:2])) >= trntrRamLimitLow_ANY)), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trntrnextlocaltoupdateRamWpWrapTwoNewFrame_ANY_ff (.o_q(trntrnextlocaltoupdateRamWpWrapTwoNewFrame_ANY), .i_d((trntrlocalRamWpLow_ANY + $bits(trntrlocalRamWpLow_ANY)'(trntrFrameLength_ANY[9:2]*2)) >= trntrRamLimitLow_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  /* verilator lint_off WIDTHEXPAND */
  assign trntrnextlocaltoupdateRamWpWrap_ANY = (trntrnextlocaltoupdateRamWpWrapOneNewFrame_ANY & ((|trntrnorthcoresNewFrameStart_ANY_d1) | (|trntrsouthcoresNewFrameStart_ANY_d1))) | (trntrnextlocaltoupdateRamWpWrapTwoNewFrame_ANY & ((|trntrnorthcoresNewFrameStart_ANY_d1) & (|trntrsouthcoresNewFrameStart_ANY_d1)));
  /* verilator lint_on WIDTHEXPAND */

  /* verilator lint_off WIDTHEXPAND */
  assign trntrnextlocaltoupdateRamWpLow_ANY = (trntrnorthcoresNewFrameStart_ANY & trntrsouthcoresNewFrameStart_ANY)?trntrnextlocalRamWpLow_ANY[2]:((trntrnorthcoresNewFrameStart_ANY | trntrsouthcoresNewFrameStart_ANY)?trntrnextlocalRamWpLow_ANY[1]:trntrnextlocalRamWpLow_ANY[0]);
  /* verilator lint_on WIDTHEXPAND */
  
  always_comb begin
    trntrnextlocalRamWpLow_ANY[0] = trntrlocalRamWpLow_ANY;
    trntrnextlocalRamWpLow_ANY[1] = '0;
    trntrnextlocalRamWpLow_ANY[2] = '0;
    /* verilator lint_off WIDTHEXPAND */
    for (int i=0; i<2; i++) begin
    /*assign*/ trntrnextlocalRamWpLow_ANY[i+1] = trntrRamMode_ANY?((trntrnextlocalRamWpLow_ANY[i] >= trntrMemMode_nextlocalWrapCond_WpLow_ANY)?trntrRamSMEMStartLow_ANY:$bits(trntrnextlocalRamWpLow_ANY[i])'(trntrnextlocalRamWpLow_ANY[i] + trntrFrameLength_ANY[9:2]))
                                                             :((trntrnextlocalRamWpLow_ANY[i] > trntrRamMode_nextlocalWrapCond_WpLow_ANY)?trntrRamStartLow_ANY:$bits(trntrnextlocalRamWpLow_ANY[i])'(trntrnextlocalRamWpLow_ANY[i] + trntrFrameLength_ANY[9:2]));
    end /* verilator lint_on WIDTHEXPAND */
  end

  // Timing Flops used in comparison maths 
  //Flop-1: (trntrRamSMEMStartLow_ANY + trntrRamSMEMSizeLow_ANY*2) - trntrFrameLength_ANY[9:2] 
  //Flop-2: trntrRamLimitLow_ANY - trntrFrameLength_ANY[9:2] 
  dfd_rv_dff #(.WIDTH(30)) trntrMemMode_nextlocalWrapCond_WpLow_ANY_ff (.o_q(trntrMemMode_nextlocalWrapCond_WpLow_ANY), .i_d($bits(trntrMemMode_nextlocalWrapCond_WpLow_ANY)'($bits(trntrMemMode_nextlocalWrapCond_WpLow_ANY)'(trntrRamSMEMStartLow_ANY) + $bits(trntrMemMode_nextlocalWrapCond_WpLow_ANY)'(trntrRamSMEMSizeLow_ANY*2) - $bits(trntrMemMode_nextlocalWrapCond_WpLow_ANY)'(trntrFrameLength_ANY[9:2]))), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n)); 
  dfd_rv_dff #(.WIDTH(30)) trntrRamMode_nextlocalWrapCond_WpLow_ANY_ff (.o_q(trntrRamMode_nextlocalWrapCond_WpLow_ANY), .i_d($bits(trntrRamMode_nextlocalWrapCond_WpLow_ANY)'($bits(trntrRamMode_nextlocalWrapCond_WpLow_ANY)'(trntrRamLimitLow_ANY) - $bits(trntrRamMode_nextlocalWrapCond_WpLow_ANY)'(trntrFrameLength_ANY[9:2]))), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  for (genvar i=0; i<NUM_CORES; i++) begin
    /* verilator lint_off WIDTHEXPAND */
    assign trntrcoreNewFrameStart_ANY[i] = ~|(trntrFrameLength_ANY[9]?trntrcorenextwritecnt_ANY[i][4:0]:trntrFrameLength_ANY[8]?trntrcorenextwritecnt_ANY[i][3:0]:trntrFrameLength_ANY[7]?trntrcorenextwritecnt_ANY[i][2:0]:trntrcorenextwritecnt_ANY[i][1:0]) & InsnTraceWrEnPerCore_TS0[i]; 
    /* verilator lint_on WIDTHEXPAND */
    assign trntrcorefullRamWpLow_ANY[i] = trntrcoreNewFrameStart_ANY[i]?(trntrfirstcoreNewFrameStart_ANY[i]?trntrnextlocalRamWpLow_ANY[0]:trntrnextlocalRamWpLow_ANY[1]):{trntrcorenextRamWpLow_ANY[i][31:4] + 28'h1 , 2'h0}; 

    assign trntrcoreRamWpLow_ANY[i] = trntrRamMode_ANY?(((trntrcorefullRamWpLow_ANY[i] - trntrRamSMEMStartLow_ANY) & (trntrRamSMEMSizeLow_ANY - 1'b1)) + trntrRamSMEMStartLow_ANY):trntrcorefullRamWpLow_ANY[i];
    assign trntrcoreRamWpAddr_ANY[i] = trntrcoreRamWpLow_ANY[i][6+:TRC_RAM_INDEX_WIDTH];
    assign trntrcoreRamWpWrap_ANY[i] = |((trntrcorefullRamWpLow_ANY[i] - trntrRamSMEMStartLow_ANY) & trntrRamSMEMSizeLow_ANY); // |((trntrcoreRamWpAddr_ANY[i] - trntrRamSMEMStartAddr_ANY) & trntrRamSMEMTotalSets_ANY)
 
    // Timing flops
    dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH)) trntrcoreRamWpAddr_ANY_d1_ff (.o_q(trntrcoreRamWpAddr_ANY_d1[i]), .i_d(trntrcoreRamWpAddr_ANY[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
    dfd_rv_dff #(.WIDTH(1)) trntrcoreRamWpWrap_ANY_d1_ff (.o_q(trntrcoreRamWpWrap_ANY_d1[i]), .i_d(trntrcoreRamWpWrap_ANY[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

    dfd_rv_dff #(.WIDTH(30), .RESET_VALUE(0)) trntrcorenextRamWpLow_ANY_ff (
        .o_q          (trntrcorenextRamWpLow_ANY[i]),
        .i_d          (trntrRamEnableStart_ANY_d1?(trntrRamMode_ANY?trntrRamSMEMStartLow_ANY:trntrRamStartLow_ANY):trntrcorefullRamWpLow_ANY[i]),
        .i_en         (trntrRamEnableStart_ANY_d1 | Eff_InsnTraceWrEnPerCore_TS0[i]),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

    dfd_rv_dff #(.WIDTH(5), .RESET_VALUE(0)) trntrcorenextwritecnt_ANY_ff (
        .o_q          (trntrcorenextwritecnt_ANY[i]),
        .i_d          (trntrcorewritecnt_ANY[i]), 
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

    dfd_rv_dff_clr #(.WIDTH(1), .RESET_VALUE(0)) trntrcoreframefillpendingwhileoverflow_ANY_ff (
        .o_q          (trntrcoreframefillpendingwhileoverflow_ANY[i]),
        .i_d          (1'b1),
        .i_clr        (trntrcoreFrameFillComplete_ANY[i]),
        .i_en         (|trntrcoreptrmatchesanypendingframeafteroverflow_ANY[i] & ~trntrStoponWrap_ANY & TrCsrTrramwplow.Trramwrap), 
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

    assign trntrcorewritecnt_ANY[i] = trntrRamEnableStart_ANY_d1?(5'b0):(InsnTraceWrEnPerCore_TS0[i]?(trntrcorenextwritecnt_ANY[i] + 1'b1):trntrcorenextwritecnt_ANY[i]);  

    assign trntrcoreRamAddrtoNextLocalSetDiff_ANY[i] = (TrntrMemRamRdAddrWrap_ANY^trntrcoreRamWpWrap_ANY_d1[i])
                                                      ?$bits(trntrcoreRamAddrtoNextLocalSetDiff_ANY[i])'(trntrRamSMEMTotalSets_ANY - (TrntrMemRamRdAddr_TS1 - trntrcoreRamWpAddr_ANY_d1[i]))
                                                      :$bits(trntrcoreRamAddrtoNextLocalSetDiff_ANY[i])'(trntrcoreRamWpAddr_ANY_d1[i] - TrntrMemRamRdAddr_TS1);

    dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH+1), .RESET_VALUE(0)) trntrcoreRamAddrtoNextLocalSetDiff_ANY_stg_ff (
        .o_q          (trntrcoreRamAddrtoNextLocalSetDiff_ANY_stg[i]),
        .i_d          (trntrcoreRamAddrtoNextLocalSetDiff_ANY[i]), 
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

    assign trntrcoretoFlushEnable_ANY[i] = (~trntrcoreFrameFillComplete_ANY[i] & (trntrcoreRamAddrtoNextLocalSetDiff_ANY_stg[i] <= (TRC_RAM_INDEX_WIDTH+1)'(trntrcoretoFlushThreshold_ANY))) & |trntrNumFramesFilledInSRAM_ANY;
    assign trntrcoretoFlushClear_ANY[i] =  trntrMemRamRdEnFromCore_ANY[i]; 

    assign trntrMemRamRdEnFromCore_ANY_stg[i] = trntrcoreFrameFillComplete_d1_ANY[i] | (~trntrcoreFrameFillComplete_d1_ANY[i] & ((TrntrMemRamRdAddrWrap_ANY^trntrcoreRamWpWrap_ANY_d1[i])?($bits(trntrRamSMEMTotalSets_ANY)'(trntrcoreRamWpAddr_ANY_d1[i] - TrntrMemRamRdAddr_TS1) > trntrRamSMEMTotalSets_ANY):((trntrcoreRamWpAddr_ANY_d1[i] > TrntrMemRamRdAddr_TS1))));
    /* verilator lint_off WIDTHEXPAND */
    assign trntrcoreFrameFillComplete_ANY[i] = ~|(trntrFrameLength_ANY[9]?trntrcorewritecnt_ANY[i][4:0]:trntrFrameLength_ANY[8]?trntrcorewritecnt_ANY[i][3:0]:trntrFrameLength_ANY[7]?trntrcorewritecnt_ANY[i][2:0]:trntrcorewritecnt_ANY[i][1:0]);
    /* verilator lint_on WIDTHEXPAND */

    for (genvar j=0; j<NUM_CORES; j++) begin
      assign trntrcoreptrmatchesanypendingframeafteroverflow_ANY[i][j] = (i == j)?1'b0:(~trntrcoreFrameFillComplete_ANY[i] & ~trntrcoreFrameFillComplete_ANY[j] & trntrcoreFrameFillComplete_d1_ANY[j] & trntrcoreNewFrameStart_ANY[j] & ((trntrcorefullRamWpLow_ANY[i] & (trntrFrameLength_ANY[9]?30'h3fffff10:trntrFrameLength_ANY[8]?30'h3fffffc0:trntrFrameLength_ANY[7]?30'h3fffffe0:30'h3ffffff0)) == (trntrcorefullRamWpLow_ANY[j])));
    end
  end

  dfd_rv_dff #(.WIDTH(NUM_CORES), .RESET_VALUE(0)) trntrMemRamRdEnFromCore_ANY_ff (
        .o_q          (trntrMemRamRdEnFromCore_ANY),
        .i_d          (trntrMemRamRdEnFromCore_ANY_stg),
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

  dfd_rv_dff_clr #(.WIDTH(1)) TrntrMemModeRamFlush_ANY_ff (
    .o_q          (TrntrMemModeRamFlush_ANY),
    .i_d          (1'b1),
    .i_clr        (&trntrcoretoFlushClear_ANY),
    .i_en         (|trntrcoretoFlushEnable_ANY),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  always_comb begin
    trntrNumFrameFillComplete_ANY = '0;
    for (int i=0; i<NUM_CORES; i++) begin
      /* verilator lint_off WIDTHEXPAND */
      trntrNumFrameFillComplete_ANY = $bits(trntrNumFrameFillComplete_ANY)'(trntrNumFrameFillComplete_ANY + (trntrcoreFrameFillComplete_ANY[i] & ~trntrcoreFrameFillComplete_d1_ANY[i]));
      /* verilator lint_on WIDTHEXPAND */
    end
  end

  dfd_rv_dff #(.WIDTH(NUM_CORES), .RESET_VALUE({NUM_CORES{1'b1}})) trntrcoreFrameFillComplete_d1_ANY_ff (
        .o_q          (trntrcoreFrameFillComplete_d1_ANY),
        .i_d          (trntrcoreFrameFillComplete_ANY),
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

  dfd_rv_dff_clr #(.WIDTH(9)) trntrNumFramesFilledInSRAM_ANY_ff (
        .o_q          (trntrNumFramesFilledInSRAM_ANY),
        .i_d          ($bits(trntrNumFramesFilledInSRAM_ANY)'(trntrNumFramesFilledInSRAM_ANY + trntrNumFrameFillComplete_ANY_d1*InsnTrace_NumSetsPerFrame_ANY - $bits(trntrNumFramesFilledInSRAM_ANY)'(TrntrMemAxiWrVld_ANY))),
        .i_clr        (trntrRamEnableStart_ANY_d1),
        .i_en         (trntrRamMode_ANY & (|trntrNumFrameFillComplete_ANY_d1 | (TrntrMemAxiWrVld_ANY))),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );
  
  // Staging Flops
  dfd_rv_dff #(.WIDTH(9)) trntrNumFrameFillComplete_ANY_d1_ff (
        .o_q          (trntrNumFrameFillComplete_ANY_d1),
        .i_d          (trntrNumFrameFillComplete_ANY),
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

  dfd_rv_dff #(.WIDTH(9)) trntrNumFramesFilledInSRAM_ANY_d1_ff (
        .o_q          (trntrNumFramesFilledInSRAM_ANY_d1),
        .i_d          (trntrNumFramesFilledInSRAM_ANY),
        .i_en         (1'b1),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
      );

  // ----------------------------------------------------------------------------------------------
  // Flops to store the outstanding writes to the RAM in case of multiple writes to same way
  // ----------------------------------------------------------------------------------------------
  for (genvar i=0; i<8; i++) begin
    dfd_rv_dff #(.WIDTH(1)) TrRamPendPktVld_ff (
      .o_q          (TrRamPendPktVld_ANY[i]),
      .i_d          (TrRamPendWrEn_ANY[i] | ~TrRamPendRdEn_ANY[i]), 
      .i_en         (TrRamPendWrEn_ANY[i] | TrRamPendRdEn_ANY[i]),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    dfd_rv_dff #(.WIDTH($bits(TrRamPendPkt_s))) TrRamPendPkt_ff (
      .o_q          (TrRamPendPktRd_ANY[i]),
      .i_d          (TrRamPendPktWr_ANY[i]), 
      .i_en         (TrRamPendWrEn_ANY[i]),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );
  end

  for (genvar i=0; i<8; i++) begin
    assign TrRamPendNtracePktVld_ANY[i] = TrRamPendPktVld_ANY[i] & TrRamPendPktRd_ANY[i].TrRamPendSrc_ANY;
    assign TrRamPendDstPktVld_ANY[i] = TrRamPendPktVld_ANY[i] & ~TrRamPendPktRd_ANY[i].TrRamPendSrc_ANY;
  end

  always_comb begin
    TrRamFreeWayMaskPend_ANY = TrRamFreeWayMask_ANY; 
    TrRamPendRdEn_ANY = 8'h0;
    TrdstRamPendPktInhibitRamRd_ANY = 4'h0;
    TrntrRamPendPktInhibitRamRd_ANY = 4'h0;
    for (int i=0; i<8; i++) begin
      if (TrRamFreeWayMaskPend_ANY[TrRamPendPktRd_ANY[i].TrRamPendWayIdx_ANY] & TrRamPendPktVld_ANY[i]) begin 
        TrRamFreeWayMaskPend_ANY[TrRamPendPktRd_ANY[i].TrRamPendWayIdx_ANY] = 1'b0;
        TrRamPendRdEn_ANY[i] = 1'b1;
      end

      if (TrRamPendWrEn_ANY[i]) begin
        if (TrRamPendPktWr_ANY[i].TrRamPendAddr_ANY == TrdstMemRamRdAddr_TS1) begin
          TrdstRamPendPktInhibitRamRd_ANY[TrRamPendPktWr_ANY[i].TrRamPendWayIdx_ANY] = 1'b1;
        end
        else if (TrRamPendPktWr_ANY[i].TrRamPendAddr_ANY == TrntrMemRamRdAddr_TS1) begin
          TrntrRamPendPktInhibitRamRd_ANY[TrRamPendPktWr_ANY[i].TrRamPendWayIdx_ANY] = 1'b1; 
        end
      end

      if (TrRamPendPktVld_ANY[i]) begin
        if (TrRamPendPktRd_ANY[i].TrRamPendAddr_ANY == TrdstMemRamRdAddr_TS1) begin
          TrdstRamPendPktInhibitRamRd_ANY[TrRamPendPktRd_ANY[i].TrRamPendWayIdx_ANY] = 1'b1;
        end
        else if (TrRamPendPktRd_ANY[i].TrRamPendAddr_ANY == TrntrMemRamRdAddr_TS1) begin
          TrntrRamPendPktInhibitRamRd_ANY[TrRamPendPktRd_ANY[i].TrRamPendWayIdx_ANY] = 1'b1;
        end
      end
    end
  end

  dfd_rv_dff #(.WIDTH(TRC_RAM_WAYS)) TrRamFreeWayMaskPend_ANY_stg_ff (
    .o_q          (TrRamFreeWayMaskPend_ANY_stg),
    .i_d          (TrRamFreeWayMaskPend_ANY),
    .i_en         (1'b1),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );
  
  dfd_rv_dff #(.WIDTH(TRC_RAM_WAYS)) TrdstRamPendPktInhibitRamRd_ANY_stg_ff (
    .o_q          (TrdstRamPendPktInhibitRamRd_ANY_stg),
    .i_d          (TrdstRamPendPktInhibitRamRd_ANY),
    .i_en         (1'b1),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  dfd_rv_dff #(.WIDTH(TRC_RAM_WAYS)) TrntrRamPendPktInhibitRamRd_ANY_stg_ff (
    .o_q          (TrntrRamPendPktInhibitRamRd_ANY_stg),
    .i_d          (TrntrRamPendPktInhibitRamRd_ANY),
    .i_en         (1'b1),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  dfd_rv_ffsN #(
    .DIR_L2H(1'b0),
    .WIDTH(8),
    .DATA_WIDTH(8),
    .NUM_SEL(2)
  ) TrRamPendWrEn_ffsN (
    .req_in(~(TrRamPendPktVld_ANY & ~TrRamPendRdEn_ANY)),
    .data_in('0),
    .req_out({TrRamPendWrEn_Select_ANY[1],TrRamPendWrEn_Select_ANY[0]}),
    .req_sum(),
    .data_out(),
    .enc_req_out()
  );

  assign TrRamPendBufferNorthWrEn_ANY = (TrRamPendPktNorthWrEn_TS0 & TrRamPendPktSouthWrEn_TS0)?TrRamPendWrEn_Select_ANY[1]:TrRamPendWrEn_Select_ANY[0];
  assign TrRamPendBufferSouthWrEn_ANY = TrRamPendWrEn_Select_ANY[0];
  
  assign TrRamPendWrEn_ANY = ({8{TrRamPendPktNorthWrEn_TS0}} & TrRamPendBufferNorthWrEn_ANY) | ({8{TrRamPendPktSouthWrEn_TS0}} & TrRamPendBufferSouthWrEn_ANY); 

  always_comb begin
    TrRamPendPktWr_ANY = '0;
    for (int i=0; i<8; i++) begin
      TrRamPendPktWr_ANY[i] |= ((TrRamPendBufferNorthWrEn_ANY[i] & TrRamPendPktNorthWrEn_TS0)?TrRamPendPktNorthWr_TS0:'0) | ((TrRamPendBufferSouthWrEn_ANY[i] & TrRamPendPktSouthWrEn_TS0)?TrRamPendPktSouthWr_TS0:'0);
    end
  end

  // --------------------------------------------------------------------------
  // Trace Sink RAM Write
  // --------------------------------------------------------------------------
  for (genvar i=0; i<TRC_RAM_WAYS; i++) begin: TrcSinkWayControl
    // Way's Write enable
    assign TraceWrEn_TS0_stg[i] = (TrRamNorthTraceWrEn_TS0 & (TrRamNorthTraceWrWay_TS0 == i[1:0]))
                            | (TrRamSouthTraceWrEn_TS0 & (TrRamSouthTraceWrWay_TS0 == i[1:0]))  
                            | (TrRamPendRdEn_ANY[0] & (TrRamPendPktRd_ANY[0].TrRamPendWayIdx_ANY == i[1:0])) 
                            | (TrRamPendRdEn_ANY[1] & (TrRamPendPktRd_ANY[1].TrRamPendWayIdx_ANY == i[1:0])) 
                            | (TrRamPendRdEn_ANY[2] & (TrRamPendPktRd_ANY[2].TrRamPendWayIdx_ANY == i[1:0])) 
                            | (TrRamPendRdEn_ANY[3] & (TrRamPendPktRd_ANY[3].TrRamPendWayIdx_ANY == i[1:0]))
                            | (TrRamPendRdEn_ANY[4] & (TrRamPendPktRd_ANY[4].TrRamPendWayIdx_ANY == i[1:0]))
                            | (TrRamPendRdEn_ANY[5] & (TrRamPendPktRd_ANY[5].TrRamPendWayIdx_ANY == i[1:0]))
                            | (TrRamPendRdEn_ANY[6] & (TrRamPendPktRd_ANY[6].TrRamPendWayIdx_ANY == i[1:0]))
                            | (TrRamPendRdEn_ANY[7] & (TrRamPendPktRd_ANY[7].TrRamPendWayIdx_ANY == i[1:0]));

    // Write Data
    assign TraceWrData_TS0_stg[2*i] = ({(DATA_WIDTH/2){TrRamNorthTraceWrEn_TS0 & (TrRamNorthTraceWrWay_TS0 == i[1:0])}} & TrRamNorthTraceWrData_TS0[0+:DATA_WIDTH/2])
                                | ({(DATA_WIDTH/2){TrRamSouthTraceWrEn_TS0 & (TrRamSouthTraceWrWay_TS0 == i[1:0])}} & TrRamSouthTraceWrData_TS0[0+:DATA_WIDTH/2])
                                | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[0] & (TrRamPendPktRd_ANY[0].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[0].TrRamPendData_ANY[0+:DATA_WIDTH/2])
                                | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[1] & (TrRamPendPktRd_ANY[1].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[1].TrRamPendData_ANY[0+:DATA_WIDTH/2])
                                | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[2] & (TrRamPendPktRd_ANY[2].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[2].TrRamPendData_ANY[0+:DATA_WIDTH/2])
                                | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[3] & (TrRamPendPktRd_ANY[3].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[3].TrRamPendData_ANY[0+:DATA_WIDTH/2])
                                | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[4] & (TrRamPendPktRd_ANY[4].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[4].TrRamPendData_ANY[0+:DATA_WIDTH/2])
                                | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[5] & (TrRamPendPktRd_ANY[5].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[5].TrRamPendData_ANY[0+:DATA_WIDTH/2])
                                | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[6] & (TrRamPendPktRd_ANY[6].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[6].TrRamPendData_ANY[0+:DATA_WIDTH/2])
                                | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[7] & (TrRamPendPktRd_ANY[7].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[7].TrRamPendData_ANY[0+:DATA_WIDTH/2]); 

    assign TraceWrData_TS0_stg[2*i+1] = ({(DATA_WIDTH/2){TrRamNorthTraceWrEn_TS0 & (TrRamNorthTraceWrWay_TS0 == i[1:0])}} & TrRamNorthTraceWrData_TS0[DATA_WIDTH/2+:DATA_WIDTH/2])
                                  | ({(DATA_WIDTH/2){TrRamSouthTraceWrEn_TS0 & (TrRamSouthTraceWrWay_TS0 == i[1:0])}} & TrRamSouthTraceWrData_TS0[DATA_WIDTH/2+:DATA_WIDTH/2])
                                  | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[0] & (TrRamPendPktRd_ANY[0].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[0].TrRamPendData_ANY[DATA_WIDTH/2+:DATA_WIDTH/2])
                                  | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[1] & (TrRamPendPktRd_ANY[1].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[1].TrRamPendData_ANY[DATA_WIDTH/2+:DATA_WIDTH/2])
                                  | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[2] & (TrRamPendPktRd_ANY[2].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[2].TrRamPendData_ANY[DATA_WIDTH/2+:DATA_WIDTH/2])
                                  | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[3] & (TrRamPendPktRd_ANY[3].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[3].TrRamPendData_ANY[DATA_WIDTH/2+:DATA_WIDTH/2])
                                  | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[4] & (TrRamPendPktRd_ANY[4].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[4].TrRamPendData_ANY[DATA_WIDTH/2+:DATA_WIDTH/2])
                                  | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[5] & (TrRamPendPktRd_ANY[5].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[5].TrRamPendData_ANY[DATA_WIDTH/2+:DATA_WIDTH/2])
                                  | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[6] & (TrRamPendPktRd_ANY[6].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[6].TrRamPendData_ANY[DATA_WIDTH/2+:DATA_WIDTH/2])
                                  | ({(DATA_WIDTH/2){TrRamPendRdEn_ANY[7] & (TrRamPendPktRd_ANY[7].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[7].TrRamPendData_ANY[DATA_WIDTH/2+:DATA_WIDTH/2]);

    // Write Addr
    assign TraceWrAddr_TS0_stg[i] = ({(TRC_RAM_INDEX_WIDTH){TrRamNorthTraceWrEn_TS0 & (TrRamNorthTraceWrWay_TS0 == i[1:0])}} & TrRamNorthTraceWrAddr_TS0)
                              | ({(TRC_RAM_INDEX_WIDTH){TrRamSouthTraceWrEn_TS0 & (TrRamSouthTraceWrWay_TS0 == i[1:0])}} & TrRamSouthTraceWrAddr_TS0)
                              | ({(TRC_RAM_INDEX_WIDTH){TrRamPendRdEn_ANY[0] & (TrRamPendPktRd_ANY[0].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[0].TrRamPendAddr_ANY)
                              | ({(TRC_RAM_INDEX_WIDTH){TrRamPendRdEn_ANY[1] & (TrRamPendPktRd_ANY[1].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[1].TrRamPendAddr_ANY)
                              | ({(TRC_RAM_INDEX_WIDTH){TrRamPendRdEn_ANY[2] & (TrRamPendPktRd_ANY[2].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[2].TrRamPendAddr_ANY)
                              | ({(TRC_RAM_INDEX_WIDTH){TrRamPendRdEn_ANY[3] & (TrRamPendPktRd_ANY[3].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[3].TrRamPendAddr_ANY)
                              | ({(TRC_RAM_INDEX_WIDTH){TrRamPendRdEn_ANY[4] & (TrRamPendPktRd_ANY[4].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[4].TrRamPendAddr_ANY)
                              | ({(TRC_RAM_INDEX_WIDTH){TrRamPendRdEn_ANY[5] & (TrRamPendPktRd_ANY[5].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[5].TrRamPendAddr_ANY)
                              | ({(TRC_RAM_INDEX_WIDTH){TrRamPendRdEn_ANY[6] & (TrRamPendPktRd_ANY[6].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[6].TrRamPendAddr_ANY)
                              | ({(TRC_RAM_INDEX_WIDTH){TrRamPendRdEn_ANY[7] & (TrRamPendPktRd_ANY[7].TrRamPendWayIdx_ANY == i[1:0])}} & TrRamPendPktRd_ANY[7].TrRamPendAddr_ANY);

    dfd_rv_dff #(.WIDTH(1)) TraceWrEn_TS0_ff (.o_q(TraceWrEn_TS0[i]), .i_d(TraceWrEn_TS0_stg_d1[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
    dfd_rv_dff #(.WIDTH(TRC_RAM_DATA_WIDTH)) TraceWrData_TS0_even_ff (.o_q(TraceWrData_TS0[2*i]), .i_d(TraceWrData_TS0_stg_d1[2*i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
    dfd_rv_dff #(.WIDTH(TRC_RAM_DATA_WIDTH)) TraceWrData_TS0_odd_ff (.o_q(TraceWrData_TS0[2*i+1]), .i_d(TraceWrData_TS0_stg_d1[2*i+1]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
    dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH)) TraceWrAddr_TS0_ff (.o_q(TraceWrAddr_TS0[i]), .i_d(TraceWrAddr_TS0_stg_d1[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

    dfd_rv_dff #(.WIDTH(1)) TraceWrEn_TS0_stg_ff (.o_q(TraceWrEn_TS0_stg_d1[i]), .i_d(TraceWrEn_TS0_stg[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
    dfd_rv_dff #(.WIDTH(TRC_RAM_DATA_WIDTH)) TraceWrData_TS0_even_stg_ff (.o_q(TraceWrData_TS0_stg_d1[2*i]), .i_d(TraceWrData_TS0_stg[2*i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
    dfd_rv_dff #(.WIDTH(TRC_RAM_DATA_WIDTH)) TraceWrData_TS0_odd_stg_ff (.o_q(TraceWrData_TS0_stg_d1[2*i+1]), .i_d(TraceWrData_TS0_stg[2*i+1]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
    dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH)) TraceWrAddr_TS0_stg_ff (.o_q(TraceWrAddr_TS0_stg_d1[i]), .i_d(TraceWrAddr_TS0_stg[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

    // Actual Ram Addr (Write + Read Interleaved)
    assign TraceAddr_ANY[i] = TraceWrEn_TS0[i]?TraceWrAddr_TS0[i]:TraceRdAddr_TS1;  
  end

  assign TraceRamWrEn_TS0_stg = trdstRamWrEn_TS0_stg | trntrRamWrEn_TS0_stg; // TrRamNorthTraceWrEn_TS0 | TrRamSouthTraceWrEn_TS0 | (|TrRamPendRdEn_ANY);
  assign trdstRamWrEn_TS0_stg = (TrRamNorthTraceWrEn_TS0 & ~TrRamNorthTraceWrSrc_TS0) | (TrRamSouthTraceWrEn_TS0 & ~TrRamSouthTraceWrSrc_TS0) | (|(TrRamPendRdEn_ANY & TrRamPendDstPktVld_ANY));
  assign trntrRamWrEn_TS0_stg = (TrRamNorthTraceWrEn_TS0 & TrRamNorthTraceWrSrc_TS0) | (TrRamSouthTraceWrEn_TS0 & TrRamSouthTraceWrSrc_TS0) | (|(TrRamPendRdEn_ANY & TrRamPendNtracePktVld_ANY));

  dfd_rv_dff #(.WIDTH(1)) TraceWrEn_TS0_ff (.o_q(TraceRamWrEn_TS0), .i_d(TraceRamWrEn_TS0_stg_d1), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) TraceWrEn_TS0_stg_ff (.o_q(TraceRamWrEn_TS0_stg_d1), .i_d(TraceRamWrEn_TS0_stg), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  dfd_rv_dff #(.WIDTH(1)) trdstRamWrEn_TS0_ff (.o_q(trdstRamWrEn_TS0), .i_d(trdstRamWrEn_TS0_stg_d1), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trdstRamWrEn_TS0_stg_ff (.o_q(trdstRamWrEn_TS0_stg_d1), .i_d(trdstRamWrEn_TS0_stg), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  dfd_rv_dff #(.WIDTH(1)) trntrRamWrEn_TS0_ff (.o_q(trntrRamWrEn_TS0), .i_d(trntrRamWrEn_TS0_stg_d1), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trntrRamWrEn_TS0_stg_ff (.o_q(trntrRamWrEn_TS0_stg_d1), .i_d(trntrRamWrEn_TS0_stg), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  
  // --------------------------------------------------------------------------
  // Trace Sink RAM Connection (SRAM in trace_mem)
  // --------------------------------------------------------------------------
  // 32KB = 8 instances of 512x64 macros
  // for (genvar gc=0; gc<TRC_RAM_INSTANCES; gc++) begin: TrcSinkCells
  //   dfd_rv_mem_model #(
  //                   .ADDR_WIDTH(TRC_RAM_INDEX_WIDTH),
  //                   .DATA_WIDTH(TRC_RAM_DATA_WIDTH),
  //                   .RW_PORTS(1)
  //   ) TrcSinkRam (
  //     //Inputs
  //     .i_clk                   (clk),
  //     .i_reset_n               (reset_n),
  //     .i_mem_chip_en           (TraceWrEn_TS0[gc/2] | TraceRdEn_TS1[gc]),
  //     .i_mem_wr_en             (TraceWrEn_TS0[gc/2]),
  //     .i_mem_rd_en             ('0),
  //     .i_mem_addr              (TraceAddr_ANY[gc/2]),
  //     .i_mem_wr_data           (TraceWrData_TS0[gc]), 
  //     .i_mem_wr_mask_en        ('0),

  //     .i_reg_mem_faulty_io     ('0),
  //     .i_reg_mem_column_repair (1'b0),

  //     //Outputs
  //     .o_mem_rd_data           () 
  //   );
  // end

  always_comb begin: always_blk_1
    for (int gc = 0; gc<TRC_RAM_INSTANCES; gc++) begin
      SinkMemPktIn[gc].mem_chip_en    = TraceWrEn_TS0[gc/2] | TraceRdEn_TS1[gc];
      SinkMemPktIn[gc].mem_wr_en      = TraceWrEn_TS0[gc/2];
      SinkMemPktIn[gc].mem_wr_addr    = TraceAddr_ANY[gc/2];
      SinkMemPktIn[gc].mem_wr_data    = TraceWrData_TS0[gc];
      SinkMemPktIn[gc].mem_wr_mask_en = 1'b0;

      TraceRamData_TS2[gc] = SinkMemPktOut[gc].mem_rd_data;
    end
  end

  // --------------------------------------------------------------------------
  // Trace Sink RAM Read
  // --------------------------------------------------------------------------
  // dfd_rv_dff #(.WIDTH(1)) TraceMemRdEn_ANY_ff (.o_q(TraceMemRdEn_ANY), .i_d(TraceMemRdEn_ANY_stg), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  // dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH)) TraceMemRdAddr_TS1_ff (.o_q(TraceMemRdAddr_TS1), .i_d(TraceMemRdAddr_TS1_stg), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  // dfd_rv_dff #(.WIDTH(TRC_RAM_INSTANCES)) TraceMemPerWayRdEn_TS1_ff (.o_q(TraceMemPerWayRdEn_TS1), .i_d(TraceMemPerWayRdEn_TS1_stg), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  assign TraceRdAddr_TS1 = TraceMemRdEn_ANY?TraceMemRdAddr_TS1:(trRamDataRdEn_ANY ? trntrRamRpLow_ANY[6+:TRC_RAM_INDEX_WIDTH] : trdstRamRpLow_ANY[6+:TRC_RAM_INDEX_WIDTH]);
  for (genvar i=0; i<TRC_RAM_INSTANCES; i++) begin : TraceReadEn
    assign InsnTraceRdEn_TS1[i] = ((trntrRamWpLow_ANY != trntrRamRpLow_ANY) | TrCsrTrramwplow.Trramwrap) & trRamDataRdEn_ANY &
                                  (trntrRamRpLow_ANY[5:3] == i[2:0]);
    assign DataTraceRdEn_TS1[i] = ((trdstRamWpLow_ANY != trdstRamRpLow_ANY) | TrCsrTrdstramwplow.Trdstramwrap) & trdstRamDataRdEn_ANY &
                                  (trdstRamRpLow_ANY[5:3] == i[2:0]);
    assign TraceRdEn_TS1[i] = TraceMemRdEn_ANY?TraceMemPerWayRdEn_TS1[i]:(trRamDataRdEn_ANY ? InsnTraceRdEn_TS1[i] : DataTraceRdEn_TS1[i]);
    
    dfd_rv_dff #(.WIDTH(1)) TraceRdEnTS2_ff (.o_q(TraceRdEn_TS2[i]), .i_d(TraceRdEn_TS1[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  end

  dfd_rv_dff #(.WIDTH(1)) InsnTraceRdEnTS2_ff (.o_q(InsnTraceRdEn_TS2), .i_d(trRamDataRdEn_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) DstTraceRdEnTS2_ff (.o_q(DataTraceRdEn_TS2), .i_d(trdstRamDataRdEn_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  dfd_rv_dff #(.WIDTH(1)) InsnTraceRdEnTS3_ff (.o_q(InsnTraceRdEn_TS3), .i_d(InsnTraceRdEn_TS2), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) DstTraceRdEnTS3_ff (.o_q(DataTraceRdEn_TS3), .i_d(DataTraceRdEn_TS2), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  // --------------------------------------------------------------------------
  // Trace Control : Backpressure the grants
  // --------------------------------------------------------------------------
  // Assert the Backpressure to the core when the space left in the RAM is less than N*F*D/4
  // Compute the number of inflight packets per-core = ceil(2*D/4)-1 // D-> Max delay in the path

  assign TN_TR_NTrace_NumPkt_PerFrame = trntrFrameLength_ANY[9:4]; // Each packet is of 16-bytes wide
  assign TN_TR_Dst_NumPkt_PerFrame = trdstFrameLength_ANY[9:4]; // Each packet is of 16-bytes wide

  assign InsnTrace_NumSetsPerFrame_ANY = trntrFrameLength_ANY[9:6];
  assign DataTrace_NumSetsPerFrame_ANY = trdstFrameLength_ANY[9:6];

  /* verilator lint_off WIDTHEXPAND */
  assign InsnTrace_NumInFlightFrame_ANY = $bits(InsnTrace_NumInFlightFrame_ANY)'((TN_TR_NTrace_NumPkt_PerFrame == 6'h20)?INFLIGHT_FRAME_CNT_512B:((TN_TR_NTrace_NumPkt_PerFrame == 6'h10)?INFLIGHT_FRAME_CNT_256B:(TN_TR_NTrace_NumPkt_PerFrame == 6'h8)?INFLIGHT_FRAME_CNT_128B:INFLIGHT_FRAME_CNT_64B));
  assign DataTrace_NumInFlightFrame_ANY = $bits(DataTrace_NumInFlightFrame_ANY)'((TN_TR_Dst_NumPkt_PerFrame == 6'h20)?INFLIGHT_FRAME_CNT_512B:((TN_TR_Dst_NumPkt_PerFrame == 6'h10)?INFLIGHT_FRAME_CNT_256B:(TN_TR_Dst_NumPkt_PerFrame == 6'h8)?INFLIGHT_FRAME_CNT_128B:INFLIGHT_FRAME_CNT_64B));
  /* verilator lint_on WIDTHEXPAND */

  dfd_rv_dff #(.WIDTH(32), .RESET_VALUE(0)) InsnTrace_InFlightData_BackPressure_Threshold_ANY_ff (
    .o_q          (InsnTrace_InFlightData_BackPressure_Threshold_ANY),
    .i_d          ($bits(InsnTrace_InFlightData_BackPressure_Threshold_ANY)'(InsnTrace_NumSetsPerFrame_ANY*InsnTrace_NumInFlightFrame_ANY*TR_TS_Ntrace_NumEnabled_Srcs)),
    .i_en         (1'b1),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  dfd_rv_dff #(.WIDTH(32), .RESET_VALUE(0)) DataTrace_InFlightData_BackPressure_Threshold_ANY_ff (
    .o_q          (DataTrace_InFlightData_BackPressure_Threshold_ANY),
    .i_d          ($bits(InsnTrace_InFlightData_BackPressure_Threshold_ANY)'(DataTrace_NumSetsPerFrame_ANY*DataTrace_NumInFlightFrame_ANY*TR_TS_Dst_NumEnabled_Srcs)),
    .i_en         (1'b1),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH + 1), .RESET_VALUE(0)) trntrcoretoFlushThreshold_ANY_ff (
    .o_q          (trntrcoretoFlushThreshold_ANY),
    .i_d          ($bits(trntrcoretoFlushThreshold_ANY)'((TR_TS_Ntrace_NumEnabled_Srcs[3])?(trntrRamSMEMTotalSets_ANY >> 3'h4):(TR_TS_Ntrace_NumEnabled_Srcs[2])?(trntrRamSMEMTotalSets_ANY >> 3'h2):(TR_TS_Ntrace_NumEnabled_Srcs[1])?(trntrRamSMEMTotalSets_ANY >> 3'h1):(trntrRamSMEMTotalSets_ANY >> 3'h1))),
    .i_en         (1'b1),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH + 1), .RESET_VALUE(0)) trdstcoretoFlushThreshold_ANY_ff (
    .o_q          (trdstcoretoFlushThreshold_ANY),
    .i_d          ($bits(trdstcoretoFlushThreshold_ANY)'((TR_TS_Dst_NumEnabled_Srcs[3])?(trdstRamSMEMTotalSets_ANY >> 3'h4):(TR_TS_Dst_NumEnabled_Srcs[2])?(trdstRamSMEMTotalSets_ANY >> 3'h2):(TR_TS_Dst_NumEnabled_Srcs[1])?(trdstRamSMEMTotalSets_ANY >> 3'h1):(trdstRamSMEMTotalSets_ANY >> 3'h1))),
    .i_en         (1'b1),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  // SRAM Mode
  /* verilator lint_off WIDTHEXPAND */
  assign trntrRamModeBP_ANY = (trntrRamLimitLow_ANY - TrCsrTrramwplow.Trramwplow)*4 <= InsnTrace_InFlightData_BackPressure_Threshold_ANY*64;
  assign trdstRamModeBP_ANY = (trdstRamLimitLow_ANY - TrCsrTrdstramwplow.Trdstramwplow)*4 <= DataTrace_InFlightData_BackPressure_Threshold_ANY*64;

  // SMEM Mode
  assign trntrMemAvailableSpace_ANY = $bits(trntrMemAvailableSpace_ANY)'(trntrMemSMEMLimitAddr_ANY - TrntrMemAxiWrAddr_ANY); 
  assign trdstMemAvailableSpace_ANY = $bits(trdstMemAvailableSpace_ANY)'(trdstMemSMEMLimitAddr_ANY - TrdstMemAxiWrAddr_ANY); 

  assign trntrMemBytestoWrite_ANY = ((trntrnextlocaltoupdateRamWpLow_ANY_stg - trntrRamSMEMStartLow_ANY)*4 - (TrntrMemRamRdAddr_TS1 - $bits(TrntrMemRamRdAddr_TS1)'(trntrRamSMEMStartAddr_ANY))*64);
  assign trdstMemBytestoWrite_ANY = ((trdstnextlocaltoupdateRamWpLow_ANY_stg - trdstRamSMEMStartLow_ANY)*4 - (TrdstMemRamRdAddr_TS1 - $bits(TrdstMemRamRdAddr_TS1)'(trdstRamSMEMStartAddr_ANY))*64);

  assign trntrMemModeBP_ANY = (trntrMemAvailableSpace_ANY - trntrMemBytestoWrite_ANY) <= InsnTrace_InFlightData_BackPressure_Threshold_ANY*64;
  assign trdstMemModeBP_ANY = (trdstMemAvailableSpace_ANY - trdstMemBytestoWrite_ANY) <= DataTrace_InFlightData_BackPressure_Threshold_ANY*64;
  /* verilator lint_on WIDTHEXPAND */

  // Actual Control signals to Sources
  assign TS_TR_Ntrace_Bp_int =  (~trntrRamMode_ANY & trntrStoponWrap_ANY & (~trntrRamActiveEnable_ANY | trntrRamModeBP_ANY)) | (trntrRamMode_ANY & ((TrntrMemModeRamBackPressure_ANY & ~TrntrMemModeRamFlush_ANY) | (trntrStoponWrap_ANY & (~trntrRamActiveEnable_ANY | trntrMemModeBP_ANY))));
  assign TS_TR_Dst_Bp_int = (~trdstRamMode_ANY & trdstStoponWrap_ANY & (~trdstRamActiveEnable_ANY | trdstRamModeBP_ANY)) | (trdstRamMode_ANY & ((TrdstMemModeRamBackPressure_ANY & ~TrdstMemModeRamFlush_ANY) | (trdstStoponWrap_ANY & (~trdstRamActiveEnable_ANY | trdstMemModeBP_ANY)))); 

  assign TS_TR_Ntrace_Flush_int = (~trntrRamMode_ANY & trntrStoponWrap_ANY & (~trntrRamActiveEnable_ANY | trntrRamModeBP_ANY)) | (trntrRamMode_ANY & (TrntrMemModeRamFlush_ANY | (trntrStoponWrap_ANY & (~trntrRamActiveEnable_ANY | trntrMemModeBP_ANY))));
  assign TS_TR_Dst_Flush_int = (~trdstRamMode_ANY & trdstStoponWrap_ANY & (~trdstRamActiveEnable_ANY | trdstRamModeBP_ANY)) | (trdstRamMode_ANY & (TrdstMemModeRamFlush_ANY | (trdstStoponWrap_ANY & (~trdstRamActiveEnable_ANY | trdstMemModeBP_ANY)))); 

  dfd_rv_dff #(.WIDTH(1)) TS_TR_Ntrace_Bp_ff (.o_q(TS_TR_Ntrace_Bp), .i_d(TS_TR_Ntrace_Bp_int), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) TS_TR_Dst_Bp_ff (.o_q(TS_TR_Dst_Bp), .i_d(TS_TR_Dst_Bp_int), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n)); 
  dfd_rv_dff #(.WIDTH(1)) TS_TR_Ntrace_Flush_ff (.o_q(TS_TR_Ntrace_Flush), .i_d(TS_TR_Ntrace_Flush_int), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n)); 
  dfd_rv_dff #(.WIDTH(1)) TS_TR_Dst_Flush_ff (.o_q(TS_TR_Dst_Flush), .i_d(TS_TR_Dst_Flush_int), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));  

  dfd_rv_dff_clr #(.WIDTH(1)) TrntrMemModeRamBackPressure_ff (
    .o_q          (TrntrMemModeRamBackPressure_ANY),
    .i_d          (1'b1),
    .i_clr        ($bits(trntrcoretoFlushThreshold_ANY)'(trntrNumFramesFilledInSRAM_ANY*InsnTrace_NumSetsPerFrame_ANY) <= (trntrcoretoFlushThreshold_ANY + (trntrcoretoFlushThreshold_ANY >> 1))),
    .i_en         (~TrntrMemModeRamFlush_ANY & $bits(trntrcoretoFlushThreshold_ANY)'(trntrNumFramesFilledInSRAM_ANY*InsnTrace_NumSetsPerFrame_ANY) > trntrcoretoFlushThreshold_ANY),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  dfd_rv_dff_clr #(.WIDTH(1)) TrdstMemModeRamBackPressure_ff (
    .o_q          (TrdstMemModeRamBackPressure_ANY),
    .i_d          (1'b1),
    .i_clr        ($bits(trdstcoretoFlushThreshold_ANY)'(trdstNumFramesFilledInSRAM_ANY*DataTrace_NumSetsPerFrame_ANY) <= (trdstcoretoFlushThreshold_ANY + (trdstcoretoFlushThreshold_ANY >> 1))),
    .i_en         (~TrdstMemModeRamFlush_ANY & $bits(trdstcoretoFlushThreshold_ANY)'(trdstNumFramesFilledInSRAM_ANY*DataTrace_NumSetsPerFrame_ANY) > trdstcoretoFlushThreshold_ANY),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  ); 

  // --------------------------------------------------------------------------
  // Debug Signal Trace SMEM Storage Buffer
  // --------------------------------------------------------------------------
  for (genvar i=0; i<TRC_RAM_INSTANCES; i++) begin
    dfd_rv_dff #(.WIDTH(1)) TrdstMemRdBufferVld_TS5_ff (
      .o_q          (TrdstMemRdBufferVld_TS5[i]),
      .i_d          (TrdstMemRdBufferVld_TS4[i]), 
      .i_en         (1'b1),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    dfd_rv_dff #(.WIDTH(1)) TrdstMemRdBufferVld_TS4_ff (
      .o_q          (TrdstMemRdBufferVld_TS4[i]),
      .i_d          (TrdstMemRdBufferVld_TS3[i]), 
      .i_en         (1'b1),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    dfd_rv_dff_clr #(.WIDTH(1)) TrdstMemRdBufferVld_ff (
      .o_q          (TrdstMemRdBufferVld_TS3[i]),
      .i_d          (TrdstMemAxiWrVld_ANY?1'b0:TrdstMemRamRdEn_TS2[i]), 
      .i_en         (TrdstMemRamRdEn_TS2[i] | TrdstMemAxiWrVld_ANY),
      .i_clr        (trdstRamEnableStart_ANY_d1),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    dfd_rv_dff #(.WIDTH(TRC_RAM_DATA_WIDTH)) TrdstMemRdBuffer_ff (
      .o_q          (TrdstMemRdBuffer_TS3[i]),
      .i_d          (TraceRamData_TS2[i]), 
      .i_en         (TrdstMemRamRdEn_TS2[i] | TrdstMemAxiWrVld_ANY),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    dfd_rv_dff #(.WIDTH(1)) TrdstMemRamRdEn_d1_ff (
      .o_q          (TrdstMemRamRdEn_TS2[i]),
      .i_d          (TrdstMemRamRdRdy_TS1 & TrdstMemRamRdEn_TS1[i]), 
      .i_en         (1'b1),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    assign TrdstMemRamRdEn_TS1_stg[i] = (TrdstMemRamRdRamEn_ANY & TrRamFreeWayMaskPend_ANY_stg[i/2] & ~TrdstRamPendPktInhibitRamRd_ANY_stg[i/2] & ~TrdstMemRamRdEn_TS2[i] & ~TrdstMemRdBufferVld_TS3[i] & ~TrdstMemRdBufferVld_TS4[i] & ~TrdstMemRdBufferVld_TS5[i])
                               & (&trdstMemRamRdEnFromCore_ANY) & (|trdstNumFramesFilledInSRAM_ANY_d1);

    dfd_rv_dff #(.WIDTH(1)) TrdstMemRamRdEn_TS1_ff (.o_q(TrdstMemRamRdEn_TS1[i]), .i_d(TrdstMemRamRdEn_TS1_stg[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  end

  dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH+1), .RESET_VALUE(0)) TrdstMemRamRdAddrFlop_ANY_ff (
        .o_q          (TrdstMemRamRdAddrFlop_ANY),
        .i_d          (trdstRamEnableStart_ANY_d1?trdstRamSMEMStartAddr_ANY:$bits(TrdstMemRamRdAddrFlop_ANY)'(TrdstMemRamRdAddrFlop_ANY + 1'b1)),
        .i_en         (trdstRamEnableStart_ANY_d1 | TrdstMemAxiWrVld_ANY),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
  );

      dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH)) TrdstMemRamRdAddr_TS1_ff (
      .o_q          (TrdstMemRamRdAddr_TS1),
      .i_d          (TrdstMemRamRdAddr_TS1_stg), 
      .i_en         (1'b1),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    ); 

  assign TrdstMemRamRdAddr_TS1_stg = TRC_RAM_INDEX_WIDTH'(((TrdstMemRamRdAddrFlop_ANY - trdstRamSMEMStartAddr_ANY) & (trdstRamSMEMTotalSets_ANY - 1'b1)) + trdstRamSMEMStartAddr_ANY); 
  assign TrdstMemRamRdAddrWrap_ANY = |((TrdstMemRamRdAddrFlop_ANY - trdstRamSMEMStartAddr_ANY) & trdstRamSMEMTotalSets_ANY);

  assign TrdstMemRdBufferFull_ANY = &TrdstMemRdBufferVld_TS3;
  assign TrdstMemAxiWrVld_ANY = TrMemAxiWrRdy_ANY & TrdstMemRdBufferFull_ANY & (TrntrMemRdBufferFull_ANY?(TrMemAxiWrVld_NtraceOrDst_ANY == 1'b0):1'b1);
  assign TrdstMemAxiWrData_ANY = TrdstMemRdBuffer_TS3;
  assign TrdstMemRamRdRamEn_ANY = trdstMemModeEnable_ANY;

  dfd_rv_dff #(.WIDTH(AXI_ADDR_WIDTH)) TrdstMemAxiWrAddr_ff (
    .o_q          (TrdstMemAxiWrAddr_ANY),
    .i_d          ((trdstRamEnableStart_ANY_d1 | ($bits(trdstMemSMEMLimitAddr_ANY)'(TrdstMemAxiWrAddr_ANY + 'h40) >= trdstMemSMEMLimitAddr_ANY))?trdstMemSMEMStartAddr_ANY:$bits(TrdstMemAxiWrAddr_ANY)'(TrdstMemAxiWrAddr_ANY + 'h40)),
    .i_en         (trdstRamEnableStart_ANY_d1 | (trdstMemModeEnable_ANY & TrdstMemAxiWrVld_ANY)),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  dfd_rv_dff #(.WIDTH(1)) TrdstMemAxiWrAddrWrap_ff (
    .o_q          (TrdstMemAxiWrAddrWrap_ANY),
    .i_d          (($bits(trdstMemSMEMLimitAddr_ANY)'(TrdstMemAxiWrAddr_ANY + 'h40) >= trdstMemSMEMLimitAddr_ANY)),
    .i_en         (trdstRamEnableStart_ANY_d1 | (trdstMemModeEnable_ANY & TrdstMemAxiWrVld_ANY)),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  // --------------------------------------------------------------------------
  // N-Trace SMEM Storage Buffer
  // --------------------------------------------------------------------------
  for (genvar i=0; i<TRC_RAM_INSTANCES; i++) begin
    dfd_rv_dff #(.WIDTH(1)) TrntrMemRdBufferVld_TS5_ff (
      .o_q          (TrntrMemRdBufferVld_TS5[i]),
      .i_d          (TrntrMemRdBufferVld_TS4[i]), 
      .i_en         (1'b1),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    dfd_rv_dff #(.WIDTH(1)) TrntrMemRdBufferVld_TS4_ff (
      .o_q          (TrntrMemRdBufferVld_TS4[i]),
      .i_d          (TrntrMemRdBufferVld_TS3[i]), 
      .i_en         (1'b1),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    dfd_rv_dff_clr #(.WIDTH(1)) TrntrMemRdBufferVld_ff (
      .o_q          (TrntrMemRdBufferVld_TS3[i]),
      .i_d          (TrntrMemAxiWrVld_ANY?1'b0:TrntrMemRamRdEn_TS2[i]), 
      .i_en         (TrntrMemRamRdEn_TS2[i] | TrntrMemAxiWrVld_ANY),
      .i_clr        (trntrRamEnableStart_ANY_d1),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    dfd_rv_dff #(.WIDTH(TRC_RAM_DATA_WIDTH)) TrntrMemRdBuffer_ff (
      .o_q          (TrntrMemRdBuffer_TS3[i]),
      .i_d          (TraceRamData_TS2[i]), 
      .i_en         (TrntrMemRamRdEn_TS2[i] | TrntrMemAxiWrVld_ANY),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    dfd_rv_dff #(.WIDTH(1)) TrntrMemRamRdEn_d1_ff (
      .o_q          (TrntrMemRamRdEn_TS2[i]),
      .i_d          (TrntrMemRamRdRdy_TS1 & TrntrMemRamRdEn_TS1[i]), 
      .i_en         (1'b1),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

    assign TrntrMemRamRdEn_TS1_stg[i] = (TrntrMemRamRdRamEn_ANY & TrRamFreeWayMaskPend_ANY_stg[i/2] & ~TrntrRamPendPktInhibitRamRd_ANY_stg[i/2] & ~TrntrMemRamRdEn_TS2[i] & ~TrntrMemRdBufferVld_TS3[i] & ~TrntrMemRdBufferVld_TS4[i] & ~TrntrMemRdBufferVld_TS5[i])
                               & (&trntrMemRamRdEnFromCore_ANY) & (|trntrNumFramesFilledInSRAM_ANY_d1);

    dfd_rv_dff #(.WIDTH(1)) TrntrMemRamRdEn_TS1_ff (.o_q(TrntrMemRamRdEn_TS1[i]), .i_d(TrntrMemRamRdEn_TS1_stg[i]), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n)); 
  end

  dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH+1), .RESET_VALUE(0)) TrntrMemRamRdAddrFlop_ANY_ff (
        .o_q          (TrntrMemRamRdAddrFlop_ANY),
        .i_d          (trntrRamEnableStart_ANY_d1?trntrRamSMEMStartAddr_ANY:$bits(TrntrMemRamRdAddrFlop_ANY)'(TrntrMemRamRdAddrFlop_ANY + 1'b1)),
        .i_en         (trntrRamEnableStart_ANY_d1 | TrntrMemAxiWrVld_ANY),
        .i_clk        (clk),
        .i_reset_n    (reset_n)
  ); 

  dfd_rv_dff #(.WIDTH(TRC_RAM_INDEX_WIDTH)) TrntrMemRamRdAddr_TS1_ff (
      .o_q          (TrntrMemRamRdAddr_TS1),
      .i_d          (TrntrMemRamRdAddr_TS1_stg), 
      .i_en         (1'b1),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    ); 

  assign TrntrMemRamRdAddr_TS1_stg = TRC_RAM_INDEX_WIDTH'(((TrntrMemRamRdAddrFlop_ANY - trntrRamSMEMStartAddr_ANY) & (trntrRamSMEMTotalSets_ANY - 1'b1)) + trntrRamSMEMStartAddr_ANY); 
  assign TrntrMemRamRdAddrWrap_ANY = |((TrntrMemRamRdAddrFlop_ANY - trntrRamSMEMStartAddr_ANY) & trntrRamSMEMTotalSets_ANY);

  assign TrntrMemRdBufferFull_ANY = &TrntrMemRdBufferVld_TS3;
  assign TrntrMemAxiWrVld_ANY = TrMemAxiWrRdy_ANY & TrntrMemRdBufferFull_ANY & (TrdstMemRdBufferFull_ANY?(TrMemAxiWrVld_NtraceOrDst_ANY == 1'b1):1'b1); 
  assign TrntrMemAxiWrData_ANY = TrntrMemRdBuffer_TS3;
  assign TrntrMemRamRdRamEn_ANY = trntrMemModeEnable_ANY;

  dfd_rv_dff #(.WIDTH(AXI_ADDR_WIDTH)) TrntrMemAxiWrAddr_ff (
    .o_q          (TrntrMemAxiWrAddr_ANY),
    .i_d          ((trntrRamEnableStart_ANY_d1 | ($bits(trntrMemSMEMLimitAddr_ANY)' (TrntrMemAxiWrAddr_ANY + 'h40) >= trntrMemSMEMLimitAddr_ANY))?trntrMemSMEMStartAddr_ANY:$bits(TrntrMemAxiWrAddr_ANY)'(TrntrMemAxiWrAddr_ANY + 'h40)),
    .i_en         (trntrRamEnableStart_ANY_d1 | (trntrMemModeEnable_ANY & TrntrMemAxiWrVld_ANY)),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  dfd_rv_dff #(.WIDTH(1)) TrntrMemAxiWrAddrWrap_ff (
    .o_q          (TrntrMemAxiWrAddrWrap_ANY),
    .i_d          (($bits(trntrMemSMEMLimitAddr_ANY)'(TrntrMemAxiWrAddr_ANY + 'h40) >= trntrMemSMEMLimitAddr_ANY)),
    .i_en         (trntrRamEnableStart_ANY_d1 | (trntrMemModeEnable_ANY & TrntrMemAxiWrVld_ANY)),
    .i_clk        (clk),
    .i_reset_n    (reset_n)
  );

  // --------------------------------------------------------------------------
  // N-Trace and DST SMEM Reads/Writes Interleave
  // --------------------------------------------------------------------------
  dfd_rv_dff #(.WIDTH(1)) TrMemRamRd_NtraceOrDst_ANY_ff (.o_q(TrMemRamRd_NtraceOrDst_ANY), .i_d(~TrMemRamRd_NtraceOrDst_ANY), .i_en(TrMemAxiWrRdy_ANY & (|TrntrMemRamRdEn_TS1 & |TrdstMemRamRdEn_TS1)), .i_clk(clk), .i_reset_n(reset_n)); 
  
  assign TrdstMemRamRdRdy_TS1 = |TrdstMemRamRdEn_TS1 & (|TrntrMemRamRdEn_TS1?(TrMemRamRd_NtraceOrDst_ANY == 1'b0):1'b1);
  assign TrntrMemRamRdRdy_TS1 = |TrntrMemRamRdEn_TS1 & (|TrdstMemRamRdEn_TS1?(TrMemRamRd_NtraceOrDst_ANY == 1'b1):1'b1); 

  assign TraceMemRdEn_ANY = TrdstMemRamRdRdy_TS1 | TrntrMemRamRdRdy_TS1;
  assign TraceMemRdAddr_TS1 = TrntrMemRamRdRdy_TS1?TrntrMemRamRdAddr_TS1:TrdstMemRamRdAddr_TS1;
  assign TraceMemPerWayRdEn_TS1 = TrntrMemRamRdRdy_TS1?TrntrMemRamRdEn_TS1:TrdstMemRamRdEn_TS1;

  dfd_rv_dff #(.WIDTH(1)) TrMemAxiWrVld_NtraceOrDst_ANY_ff (.o_q(TrMemAxiWrVld_NtraceOrDst_ANY), .i_d(~TrMemAxiWrVld_NtraceOrDst_ANY), .i_en(TrMemAxiWrRdy_ANY & (TrntrMemRdBufferFull_ANY & TrdstMemRdBufferFull_ANY)), .i_clk(clk), .i_reset_n(reset_n));

  assign TrMemAxiWrVld_ANY = TrntrMemAxiWrVld_ANY | TrdstMemAxiWrVld_ANY;
  assign TrMemAxiWrAddr_ANY = TrntrMemAxiWrVld_ANY?TrntrMemAxiWrAddr_ANY:TrdstMemAxiWrAddr_ANY;
  assign TrMemAxiWrData_ANY = TrntrMemAxiWrVld_ANY?TrntrMemAxiWrData_ANY:TrdstMemAxiWrData_ANY;

  // --------------------------------------------------------------------------
  // Trace RAM Control Interface MMRs
  // --------------------------------------------------------------------------
  // N-Trace
  assign trntrRamActive_ANY = TrCsrTrramcontrol.Trramactive;
  assign trntrRamEnable_ANY = TrCsrTrramcontrol.Trramenable;
  assign trntrRamActiveEnable_ANY = TrCsrTrramcontrol.Trramactive & trntrRamEnable_ANY;
  assign trntrRamMode_ANY_stg = TrCsrTrramcontrol.Trrammode;
  assign trntrStoponWrap_ANY = TrCsrTrramcontrol.Trramstoponwrap;
  assign trntrMemModeEnable_ANY = trntrRamMode_ANY;

  dfd_rv_dff #(.WIDTH(1)) trntrRamMode_ANY_ff (.o_q(trntrRamMode_ANY), .i_d(trntrRamMode_ANY_stg), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n)); 

  assign trntrRamEnableStart_ANY = trntrRamActiveEnable_ANY & ~trntrRamActiveEnable_ANY_d1;
  assign trntrRamEnableStop_ANY = ~trntrRamActiveEnable_ANY & trntrRamActiveEnable_ANY_d1;

  dfd_rv_dff #(.WIDTH(1)) trRamEnable_ANY_d1_ff (.o_q(trntrRamActiveEnable_ANY_d1), .i_d(trntrRamActiveEnable_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trntrRamEnableStart_ANY_d1_ff (.o_q(trntrRamEnableStart_ANY_d1), .i_d(trntrRamEnableStart_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  // DST
  assign trdstRamActive_ANY = TrCsrTrdstramcontrol.Trdstramactive;
  assign trdstRamEnable_ANY = TrCsrTrdstramcontrol.Trdstramenable;
  assign trdstRamActiveEnable_ANY = TrCsrTrdstramcontrol.Trdstramactive & trdstRamEnable_ANY;
  assign trdstRamMode_ANY_stg = TrCsrTrdstramcontrol.Trdstrammode;
  assign trdstStoponWrap_ANY = TrCsrTrdstramcontrol.Trdstramstoponwrap; 
  assign trdstMemModeEnable_ANY = trdstRamMode_ANY; 

  dfd_rv_dff #(.WIDTH(1)) trdstRamMode_ANY_ff (.o_q(trdstRamMode_ANY), .i_d(trdstRamMode_ANY_stg), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  assign trdstRamEnableStart_ANY = trdstRamActiveEnable_ANY & ~trdstRamActiveEnable_ANY_d1;
  assign trdstRamEnableStop_ANY = ~trdstRamActiveEnable_ANY & trdstRamActiveEnable_ANY_d1;

  dfd_rv_dff #(.WIDTH(1)) trdstRamActiveEnable_ANY_d1_ff (.o_q(trdstRamActiveEnable_ANY_d1), .i_d(trdstRamActiveEnable_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) trdstRamEnableStart_ANY_d1_ff (.o_q(trdstRamEnableStart_ANY_d1), .i_d(trdstRamEnableStart_ANY), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  // ----------------------------------------------------------------------------------------------
  // Trace RAM Pointer MMRs
  // ----------------------------------------------------------------------------------------------
  // N-trace
  assign trntrRamStartLow_ANY = TrCsrTrramstartlow.Trramstartlow;
  assign trntrRamStartHigh_ANY = TrCsrTrramstarthigh.Trramstarthigh;
  assign trntrRamLimitLow_ANY = TrCsrTrramlimitlow.Trramlimitlow;
  assign trntrRamLimitHigh_ANY = TrCsrTrramlimithigh.Trramlimithigh;
  assign trntrRamWpLow_ANY = TrCsrTrramwplow.Trramwplow;
  assign trntrRamWpHigh_ANY = TrCsrTrramwphigh.Trramwphigh;
  assign trntrRamRpLow_ANY = TrCsrTrramrplow.Trramrplow;

  assign trntrMemSMEMStartAddr_ANY = {trntrRamStartHigh_ANY[AXI_ADDR_WIDTH-33:0], trntrRamStartLow_ANY, 2'b00};
  assign trntrMemSMEMLimitAddr_ANY = {trntrRamLimitHigh_ANY[AXI_ADDR_WIDTH-33:0], trntrRamLimitLow_ANY, 2'b00};

  // Ram Control
  always_comb begin
    TrCsrTrramcontrolWr = '0;
    TrCsrTrramcontrolWr.TrramemptyWrEn = 1'b1;
    TrCsrTrramcontrolWr.Data.Trramempty = /*~|TrRamPendPktVld_ANY*/ ~|TrRamPendNtracePktVld_ANY & TrntrFlushTimeoutDone_ANY & (~trntrRamMode_ANY | (trntrRamMode_ANY & ~|trntrNumFramesFilledInSRAM_ANY));
    TrCsrTrramcontrolWr.TrramenableWrEn = trntrRamEnable_ANY & trntrStoponWrap_ANY; 
    TrCsrTrramcontrolWr.Data.Trramenable = ~(TS_TR_Ntrace_Bp_int & TS_TR_Ntrace_Flush_int);
  end

  assign TrntrFlushTimeoutCntrClr_ANY = (TrntrFlushTimeoutCntr_ANY == TR_SINK_FLUSH_TIMEOUT);

  dfd_rv_dff_clr #(.WIDTH(1), .RESET_VALUE(0)) TrntrFlushTimeoutStart_ANY_ff (
      .o_q          (TrntrFlushTimeoutStart_ANY),
      .i_d          (1'b1), 
      .i_en         (~trntrRamActiveEnable_ANY & trntrRamActiveEnable_ANY_d1),
      .i_clr        (trntrRamEnableStart_ANY),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

  dfd_rv_dff_clr #(.WIDTH(16), .RESET_VALUE(0)) TrntrFlushTimeoutCntr_ANY_ff (
      .o_q          (TrntrFlushTimeoutCntr_ANY),
      .i_d          ($bits(TrntrFlushTimeoutCntr_ANY)'(TrntrFlushTimeoutCntr_ANY + 1'b1)), 
      .i_en         (TrntrFlushTimeoutStart_ANY & ~TrntrFlushTimeoutDone_ANY),
      .i_clr        (TrntrFlushTimeoutCntrClr_ANY),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

  dfd_rv_dff_clr #(.WIDTH(1), .RESET_VALUE(1)) TrntrFlushTimeoutDone_ANY_ff (
      .o_q          (TrntrFlushTimeoutDone_ANY),
      .i_d          (1'b1), 
      .i_en         (TrntrFlushTimeoutCntrClr_ANY),
      .i_clr        (trntrRamEnableStart_ANY),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

  // Ram Write Pointer Low
  assign trntrramwplowSRAMWrdata = /*((trntrlocalRamWpLow_ANY == trntrRamLimitLow_ANY) & ~trntrStoponWrap_ANY)?trntrRamStartLow_ANY:*/(trntrlocalRamWpLow_ANY);
  assign trntrramwplowSMEMWrdata = TrntrMemAxiWrAddr_ANY[31:2];
  always_comb begin
    TrCsrTrramwplowWr = '0;
    TrCsrTrramwphighWr = '0;
    TrCsrTrramwplowWr.TrramwplowWrEn = trntrRamActive_ANY & ((~trntrRamMode_ANY & trntrRamWrEn_TS0 /*TraceRamWrEn_TS0*/) | (trntrRamMode_ANY & TrntrMemAxiWrVld_ANY));
    TrCsrTrramwplowWr.Data.Trramwplow  = ~trntrRamMode_ANY?trntrramwplowSRAMWrdata:trntrramwplowSMEMWrdata;
    TrCsrTrramwplowWr.TrramwrapWrEn = (trntrRamEnable_ANY | trntrStoponWrap_ANY) & ~TrCsrTrramwplow.Trramwrap & ((~trntrRamMode_ANY & trntrRamWrEn_TS0 /*TraceRamWrEn_TS0*/) | (trntrRamMode_ANY & TrntrMemAxiWrVld_ANY));
    TrCsrTrramwplowWr.Data.Trramwrap = ((~trntrRamMode_ANY & trntrnextlocaltoupdateRamWpWrap_ANY_stg_d1) | (trntrRamMode_ANY & TrntrMemAxiWrAddrWrap_ANY/*((TrntrMemAxiWrAddr_ANY + 'h40) >= trntrMemSMEMLimitAddr_ANY)*/));
    TrCsrTrramwphighWr.TrramwphighWrEn = (trntrRamMode_ANY & TrntrMemAxiWrVld_ANY);
    TrCsrTrramwphighWr.Data.Trramwphigh = $bits(TrCsrTrramwphighWr.Data.Trramwphigh)'(TrntrMemAxiWrAddr_ANY[AXI_ADDR_WIDTH-1:32]);
  end

  // Ram Read Pointer Low
  always_comb begin
    TrCsrTrramrplowWr = '0;
    TrCsrTrramrplowWr.TrramrplowWrEn = InsnTraceRdEn_TS2;
    TrCsrTrramrplowWr.Data.Trramrplow  = trntrRamRpLow_ANY[31:2] + 30'h1;
  end
  assign TrCsrTrramrphighWr = '0;

  // Ram Read Data
  always_comb begin
    TraceRamData64b_TS2 = '0;
    for (int i=0; i<TRC_RAM_INSTANCES; i++) begin
      TraceRamData64b_TS2 = TraceRamData64b_TS2 | ({64{TraceRdEn_TS2[i]}} & TraceRamData_TS2[i]);
    end
  end

  always_comb begin
    TrCsrTrramdataWr = '0;
    TrCsrTrramdataWr.TrramdataWrEn = InsnTraceRdEn_TS2;
    TrCsrTrramdataWr.Data.Trramdata = trntrRamRpLow_ANY[2] ? TraceRamData64b_TS2[63:32] :
                                                          TraceRamData64b_TS2[31:0];
  end

  // DST
  assign trdstRamStartLow_ANY = TrCsrTrdstramstartlow.Trdstramstartlow;
  assign trdstRamStartHigh_ANY = TrCsrTrdstramstarthigh.Trdstramstarthigh;
  assign trdstRamLimitLow_ANY = TrCsrTrdstramlimitlow.Trdstramlimitlow;
  assign trdstRamLimitHigh_ANY = TrCsrTrdstramlimithigh.Trdstramlimithigh;
  assign trdstRamWpLow_ANY = TrCsrTrdstramwplow.Trdstramwplow;
  assign trdstRamWpHigh_ANY = TrCsrTrdstramwphigh.Trdstramwphigh;
  assign trdstRamRpLow_ANY = TrCsrTrdstramrplow.Trdstramrplow;

  assign trdstMemSMEMStartAddr_ANY = {trdstRamStartHigh_ANY[AXI_ADDR_WIDTH-33:0], trdstRamStartLow_ANY, 2'b00};
  assign trdstMemSMEMLimitAddr_ANY = {trdstRamLimitHigh_ANY[AXI_ADDR_WIDTH-33:0], trdstRamLimitLow_ANY, 2'b00}; 

  // Ram Control
  always_comb begin
    TrCsrTrdstramcontrolWr = '0;
    TrCsrTrdstramcontrolWr.TrdstramemptyWrEn = 1'b1;
    TrCsrTrdstramcontrolWr.Data.Trdstramempty = /*~|TrRamPendPktVld_ANY*/ ~|TrRamPendDstPktVld_ANY & TrdstFlushTimeoutDone_ANY & (~trdstRamMode_ANY | (trdstRamMode_ANY & ~|trdstNumFramesFilledInSRAM_ANY));
    TrCsrTrdstramcontrolWr.TrdstramenableWrEn = trdstRamEnable_ANY & trdstStoponWrap_ANY; 
    TrCsrTrdstramcontrolWr.Data.Trdstramenable = ~(TS_TR_Dst_Bp_int & TS_TR_Dst_Flush_int);
  end

  assign TrdstFlushTimeoutCntrClr_ANY = (TrdstFlushTimeoutCntr_ANY == TR_SINK_FLUSH_TIMEOUT);

  dfd_rv_dff_clr #(.WIDTH(1), .RESET_VALUE(0)) TrdstFlushTimeoutStart_ANY_ff (
      .o_q          (TrdstFlushTimeoutStart_ANY),
      .i_d          (1'b1), 
      .i_en         (~trdstRamActiveEnable_ANY & trdstRamActiveEnable_ANY_d1),
      .i_clr        (trdstRamEnableStart_ANY),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

  dfd_rv_dff_clr #(.WIDTH(16), .RESET_VALUE(0)) TrdstFlushTimeoutCntr_ANY_ff (
      .o_q          (TrdstFlushTimeoutCntr_ANY),
      .i_d          ($bits(TrdstFlushTimeoutCntr_ANY)'(TrdstFlushTimeoutCntr_ANY + 1'b1)), 
      .i_en         (TrdstFlushTimeoutStart_ANY & ~TrdstFlushTimeoutDone_ANY),
      .i_clr        (TrdstFlushTimeoutCntrClr_ANY),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

  dfd_rv_dff_clr #(.WIDTH(1), .RESET_VALUE(1)) TrdstFlushTimeoutDone_ANY_ff (
      .o_q          (TrdstFlushTimeoutDone_ANY),
      .i_d          (1'b1), 
      .i_en         (TrdstFlushTimeoutCntrClr_ANY),
      .i_clr        (trdstRamEnableStart_ANY),
      .i_clk        (clk),
      .i_reset_n    (reset_n)
    );

  // Ram Write Pointer Low
  assign trdstramwplowSRAMWrdata = /*((trdstlocalRamWpLow_ANY == trdstRamLimitLow_ANY) & ~trdstStoponWrap_ANY)?trdstRamStartLow_ANY:*/(trdstlocalRamWpLow_ANY);
  assign trdstramwplowSMEMWrdata = TrdstMemAxiWrAddr_ANY[31:2];
  always_comb begin
    TrCsrTrdstramwplowWr = '0;
    TrCsrTrdstramwphighWr = '0;
    TrCsrTrdstramwplowWr.TrdstramwplowWrEn = trdstRamActive_ANY & ((~trdstRamMode_ANY & trdstRamWrEn_TS0 /*TraceRamWrEn_TS0*/) | (trdstRamMode_ANY & TrdstMemAxiWrVld_ANY));
    TrCsrTrdstramwplowWr.Data.Trdstramwplow  = ~trdstRamMode_ANY?trdstramwplowSRAMWrdata:trdstramwplowSMEMWrdata;
    TrCsrTrdstramwplowWr.TrdstramwrapWrEn = (trdstRamEnable_ANY | trdstStoponWrap_ANY) & ~TrCsrTrdstramwplow.Trdstramwrap & ((~trdstRamMode_ANY & trdstRamWrEn_TS0 /*TraceRamWrEn_TS0*/) | (trdstRamMode_ANY & TrdstMemAxiWrVld_ANY));
    TrCsrTrdstramwplowWr.Data.Trdstramwrap = ((~trdstRamMode_ANY & trdstnextlocaltoupdateRamWpWrap_ANY_stg_d1) | (trdstRamMode_ANY & TrdstMemAxiWrAddrWrap_ANY/*((TrdstMemAxiWrAddr_ANY + 'h40) >= trdstMemSMEMLimitAddr_ANY)*/));
    TrCsrTrdstramwphighWr.TrdstramwphighWrEn = (trdstRamMode_ANY & TrdstMemAxiWrVld_ANY);
    TrCsrTrdstramwphighWr.Data.Trdstramwphigh = $bits(TrCsrTrdstramwphighWr.Data.Trdstramwphigh)'(TrdstMemAxiWrAddr_ANY[AXI_ADDR_WIDTH-1:32]);
  end

  // Ram Read Pointer Low
  always_comb begin
    TrCsrTrdstramrplowWr = '0;
    TrCsrTrdstramrplowWr.TrdstramrplowWrEn = DataTraceRdEn_TS2;
    TrCsrTrdstramrplowWr.Data.Trdstramrplow  = trdstRamRpLow_ANY[31:2] + 30'h1;
  end
  assign TrCsrTrdstramrphighWr = '0;

  always_comb begin
    TrCsrTrdstramdataWr = '0;
    TrCsrTrdstramdataWr.TrdstramdataWrEn = DataTraceRdEn_TS2;
    TrCsrTrdstramdataWr.Data.Trdstramdata = trdstRamRpLow_ANY[2] ? TraceRamData64b_TS2[63:32] :
                                                                   TraceRamData64b_TS2[31:0];
  end
  
  // --------------------------------------------------------------------------
  // Assertion Checks
  // --------------------------------------------------------------------------
  `ifdef ASSERTION_ENABLE
    /* verilator lint_off SYNCASYNCNET */
    for (genvar i=0; i<TRC_RAM_INSTANCES; i++) begin
      `RV_ASSERT(ERR_TRACE_RAM_RD_WR_COLLISION, clk, reset_n, 1'b1, ((TraceWrEn_TS0[i/2] & TraceRdEn_TS1[i]) == 1'b0) , "Trace SRAM read and write collision detected")
    end

    for (genvar i=0; i<NUM_CORES; i++) begin
      `RV_ASSERT(TRNTRRAMCOREWPLOW_LIMIT_CHECK, clk, reset_n, (trntrRamActive_ANY & trntrcoreNewFrameStart_ANY[i]) , ~trntrRamMode_ANY?(trntrcoreRamWpLow_ANY[i] <= trntrRamLimitLow_ANY):(trntrcoreRamWpLow_ANY[i] <= trntrRamSMEMLimitLow_ANY) , "Ntrace RAM write pointer is greater than limit")
      `RV_ASSERT(TRDSTRAMCOREWPLOW_LIMIT_CHECK, clk, reset_n, (trdstRamActive_ANY & trdstcoreNewFrameStart_ANY[i]) , ~trdstRamMode_ANY?(trdstcoreRamWpLow_ANY[i] <= trdstRamLimitLow_ANY):(trdstcoreRamWpLow_ANY[i] <= trdstRamSMEMLimitLow_ANY) , "DST RAM write pointer is greater than limit")
    end
    // `RV_ASSERT(TRRAMWPWRAP_IN_STOPONWRAP_CHECK, clk, reset_n, 1'b1, (trntrStoponWrap_ANY && $rose(TrCsrTrramwplow.Trramwrap) |-> (trntrRamWpLow_ANY == trntrRamStartLow_ANY)), "NTrace RAM wrap is set in stop_on_wrap mode when RAM write pointer != RAM start pointer")
    // `RV_ASSERT(TRDSTRAMWPWRAP_IN_STOPONWRAP_CHECK, clk, reset_n, 1'b1, (trdstStoponWrap_ANY && $rose(TrCsrTrdstramwplow.Trdstramwrap) |-> (trdstRamWpLow_ANY == trdstRamStartLow_ANY)), "DST RAM wrap is set in stop_on_wrap mode when RAM write pointer != RAM start pointer")
    
    /* verilator lint_on SYNCASYNCNET */
  `endif  

endmodule
 


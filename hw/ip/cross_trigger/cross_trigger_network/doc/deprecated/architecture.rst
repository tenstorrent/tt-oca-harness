============
Architecture
============

Block Diagram
=============

The Cross Trigger Network consists of the following major blocks::

    +------------------------------------------------------------------+
    |                    Cross Trigger Network (CTN)                   |
    +------------------------------------------------------------------+
    |                                                                  |
    |  +------------------+    +------------------+                    |
    |  |  AXI-Lite Xbar   |    |   Clock Stop     |                    |
    |  |                  |    |     Control      |                    |
    |  +--------+---------+    +--------+---------+                    |
    |           |                       |                              |
    |           v                       v                              |
    |  +--------+---------+    +--------+---------+                    |
    |  | CTP[0] | CTP[1]  |    | clk_stop_req[n]  |----> stop_clks_o   |
    |  |  ...   | CTP[N]  |    +------------------+                    |
    |  +--------+---------+                                            |
    |           |                                                      |
    |           v                                                      |
    |  +------------------+    +------------------+                    |
    |  | Internal CTP[0]  |    | Cross Trigger    |                    |
    |  | Internal CTP[M]  |--->|     Matrix       |                    |
    |  +------------------+    +------------------+                    |
    |                                                                  |
    +------------------------------------------------------------------+

Signal Flow
===========

External Cross Trigger Flow
---------------------------

1. **Outgoing Trigger**: CTM ct_src → CTP ct_src_i → GPIO pads
2. **Incoming Trigger**: GPIO pads → CTP ct_dst_o → CTM ct_dst_i

Internal Cross Trigger Flow
---------------------------

1. **To Internal Sink**: CTM ct_src → Internal CTP → ctm_src_req_o
2. **From Internal Source**: ctm_dst_req_i → Internal CTP → CTM ct_dst

Component Details
=================

AXI-Lite Crossbar
-----------------

The AXI-Lite crossbar routes CSR transactions to the appropriate subordinate:

* **Slave Port**: Single port connected to DTP's AXI-Lite interface
* **Master Ports**: 1 port for CTM (index 0) + NUM_CTP ports for external CTPs (indices 1+)
* **Address Decoding**: CTM at 0x0000-0x01FF (512 bytes), CTPs at 0x0200 + (index × 0x10) (16 bytes each)

Configuration::

    NoSlvPorts:     1
    NoMstPorts:     NUM_CTP + 1
    MaxMstTrans:    1
    MaxSlvTrans:    1
    FallThrough:    0
    LatencyMode:    NO_LATENCY

External Cross Trigger Ports
----------------------------

Each external CTP is a full ``cross_trigger_port`` module with:

* AXI-Lite CSR interface for runtime configuration
* Wire-OR and Point-to-Point mode support
* Four GPIO pad interfaces (CT_Req_out, CT_Req_in, CT_Ack_in, CT_Ack_out)
* Pulse stretching and signal inversion capabilities

Internal Cross Trigger Ports
----------------------------

Internal CTPs use the ``cross_trigger_port_core`` module without CSRs:

* Static configuration via synthesis parameters
* Mode determined by INT_CT_MODE parameter bit (0 = Wire-OR, 1 = P2P)
* GPIO interface repurposed for internal signal connections
* Minimal resource usage

The internal CTP signal routing is mode-dependent:

**Wire-OR Mode (INT_CT_MODE[n] = 0)**::

    Output: ct_req_out_dout_en → ctm_src_req_o (stretched pulse to CLA)
    Input:  ct_req_out_din     ← ctm_dst_req_i (stretched pulse from CLA)
    Note: dout is static; dout_en indicates active pulse

**Point-to-Point Mode (INT_CT_MODE[n] = 1)**::

    Output: ct_req_out_dout → ctm_src_req_o (handshake request to CLA)
    Input:  ct_req_in_din   ← ctm_dst_req_i (handshake request from CLA)
    Input:  ct_ack_in_din   ← ctm_src_ack_i (handshake ack from CLA)
    Output: ct_ack_out_dout → ctm_dst_ack_o (handshake ack to CLA)

Cross Trigger Matrix
--------------------

The CTM routes cross trigger signals between all CTPs:

* **Inputs (ct_dst_i)**: NUM_CTP + NUM_INT_CT destination signals
* **Outputs (ct_src_o)**: NUM_CTP + NUM_INT_CT source signals
* **Routing**: Configurable via CSR registers (OR mask per output)

Clock Stop Control
------------------

The clock stop control module aggregates multiple clock stop requests:

* OR-tree reduction of NUM_CLK_STOP_REQ inputs
* Gated by cla_clock_stop_en from JTAG interface
* OR'd with jtag_clock_stop for direct JTAG control
* Registered output to prevent glitches

Logic::

    cla_clock_stop = cla_clock_stop_en & (|clk_stop_req)
    stop_clks = reg(jtag_clock_stop | cla_clock_stop)

Port Indexing
=============

CTM ports are indexed as follows:

+---------------+---------------------------+
| Port Index    | Description               |
+===============+===========================+
| 0 to N-1      | External CTPs (NUM_CTP)   |
+---------------+---------------------------+
| N to N+M-1    | Internal CTPs (NUM_INT_CT)|
+---------------+---------------------------+

Where N = NUM_CTP and M = NUM_INT_CT.

This indexing is used for:

* CTM ct_dst_i and ct_src_o port assignment
* CTM routing configuration registers

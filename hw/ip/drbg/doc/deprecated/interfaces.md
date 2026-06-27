# DRBG Wrapper Interfaces

## Top-Level Clocks and Reset

The DRBG wrapper operates entirely in one clock and reset domain.

| Signal | Direction | Description |
|---|---|---|
| `clk_i` | input | Primary wrapper clock |
| `rst_ni` | input | Active-low reset; may assert asynchronously and must deassert synchronously to `clk_i` |

The wrapper adds no internal CDC logic. Any clock-domain crossing must be
handled outside the wrapper.

## Parameters

| Parameter | Type | Default | Description |
|---|---|---:|---|
| `INGRESS_FIFO_DEPTH` | `int unsigned` | `12` | Shared depth for the distribution FIFO and CSRNG-word FIFO |
| `SEED_FIFO_DEPTH` | `int unsigned` | `1` | Number of complete 384-bit seeds buffered for CSRNG |
| `EDN_ENDPOINT_COUNT` | `int unsigned` | `1` | Number of exposed EDN endpoint streams |
| `ENDPOINT_FIFO_DEPTH` | `int unsigned` | `8` | FIFO depth for each endpoint AXI-Stream output |
| `csrng_axil_req_t` | `type` | `drbg_axil64_req_t` | External CSRNG AXI-Lite request type |
| `csrng_axil_rsp_t` | `type` | `drbg_axil64_resp_t` | External CSRNG AXI-Lite response type |
| `edn_axil_req_t` | `type` | `drbg_axil64_req_t` | External EDN AXI-Lite request type |
| `edn_axil_rsp_t` | `type` | `drbg_axil64_resp_t` | External EDN AXI-Lite response type |

## Package Dependencies

The wrapper depends on the following package families:

| Package | Purpose |
|---|---|
| `drbg_pkg` | Wrapper-local parameters and AXI-Lite / AXI-Stream typedefs |
| `csrng_pkg`, `csrng_reg_pkg` | CSRNG request/response types and register constants |
| `edn_pkg`, `edn_reg_pkg` | EDN endpoint request/response types and register constants |
| `entropy_src_pkg` | CSRNG entropy request/response interface |
| `tlul_pkg` | Internal CSR bridge target bus |
| `lc_ctrl_pkg` | Lifecycle sideband control input |
| `prim_mubi_pkg` | MuBi sideband control input |
| `prim_alert_pkg` | Alert request/response signaling |

## Entropy Ingress

The entropy ingress is a producer-driven word stream with no backpressure.

| Signal | Direction | Width | Description |
|---|---|---:|---|
| `entropy_stream_data_i` | input | 32 | Entropy word sampled when `entropy_stream_vld_i` is high |
| `entropy_stream_vld_i` | input | 1 | One-cycle push pulse for `entropy_stream_data_i` |

Behavioral contract:

- `entropy_stream_vld_i` is a pulse, not a ready/valid handshake.
- The wrapper samples `entropy_stream_data_i` only in cycles where
  `entropy_stream_vld_i` is asserted.
- There is no ingress ready signal back to the producer.

## Entropy Distribution AXI-Stream

Accepted entropy words can be observed on an AXI-Stream output.

| Signal | Direction | Width | Description |
|---|---|---:|---|
| `entropy_axis_o.tvalid` | output | 1 | Output word valid |
| `entropy_axis_o.tdata` | output | 32 | Output entropy word |
| `entropy_axis_o.tstrb` | output | 4 | Always `4'hF` for valid transfers |
| `entropy_axis_i.tready` | input | 1 | Downstream backpressure |

Behavioral contract:

- The wrapper produces full 32-bit beats only.
- `tstrb` is valid only when `tvalid` is high and is always `4'hF`.
- Downstream backpressure is supported through `tready`.

## EDN Endpoint AXI-Stream Outputs

Each wrapped EDN endpoint is converted into one external AXI-Stream channel.

| Signal | Direction | Width | Description |
|---|---|---:|---|
| `edn_axis_o[n].tvalid` | output | 1 | Endpoint `n` output valid |
| `edn_axis_o[n].tdata` | output | 32 | Endpoint `n` output word |
| `edn_axis_o[n].tstrb` | output | 4 | Always `4'hF` for valid transfers |
| `edn_axis_i[n].tready` | input | 1 | Endpoint `n` backpressure |

Behavioral contract:

- Each endpoint is buffered independently.
- Backpressure on one endpoint does not block another endpoint unless the shared
  wrapped EDN logic itself stops issuing requests.
- The current wrapper contract does not expose EDN FIPS metadata on the
  external stream.

## CSRNG and EDN Control-Plane AXI-Lite Ports

The wrapper preserves separate control ports for CSRNG and EDN.

| Interface | Direction | Description |
|---|---|---|
| `csrng_axil_req_i`, `csrng_axil_rsp_o` | input/output | External CSRNG AXI-Lite slave port |
| `edn_axil_req_i`, `edn_axil_rsp_o` | input/output | External EDN AXI-Lite slave port |

The external ports are 64-bit AXI-Lite surfaces that are converted internally
to 32-bit AXI-Lite and then to TL-UL for the wrapped IP.

### Supported accesses

- aligned 32-bit lower-lane accesses,
- aligned 32-bit upper-lane accesses,
- accesses that target exactly one wrapped 32-bit CSR lane.

### Unsupported accesses

- unaligned reads or writes,
- writes that drive both lanes at once,
- transfers that span multiple wrapped 32-bit CSRs.

Unsupported accesses return AXI `SLVERR` and do not emit a TL-UL request toward
the wrapped CSRNG or EDN instance.

## Sideband Inputs

The wrapper forwards the CSRNG sideband controls directly to the wrapped CSRNG
instance.

| Signal | Direction | Type | Description |
|---|---|---|---|
| `otp_en_csrng_sw_app_read_i` | input | `prim_mubi_pkg::mubi8_t` | OTP-controlled gate for software CSRNG state/genbits visibility |
| `lc_hw_debug_en_i` | input | `lc_ctrl_pkg::lc_tx_t` | Lifecycle-controlled seed diversification selector |

## Alerts

The wrapper does not reinterpret alert behavior. It forwards the wrapped alert
ports directly.

| Signal | Direction | Description |
|---|---|---|
| `csrng_alert_rx_i`, `csrng_alert_tx_o` | input/output | CSRNG alert channels |
| `edn_alert_rx_i`, `edn_alert_tx_o` | input/output | EDN alert channels |

## Interrupts

The wrapper surfaces the wrapped interrupt outputs directly.

| Signal | Direction | Source |
|---|---|---|
| `intr_cs_cmd_req_done_o` | output | Wrapped CSRNG |
| `intr_cs_entropy_req_o` | output | Wrapped CSRNG |
| `intr_cs_hw_inst_exc_o` | output | Wrapped CSRNG |
| `intr_cs_fatal_err_o` | output | Wrapped CSRNG |
| `intr_edn_cmd_req_done_o` | output | Wrapped EDN |
| `intr_edn_fatal_err_o` | output | Wrapped EDN |

## Internal Interface Adaptation Summary

The external and internal contracts differ in several places:

| External view | Internal view | Adapter role |
|---|---|---|
| 32-bit pulse entropy stream | `entropy_src_hw_if` seed request/ack interface | `drbg_csrng_seed_adapter` repacks 12 words into one 384-bit seed |
| 64-bit AXI-Lite | 32-bit AXI-Lite | `drbg_axil64_lane_adapter` filters and narrows accesses |
| 32-bit AXI-Lite | TL-UL | `axi_lite_to_tlul` bridges the wrapped CSR bus |
| EDN req/rsp endpoint interface | AXI-Stream output | `drbg_edn_axis_adapter` buffers and exports endpoint data |

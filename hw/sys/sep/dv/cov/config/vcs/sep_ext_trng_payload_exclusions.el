//==================================================
// SEP VCS coverage exclusions -- external-TRNG AXI-Stream payload tie.
// Format Version: 2
// ExclMode: default
//
// Scope: the cocotb VCS elaboration of sep_uvm_top, target `default`.
// Do not merge a `rom_boot` target run against this file.
//
// Only the STREAM PAYLOAD is waived, on the three modules the struct crosses:
// sep_ip_integration (where it is tied), sep (which passes it through) and
// sep_crypto (which consumes it). Nine signals each: tvalid, tdata[31:0] and
// tstrb[3:0] for all three EXT_TRNG_NUM_AXIS slots.
//
// NOT waived, deliberately: the entropy source mux in sep_crypto.sv:845-871.
// Its select comes from a CSR, both arms are reachable, and the back-pressure
// policy on each arm is a contract a test can state. Adding the mux here would
// waive live logic.
//
// Checksums are the module and metric checksums this design reports; they come
// from `urg -dump full_exclusions tgl` on the merged vdb, not by hand.
//==================================================

CHECKSUM: "3762633386 3007257968"
ANNOTATION: "SEP-EXTTRNG-PAYLOAD-TIE: the external-TRNG AXI-Stream has no master in this elaboration. sep_ip_integration.sv:773 drives ext_trng_axis_req_o with '{default: '0} and :774 ties ext_trng_irq_o low, so tvalid, tdata and tstrb hold zero everywhere this struct travels. The tie is in RTL, not in the testbench, so no plusarg, framework or test can present a second value. The source-select mux that consumes the stream is NOT waived: ext_trng_src_sel_i comes from a CSR (sep.sv:1028), so both arms of sep_crypto.sv:851 stay graded and a TRNG-mux test reaches them."
MODULE: sep
Toggle ext_trng_axis_req_i[0].tdata "logic ext_trng_axis_req_i[0].tdata[31:0]"
Toggle ext_trng_axis_req_i[0].tstrb "logic ext_trng_axis_req_i[0].tstrb[3:0]"
Toggle ext_trng_axis_req_i[0].tvalid "logic ext_trng_axis_req_i[0].tvalid"
Toggle ext_trng_axis_req_i[1].tdata "logic ext_trng_axis_req_i[1].tdata[31:0]"
Toggle ext_trng_axis_req_i[1].tstrb "logic ext_trng_axis_req_i[1].tstrb[3:0]"
Toggle ext_trng_axis_req_i[1].tvalid "logic ext_trng_axis_req_i[1].tvalid"
Toggle ext_trng_axis_req_i[2].tdata "logic ext_trng_axis_req_i[2].tdata[31:0]"
Toggle ext_trng_axis_req_i[2].tstrb "logic ext_trng_axis_req_i[2].tstrb[3:0]"
Toggle ext_trng_axis_req_i[2].tvalid "logic ext_trng_axis_req_i[2].tvalid"

CHECKSUM: "1124823661 940838130"
ANNOTATION: "SEP-EXTTRNG-PAYLOAD-TIE: the external-TRNG AXI-Stream has no master in this elaboration. sep_ip_integration.sv:773 drives ext_trng_axis_req_o with '{default: '0} and :774 ties ext_trng_irq_o low, so tvalid, tdata and tstrb hold zero everywhere this struct travels. The tie is in RTL, not in the testbench, so no plusarg, framework or test can present a second value. The source-select mux that consumes the stream is NOT waived: ext_trng_src_sel_i comes from a CSR (sep.sv:1028), so both arms of sep_crypto.sv:851 stay graded and a TRNG-mux test reaches them."
MODULE: sep_crypto
Toggle ext_trng_axis_req_i[0].tdata "logic ext_trng_axis_req_i[0].tdata[31:0]"
Toggle ext_trng_axis_req_i[0].tstrb "logic ext_trng_axis_req_i[0].tstrb[3:0]"
Toggle ext_trng_axis_req_i[0].tvalid "logic ext_trng_axis_req_i[0].tvalid"
Toggle ext_trng_axis_req_i[1].tdata "logic ext_trng_axis_req_i[1].tdata[31:0]"
Toggle ext_trng_axis_req_i[1].tstrb "logic ext_trng_axis_req_i[1].tstrb[3:0]"
Toggle ext_trng_axis_req_i[1].tvalid "logic ext_trng_axis_req_i[1].tvalid"
Toggle ext_trng_axis_req_i[2].tdata "logic ext_trng_axis_req_i[2].tdata[31:0]"
Toggle ext_trng_axis_req_i[2].tstrb "logic ext_trng_axis_req_i[2].tstrb[3:0]"
Toggle ext_trng_axis_req_i[2].tvalid "logic ext_trng_axis_req_i[2].tvalid"

CHECKSUM: "3175113314 622302765"
ANNOTATION: "SEP-EXTTRNG-PAYLOAD-TIE: the external-TRNG AXI-Stream has no master in this elaboration. sep_ip_integration.sv:773 drives ext_trng_axis_req_o with '{default: '0} and :774 ties ext_trng_irq_o low, so tvalid, tdata and tstrb hold zero everywhere this struct travels. The tie is in RTL, not in the testbench, so no plusarg, framework or test can present a second value. The source-select mux that consumes the stream is NOT waived: ext_trng_src_sel_i comes from a CSR (sep.sv:1028), so both arms of sep_crypto.sv:851 stay graded and a TRNG-mux test reaches them."
MODULE: sep_ip_integration
Toggle ext_trng_axis_req_o[0].tdata "logic ext_trng_axis_req_o[0].tdata[31:0]"
Toggle ext_trng_axis_req_o[0].tstrb "logic ext_trng_axis_req_o[0].tstrb[3:0]"
Toggle ext_trng_axis_req_o[0].tvalid "logic ext_trng_axis_req_o[0].tvalid"
Toggle ext_trng_axis_req_o[1].tdata "logic ext_trng_axis_req_o[1].tdata[31:0]"
Toggle ext_trng_axis_req_o[1].tstrb "logic ext_trng_axis_req_o[1].tstrb[3:0]"
Toggle ext_trng_axis_req_o[1].tvalid "logic ext_trng_axis_req_o[1].tvalid"
Toggle ext_trng_axis_req_o[2].tdata "logic ext_trng_axis_req_o[2].tdata[31:0]"
Toggle ext_trng_axis_req_o[2].tstrb "logic ext_trng_axis_req_o[2].tstrb[3:0]"
Toggle ext_trng_axis_req_o[2].tvalid "logic ext_trng_axis_req_o[2].tvalid"

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC OSS TB top shared by the native cocotb / PyUVM flow and the
// SystemVerilog UVM flow. ONE module, two shapes:
//   * default (cocotb, `--dut smc`): the pin-level ANSI port list cocotb
//     drives and samples;
//   * `UVM` (SV-UVM, `--dut smc --framework uvm`): the port list is replaced
//     by internal TB signals and the harness block at the end of the module
//     adds the clocks, the shared-VIP interfaces, quiescent tie-offs,
//     uvm_config_db publication, and run_test(). Test classes are compiled
//     via `include "smc_tests.sv".
// Every TB signal is declared once, in tb/smc_tb_signal_list.svh, and
// expanded into the selected shape by the SMC_TB_* macros below.
//
// Instantiates hw/top/smc_wrapper.sv (smc + smc_ip_integration). File name is
// tb_top.sv / module smc_uvm_top so `--dut smc_wrapper` +
// smc_wrapper_sim_cfg.toml is the single launch entry.
//
// Cocotb port surface keeps the SmcEnv catalog pin names. Hierarchical XMRs
// into the core use u_dut.u_smc.*.
//
// PLL/PVT/adopter-extension/GPIO-ctrl AXI-Lite macros and eFuse live inside
// smc_ip_integration. DTP CSR and I3C DAT/DCT remain smc_wrapper boundary
// ports (resp/mem idle — no TB placeholder; smc_wrapper-only DTP CSR gap —
// SMU wires DTP internally). CPU ROM/scratch/L1$ macros come with
// smc_ip_integration; smc_cpu_mem_dv.sv binds into it for the DV hooks.
//
// Additive elaboration-alias outputs (dut_present_o / powergood_o / ...) sit
// at the end of the port list for the thin elaboration smoke.

`timescale 1ps/1fs

// Shape selection for smc_tb_signal_list.svh: the same list expands as the
// ANSI port list (cocotb) or as internal TB signals (`UVM`). The macros live
// only from here to the `undef block after the module header.
`ifndef UVM
    // cocotb shape: every entry is a pin-level ANSI port, published to cocotb
    // through the Verilator metacomment (smc_public_scope.vlt publishes the
    // whole module as well).
    `define SMC_TB_IN_FIRST(dtype, name) input  wire dtype name /*verilator public_flat_rw*/
    `define SMC_TB_IN(dtype, name)     , input  wire dtype name /*verilator public_flat_rw*/
    `define SMC_TB_OUT(dtype, name)    , output dtype name /*verilator public_flat_rw*/
`else
    // SV-UVM shape: every entry is an internal TB signal for the harness
    // block at the end of this module.
    `define SMC_TB_IN_FIRST(dtype, name) dtype name;
    `define SMC_TB_IN(dtype, name) dtype name;
    `define SMC_TB_OUT(dtype, name) dtype name;
`endif

module smc_uvm_top
    import smc_pkg::*;
    import smc_efuse_pkg::*;
    import smc_4core_cpu_pkg::*;
`ifndef UVM
(
    `include "smc_tb_signal_list.svh"
);
`else
;
    `include "smc_tb_signal_list.svh"
`endif

`undef SMC_TB_IN_FIRST
`undef SMC_TB_IN
`undef SMC_TB_OUT

    /* verilator public_module */

    // Cocotb drives rst_cold_ni / rst_cool_ni / powergood_i after time 0.
    // Until then each input wire is Z, and PeakRDL immediate asserts in an
    // always_ff else treat `if (~arst_n)` as false when arst_n is X/Z. Hold
    // the safe idle (resets asserted, powergood low) until the port is a
    // known 0/1, then follow. An X/Z after cocotb has driven the port is a
    // testbench defect: latching the last good level would hide it, so it
    // fails here instead.
    //
    // $fatal, not $error: this is the safety net for the whole reset-hold
    // change, and $error only prints on Xcelium and VCS -- the run would go
    // green with the DUT on a stale reset level. It is also not a DUT finding
    // that a scoreboard should weigh; the stimulus is wrong and nothing after
    // it means anything.
    //
    // Each block is sensitive to its input alone rather than @(*). Under @(*)
    // the *_driven flag it writes is also in its own inferred sensitivity
    // list, which makes the block self-retriggering and draws UNOPTFLAT and
    // LATCH from Verilator. The value latch on *_int is deliberate.
    logic rst_cold_n_int = 1'b0;
    logic rst_cold_n_driven = 1'b0;
    always @(rst_cold_ni) begin
        if ((rst_cold_ni === 1'b0) || (rst_cold_ni === 1'b1)) begin
            rst_cold_n_int = rst_cold_ni;
            rst_cold_n_driven = 1'b1;
        end else if (rst_cold_n_driven) begin
            $fatal(1, "%0t: rst_cold_ni went %b after being driven; the DUT would run on the last known level",
                   $time, rst_cold_ni);
        end
    end

    logic rst_cool_n_int = 1'b0;
    logic rst_cool_n_driven = 1'b0;
    always @(rst_cool_ni) begin
        if ((rst_cool_ni === 1'b0) || (rst_cool_ni === 1'b1)) begin
            rst_cool_n_int = rst_cool_ni;
            rst_cool_n_driven = 1'b1;
        end else if (rst_cool_n_driven) begin
            $fatal(1, "%0t: rst_cool_ni went %b after being driven; the DUT would run on the last known level",
                   $time, rst_cool_ni);
        end
    end

    logic powergood_int = 1'b0;
    logic powergood_driven = 1'b0;
    always @(powergood_i) begin
        if ((powergood_i === 1'b0) || (powergood_i === 1'b1)) begin
            powergood_int = powergood_i;
            powergood_driven = 1'b1;
        end else if (powergood_driven) begin
            $fatal(1, "%0t: powergood_i went %b after being driven; the DUT would run on the last known level",
                   $time, powergood_i);
        end
    end

    // Assertion classes held off, and why each is not a DUT contract here.
    //
    // noXOnCsI: prim_rom.sv:40 is `assert property (@(posedge clk_i)
    // disable iff (('0) !== '0) !$isunknown(req_i))`. The disable is never
    // true, so the reset hold above cannot gate it, and req_i is X until
    // the TileLink converter leaves reset. Hold this one assertion off
    // until cold reset has released and one SMC clock edge has sampled a
    // known req_i, then re-arm by the assertion's own hierarchical name
    // so a later X still fails. $assertcontrol is not used: the commercial
    // compile timescale is 1ns/1ps, and Xcelium rejects $assertcontrol(4, 31).
`ifndef VERILATOR
    initial begin
        $assertoff(0, u_dut.u_smc_ip_integration.u_mems.rom_mem.mem.noXOnCsI);
        wait (rst_cold_n_int === 1'b1);
        @(posedge clk_smc_i);
        $asserton(0, u_dut.u_smc_ip_integration.u_mems.rom_mem.mem.noXOnCsI);
    end
`endif

    localparam logic [31:0] SMC_TEST_PASS = 32'hACAF_ACA1;
    localparam logic [31:0] SMC_TEST_FAIL = 32'hFFFF_FFFF;

    smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req;
    smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp;
    smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req;
    smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp;
    smc_jtag_56_64_2_12_axi_req_t    jtag_axi_in_req;
    smc_jtag_56_64_2_12_axi_resp_t   jtag_axi_in_resp;
    smc_sys_out_56_64_8_12_axi_req_t  output_axi_req;
    smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp;

    // Physical GPIO pad bus between smc_wrapper's internal smc <->
    // smc_ip_integration prim_pad_shim instances and this TB. Driven by the
    // per-pin injection block below; see header risk note.
    wire [smc_pkg::NUM_GPIO_WRAPS-1:0] gpio_pad_io;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] tb_pad_drive_en;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] tb_pad_drive_val;

    // Telemetry ATB bundle (receiver 0 driven; 1/2 quiet).
    telemetry_receiver_pkg::telemetry_data_t
        [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_atdata;
    telemetry_receiver_pkg::atb_id_t
        [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_atid;
    logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_atvalid;
    logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_atready;
    logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_afvalid;
    logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_afready;

    assign tb_telemetry_atdata[0] = tb_telemetry0_atdata;
    assign tb_telemetry_atid[0] = tb_telemetry0_atid;
    assign tb_telemetry_atvalid[0] = tb_telemetry0_atvalid;
    assign tb_telemetry0_atready = tb_telemetry_atready[0];
    assign tb_telemetry0_afvalid = tb_telemetry_afvalid[0];
    assign tb_telemetry_afready[0] = tb_telemetry0_afready;
    for (genvar tel_i = 1; tel_i < smc_config_pkg::NUM_TELEMETRY_RECEIVERS; tel_i++) begin : gen_tel_tie
        assign tb_telemetry_atdata[tel_i] = '0;
        assign tb_telemetry_atid[tel_i] = '0;
        assign tb_telemetry_atvalid[tel_i] = 1'b0;
        assign tb_telemetry_afready[tel_i] = 1'b1;
    end

    // NOTE: the adopter external window (PLL / PVT / GPIO ctrl) and the eFuse
    // bank/shim macro are absorbed into hw/top/smc_ip_integration.sv
    // (instantiated inside smc_wrapper as u_smc.smc_external_req_o feeding
    // u_smc_ip_integration directly) --
    // they are no longer boundary ports of smc_wrapper, so there is nothing
    // to declare/terminate for them at this TB level (see header comment).
    // DTP CSR (axil_dtp_csr_req_o) remains a smc_wrapper boundary port.
    smc_axil_32_32_req_t  axil_dtp_csr_req;
    smc_axil_32_32_resp_t axil_dtp_csr_resp;

    // I3C DAT/DCT memory boundary exposed by the current open SMC RTL.
    i3c_pkg::dat_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_src;
    i3c_pkg::dat_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_sink;
    i3c_pkg::dct_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_src;
    i3c_pkg::dct_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_sink;

    // Direct smc_wrapper boundary ports (top-level outputs -- no XMR needed).
    logic sync_irq;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0]    gpio_interrupt;
    logic [smc_config_pkg::NUM_UART-1:0]   uart_interrupt;

    localparam int unsigned I2C0_SCL_PAD = 37;
    localparam int unsigned I2C0_SDA_PAD = 38;
    localparam int unsigned I2C0_SMBALERT_PAD = 39;
    localparam int unsigned I2C0_SMBSUS_PAD = 40;
    // I2C1 pads (padring: 37+4*i / 38+4*i). Commercial TB shorts I2C0/1/2
    // SCL/SDA via tranif1 for internal P0 controller↔target loops.
    localparam int unsigned I2C1_SCL_PAD = 41;
    localparam int unsigned I2C1_SDA_PAD = 42;
    localparam int unsigned I2C1_SMBALERT_PAD = 43;
    localparam int unsigned I2C1_SMBSUS_PAD = 44;
    localparam int unsigned I2C2_SCL_PAD = 45;
    localparam int unsigned I2C2_SDA_PAD = 46;
    localparam int unsigned I2C2_SMBALERT_PAD = 47;
    localparam int unsigned I2C2_SMBSUS_PAD = 48;
    localparam int unsigned I3C0_SCL_PAD = 27;
    localparam int unsigned I3C0_SDA_PAD = 28;
    // Per smc_padring.sv gen_uart_connections (base 11+4*u):
    //   pad 11 = UART0 RX (pad -> core), pad 12 = UART0 TX (core -> pad).
    localparam int unsigned UART0_RX_PAD = 11;
    localparam int unsigned UART0_TX_PAD = 12;
    localparam int unsigned UART1_RX_PAD = 11 + (1 * 4); // pad 15
    localparam int unsigned UART1_TX_PAD = 12 + (1 * 4); // pad 16
    localparam int unsigned UART2_RX_PAD = 11 + (2 * 4); // pad 19
    localparam int unsigned UART2_TX_PAD = 12 + (2 * 4); // pad 20
    localparam int unsigned UART3_RX_PAD = 11 + (3 * 4); // pad 23
    localparam int unsigned UART3_TX_PAD = 12 + (3 * 4); // pad 24
    // smc_padring.sv: boot_stall is lsio pad 57 (active-high; was pad 60).
    // Default pullup/'1 would sticky-stall fuse_reset_n and hold the warm
    // reset domain (SCRATCH_COLD_WARM hang). Drive 0 unless +smc_hold_cpu_boot.
    localparam int unsigned BOOT_STALL_PAD = 57;
    bit tb_hold_cpu_boot /*verilator public_flat_rw*/;
    // +smc_hold_ext_boot: keep ext_boot_seq_done_i=0 from t=0 so
    // fuse_reset_n stays low after sense (efuse_interface_controller
    // reset_n = sense && rst_ni && ext_boot_seq_done).
    bit tb_hold_ext_boot /*verilator public_flat_rw*/;
    // +smc_uart_cross_3to0: short commercial UART pairs 0↔3 and 1↔2
    // (TX of each into RX of the peer). Name kept for enrolled tests.
    bit tb_uart_cross_3to0;
    initial begin
        tb_hold_cpu_boot = 1'b0;
        if ($test$plusargs("smc_hold_cpu_boot")) begin
            tb_hold_cpu_boot = 1'b1;
            $display("[tb_top] +smc_hold_cpu_boot: pad57 boot_stall held until TB release");
        end
        tb_hold_ext_boot = 1'b0;
        if ($test$plusargs("smc_hold_ext_boot")) begin
            tb_hold_ext_boot = 1'b1;
            $display("[tb_top] +smc_hold_ext_boot: ext_boot_seq_done held 0 until TB release");
        end
        tb_uart_cross_3to0 = 1'b0;
        if ($test$plusargs("smc_uart_cross_3to0")) begin
            tb_uart_cross_3to0 = 1'b1;
            $display("[tb_top] +smc_uart_cross_3to0: UART0<->3 and UART1<->2 TX/RX short");
        end
    end

    // Minimal LSIO open-drain resolver for I2C0. The SMC padring maps I2C0
    // SCL/SDA to GPIO pads 37/38. Released lines resolve high; either the DUT
    // or cocotb side may pull a line low. `u_smc_peripherals` now sits one
    // level deeper (u_dut.u_smc.u_smc_peripherals) since u_dut is
    // smc_wrapper.
    //
    // +smc_i2c_shared_bus: OR I2C1/I2C2 open-drain pulls into the same resolved
    // bus and drive those pads with that value (commercial tranif1 short).
    // Default off so existing I2C0↔VIP tests stay isolated on pads 37/38.
    logic tb_i2c_shared_bus;
    logic tb_i2c1_scl_dut_low;
    logic tb_i2c1_sda_dut_low;
    logic tb_i2c2_scl_dut_low;
    logic tb_i2c2_sda_dut_low;
    initial begin
        tb_i2c_shared_bus = 1'b0;
        if ($test$plusargs("smc_i2c_shared_bus")) begin
            tb_i2c_shared_bus = 1'b1;
            $display("[tb_top] +smc_i2c_shared_bus: I2C0/I2C1/I2C2 pads share OD bus (SCL/SDA + SMBus alert/suspend)");
        end
    end
    assign tb_i2c0_scl_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_scl_o[0];
    assign tb_i2c0_sda_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_sda_o[0];
    assign tb_i2c1_scl_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_scl_o[1];
    assign tb_i2c1_sda_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_sda_o[1];
    assign tb_i2c2_scl_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_scl_o[2];
    assign tb_i2c2_sda_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_sda_o[2];
    assign tb_i2c0_scl = !(tb_i2c0_scl_dut_low || tb_i2c0_scl_ext_low ||
                           (tb_i2c_shared_bus && (tb_i2c1_scl_dut_low ||
                                                  tb_i2c2_scl_dut_low)));
    assign tb_i2c0_sda = !(tb_i2c0_sda_dut_low || tb_i2c0_sda_ext_low ||
                           (tb_i2c_shared_bus && (tb_i2c1_sda_dut_low ||
                                                  tb_i2c2_sda_dut_low)));
    // SMBus sideband OD (commercial tranif1 on i2c_smbus_alert / suspend):
    // wrap *_no is 0 while that controller asserts the open-drain line.
    logic tb_i2c0_smbalert_dut_low;
    logic tb_i2c1_smbalert_dut_low;
    logic tb_i2c2_smbalert_dut_low;
    logic tb_i2c0_smbsus_dut_low;
    logic tb_i2c1_smbsus_dut_low;
    logic tb_i2c2_smbsus_dut_low;
    logic tb_i2c_smbalert;
    logic tb_i2c_smbsus;
    assign tb_i2c0_smbalert_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbalert_no[0];
    assign tb_i2c1_smbalert_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbalert_no[1];
    assign tb_i2c2_smbalert_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbalert_no[2];
    assign tb_i2c0_smbsus_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbsus_no[0];
    assign tb_i2c1_smbsus_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbsus_no[1];
    assign tb_i2c2_smbsus_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbsus_no[2];
    assign tb_i2c_smbalert = !(tb_i2c0_smbalert_dut_low ||
                               (tb_i2c_shared_bus &&
                                (tb_i2c1_smbalert_dut_low ||
                                 tb_i2c2_smbalert_dut_low)));
    assign tb_i2c_smbsus = !(tb_i2c0_smbsus_dut_low ||
                             (tb_i2c_shared_bus &&
                              (tb_i2c1_smbsus_dut_low ||
                               tb_i2c2_smbsus_dut_low)));
    assign tb_i2c0_enable = u_dut.u_smc.u_smc_peripherals.i2c_enable_smc_clk[0];
    assign tb_i2c0_scl_i  = u_dut.u_smc.u_smc_peripherals.i2c_scl_i[0];
    assign tb_i2c0_sda_i  = u_dut.u_smc.u_smc_peripherals.i2c_sda_i[0];
    assign tb_i3c0_scl_dut_low = u_dut.u_smc.u_smc_peripherals.i3c_scl_oe_to_pad[0] &&
                                  !u_dut.u_smc.u_smc_peripherals.i3c_scl_to_pad[0];
    assign tb_i3c0_sda_dut_low = u_dut.u_smc.u_smc_peripherals.i3c_sda_oe_to_pad[0] &&
                                  !u_dut.u_smc.u_smc_peripherals.i3c_sda_to_pad[0];
    assign tb_i3c0_scl = !(tb_i3c0_scl_dut_low || tb_i3c0_scl_ext_low);
    assign tb_i3c0_sda = !(tb_i3c0_sda_dut_low || tb_i3c0_sda_ext_low);

    // ------------------------------------------------------------------
    // Pad injection (KNOWN RISK -- see header + summary).
    //
    // pad2core/core2pad are no longer TB-facing ports: they are internal
    // smc_wrapper nets routed through one prim_pad_shim.sv per pin
    // (hw/top/smc_ip_integration.sv) onto the physical `gpio_pad_io` inout
    // bus. There is no legal way to XMR-assign `u_dut.u_smc.pad2core_i`
    // (it is already driven by u_smc_ip_integration's pad2core_o), so
    // external stimulus must be injected onto `gpio_pad_io` itself:
    //   - A weak `pullup` per pin gives idle/unconnected pads a defined '1
    //     (mirrors bare tb_top's tb_pad2core default) without ever
    //     contending with a real (strength-1) driver.
    //   - `tb_pad_drive_en/val` strongly drive only the specific pins this
    //     TB wants to inject (GPIO overrides, I2C0/I3C0 open-drain lines,
    //     UART0 RX, SPI DQ0 MISO, AVSBus sdata, OCTS secondary inject,
    //     boot-stall hold) -- computed with the exact same mux logic bare
    //     tb_top used for tb_pad2core.
    //   - For I2C0/I3C0, the resolved value (DUT-low XMR probe OR ext-low)
    //     is *always* strongly driven back onto the pad so pad2core reads
    //     the correct bus state for ACK / clock-stretch (mirrors tb_top's
    //     manual open-drain reconstruction). This assumes the digital I2C/
    //     I3C core only asserts its own pad OE while driving logic 0
    //     (never asserts OE to push a logic 1); if that assumption is ever
    //     violated, the DUT's own strong '1 push and this block's strong
    //     '0 pull could momentarily contend (X) around edges. See summary.
    //   - All other DUT-owned output pads (UART0 TX, AVS clk/mdata, OCTS
    //     observe, general GPIO outputs) are left un-driven here (Z) and
    //     read back via XMR into u_dut.u_smc.core2pad_o/core2pad_en_o,
    //     exactly like bare tb_top, so this injection block never contends
    //     with the DUT's own output drive on those pins.
    // ------------------------------------------------------------------
    always_comb begin
        tb_pad_drive_en  = '0;
        tb_pad_drive_val = '1;

        for (int unsigned gpio_idx = 0; gpio_idx < smc_pkg::NUM_GPIO_WRAPS; gpio_idx++) begin
            if (tb_gpio_ext_drive_en[gpio_idx]) begin
                tb_pad_drive_en[gpio_idx]  = 1'b1;
                tb_pad_drive_val[gpio_idx] = tb_gpio_ext_drive_value[gpio_idx];
            end
        end

        // I2C0 / I3C0 open-drain pads: Verilator ignores `pullup`, so always
        // strongly drive the resolved OD value (0 when DUT or VIP pulls low,
        // 1 when both released). Safe because the digital I2C/I3C core only
        // asserts OE while driving logic 0 (never pushes a strong 1).
        tb_pad_drive_en[I2C0_SCL_PAD]  = 1'b1;
        tb_pad_drive_val[I2C0_SCL_PAD] = tb_i2c0_scl;
        tb_pad_drive_en[I2C0_SDA_PAD]  = 1'b1;
        tb_pad_drive_val[I2C0_SDA_PAD] = tb_i2c0_sda;
        if (tb_i2c_shared_bus) begin
            tb_pad_drive_en[I2C1_SCL_PAD]  = 1'b1;
            tb_pad_drive_val[I2C1_SCL_PAD] = tb_i2c0_scl;
            tb_pad_drive_en[I2C1_SDA_PAD]  = 1'b1;
            tb_pad_drive_val[I2C1_SDA_PAD] = tb_i2c0_sda;
            tb_pad_drive_en[I2C2_SCL_PAD]  = 1'b1;
            tb_pad_drive_val[I2C2_SCL_PAD] = tb_i2c0_scl;
            tb_pad_drive_en[I2C2_SDA_PAD]  = 1'b1;
            tb_pad_drive_val[I2C2_SDA_PAD] = tb_i2c0_sda;
            // Shared SMBus alert / suspend (commercial i2c_smbus_alert/suspend).
            tb_pad_drive_en[I2C0_SMBALERT_PAD]  = 1'b1;
            tb_pad_drive_val[I2C0_SMBALERT_PAD] = tb_i2c_smbalert;
            tb_pad_drive_en[I2C1_SMBALERT_PAD]  = 1'b1;
            tb_pad_drive_val[I2C1_SMBALERT_PAD] = tb_i2c_smbalert;
            tb_pad_drive_en[I2C2_SMBALERT_PAD]  = 1'b1;
            tb_pad_drive_val[I2C2_SMBALERT_PAD] = tb_i2c_smbalert;
            tb_pad_drive_en[I2C0_SMBSUS_PAD]  = 1'b1;
            tb_pad_drive_val[I2C0_SMBSUS_PAD] = tb_i2c_smbsus;
            tb_pad_drive_en[I2C1_SMBSUS_PAD]  = 1'b1;
            tb_pad_drive_val[I2C1_SMBSUS_PAD] = tb_i2c_smbsus;
            tb_pad_drive_en[I2C2_SMBSUS_PAD]  = 1'b1;
            tb_pad_drive_val[I2C2_SMBSUS_PAD] = tb_i2c_smbsus;
        end
        tb_pad_drive_en[I3C0_SCL_PAD]  = 1'b1;
        tb_pad_drive_val[I3C0_SCL_PAD] = tb_i3c0_scl;
        tb_pad_drive_en[I3C0_SDA_PAD]  = 1'b1;
        tb_pad_drive_val[I3C0_SDA_PAD] = tb_i3c0_sda;

        // UART0 RX: external VIP, or UART3 TX when +smc_uart_cross_3to0.
        tb_pad_drive_en[UART0_RX_PAD]  = 1'b1;
        tb_pad_drive_val[UART0_RX_PAD] = tb_uart_cross_3to0
            ? u_dut.u_smc.core2pad_o[UART3_TX_PAD]
            : tb_uart0_rx_ext_drive;
        if (tb_uart_cross_3to0) begin
            // Pair 0↔3
            tb_pad_drive_en[UART3_RX_PAD]  = 1'b1;
            tb_pad_drive_val[UART3_RX_PAD] = u_dut.u_smc.core2pad_o[UART0_TX_PAD];
            // Pair 1↔2
            tb_pad_drive_en[UART2_RX_PAD]  = 1'b1;
            tb_pad_drive_val[UART2_RX_PAD] = u_dut.u_smc.core2pad_o[UART1_TX_PAD];
            tb_pad_drive_en[UART1_RX_PAD]  = 1'b1;
            tb_pad_drive_val[UART1_RX_PAD] = u_dut.u_smc.core2pad_o[UART2_TX_PAD];
        end

        // Boot stall: released by default; held when +smc_hold_cpu_boot is set
        // unless a test explicitly drives pad 57 via GPIO override.
        if (!tb_gpio_ext_drive_en[BOOT_STALL_PAD]) begin
            tb_pad_drive_en[BOOT_STALL_PAD]  = 1'b1;
            tb_pad_drive_val[BOOT_STALL_PAD] = tb_hold_cpu_boot;
        end

        // SPI DQ0 MISO from flash BFM when SPI mux is enabled (pads 0-7).
        if (tb_spi_enable) begin
            tb_pad_drive_en[0]  = 1'b1;
            tb_pad_drive_val[0] = tb_spi_miso_ext;
        end

        // AVSBus sdata (pad 51): external slave ACK BFM into DUT.
        tb_pad_drive_en[51]  = 1'b1;
        tb_pad_drive_val[51] = tb_avs_sdata_ext;

        // OCTS dual-chiplet secondary inject (pads 55/56). Harmless when
        // primary (padring disables pad2core on these pads).
        tb_pad_drive_en[55]  = 1'b1;
        tb_pad_drive_val[55] = tb_octs_sync_load_ext;
        tb_pad_drive_en[56]  = 1'b1;
        tb_pad_drive_val[56] = tb_octs_cnt_credit_ext;
    end

    for (genvar gpio_idx = 0; gpio_idx < smc_pkg::NUM_GPIO_WRAPS; gpio_idx++) begin : gen_gpio_pad_drive
        // Weak pull-up default (never contends with any real driver) plus a
        // strong TB-owned drive only where tb_pad_drive_en requests one.
        pullup u_pad_pullup (gpio_pad_io[gpio_idx]);
        assign gpio_pad_io[gpio_idx] = tb_pad_drive_en[gpio_idx] ? tb_pad_drive_val[gpio_idx] : 1'bz;
    end

    // UART0 TX: the DUT drives one line out to the external world.
    assign tb_uart0_tx_from_dut = u_dut.u_smc.core2pad_o[UART0_TX_PAD];
    // I2C0 SMBALERT# (pad 39): OE-aware resolve (active-low when DUT drives).
    // core2pad_en_o is active-high (~lsio_core2pad_en_ni); data is 0 when OE.
    // Under +smc_i2c_shared_bus the pad is TB-driven with the shared OD net.
    assign tb_i2c0_smbalert = tb_i2c_shared_bus
                              ? tb_i2c_smbalert
                              : (u_dut.u_smc.core2pad_en_o[I2C0_SMBALERT_PAD]
                                 ? u_dut.u_smc.core2pad_o[I2C0_SMBALERT_PAD]
                                 : 1'b1);
    // AVSBus pads 49/50 (clk/mdata) and OCTS pads 55/56 (sync/credit) observe.
    assign tb_avs_clk_from_dut = u_dut.u_smc.core2pad_o[49];
    assign tb_avs_mdata_from_dut = u_dut.u_smc.core2pad_o[50];
    assign tb_octs_sync_load_from_dut = u_dut.u_smc.core2pad_o[55];
    assign tb_octs_cnt_credit_from_dut = u_dut.u_smc.core2pad_o[56];

    assign sep_axi_in_req.aw.id     = s_axi_awid;
    assign sep_axi_in_req.aw.addr   = s_axi_awaddr;
    assign sep_axi_in_req.aw.len    = s_axi_awlen;
    assign sep_axi_in_req.aw.size   = s_axi_awsize;
    assign sep_axi_in_req.aw.burst  = s_axi_awburst;
    assign sep_axi_in_req.aw.lock   = s_axi_awlock;
    assign sep_axi_in_req.aw.cache  = s_axi_awcache;
    assign sep_axi_in_req.aw.prot   = s_axi_awprot;
    assign sep_axi_in_req.aw.qos    = s_axi_awqos;
    assign sep_axi_in_req.aw.region = s_axi_awregion;
    assign sep_axi_in_req.aw.user   = s_axi_awuser;
    // Pack ATOP=0 on all AXI ingresses; the outbound filter's err_slv is
    // built with `.ATOPs(1'b0)` and its `assume` on `atop == '0 fires a
    // fatal on Xcelium when the field is left X-propagating.
    assign sep_axi_in_req.aw.atop   = '0;
    assign sep_axi_in_req.aw_valid  = s_axi_awvalid;
    assign s_axi_awready            = sep_axi_in_resp.aw_ready;

    assign sep_axi_in_req.w.data    = s_axi_wdata;
    assign sep_axi_in_req.w.strb    = s_axi_wstrb;
    assign sep_axi_in_req.w.last    = s_axi_wlast;
    assign sep_axi_in_req.w.user    = s_axi_wuser;
    assign sep_axi_in_req.w_valid   = s_axi_wvalid;
    assign s_axi_wready             = sep_axi_in_resp.w_ready;

    assign s_axi_bid                = sep_axi_in_resp.b.id;
    assign s_axi_bresp              = sep_axi_in_resp.b.resp;
    assign s_axi_buser              = sep_axi_in_resp.b.user;
    assign s_axi_bvalid             = sep_axi_in_resp.b_valid;
    assign sep_axi_in_req.b_ready   = s_axi_bready;

    assign sep_axi_in_req.ar.id     = s_axi_arid;
    assign sep_axi_in_req.ar.addr   = s_axi_araddr;
    assign sep_axi_in_req.ar.len    = s_axi_arlen;
    assign sep_axi_in_req.ar.size   = s_axi_arsize;
    assign sep_axi_in_req.ar.burst  = s_axi_arburst;
    assign sep_axi_in_req.ar.lock   = s_axi_arlock;
    assign sep_axi_in_req.ar.cache  = s_axi_arcache;
    assign sep_axi_in_req.ar.prot   = s_axi_arprot;
    assign sep_axi_in_req.ar.qos    = s_axi_arqos;
    assign sep_axi_in_req.ar.region = s_axi_arregion;
    assign sep_axi_in_req.ar.user   = s_axi_aruser;
    assign sep_axi_in_req.ar_valid  = s_axi_arvalid;
    assign s_axi_arready            = sep_axi_in_resp.ar_ready;

    assign s_axi_rid                = sep_axi_in_resp.r.id;
    assign s_axi_rdata              = sep_axi_in_resp.r.data;
    assign s_axi_rresp              = sep_axi_in_resp.r.resp;
    assign s_axi_rlast              = sep_axi_in_resp.r.last;
    assign s_axi_ruser              = sep_axi_in_resp.r.user;
    assign s_axi_rvalid             = sep_axi_in_resp.r_valid & ~tb_sep_axi_r_hold;
    assign sep_axi_in_req.r_ready   = s_axi_rready & ~tb_sep_axi_r_hold;

    assign sys_axi_in_req.aw.id     = sys_axi_awid;
    assign sys_axi_in_req.aw.addr   = sys_axi_awaddr;
    assign sys_axi_in_req.aw.len    = sys_axi_awlen;
    assign sys_axi_in_req.aw.size   = sys_axi_awsize;
    assign sys_axi_in_req.aw.burst  = sys_axi_awburst;
    assign sys_axi_in_req.aw.lock   = sys_axi_awlock;
    assign sys_axi_in_req.aw.cache  = sys_axi_awcache;
    assign sys_axi_in_req.aw.prot   = sys_axi_awprot;
    assign sys_axi_in_req.aw.qos    = sys_axi_awqos;
    assign sys_axi_in_req.aw.region = sys_axi_awregion;
    assign sys_axi_in_req.aw.user   = sys_axi_awuser;
    assign sys_axi_in_req.aw.atop   = '0;
    assign sys_axi_in_req.aw_valid  = sys_axi_awvalid;
    assign sys_axi_awready          = sys_axi_in_resp.aw_ready;

    assign sys_axi_in_req.w.data    = sys_axi_wdata;
    assign sys_axi_in_req.w.strb    = sys_axi_wstrb;
    assign sys_axi_in_req.w.last    = sys_axi_wlast;
    assign sys_axi_in_req.w.user    = sys_axi_wuser;
    assign sys_axi_in_req.w_valid   = sys_axi_wvalid;
    assign sys_axi_wready           = sys_axi_in_resp.w_ready;

    assign sys_axi_bid              = sys_axi_in_resp.b.id;
    assign sys_axi_bresp            = sys_axi_in_resp.b.resp;
    assign sys_axi_buser            = sys_axi_in_resp.b.user;
    assign sys_axi_bvalid           = sys_axi_in_resp.b_valid;
    assign sys_axi_in_req.b_ready   = sys_axi_bready;

    assign sys_axi_in_req.ar.id     = sys_axi_arid;
    assign sys_axi_in_req.ar.addr   = sys_axi_araddr;
    assign sys_axi_in_req.ar.len    = sys_axi_arlen;
    assign sys_axi_in_req.ar.size   = sys_axi_arsize;
    assign sys_axi_in_req.ar.burst  = sys_axi_arburst;
    assign sys_axi_in_req.ar.lock   = sys_axi_arlock;
    assign sys_axi_in_req.ar.cache  = sys_axi_arcache;
    assign sys_axi_in_req.ar.prot   = sys_axi_arprot;
    assign sys_axi_in_req.ar.qos    = sys_axi_arqos;
    assign sys_axi_in_req.ar.region = sys_axi_arregion;
    assign sys_axi_in_req.ar.user   = sys_axi_aruser;
    assign sys_axi_in_req.ar_valid  = sys_axi_arvalid;
    assign sys_axi_arready          = sys_axi_in_resp.ar_ready;

    assign sys_axi_rid              = sys_axi_in_resp.r.id;
    assign sys_axi_rdata            = sys_axi_in_resp.r.data;
    assign sys_axi_rresp            = sys_axi_in_resp.r.resp;
    assign sys_axi_rlast            = sys_axi_in_resp.r.last;
    assign sys_axi_ruser            = sys_axi_in_resp.r.user;
    assign sys_axi_rvalid           = sys_axi_in_resp.r_valid & ~tb_sys_axi_r_hold;
    assign sys_axi_in_req.r_ready   = sys_axi_rready & ~tb_sys_axi_r_hold;

    assign jtag_axi_in_req.aw.id     = jtag_axi_awid;
    assign jtag_axi_in_req.aw.addr   = jtag_axi_awaddr;
    assign jtag_axi_in_req.aw.len    = jtag_axi_awlen;
    assign jtag_axi_in_req.aw.size   = jtag_axi_awsize;
    assign jtag_axi_in_req.aw.burst  = jtag_axi_awburst;
    assign jtag_axi_in_req.aw.lock   = jtag_axi_awlock;
    assign jtag_axi_in_req.aw.cache  = jtag_axi_awcache;
    assign jtag_axi_in_req.aw.prot   = jtag_axi_awprot;
    assign jtag_axi_in_req.aw.qos    = jtag_axi_awqos;
    assign jtag_axi_in_req.aw.region = jtag_axi_awregion;
    assign jtag_axi_in_req.aw.user   = jtag_axi_awuser;
    assign jtag_axi_in_req.aw.atop   = '0;
    assign jtag_axi_in_req.aw_valid  = jtag_axi_awvalid;
    assign jtag_axi_awready          = jtag_axi_in_resp.aw_ready;

    assign jtag_axi_in_req.w.data    = jtag_axi_wdata;
    assign jtag_axi_in_req.w.strb    = jtag_axi_wstrb;
    assign jtag_axi_in_req.w.last    = jtag_axi_wlast;
    assign jtag_axi_in_req.w.user    = jtag_axi_wuser;
    assign jtag_axi_in_req.w_valid   = jtag_axi_wvalid;
    assign jtag_axi_wready           = jtag_axi_in_resp.w_ready;

    assign jtag_axi_bid              = jtag_axi_in_resp.b.id;
    assign jtag_axi_bresp            = jtag_axi_in_resp.b.resp;
    assign jtag_axi_buser            = jtag_axi_in_resp.b.user;
    assign jtag_axi_bvalid           = jtag_axi_in_resp.b_valid;
    assign jtag_axi_in_req.b_ready   = jtag_axi_bready;

    assign jtag_axi_in_req.ar.id     = jtag_axi_arid;
    assign jtag_axi_in_req.ar.addr   = jtag_axi_araddr;
    assign jtag_axi_in_req.ar.len    = jtag_axi_arlen;
    assign jtag_axi_in_req.ar.size   = jtag_axi_arsize;
    assign jtag_axi_in_req.ar.burst  = jtag_axi_arburst;
    assign jtag_axi_in_req.ar.lock   = jtag_axi_arlock;
    assign jtag_axi_in_req.ar.cache  = jtag_axi_arcache;
    assign jtag_axi_in_req.ar.prot   = jtag_axi_arprot;
    assign jtag_axi_in_req.ar.qos    = jtag_axi_arqos;
    assign jtag_axi_in_req.ar.region = jtag_axi_arregion;
    assign jtag_axi_in_req.ar.user   = jtag_axi_aruser;
    assign jtag_axi_in_req.ar_valid  = jtag_axi_arvalid;
    assign jtag_axi_arready          = jtag_axi_in_resp.ar_ready;

    assign jtag_axi_rid              = jtag_axi_in_resp.r.id;
    assign jtag_axi_rdata            = jtag_axi_in_resp.r.data;
    assign jtag_axi_rresp            = jtag_axi_in_resp.r.resp;
    assign jtag_axi_rlast            = jtag_axi_in_resp.r.last;
    assign jtag_axi_ruser            = jtag_axi_in_resp.r.user;
    assign jtag_axi_rvalid           = jtag_axi_in_resp.r_valid;
    assign jtag_axi_in_req.r_ready   = jtag_axi_rready;

    // ------------------------------------------------------------------
    // SYS_OUT AXI slave — same posture as SEP tb_top rom_boot `u_smc_mem`:
    // pulp axi_sim_mem on the boundary, optional $readmemh preload, no Force,
    // no custom DV mem module. ApplDelay/AcqDelay match SEP Verilator floor.
    // ------------------------------------------------------------------
    smc_sys_out_56_64_8_12_axi_req_t  [0:0] output_mem_req;
    smc_sys_out_56_64_8_12_axi_resp_t [0:0] output_mem_resp;
    smc_sys_out_56_64_8_12_axi_req_t        output_mem_req_n;
    smc_sys_out_56_64_8_12_axi_resp_t       output_axi_resp_n;

    always_comb begin
        output_mem_req_n         = output_axi_req;
        output_mem_req_n.r_ready = output_axi_req.r_ready & ~tb_output_axi_resp_hold;
        output_mem_req_n.b_ready = output_axi_req.b_ready & ~tb_output_axi_resp_hold;
    end
    always_comb begin
        output_axi_resp_n         = output_mem_resp[0];
        output_axi_resp_n.r_valid = output_mem_resp[0].r_valid & ~tb_output_axi_resp_hold;
        output_axi_resp_n.b_valid = output_mem_resp[0].b_valid & ~tb_output_axi_resp_hold;
    end
    assign output_mem_req[0] = output_mem_req_n;
    assign output_axi_resp   = output_axi_resp_n;

    // SMC smc_clk floor is 4ns (env_cfg); keep ApplDelay < AcqDelay < 4ns.
    axi_sim_mem #(
        .AddrWidth         (56),
        .DataWidth         (64),
        .IdWidth           (8),
        .UserWidth         (12),
        .NumPorts          (1),
        .axi_req_t         (smc_sys_out_56_64_8_12_axi_req_t),
        .axi_rsp_t         (smc_sys_out_56_64_8_12_axi_resp_t),
        .WarnUninitialized (1'b0),
        .UninitializedData ("zeros"),
        .ClearErrOnAccess  (1'b1),
        .ApplDelay         (1ns),
        .AcqDelay          (2ns)
    ) u_output_mem (
        .clk_i     (clk_smc_i),
        .rst_ni    (rst_cold_n_int),
        .axi_req_i (output_mem_req),
        .axi_rsp_o (output_mem_resp)
    );

    string smc_output_hex_path;
    initial begin
        #1;
        if ($value$plusargs("smc_output_hex=%s", smc_output_hex_path)) begin
            $readmemh(smc_output_hex_path, u_output_mem.mem);
            $display("[smc_uvm_top] SYS_OUT mem preloaded from %s",
                     smc_output_hex_path);
        end
    end

    // Program TB-owned axi_sim_mem error maps (pulp werr/rerr API — not DUT Force).
    // Require strict 1'b1 so undriven X at time-0 does not spam the maps.
    always_ff @(posedge clk_smc_i) begin
        if (tb_output_err_we === 1'b1) begin
            for (int unsigned b = 0; b < 8; b++) begin
                u_output_mem.werr[tb_output_err_addr + b] = tb_output_err_resp;
                u_output_mem.rerr[tb_output_err_addr + b] = tb_output_err_resp;
            end
        end
    end

    // Observability: SEP KM-style beat counts on lifted SYS_OUT wires.
    logic [55:0] output_aw_addr_q;
    logic [63:0] output_w_data_q;
    logic [55:0] output_ar_addr_q;

    always_ff @(posedge clk_smc_i or negedge rst_cold_n_int) begin
        if (!rst_cold_n_int) begin
            output_aw_addr_q          <= '0;
            output_w_data_q           <= '0;
            output_ar_addr_q          <= '0;
            tb_output_axi_write_count <= '0;
            tb_output_axi_read_count  <= '0;
            tb_output_axi_last_addr   <= '0;
            tb_output_axi_last_wdata  <= '0;
        end else begin
            if (output_axi_req.aw_valid && output_axi_resp.aw_ready) begin
                output_aw_addr_q <= output_axi_req.aw.addr;
            end
            if (output_axi_req.w_valid && output_axi_resp.w_ready) begin
                output_w_data_q <= output_axi_req.w.data;
            end
            if (output_axi_req.ar_valid && output_axi_resp.ar_ready) begin
                output_ar_addr_q <= output_axi_req.ar.addr;
            end
            if (output_axi_resp.b_valid && output_axi_req.b_ready) begin
                tb_output_axi_write_count <= tb_output_axi_write_count + 32'd1;
                tb_output_axi_last_addr   <= output_aw_addr_q;
                tb_output_axi_last_wdata  <= output_w_data_q;
            end
            if (output_axi_resp.r_valid && output_axi_req.r_ready &&
                    output_axi_resp.r.last) begin
                tb_output_axi_read_count <= tb_output_axi_read_count + 32'd1;
                tb_output_axi_last_addr  <= output_ar_addr_q;
            end
        end
    end

    // U6-2: lift SYS_OUT AXI for SmcOutputAxiMonitor (SEP-style observe ports).
    assign tb_output_axi_bvalid  = output_axi_resp.b_valid;
    assign tb_output_axi_bready  = output_axi_req.b_ready;
    assign tb_output_axi_bresp   = output_axi_resp.b.resp;
    assign tb_output_axi_rvalid  = output_axi_resp.r_valid;
    assign tb_output_axi_rready  = output_axi_req.r_ready;
    assign tb_output_axi_rresp   = output_axi_resp.r.resp;
    assign tb_output_axi_awaddr  = output_axi_req.aw.addr;
    assign tb_output_axi_awvalid = output_axi_req.aw_valid;
    assign tb_output_axi_awready = output_axi_resp.aw_ready;
    assign tb_output_axi_araddr  = output_axi_req.ar.addr;
    assign tb_output_axi_arvalid = output_axi_req.ar_valid;
    assign tb_output_axi_arready = output_axi_resp.ar_ready;
    assign tb_output_axi_wdata   = output_axi_req.w.data;
    assign tb_output_axi_wvalid  = output_axi_req.w_valid;
    assign tb_output_axi_wready  = output_axi_resp.w_ready;

    // Product lc_state_i = {diff_n, diff_p}. Default idle is packed by
    // smc_base_test as complementary TEST_DEV ({~0, 0}).
    logic [2*smc_pkg::LC_STATE_WIDTH-1:0] lc_state_drv;
    assign lc_state_drv = tb_lc_state;

    // P2-15 JTAG-side eFuse AXI-Lite master pack/unpack.
    smc_axil_32_32_req_t  ej_axi_req;
    smc_axil_32_32_resp_t ej_axi_resp;
    assign ej_axi_req.aw.addr  = ej_axi_awaddr;
    assign ej_axi_req.aw.prot  = ej_axi_awprot;
    assign ej_axi_req.aw_valid = ej_axi_awvalid;
    assign ej_axi_awready      = ej_axi_resp.aw_ready;
    assign ej_axi_req.w.data   = ej_axi_wdata;
    assign ej_axi_req.w.strb   = ej_axi_wstrb;
    assign ej_axi_req.w_valid  = ej_axi_wvalid;
    assign ej_axi_wready       = ej_axi_resp.w_ready;
    assign ej_axi_bresp        = ej_axi_resp.b.resp;
    assign ej_axi_bvalid       = ej_axi_resp.b_valid;
    assign ej_axi_req.b_ready  = ej_axi_bready;
    assign ej_axi_req.ar.addr  = ej_axi_araddr;
    assign ej_axi_req.ar.prot  = ej_axi_arprot;
    assign ej_axi_req.ar_valid = ej_axi_arvalid;
    assign ej_axi_arready      = ej_axi_resp.ar_ready;
    assign ej_axi_rdata        = ej_axi_resp.r.data;
    assign ej_axi_rresp        = ej_axi_resp.r.resp;
    assign ej_axi_rvalid       = ej_axi_resp.r_valid;
    assign ej_axi_req.r_ready  = ej_axi_rready;

    // ------------------------------------------------------------------
    // CPU ROM/scratch/L1$ macros live inside smc_ip_integration (so both this
    // DUT and smu_wrapper get them from one place). The TB adds no memory of
    // its own; the DV collateral -- counters, FW mailbox, the inject hook and
    // the image backdoors -- binds into that module.
    // ------------------------------------------------------------------
    logic        cpu_scratch0_inject_fire;
    logic [31:0] ecc_inject_fire_count_q;

    // Port expressions here are elaborated in smc_ip_integration's scope, so
    // they name that module's own memory interfaces.
    bind smc_ip_integration smc_cpu_mem_dv u_smc_cpu_mem_dv (
        .clk_i                (clk_smc_i),
        .rst_ni               (rst_primary_smc_clk_ni),
        .rom_req_i            (rom_intf_req),
        .scratch_ram_req_i    (scratch_ram_intf_req),
        .l1_dcache_data_req_i (l1_dcache_data_intf_req),
        .ecc_inject_sbe_i     (smc_uvm_top.tb_cpu_ecc_inject_sbe),
        .ecc_inject_dbe_i     (smc_uvm_top.tb_cpu_ecc_inject_dbe),
        .ecc_poke_en_i        (smc_uvm_top.tb_cpu_ecc_poke_en),
        .ecc_poke_entry_i     (smc_uvm_top.tb_cpu_ecc_poke_entry),
        .ecc_poke_mask_i      (smc_uvm_top.tb_cpu_ecc_poke_mask)
    );

    // Cluster DED from the CPU (smc_4core_cpu.sv flops
    // |{io_errors_uncorrectable_valid, uncorrectable_2} into it). Sticky, so a
    // polling test cannot miss it.
    logic cpu_cluster_ded;
    logic cpu_cluster_ded_seen_q;
    always_ff @(posedge clk_smc_i or negedge rst_cold_n_int) begin
        if (!rst_cold_n_int) begin
            cpu_cluster_ded_seen_q <= 1'b0;
        end else if (cpu_cluster_ded) begin
            cpu_cluster_ded_seen_q <= 1'b1;
        end
    end
    assign tb_cluster_ded      = cpu_cluster_ded;
    assign tb_cluster_ded_seen = cpu_cluster_ded_seen_q;

    // Bound-instance observability -> the cocotb pins (names unchanged).
    `define CPU_MEM_DV u_dut.u_smc_ip_integration.u_smc_cpu_mem_dv
    assign tb_cpu_rom_read_count      = `CPU_MEM_DV.rom_read_count_q;
    assign tb_cpu_scratch_read_count  = `CPU_MEM_DV.scratch_ram_read_count_q;
    assign tb_cpu_scratch_write_count = `CPU_MEM_DV.scratch_ram_write_count_q;
    assign tb_cpu_dcache_write_count  = `CPU_MEM_DV.dcache_data_write_count_q;
    assign tb_cpu_fw_mailbox          = `CPU_MEM_DV.fw_mailbox_q;
    assign tb_cpu_fw_mailbox_valid    = `CPU_MEM_DV.fw_mailbox_valid_q;
    assign cpu_scratch0_inject_fire   = `CPU_MEM_DV.scratch0_inject_fire_q;

    // Probe pin kept for cocotb init compatibility; do not OR into the score.
    logic unused_ecc_probe;
    assign unused_ecc_probe = tb_cpu_ecc_inject_probe;

    always_ff @(posedge clk_smc_i or negedge rst_cold_n_int) begin
        if (!rst_cold_n_int) begin
            ecc_inject_fire_count_q <= '0;
        end else if (cpu_scratch0_inject_fire) begin
            ecc_inject_fire_count_q <= ecc_inject_fire_count_q + 32'd1;
        end
    end
    assign tb_cpu_ecc_inject_fire_count = ecc_inject_fire_count_q;
    assign tb_cpu_scratch0_inject_fire = cpu_scratch0_inject_fire;

    // ------------------------------------------------------------------
    // DTP CSR boundary (smc_wrapper only): NO TB err_slv (policy: no
    // placeholder). resp idle until a legal subordinate exists. Not an
    // SMU gap — smu.sv already connects SMC axil_dtp_csr to DTP.
    // ------------------------------------------------------------------
    assign axil_dtp_csr_resp = '0;

    smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl [31:0];

    // ------------------------------------------------------------------
    // DUT: smc_wrapper (smc + smc_ip_integration).
    //
    // Ports absorbed by smc_ip_integration and NOT present on this boundary:
    // smc_external_*, efuse_bank_ctrl_*, efuse_shim_command_*, pad2core_i, core2pad_o,
    // pad2core_en_o, core2pad_en_o (internal smc_wrapper nets → gpio_pad_io).
    // CPU ROM/scratch/L1$ macros and the trace sink RAMs are inside
    // smc_ip_integration.
    // ------------------------------------------------------------------
    smc_wrapper u_dut (
        .clk_smc_i,
        .clk_ref_i,
        .clk_periph_i,
        .powergood_i                (powergood_int),
        .powergood_stable_o,
        .rst_cold_ni                (rst_cold_n_int),
        .rst_cold_stable_ref_clk_no,
        .rst_primary_ref_clk_no,
        .rst_primary_smc_clk_no,
        .rst_wdt_smc_clk_no,
        .rst_primary_periph_clk_no  (),
        .sys_axi_in_req_i           (sys_axi_in_req),
        .sys_axi_in_resp_o          (sys_axi_in_resp),
        .jtag_axi_in_req_i          (jtag_axi_in_req),
        .jtag_axi_in_resp_o         (jtag_axi_in_resp),
        // P2-15 lifecycle-gated eFuse JTAG access-control path.
        .axil_smc_otp_jtag_req_i    (ej_axi_req),
        .axil_smc_otp_jtag_resp_o   (ej_axi_resp),
        .sep_axi_in_req_i           (sep_axi_in_req),
        .sep_axi_in_resp_o          (sep_axi_in_resp),
        .output_axi_req_o           (output_axi_req),
        .output_axi_resp_i          (output_axi_resp),
        .axil_dtp_csr_req_o         (axil_dtp_csr_req),
        .axil_dtp_csr_resp_i        (axil_dtp_csr_resp),
        .shadow_regs_o              (),
        .lsio_interface_select_o    (),
        .gpio_pad_io                (gpio_pad_io),
        .rst_cool_n_from_pin_i      (rst_cool_n_int),
        // SPI octal-flash pads (U2-1). Cocotb drives tb_spi_*; idle default is
        // inactive CS/enable (tests that do not touch SPI leave them at 0).
        .spi_enable_i               (tb_spi_enable),
        .spi_clk_i                  (tb_spi_clk),
        .spi_txd_i                  (tb_spi_txd),
        .spi_cs_n_i                 (tb_spi_cs_n),
        .spi_cs_oe_n_i              (tb_spi_cs_oe_n),
        .spi_cs_ie_n_i              (tb_spi_cs_ie_n),
        .spi_clk_ie_n_i             (tb_spi_clk_ie_n),
        .spi_clk_oe_n_i             (tb_spi_clk_oe_n),
        .spi_dqs_ie_n_i             (tb_spi_dqs_ie_n),
        .spi_dqs_oe_n_i             (tb_spi_dqs_oe_n),
        .spi_dq_ie_n_i              (tb_spi_dq_ie_n),
        .spi_dq_oe_n_i              (tb_spi_dq_oe_n),
        .spi_rxd_o                  (tb_spi_rxd),
        .spi_rxds_o                 (tb_spi_rxds),
        .spi_mem_rebar_oepad_i      (1'b0),
        .spi_mem_rebar_opad_i       (1'b0),
        .spi_mem_rebar_iepad_i      (1'b0),
        .spi_mem_rebar_ipad_o       (tb_spi_mem_rebar_ipad),
        // Telemetry ATB: clock/reset async write domain; receiver 0 driven by
        // tb_telemetry0_* (U4-6); receivers 1/2 remain quiet.
        .clk_telemetry_i            (clk_smc_i),
        .rst_telemetry_ni           (rst_cold_n_int),
        .telemetry_atdata_i         (tb_telemetry_atdata),
        .telemetry_atid_i           (tb_telemetry_atid),
        .telemetry_atready_o       (tb_telemetry_atready),
        .telemetry_atvalid_i        (tb_telemetry_atvalid),
        .telemetry_afvalid_o        (tb_telemetry_afvalid),
        .telemetry_afready_i        (tb_telemetry_afready),
        .cluster_ded_o              (cpu_cluster_ded),
        .wdt_first_timeout_o        (),
        .wdt_second_timeout_o       (),
        .smc_global_base_o          (),
        .smc_region_size_o          (),
        .ext_interrupts_i           ({{(smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS-1){1'b0}},
                                       tb_ext_interrupt_0_i}),
        .sep_mailbox_interrupts_i   (tb_sep_mailbox_interrupts),
        .sep_wdt_reset_n_i          (tb_sep_wdt_reset_n),
        .fuse_sense_done_o,
        .fuse_reset_n_delayed_o     (tb_fuse_reset_n),
        .skip_mem_repair_o          (tb_skip_mem_repair_o),
        .ext_boot_seq_done_i        (~tb_hold_ext_boot),
        .sep_security_disable_i     (1'b0),
        .temp_interrupt_i           (tb_temp_interrupt_i),
        .lc_state_i                 (lc_state_drv),
        .lc_sigint_err_o            (),
        .ras_bank_chip_o            (),
        .ras_bank_instance_o        (),
        .ndmreset_request_i         (tb_ndmreset_request),
        .ndmreset_process_o         (tb_ndmreset_process),
        .ext_mailbox_interrupts_o   (),
        .cfg_flr_pf_active_i        (tb_cfg_flr_pf_active),
        .isolate_req_o              (tb_isolate_req_o),
        .ss_reset_complete_i        (tb_ss_reset_complete),
        .ss_config_o                (),
        .ss_reset_ctrl_o            (ss_reset_ctrl),
        .sync_irq_o                 (sync_irq),
        .disable_sram_auto_init_i   (1'b1),
        .init_mem_done_o,
        .chiplet_is_primary_i       (tb_chiplet_is_primary),
        .timer_count_o              (),
        .boot_stall_jtag_ovrd_i     (tb_boot_stall_jtag_ovrd_i),
        .boot_stall_jtag_val_i      (tb_boot_stall_jtag_val_i),
        .boot_stall_combined_o      (tb_boot_stall_combined_o),
        .jtag_reset_ctrl_i          (jtag_smc_reset_ctrl_t'(tb_jtag_reset_ctrl)),
        .cla_ext_action_custom_o    (),
        .xtrigger_ss_o              (),
        .xtrigger_ss_i              ('0),
        .tdr_dbg_ctrl_clock_stop_en_i (1'b0),
        .tdr_dbg_ctrl_clocks_stopped_by_cla_o (),
        .ext_debug_bus_i            ('0),
        // DFT scan controls: cocotb drives tb_test_en_i (default 0 in bring-up).
        // scan reset deasserted -- matches smc.sv port names (test_en_i / scan_rst_ni).
        .test_en_i                  (tb_test_en_i),
        .scan_rst_ni                (1'b1),
        .captured_straps_i          (tb_captured_straps),
        // Without an external BISR/MBIST agent the boot sequencer would wait
        // forever if these stayed low (CPU never fetches ROM) -- same fix as
        // hw/sys/smu/dv/tb/tb_wrapper_top.sv's smu_wrapper instance.
        .mem_repair_done_i          (1'b1),
        .mem_repair_success_i       (1'b1),
        .mem_repair_abort_i         (tb_mem_repair_abort),
        .mbist_done_i               (1'b1),
        .mbist_pass_i               (1'b1),
        .mbist_abort_i              (tb_mbist_abort),
        .smc_cpu_jtag_TCK_i         (tb_cpu_jtag_tck),
        .smc_cpu_jtag_TMS_i         (tb_cpu_jtag_tms),
        .smc_cpu_jtag_TDI_i         (tb_cpu_jtag_tdi),
        .smc_cpu_jtag_TDO_data_o    (tb_cpu_jtag_tdo),
        .smc_cpu_jtag_reset_i       (tb_cpu_jtag_reset),
        .smc_cpu_jtag_mfr_id_i      (11'h2AA),
        .smc_cpu_jtag_part_number_i (16'h0CA0),
        .smc_cpu_jtag_version_i     (4'h1),
        // I3C controller DAT/DCT memory boundary.
        .i3c_dat_mem_src_i          (i3c_dat_mem_src),
        .i3c_dat_mem_sink_o         (i3c_dat_mem_sink),
        .i3c_dct_mem_src_i          (i3c_dct_mem_src),
        .i3c_dct_mem_sink_o         (i3c_dct_mem_sink),
        .gpio_interrupt_o           (gpio_interrupt),
        .uart_interrupt_o           (uart_interrupt),
        .efuse_debug_bus_o          ()
    );

    // I3C DAT/DCT: NO TB prim_ram (policy: no mem placeholder). Ports idle;
    // I3C tests that need DAT/DCT are deferred until real macros exist.
    assign i3c_dat_mem_src = '0;
    assign i3c_dct_mem_src = '0;

    // Sense-done + sensed shadow probe (XMR into controller shadow regs, one
    // level deeper than bare tb_top: u_dut.u_smc.u_smc_peripherals...).
    assign tb_fuse_sense_done = fuse_sense_done_o;
    // Warm domain leave-reset (post sync). Hierarchical observe for CSR waits.
    assign tb_rst_warm_smc_clk_n = u_dut.u_smc.rst_warm_smc_clk_n;
    assign efuse_shadow_probe_o =
        u_dut.u_smc.u_smc_peripherals.u_smc_efuse_wrapper.u_efuse_interface_controller
            .u_efuse_shadow_regs.shadow_efuse_o;
    // eFuse bank storage is now inside smc_ip_integration's own
    // efuse_bank_model (hw/ip/efuse/dv/models/efuse_bank_model.sv), not a
    // efuse_bank_model. Its "programmed" and "OTP" storage collapse into the
    // same register file, so programmed_word0 mirrors otp_word0.
    assign tb_efuse_otp_word0 =
        u_dut.u_smc_ip_integration.u_efuse_bank_model.u_efuse_bank_reg
            .field_storage.EFUSE_BANK_REG[0].dout.value;
    assign tb_efuse_programmed_word0 = tb_efuse_otp_word0;

    assign tb_i2c_debug_lo    = u_dut.u_smc.i2c_debug[0];
    assign tb_i2c_cg_en       = u_dut.u_smc.cg_ctrl_i2c_cg_en;
    // Shared DMA gated clock = prim_clk_gater_hysteresis in idma_wrapper
    // (request_manager + backend domain). Passive-only assign; no force/deposit.
    assign tb_dma_cg_en = u_dut.u_smc.u_smc_base.cg_ctrl_dma_cg_en;
    assign tb_dma_gated_clk =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_dma_wrap
            .request_maneger_cg.gated_clk_o;
    assign tb_dma_busy = u_dut.u_smc.u_smc_base.dma_busy;
    assign tb_dma_frontend_busy =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_dma_wrap
            .dma_frontend_busy;
    assign tb_dma_backend_busy =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_dma_wrap
            .dma_backend_busy;
    assign tb_dma_gater_busy =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_dma_wrap
            .dma_busy;
    // Zeroer gated clocks / busy / enable — read-only assign; no force/deposit.
    assign tb_zeroer_cg_en = u_dut.u_smc.u_smc_base.cg_ctrl_zeroer_cg_en;
    assign tb_zeroer_gated_axi_clk =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_zeroer.axi_clk;
    assign tb_zeroer_gated_reg_clk =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_zeroer.reg_clk;
    assign tb_zeroer_busy = u_dut.u_smc.u_smc_base.zeroer_busy;
    assign tb_zeroer_bus_active = u_dut.u_smc.u_smc_base.zeroer_bus_active;

    // State-corruption hooks use the established clock-reissued force/release
    // convention above because no legal transaction can create an unused FSM
    // encoding or make the bank model return an error. Requests and output
    // checks stay on the real DUT paths; forcing is limited to the state flops
    // and read-error inputs, and every force is released by its enable.
`define SMC_ZEROER u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_zeroer
    assign tb_zeroer_state = `SMC_ZEROER.cur_state;
    assign tb_zeroer_intp = `SMC_ZEROER.zeroer_intp_o;
    assign tb_zeroer_awvalid = `SMC_ZEROER.mst_awvalid;
    assign tb_zeroer_wvalid = `SMC_ZEROER.mst_wvalid;
    always @(posedge clk_smc_i) begin
        if (tb_zeroer_state_inject_en === 1'b1) begin
            force `SMC_ZEROER.cur_state[2:0] = tb_zeroer_state_inject;
        end else begin
            release `SMC_ZEROER.cur_state[2:0];
        end
    end
`undef SMC_ZEROER

`define SMC_EFUSE_IFC \
    u_dut.u_smc.u_smc_peripherals.u_smc_efuse_wrapper.u_efuse_interface_controller
`define SMC_EFUSE_PROGRAM `SMC_EFUSE_IFC.u_efuse_program_interface
`define SMC_EFUSE_READ    `SMC_EFUSE_IFC.u_efuse_read_interface
    assign tb_efuse_program_state = `SMC_EFUSE_PROGRAM.program_state_q;
    assign tb_efuse_program_req_valid = `SMC_EFUSE_PROGRAM.fuse_command_req_o.valid;
    assign tb_efuse_program_busy = `SMC_EFUSE_PROGRAM.program_busy_o;
    assign tb_efuse_program_done = `SMC_EFUSE_PROGRAM.program_done_o;
    assign tb_efuse_program_error = `SMC_EFUSE_PROGRAM.program_error_o;
    assign tb_efuse_program_readback = `SMC_EFUSE_PROGRAM.program_read_back_data_o;
    assign tb_efuse_read_state = `SMC_EFUSE_READ.read_state_q;
    assign tb_efuse_read_req_valid = `SMC_EFUSE_READ.fuse_command_req_o.valid;
    assign tb_efuse_read_busy = `SMC_EFUSE_READ.read_busy_o;
    assign tb_efuse_read_done = `SMC_EFUSE_READ.read_done_o;
    assign tb_efuse_read_error = `SMC_EFUSE_READ.read_error_o;
    assign tb_efuse_readback = `SMC_EFUSE_READ.read_back_data_o;
    always @(posedge clk_smc_i) begin
        if (tb_efuse_program_state_inject_en === 1'b1) begin
            force `SMC_EFUSE_PROGRAM.program_state_q[1:0] = tb_efuse_program_state_inject;
        end else begin
            release `SMC_EFUSE_PROGRAM.program_state_q[1:0];
        end
        if (tb_efuse_read_state_inject_en === 1'b1) begin
            force `SMC_EFUSE_READ.read_state_q[1:0] = tb_efuse_read_state_inject;
        end else begin
            release `SMC_EFUSE_READ.read_state_q[1:0];
        end
        if (tb_efuse_read_error_inject === 2'b01) begin
            force `SMC_EFUSE_IFC.fuse_command_resp_interface_ctrl_r.status = 1'b1;
        end else begin
            release `SMC_EFUSE_IFC.fuse_command_resp_interface_ctrl_r.status;
        end
        if (tb_efuse_read_error_inject === 2'b10) begin
            force `SMC_EFUSE_READ.efuse_req_err_i = 1'b1;
        end else begin
            release `SMC_EFUSE_READ.efuse_req_err_i;
        end
        if (tb_efuse_read_error_inject === 2'b11) begin
            force `SMC_EFUSE_READ.secure_tm_blocked_i = 1'b1;
        end else begin
            release `SMC_EFUSE_READ.secure_tm_blocked_i;
        end
    end
`undef SMC_EFUSE_READ
`undef SMC_EFUSE_PROGRAM
`undef SMC_EFUSE_IFC

    assign tb_sync_irq        = sync_irq;
    assign tb_gpio_irq_any    = |gpio_interrupt;
    assign tb_axi_hang_irq      = u_dut.u_smc.u_smc_base.axi_hang_irq_o;
    assign tb_axi_hang_irq_sys  = u_dut.u_smc.u_smc_base.hang_irq_sys_axi;
    assign tb_axi_hang_irq_sep  = u_dut.u_smc.u_smc_base.hang_irq_sep_axi;
    assign tb_axi_hang_irq_data = u_dut.u_smc.u_smc_base.hang_irq_data_accel;
    assign tb_axi_hang_irq_periph31 = u_dut.u_smc.peripheral_interrupts[31];
    assign tb_axi_hang_irq_plic_src =
        u_dut.u_smc.cpu_interrupts[smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS + 31];
    assign tb_gpio_pad57      = u_dut.u_smc.pad2core_i[BOOT_STALL_PAD];
    assign tb_uart_irq_any    = |uart_interrupt;
    assign tb_mailbox_irq_any = |u_dut.u_smc.peripheral_interrupts[7:0];
    assign tb_avsbus_irq      = u_dut.u_smc.peripheral_interrupts[22];
    assign tb_telemetry_irq_any = |u_dut.u_smc.peripheral_interrupts[10:8];
    assign tb_efuse_locked_access_irq = u_dut.u_smc.peripheral_interrupts[28];
    assign tb_temp_interrupt_irq = u_dut.u_smc.peripheral_interrupts[27];
    assign tb_ext_interrupt_0_sync = u_dut.u_smc.u_smc_base.ext_interrupts_smc_clk[0];
    assign tb_ss0_warm_reset_n = ss_reset_ctrl[0].warm_reset_n;
    assign tb_ndmreset_irq = u_dut.u_smc.peripheral_interrupts[11];
    assign tb_rst_cool_from_flr =
        u_dut.u_smc.u_smc_peripherals.u_smc_reset_unit.rst_cool_no;
    assign tb_avsbus_cur_state_debug = u_dut.u_smc.avsbus_cur_state_debug;

    assign tb_gpio_core2pad_any    = |u_dut.u_smc.core2pad_o;
    assign tb_gpio_core2pad_en_any = |u_dut.u_smc.core2pad_en_o;
    assign tb_gpio_pad2core_en_any = |u_dut.u_smc.pad2core_en_o;
    assign tb_core2pad_o           = u_dut.u_smc.core2pad_o;
    assign tb_core2pad_en_o        = u_dut.u_smc.core2pad_en_o;

    // Per-interface idle observability -- drives Batch B per-module sanity
    // tests. Sample all four external-macro masters from real smc ports so
    // the active pulse is visible even when a wrapper/TB wire does not track
    // the same cycle as the cocotb latch (PLL/PVT/extension already did this).
    assign tb_axil_dtp_csr_active    = u_dut.u_smc.axil_dtp_csr_req_o.aw_valid
                                     | u_dut.u_smc.axil_dtp_csr_req_o.w_valid
                                     | u_dut.u_smc.axil_dtp_csr_req_o.ar_valid;
    assign tb_axil_external_active   = u_dut.u_smc.smc_external_req_o.aw_valid
                                     | u_dut.u_smc.smc_external_req_o.w_valid
                                     | u_dut.u_smc.smc_external_req_o.ar_valid;
    assign tb_axil_efuse_bank_active = u_dut.u_smc.efuse_bank_ctrl_req_o.aw_valid | u_dut.u_smc.efuse_bank_ctrl_req_o.w_valid |
                                       u_dut.u_smc.efuse_bank_ctrl_req_o.ar_valid;
    assign tb_axil_any_master_active = tb_axil_dtp_csr_active | tb_axil_external_active | tb_axil_efuse_bank_active;

    // Hierarchical CPU debug (pre-isolate-clamp PC + boundary isolate).
    assign tb_cpu_wb_pc0 =
        u_dut.u_smc.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu.wb_reg_pc_raw[0];
    assign tb_cpu_cluster_isolate =
        u_dut.u_smc.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu.cluster_boundary_isolate;
    assign tb_cpu_debug_dmactive =
        u_dut.u_smc.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu.debug_dmactive;
    assign tb_cpu_debug_dmactive_ack =
        u_dut.u_smc.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu.debug_dmactiveAck;

    // TB-GLUE only (deferred test): pulse tb_dfd_fault_inject to latch a
    // deterministic token. This is NOT smc_dfd_wrap / hw/ip/dfd coverage.
    // See hw/sys/smc/doc/dv_hack_cleanup_checklist.md Phase 1.1.
    // Hart0 PC can be X before CPU bring-up, so do not sample hierarchical PC
    // into the public capture port (cocotb cannot int() X).
    always_ff @(posedge clk_smc_i or negedge rst_cold_n_int) begin
        if (!rst_cold_n_int) begin
            tb_dbs_capture_valid <= 1'b0;
            tb_dbs_capture_data  <= '0;
        end else if (tb_dfd_fault_inject) begin
            tb_dbs_capture_valid <= 1'b1;
            tb_dbs_capture_data  <= 32'hDB5C_AFE1;  // TB token, not DUT DFD
        end
    end

    // ------------------------------------------------------------------
    // Elaboration aliases (additive; see header comment).
    // ------------------------------------------------------------------
    assign dut_present_o = 1'b1;
    assign powergood_o    = powergood_stable_o;
    assign rst_cold_n_o   = rst_cold_stable_ref_clk_no;
    assign smc_reset_n_o  = rst_primary_smc_clk_no;
    assign smc_scratch_0_o =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[0];
    assign smc_test_pass_o = (smc_scratch_0_o == SMC_TEST_PASS);
    assign smc_test_fail_o = (smc_scratch_0_o == SMC_TEST_FAIL);
    assign output_axi_write_count_o = tb_output_axi_write_count;
    assign output_axi_read_count_o  = tb_output_axi_read_count;


`ifdef UVM
    // ------------------------------------------------------------------
    // SV-UVM harness (`--dut smc --framework uvm`): clocks, the shared-VIP
    // interface instances on the SEP_IN AXI4 ingress, quiescent tie-offs
    // for every other cocotb-driven stimulus pin, uvm_config_db
    // publication, and run_test(). Compiled only when the native uvm flow
    // defines UVM; the cocotb flow sees only the ported module above.
    // ------------------------------------------------------------------
    import uvm_pkg::*;

    smc_tb_if u_tb_if ();

    // Three free-running clocks with the periods the env publishes on
    // smc_tb_if from the seeded test cfg (cocotb SmcEnvCfg.randomize_timing
    // parity: ref/periph 8..12 ns, smc 4..6 ns).
    initial begin
        clk_ref_i    = 1'b0;
        clk_smc_i    = 1'b0;
        clk_periph_i = 1'b0;
    end
    always #(u_tb_if.ref_clk_period_ns * 0.5ns)    clk_ref_i    = ~clk_ref_i;
    always #(u_tb_if.smc_clk_period_ns * 0.5ns)    clk_smc_i    = ~clk_smc_i;
    always #(u_tb_if.periph_clk_period_ns * 0.5ns) clk_periph_i = ~clk_periph_i;

    // Power-good and the cold/cool reset pins are test-sequenced through
    // smc_tb_if; the reset-unit outputs and the fuse-sense / warm-domain
    // release observables are mirrored back for the sequences and the
    // scoreboard.
    assign powergood_i = u_tb_if.powergood;
    assign rst_cold_ni = u_tb_if.rst_cold_n;
    assign rst_cool_ni = u_tb_if.rst_cool_n;
    assign u_tb_if.powergood_stable          = powergood_stable_o;
    assign u_tb_if.rst_cold_stable_ref_clk_n = rst_cold_stable_ref_clk_no;
    assign u_tb_if.rst_primary_ref_clk_n     = rst_primary_ref_clk_no;
    assign u_tb_if.rst_primary_smc_clk_n     = rst_primary_smc_clk_no;
    assign u_tb_if.rst_wdt_smc_clk_n         = rst_wdt_smc_clk_no;
    assign u_tb_if.fuse_sense_done           = tb_fuse_sense_done;
    assign u_tb_if.fuse_reset_n              = tb_fuse_reset_n;
    assign u_tb_if.rst_warm_smc_clk_n        = tb_rst_warm_smc_clk_n;

    // Cold-reset assertion counter: the scoreboard predictors re-baseline
    // their CSR shadows on it.
    logic [31:0] cold_rst_assert_count = '0;
    always @(negedge rst_cold_ni) cold_rst_assert_count <= cold_rst_assert_count + 32'd1;
    assign u_tb_if.cold_rst_assert_count = cold_rst_assert_count;

    // SEP_IN AXI4 initiator: the shared ocah_axi_vip UVM master agent drives
    // the s_axi_* request side (the agent's driver procedurally drives the
    // request payloads and valids plus bready/rready on the master
    // interface, routed out to the DUT here) and the TB wires only the
    // DUT-driven response signals back in. Geometry (56/64/6) lives in the
    // master cfg; the interface uses the default maximum widths.
    ocah_axi_if u_sep_in_master_if (.aclk(clk_smc_i), .aresetn(rst_primary_smc_clk_no));
    assign s_axi_awid     = u_sep_in_master_if.awid[5:0];
    assign s_axi_awaddr   = u_sep_in_master_if.awaddr[55:0];
    assign s_axi_awlen    = u_sep_in_master_if.awlen;
    assign s_axi_awsize   = u_sep_in_master_if.awsize;
    assign s_axi_awburst  = u_sep_in_master_if.awburst;
    assign s_axi_awlock   = u_sep_in_master_if.awlock;
    assign s_axi_awcache  = u_sep_in_master_if.awcache;
    assign s_axi_awprot   = u_sep_in_master_if.awprot;
    assign s_axi_awqos    = u_sep_in_master_if.awqos;
    assign s_axi_awregion = u_sep_in_master_if.awregion;
    assign s_axi_awuser   = u_sep_in_master_if.awuser[11:0];
    assign s_axi_awvalid  = u_sep_in_master_if.awvalid;
    assign s_axi_wdata    = u_sep_in_master_if.wdata;
    assign s_axi_wstrb    = u_sep_in_master_if.wstrb;
    assign s_axi_wlast    = u_sep_in_master_if.wlast;
    assign s_axi_wuser    = u_sep_in_master_if.wuser[11:0];
    assign s_axi_wvalid   = u_sep_in_master_if.wvalid;
    assign s_axi_bready   = u_sep_in_master_if.bready;
    assign s_axi_arid     = u_sep_in_master_if.arid[5:0];
    assign s_axi_araddr   = u_sep_in_master_if.araddr[55:0];
    assign s_axi_arlen    = u_sep_in_master_if.arlen;
    assign s_axi_arsize   = u_sep_in_master_if.arsize;
    assign s_axi_arburst  = u_sep_in_master_if.arburst;
    assign s_axi_arlock   = u_sep_in_master_if.arlock;
    assign s_axi_arcache  = u_sep_in_master_if.arcache;
    assign s_axi_arprot   = u_sep_in_master_if.arprot;
    assign s_axi_arqos    = u_sep_in_master_if.arqos;
    assign s_axi_arregion = u_sep_in_master_if.arregion;
    assign s_axi_aruser   = u_sep_in_master_if.aruser[11:0];
    assign s_axi_arvalid  = u_sep_in_master_if.arvalid;
    assign s_axi_rready   = u_sep_in_master_if.rready;

    // Response side: DUT subordinate -> agent driver/monitor.
    assign u_sep_in_master_if.awready = s_axi_awready;
    assign u_sep_in_master_if.wready  = s_axi_wready;
    assign u_sep_in_master_if.bid     = 16'(s_axi_bid);
    assign u_sep_in_master_if.bresp   = s_axi_bresp;
    assign u_sep_in_master_if.buser   = 16'(s_axi_buser);
    assign u_sep_in_master_if.bvalid  = s_axi_bvalid;
    assign u_sep_in_master_if.arready = s_axi_arready;
    assign u_sep_in_master_if.rid     = 16'(s_axi_rid);
    assign u_sep_in_master_if.rdata   = s_axi_rdata;
    assign u_sep_in_master_if.rresp   = s_axi_rresp;
    assign u_sep_in_master_if.rlast   = s_axi_rlast;
    assign u_sep_in_master_if.ruser   = 16'(s_axi_ruser);
    assign u_sep_in_master_if.rvalid  = s_axi_rvalid;

    // The SEP_IN R-channel hold is a cocotb hang-detector control; the UVM
    // shape keeps the channel transparent.
    assign tb_sep_axi_r_hold = 1'b0;

    // Passive mirror of the SEP_IN bus for the shared-VIP monitor (the
    // smc_scoreboard predictors consume its item stream) and the protocol
    // SVA, wired from the DUT-facing flat nets only.
    ocah_axi_if u_sep_in_axi_if (.aclk(clk_smc_i), .aresetn(rst_primary_smc_clk_no));
    assign u_sep_in_axi_if.awid     = 16'(s_axi_awid);
    assign u_sep_in_axi_if.awaddr   = 64'(s_axi_awaddr);
    assign u_sep_in_axi_if.awlen    = s_axi_awlen;
    assign u_sep_in_axi_if.awsize   = s_axi_awsize;
    assign u_sep_in_axi_if.awburst  = s_axi_awburst;
    assign u_sep_in_axi_if.awlock   = s_axi_awlock;
    assign u_sep_in_axi_if.awcache  = s_axi_awcache;
    assign u_sep_in_axi_if.awprot   = s_axi_awprot;
    assign u_sep_in_axi_if.awqos    = s_axi_awqos;
    assign u_sep_in_axi_if.awregion = s_axi_awregion;
    assign u_sep_in_axi_if.awuser   = 16'(s_axi_awuser);
    assign u_sep_in_axi_if.awvalid  = s_axi_awvalid;
    assign u_sep_in_axi_if.awready  = s_axi_awready;
    assign u_sep_in_axi_if.wdata    = s_axi_wdata;
    assign u_sep_in_axi_if.wstrb    = s_axi_wstrb;
    assign u_sep_in_axi_if.wlast    = s_axi_wlast;
    assign u_sep_in_axi_if.wuser    = 16'(s_axi_wuser);
    assign u_sep_in_axi_if.wvalid   = s_axi_wvalid;
    assign u_sep_in_axi_if.wready   = s_axi_wready;
    assign u_sep_in_axi_if.bid      = 16'(s_axi_bid);
    assign u_sep_in_axi_if.bresp    = s_axi_bresp;
    assign u_sep_in_axi_if.buser    = 16'(s_axi_buser);
    assign u_sep_in_axi_if.bvalid   = s_axi_bvalid;
    assign u_sep_in_axi_if.bready   = s_axi_bready;
    assign u_sep_in_axi_if.arid     = 16'(s_axi_arid);
    assign u_sep_in_axi_if.araddr   = 64'(s_axi_araddr);
    assign u_sep_in_axi_if.arlen    = s_axi_arlen;
    assign u_sep_in_axi_if.arsize   = s_axi_arsize;
    assign u_sep_in_axi_if.arburst  = s_axi_arburst;
    assign u_sep_in_axi_if.arlock   = s_axi_arlock;
    assign u_sep_in_axi_if.arcache  = s_axi_arcache;
    assign u_sep_in_axi_if.arprot   = s_axi_arprot;
    assign u_sep_in_axi_if.arqos    = s_axi_arqos;
    assign u_sep_in_axi_if.arregion = s_axi_arregion;
    assign u_sep_in_axi_if.aruser   = 16'(s_axi_aruser);
    assign u_sep_in_axi_if.arvalid  = s_axi_arvalid;
    assign u_sep_in_axi_if.arready  = s_axi_arready;
    assign u_sep_in_axi_if.rid      = 16'(s_axi_rid);
    assign u_sep_in_axi_if.rdata    = s_axi_rdata;
    assign u_sep_in_axi_if.rresp    = s_axi_rresp;
    assign u_sep_in_axi_if.rlast    = s_axi_rlast;
    assign u_sep_in_axi_if.ruser    = 16'(s_axi_ruser);
    assign u_sep_in_axi_if.rvalid   = s_axi_rvalid;
    assign u_sep_in_axi_if.rready   = s_axi_rready;

    ocah_axi_sva #(
        .IS_LITE    (1'b0),
        .ADDR_WIDTH (56),
        .DATA_WIDTH (64),
        .ID_WIDTH   (6)
    ) u_sep_in_axi_sva (
        .aclk    (clk_smc_i),
        .aresetn (rst_primary_smc_clk_no),
        .en_i    (u_tb_if.axi_sva_en),
        .awid    (s_axi_awid),
        .awaddr  (s_axi_awaddr),
        .awlen   (s_axi_awlen),
        .awsize  (s_axi_awsize),
        .awburst (s_axi_awburst),
        .awlock  (s_axi_awlock),
        .awprot  (s_axi_awprot),
        .awvalid (s_axi_awvalid),
        .awready (s_axi_awready),
        .wdata   (s_axi_wdata),
        .wstrb   (s_axi_wstrb),
        .wlast   (s_axi_wlast),
        .wvalid  (s_axi_wvalid),
        .wready  (s_axi_wready),
        .bid     (s_axi_bid),
        .bresp   (s_axi_bresp),
        .bvalid  (s_axi_bvalid),
        .bready  (s_axi_bready),
        .arid    (s_axi_arid),
        .araddr  (s_axi_araddr),
        .arlen   (s_axi_arlen),
        .arsize  (s_axi_arsize),
        .arburst (s_axi_arburst),
        .arlock  (s_axi_arlock),
        .arprot  (s_axi_arprot),
        .arvalid (s_axi_arvalid),
        .arready (s_axi_arready),
        .rid     (s_axi_rid),
        .rdata   (s_axi_rdata),
        .rresp   (s_axi_rresp),
        .rlast   (s_axi_rlast),
        .rvalid  (s_axi_rvalid),
        .rready  (s_axi_rready)
    );

    // ------------------------------------------------------------------
    // Quiescent tie-offs: every other cocotb-driven stimulus pin at the idle
    // value the cocotb smc_base_test bring-up sets. A scenario that needs
    // one of these pins promotes it into smc_tb_if; nothing here is driven
    // from class code.
    // ------------------------------------------------------------------

    // SYS_IN and JTAG AXI4 ingresses and the JTAG-side eFuse AXI-Lite master:
    // no initiator attached, request side idle.
    assign sys_axi_awid     = '0;
    assign sys_axi_awaddr   = '0;
    assign sys_axi_awlen    = '0;
    assign sys_axi_awsize   = '0;
    assign sys_axi_awburst  = '0;
    assign sys_axi_awlock   = 1'b0;
    assign sys_axi_awcache  = '0;
    assign sys_axi_awprot   = '0;
    assign sys_axi_awqos    = '0;
    assign sys_axi_awregion = '0;
    assign sys_axi_awuser   = '0;
    assign sys_axi_awvalid  = 1'b0;
    assign sys_axi_wdata    = '0;
    assign sys_axi_wstrb    = '0;
    assign sys_axi_wlast    = 1'b0;
    assign sys_axi_wuser    = '0;
    assign sys_axi_wvalid   = 1'b0;
    assign sys_axi_bready   = 1'b0;
    assign sys_axi_arid     = '0;
    assign sys_axi_araddr   = '0;
    assign sys_axi_arlen    = '0;
    assign sys_axi_arsize   = '0;
    assign sys_axi_arburst  = '0;
    assign sys_axi_arlock   = 1'b0;
    assign sys_axi_arcache  = '0;
    assign sys_axi_arprot   = '0;
    assign sys_axi_arqos    = '0;
    assign sys_axi_arregion = '0;
    assign sys_axi_aruser   = '0;
    assign sys_axi_arvalid  = 1'b0;
    assign sys_axi_rready   = 1'b0;
    assign tb_sys_axi_r_hold = 1'b0;

    assign jtag_axi_awid     = '0;
    assign jtag_axi_awaddr   = '0;
    assign jtag_axi_awlen    = '0;
    assign jtag_axi_awsize   = '0;
    assign jtag_axi_awburst  = '0;
    assign jtag_axi_awlock   = 1'b0;
    assign jtag_axi_awcache  = '0;
    assign jtag_axi_awprot   = '0;
    assign jtag_axi_awqos    = '0;
    assign jtag_axi_awregion = '0;
    assign jtag_axi_awuser   = '0;
    assign jtag_axi_awvalid  = 1'b0;
    assign jtag_axi_wdata    = '0;
    assign jtag_axi_wstrb    = '0;
    assign jtag_axi_wlast    = 1'b0;
    assign jtag_axi_wuser    = '0;
    assign jtag_axi_wvalid   = 1'b0;
    assign jtag_axi_bready   = 1'b0;
    assign jtag_axi_arid     = '0;
    assign jtag_axi_araddr   = '0;
    assign jtag_axi_arlen    = '0;
    assign jtag_axi_arsize   = '0;
    assign jtag_axi_arburst  = '0;
    assign jtag_axi_arlock   = 1'b0;
    assign jtag_axi_arcache  = '0;
    assign jtag_axi_arprot   = '0;
    assign jtag_axi_arqos    = '0;
    assign jtag_axi_arregion = '0;
    assign jtag_axi_aruser   = '0;
    assign jtag_axi_arvalid  = 1'b0;
    assign jtag_axi_rready   = 1'b0;

    assign ej_axi_awaddr  = '0;
    assign ej_axi_awprot  = '0;
    assign ej_axi_awvalid = 1'b0;
    assign ej_axi_wdata   = '0;
    assign ej_axi_wstrb   = '0;
    assign ej_axi_wvalid  = 1'b0;
    assign ej_axi_bready  = 1'b0;
    assign ej_axi_araddr  = '0;
    assign ej_axi_arprot  = '0;
    assign ej_axi_arvalid = 1'b0;
    assign ej_axi_rready  = 1'b0;

    // SYS_OUT responder controls: no error injection, no response hold.
    assign tb_output_err_we        = 1'b0;
    assign tb_output_err_addr      = '0;
    assign tb_output_err_resp      = '0;
    assign tb_output_axi_resp_hold = 1'b0;

    // DFT functional mode; open-drain I2C0/I3C0 lines released; CPU JTAG TAP
    // parked (TMS high, reset asserted); UART0 RX idle-high.
    assign tb_test_en_i        = 1'b0;
    assign tb_i2c0_scl_ext_low = 1'b0;
    assign tb_i2c0_sda_ext_low = 1'b0;
    assign tb_i3c0_scl_ext_low = 1'b0;
    assign tb_i3c0_sda_ext_low = 1'b0;
    assign tb_cpu_jtag_tck     = 1'b0;
    assign tb_cpu_jtag_tms     = 1'b1;
    assign tb_cpu_jtag_tdi     = 1'b0;
    assign tb_cpu_jtag_reset   = 1'b1;
    assign tb_uart0_rx_ext_drive = 1'b1;

    // Telemetry ATB receiver 0 quiet with AFREADY high.
    assign tb_telemetry0_atdata  = '0;
    assign tb_telemetry0_atid    = '0;
    assign tb_telemetry0_atvalid = 1'b0;
    assign tb_telemetry0_afready = 1'b1;

    // SPI octal pads idle-safe: mux off, CS deasserted, OE/IE negated high.
    assign tb_spi_enable   = 1'b0;
    assign tb_spi_clk      = 1'b0;
    assign tb_spi_txd      = '0;
    assign tb_spi_cs_n     = 1'b1;
    assign tb_spi_cs_oe_n  = 1'b1;
    assign tb_spi_cs_ie_n  = 1'b1;
    assign tb_spi_clk_ie_n = 1'b1;
    assign tb_spi_clk_oe_n = 1'b1;
    assign tb_spi_dqs_ie_n = 1'b1;
    assign tb_spi_dqs_oe_n = 1'b1;
    assign tb_spi_dq_ie_n  = '1;
    assign tb_spi_dq_oe_n  = '1;
    assign tb_spi_miso_ext = 1'b0;

    // Boot-stall JTAG override off; SEP WDT reset released; PCIe FLR idle;
    // NDM reset requests idle; interrupt pins idle; straps zero; every
    // subsystem reports reset complete; JTAG reset override off; DFX aborts
    // clear.
    assign tb_boot_stall_jtag_ovrd_i = 1'b0;
    assign tb_boot_stall_jtag_val_i  = 1'b0;
    assign tb_sep_wdt_reset_n        = 1'b1;
    assign tb_cfg_flr_pf_active      = 1'b0;
    assign tb_ndmreset_request       = '0;
    assign tb_temp_interrupt_i       = 1'b0;
    assign tb_ext_interrupt_0_i      = 1'b0;
    assign tb_captured_straps        = '0;
    assign tb_ss_reset_complete      = '1;
    assign tb_jtag_reset_ctrl        = '0;
    assign tb_mem_repair_abort       = 1'b0;
    assign tb_mbist_abort            = 1'b0;

    // Sideband: AVSBus sdata pull-up high, primary chiplet, OCTS secondary
    // inject idle-low; SEP mailbox interrupts idle; no GPIO external drive.
    assign tb_avs_sdata_ext          = 1'b1;
    assign tb_chiplet_is_primary     = 1'b1;
    assign tb_octs_sync_load_ext     = 1'b0;
    assign tb_octs_cnt_credit_ext    = 1'b0;
    assign tb_sep_mailbox_interrupts = '0;
    assign tb_gpio_ext_drive_en      = '0;
    assign tb_gpio_ext_drive_value   = '0;

    // CPU memory ECC injection and the DFD fault inject off.
    assign tb_cpu_ecc_inject_sbe   = 1'b0;
    assign tb_cpu_ecc_inject_dbe   = 1'b0;
    assign tb_cpu_ecc_inject_probe = 1'b0;
    assign tb_cpu_ecc_poke_en      = 1'b0;
    assign tb_cpu_ecc_poke_entry   = '0;
    assign tb_cpu_ecc_poke_mask    = '0;
    assign tb_dfd_fault_inject     = 1'b0;

    // Product lifecycle state idle: complementary TEST_DEV ({~0, 0}).
    assign tb_lc_state = {{smc_pkg::LC_STATE_WIDTH{1'b1}}, {smc_pkg::LC_STATE_WIDTH{1'b0}}};

    // Non-reusable test classes compile as part of this top (module scope).
    `include "smc_tests.sv"

    initial begin
        uvm_config_db#(virtual smc_tb_if)::set(null, "*", "tb_vif", u_tb_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "sep_in_master_vif", u_sep_in_master_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "sep_in_axi_vif", u_sep_in_axi_if);
        run_test();
    end
`endif

endmodule : smc_uvm_top

# Entropy Source Component Integration Notes

## CSR Memory Map

We have 39 32-bit configuration and status registers spanning addresses
0x00 through 0xBF. The registers are definitively described in the
entropy_source.rdl file.

The interface to the CSR is through the APB4 slave described in the
next section.

## Pin Interface

The SystemVerilog top level entropy_source.sv declares the following pins:

    // Global Interface
    input  logic        clk_i,
    input  logic        rst_ni,

    // APB4 Register Interface
    input  reg_addr_t   paddr_i,
    input  logic [2:0]  pprot_i,
    input  logic        psel_i,
    input  logic        penable_i,
    input  logic        pwrite_i,
    input  reg_data_t   pwdata_i,
    input  reg_strb_t   pstrb_i,
    output logic        pready_o,
    output reg_data_t   prdata_o,
    output logic        pslverr_o,

    output logic        signal_monitor_o,
    input  logic        rosc_sample_clk_i,

    output logic [31:0] entropy_stream_data_o,
    output logic [31:0] entropy_stream_vld_o,
    output logic        irq_o

Here are instructions on what to hook up and where:

1. clk_i and rst_ni are assumed to be SoC internal global clock and active low,
   asynchronous reset

2. APB4 signals are a collection of signals for the AMBA APB4 slave port
   to be connected to the System NoC

3. signal_monitor_o is an external output pin which can be muxed with GPIO.
   We expect this signal to be below 50 MHz in frequency and are flexible
   in this regard. It is a debug output pin.

4. rosc_sample_clk_i is a separate, asynchronous clock which can be driven
   by an internal PLL. We expect the frequency range to be in the range of
   100 to 400 MHz

5. The outputs entropy_stream_data_o[31:0] and entropy_stream_vld_o are
   not required and can be left *unconnected*.

6. irq_o is an interrupt signal which should be routed to a the CPU
   programmable interrupt controller. If this is difficult, we can
   leave it *unconnected*.

## Physical Design

The Synopsys timing constraint file is entropy_source.sdc located under the
syn directory.
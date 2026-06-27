// Copyright 2023 ETH Zurich and University of Bologna.
// Solderpad Hardware License, Version 0.51, see LICENSE for details.
// SPDX-License-Identifier: SHL-0.51
//
// Authors:
// - Thiemo Zaugg <zauggth@ethz.ch>


`timescale 1 ns/1 ps
`include "axi_stream/assign.svh"
module tb_axi_stream_dw_downsizer ();

  localparam int unsigned DW_IN = 32;
  localparam int unsigned DW_OUT = 8;
  localparam int unsigned ID_WIDTH  = 0;
  localparam int unsigned DEST_WIDTH  = 0;
  localparam int unsigned USER_WIDTH  = 0;
  localparam tCK = 8ns;

  logic clk_i ;
  logic rst_ni;
  logic eos    = 0;

  logic [DW_OUT-1:0] data_recv;
  logic              last_recv;

  // -------------- AXI Stream Driveres -------------
  // master driver
  AXI_STREAM_BUS_DV #(
    .DataWidth(DW_IN),
    .IdWidth  (ID_WIDTH),
    .DestWidth(DEST_WIDTH),
    .UserWidth(USER_WIDTH)
  ) master_dv (
    .clk_i(clk_i)
  );

  AXI_STREAM_BUS #(
    .DataWidth(DW_IN),
    .IdWidth  (ID_WIDTH),
    .DestWidth(DEST_WIDTH),
    .UserWidth(USER_WIDTH)
  ) master();

  `AXI_STREAM_ASSIGN(master, master_dv);

  typedef axi_stream_test::axi_stream_rand_tx #(
    .DataWidth (DW_IN),
    .IdWidth   (ID_WIDTH),
    .DestWidth (DEST_WIDTH),
    .UserWidth (USER_WIDTH),
    .TestTime  (tCK/2),
    .MinWaitCycles(0),
    .MaxWaitCycles(50)
  ) master_drv_t;

  master_drv_t master_drv = new(master_dv, "master");

  // slave driver
    AXI_STREAM_BUS_DV #(
    .DataWidth(DW_OUT),
    .IdWidth  (ID_WIDTH),
    .DestWidth(DEST_WIDTH),
    .UserWidth(USER_WIDTH)
  ) slave_dv (
    .clk_i(clk_i)
  );

  AXI_STREAM_BUS #(
    .DataWidth(DW_OUT),
    .IdWidth  (ID_WIDTH),
    .DestWidth(DEST_WIDTH),
    .UserWidth(USER_WIDTH)
  ) slave();

  `AXI_STREAM_ASSIGN(slave_dv, slave);

  typedef axi_stream_test::axi_stream_rand_rx #(
    .DataWidth (DW_OUT),
    .IdWidth   (ID_WIDTH),
    .DestWidth (DEST_WIDTH),
    .UserWidth (USER_WIDTH),
    .TestTime  (tCK/2),
    .MinWaitCycles(0),
    .MaxWaitCycles(50)
  ) slave_drv_t;

  slave_drv_t slave_drv = new(slave_dv, "slave");

  // --------------------- DUT ------------------------
  axi_stream_dw_downsizer_intf #(
    .DataWidthIn (DW_IN     ),
    .DataWidthOut(DW_OUT    ),
    .IdWidth     (ID_WIDTH  ),
    .DestWidth   (DEST_WIDTH),
    .UserWidth   (USER_WIDTH)
  ) axi_stream_dw_downsizer_inst (
    .clk_i   (clk_i ),
    .rst_ni  (rst_ni),
    .axis_in (master),
    .axis_out(slave )
  );

  // ---------------- CLOCK GENERATION ------------------
  initial begin
     while (!eos) begin
        clk_i <= 1;
        #(tCK/2);
        clk_i <= 0;
        #(tCK/2);
     end
  end

  // ------------------- TEST ------------------------
  initial begin
    eos = 1'b0;

    // RESET
    master_drv.reset();
    slave_drv.reset();
    rst_ni <= 0;
    repeat(5) @(posedge clk_i);
    rst_ni <= 1;
    @(posedge clk_i);

    // TEST 1: double transmit with interupted data_in (but on time)
    transmit_and_assert(1'b0); // without tlast asserted
    transmit_and_assert(1'b1); // with tlast asserted
    @(posedge clk_i);

    // TEST 2: double transmit with uninterupted data_in
    double_transmit_and_assert(1'b1, 0, 0);
    @(posedge clk_i);

    // TEST 3: double transmit with interupted data_in (data not on time)
    double_transmit_and_assert(1'b1, 4, 0); //with send delay
    @(posedge clk_i);

    // TEST 4: souble transmit with delayed ready from output
    double_transmit_and_assert(1'b1, 0, 1); //with read delay
    @(posedge clk_i);

    //TEST 5: no read while in transmission
    transmit_and_assert_with_interrupt(1'b1);
    @(posedge clk_i);

    //TEST 6: random test
    random_transmit();

    repeat(2) @(posedge clk_i);
    eos = 1'b1;
    $stop();
  end

  // ------------ helper functions ------------
  task transmit_and_assert(input last);
    fork
      begin // send
        master_drv.send(32'h12_34_56_ef, last);
      end
      begin // receive
        repeat(4) slave_drv.recv(data_recv, last_recv);
      end
      begin
        repeat(2) @(posedge clk_i);
        assert(slave.tdata == 8'hef);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        assert(slave.tdata == 8'h56);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        assert(slave.tdata == 8'h34);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        assert(slave.tdata == 8'h12);
        assert(slave.tlast == last);
      end
    join
  endtask : transmit_and_assert

  task double_transmit_and_assert(input last, input int SEND_DELAY, input int READ_DELAY);
    fork
      begin // send
        master_drv.send(32'h12_34_56_ef, 1'b0);
        repeat(SEND_DELAY) @(posedge clk_i);
        master_drv.send(32'h12_34_56_ef, last);
      end
      begin // receive
        repeat(4) slave_drv.recv(data_recv, last_recv);
        repeat(READ_DELAY) @(posedge clk_i);
        repeat(4) slave_drv.recv(data_recv, last_recv);
      end
      begin
        repeat(2) @(posedge clk_i);
        assert(slave.tdata == 8'hef);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        assert(slave.tdata == 8'h56);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        assert(slave.tdata == 8'h34);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        assert(slave.tdata == 8'h12);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        repeat((READ_DELAY > (SEND_DELAY-3)) ? READ_DELAY : SEND_DELAY-3) @(posedge clk_i);
        assert(slave.tdata == 8'hef);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        assert(slave.tdata == 8'h56);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        assert(slave.tdata == 8'h34);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        assert(slave.tdata == 8'h12);
        assert(slave.tlast == last);
      end
    join
  endtask : double_transmit_and_assert

  task transmit_and_assert_with_interrupt(input last);
    fork
      begin // send
        master_drv.send(32'h12_34_56_ef, last);
      end
      begin // receive
        slave_drv.recv(data_recv, last_recv);
        @(posedge clk_i);
        slave_drv.recv(data_recv, last_recv);
        slave_drv.recv(data_recv, last_recv);
        @(posedge clk_i);
        slave_drv.recv(data_recv, last_recv);
      end
      begin
        repeat(2) @(posedge clk_i);
        assert(slave.tdata == 8'hef);
        assert(slave.tlast == 1'b0);
        repeat(2) @(posedge clk_i);
        assert(slave.tdata == 8'h56);
        assert(slave.tlast == 1'b0);
        @(posedge clk_i);
        assert(slave.tdata == 8'h34);
        assert(slave.tlast == 1'b0);
        repeat(2) @(posedge clk_i);
        assert(slave.tdata == 8'h12);
        assert(slave.tlast == last);
      end
    join
  endtask : transmit_and_assert_with_interrupt

  task random_transmit();
    fork
      begin
        master_drv.send_rand(200, 1'b1);
      end
      begin
        slave_drv.recv_rand(200*(DW_IN/DW_OUT));
      end
    join

    for (int i = 0; i < master_drv.send_queue.size(); i++) begin
      assert(master_drv.send_queue[i] == {slave_drv.recv_queue[i*(DW_IN/DW_OUT)+3],
                                          slave_drv.recv_queue[i*(DW_IN/DW_OUT)+2],
                                          slave_drv.recv_queue[i*(DW_IN/DW_OUT)+1],
                                          slave_drv.recv_queue[i*(DW_IN/DW_OUT)]});
    end

  endtask : random_transmit

endmodule : tb_axi_stream_dw_downsizer

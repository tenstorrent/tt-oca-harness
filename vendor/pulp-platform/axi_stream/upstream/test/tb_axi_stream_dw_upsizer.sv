// Copyright 2023 ETH Zurich and University of Bologna.
// Solderpad Hardware License, Version 0.51, see LICENSE for details.
// SPDX-License-Identifier: SHL-0.51
//
// Authors:
// - Thiemo Zaugg <zauggth@ethz.ch>


`timescale 1 ns/1 ps
`include "axi_stream/assign.svh"
module tb_axi_stream_dw_upsizer ();

  localparam int unsigned DW_IN = 8;
  localparam int unsigned DW_OUT = 32;
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
  axi_stream_dw_upsizer_intf #(
    .DataWidthIn (DW_IN     ),
    .DataWidthOut(DW_OUT    ),
    .IdWidth     (ID_WIDTH  ),
    .DestWidth   (DEST_WIDTH),
    .UserWidth   (USER_WIDTH)
  ) axi_stream_dw_upsizer_inst (
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

    // TEST 1: transmit one block
    transmit_and_assert(1'b0); // without tlast asserted
    @(posedge clk_i);
    // TEST 2: transmit one block with TLAST at end
    transmit_and_assert(1'b1); // with tlast asserted
    @(posedge clk_i);
    // TEST 3: transmit one block with TLAST at first subtransfer
    transmit_and_assert_partial_1();
    @(posedge clk_i);
    // TEST 4: transmit one block with TLAST at the second to last subtransfer
    transmit_and_assert_partial_2();
    @(posedge clk_i);
    // TEST 5: transmit two block
    double_transmit_and_assert(1'b0); // without tlast asserted
    @(posedge clk_i);
    // TEST 6: transmit two block with TLAST at end
    double_transmit_and_assert(1'b1); // with tlast asserted
    @(posedge clk_i);
    // TEST 7: transmit two block with TLAST at the second to last subtransfer
    double_transmit_and_assert_partial();
    @(posedge clk_i);
    // TEST 8: transmit two block with TLAST at end with READ_DELAY
    double_transmit_and_assert_with_read_delay(1'b1, 1); // with tlast asserted, with READ_DELAY=1
    @(posedge clk_i);
    // TEST 9: transmit two block with TLAST at the second to last subtransfer with READ_DELAY=1
    double_transmit_and_assert_partial_with_read_delay(1); // with READ_DELAY=1
    @(posedge clk_i);
    // TEST 10: transmit two block with TLAST at end with READ_DELAY
    double_transmit_and_assert_with_read_delay(1'b1, 4); // with tlast asserted, with READ_DELAY=4
    @(posedge clk_i);
    // TEST 11: transmit two block with TLAST at the second to last subtransfer with READ_DELAY=4
    double_transmit_and_assert_partial_with_read_delay(4); // with READ_DELAY=1
    @(posedge clk_i);

    //TEST 12: random test
    random_transmit();

    repeat(2) @(posedge clk_i);
    eos = 1'b1;
    $stop();
  end

  // ------------ helper functions ------------
  task transmit_and_assert(input last);
    fork
      begin // send
        master_drv.send(8'h12, 1'b0);
        master_drv.send(8'h34, 1'b0);
        master_drv.send(8'h56, 1'b0);
        master_drv.send(8'hef, last);
      end
      begin // receive
        slave_drv.recv(data_recv, last_recv);
      end
      begin // assert output
        repeat(5) @(posedge clk_i);
        assert(slave.tdata == 32'hef_56_34_12);
        assert(slave.tlast == last);
      end
    join
  endtask : transmit_and_assert

  task transmit_and_assert_partial_1();
    fork
      begin // send
        master_drv.send(8'h12, 1'b0);
        master_drv.send(8'h34, 1'b0);
        master_drv.send(8'hef, 1'b1);
      end
      begin // receive
        slave_drv.recv(data_recv, last_recv);
      end
      begin // assert output
        repeat(5) @(posedge clk_i);
        assert(slave.tdata == 32'h00_ef_34_12);
        assert(slave.tlast == 1'b1);
      end
    join
  endtask : transmit_and_assert_partial_1

  task transmit_and_assert_partial_2();
    fork
      begin // send
        master_drv.send(8'h76, 1'b1);
      end
      begin // receive
        slave_drv.recv(data_recv, last_recv);
      end
      begin // assert output
        repeat(5) @(posedge clk_i);
        assert(slave.tdata == 32'h00_00_00_76);
        assert(slave.tlast == 1'b1);
      end
    join
  endtask : transmit_and_assert_partial_2

  task double_transmit_and_assert(input last);
    fork
      begin // send
        master_drv.send(8'h12, 1'b0);
        master_drv.send(8'h34, 1'b0);
        master_drv.send(8'h56, 1'b0);
        master_drv.send(8'hef, 1'b0);
        master_drv.send(8'h12, 1'b0);
        master_drv.send(8'h34, 1'b0);
        master_drv.send(8'h56, 1'b0);
        master_drv.send(8'hef, last);
      end
      begin // receive
        slave_drv.recv(data_recv, last_recv);
        slave_drv.recv(data_recv, last_recv);
      end
      begin // assert output
        repeat(5) @(posedge clk_i);
        assert(slave.tdata == 32'hef_56_34_12);
        assert(slave.tlast == 1'b0);
        repeat(4) @(posedge clk_i);
        assert(slave.tdata == 32'hef_56_34_12);
        assert(slave.tlast == last);
      end
    join
  endtask : double_transmit_and_assert

  task double_transmit_and_assert_partial();
    fork
      begin // send
        master_drv.send(8'h12, 1'b0);
        master_drv.send(8'h34, 1'b0);
        master_drv.send(8'h56, 1'b0);
        master_drv.send(8'hef, 1'b0);
        master_drv.send(8'h12, 1'b0);
        master_drv.send(8'h34, 1'b0);
        master_drv.send(8'hef, 1'b1);
      end
      begin // receive
        slave_drv.recv(data_recv, last_recv);
        slave_drv.recv(data_recv, last_recv);
      end
      begin // assert output
        repeat(5) @(posedge clk_i);
        assert(slave.tdata == 32'hef_56_34_12);
        assert(slave.tlast == 1'b0);
        repeat(4) @(posedge clk_i);
        assert(slave.tdata == 32'h00_ef_34_12);
        assert(slave.tlast == 1'b1);
      end
    join
  endtask : double_transmit_and_assert_partial

  task double_transmit_and_assert_with_read_delay(input last, input int READ_DELAY);
    fork
      begin // send
        master_drv.send(8'h12, 1'b0);
        master_drv.send(8'h34, 1'b0);
        master_drv.send(8'h56, 1'b0);
        master_drv.send(8'hef, 1'b0);
        master_drv.send(8'h12, 1'b0);
        master_drv.send(8'h34, 1'b0);
        master_drv.send(8'h56, 1'b0);
        master_drv.send(8'hef, last);
      end
      begin // receive
        repeat(4+READ_DELAY) @(posedge clk_i);
        slave_drv.recv(data_recv, last_recv);
        slave_drv.recv(data_recv, last_recv);
      end
      begin // assert output
        repeat(5+READ_DELAY) @(posedge clk_i);
        assert(slave.tdata == 32'hef_56_34_12);
        assert(slave.tlast == 1'b0);
        repeat(4) @(posedge clk_i);
        assert(slave.tdata == 32'hef_56_34_12);
        assert(slave.tlast == last);
      end
    join
  endtask : double_transmit_and_assert_with_read_delay

  task double_transmit_and_assert_partial_with_read_delay(input int READ_DELAY);
    fork
      begin // send
        master_drv.send(8'h12, 1'b0);
        master_drv.send(8'h34, 1'b0);
        master_drv.send(8'h56, 1'b0);
        master_drv.send(8'hef, 1'b0);
        master_drv.send(8'h12, 1'b0);
        master_drv.send(8'h34, 1'b0);
        master_drv.send(8'hef, 1'b1);
      end
      begin // receive
        repeat(4+READ_DELAY) @(posedge clk_i);
        slave_drv.recv(data_recv, last_recv);
        slave_drv.recv(data_recv, last_recv);
      end
      begin // assert output
        repeat(5+READ_DELAY) @(posedge clk_i);
        assert(slave.tdata == 32'hef_56_34_12);
        assert(slave.tlast == 1'b0);
        repeat(4) @(posedge clk_i);
        assert(slave.tdata == 32'h00_ef_34_12);
        assert(slave.tlast == 1'b1);
      end
    join
  endtask : double_transmit_and_assert_partial_with_read_delay

  task random_transmit();
    fork
      begin
        master_drv.send_rand(200*(DW_OUT/DW_IN), 1'b0);
        repeat(4) @(posedge clk_i);
      end
      begin
        slave_drv.recv_rand(200*(DW_OUT/DW_IN));
      end
    join_any

    $display("test1:");
    for (int i = 0; i < master_drv.send_queue.size()/(DW_OUT/DW_IN); i++) begin
      assert(slave_drv.recv_queue[i] == {master_drv.send_queue[i*(DW_OUT/DW_IN)+3],
                                         master_drv.send_queue[i*(DW_OUT/DW_IN)+2],
                                         master_drv.send_queue[i*(DW_OUT/DW_IN)+1],
                                         master_drv.send_queue[i*(DW_OUT/DW_IN)]});
    end

  endtask : random_transmit

endmodule : tb_axi_stream_dw_upsizer

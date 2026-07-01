// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// M Write N Read Fifo with Flush and Clear, Flush to be implemented outside

module dfd_rv_fifoMN
	#(
		parameter integer DATA_WIDTH = 4,
		parameter integer ENTRIES = 8,
		parameter bit     ALLOW_CLEAR = 1,
		parameter bit     CLEAR_ALL = ALLOW_CLEAR ? 1 : 0, //FE clears all
		parameter integer ADDR_SIZE = (ENTRIES == 1) ? 1 : $clog2(ENTRIES),
		parameter integer NUM_WR = 2,
		parameter integer NUM_RD = 2
	)
	(
		output logic [ADDR_SIZE:0]                  o_cnt,
		output logic [NUM_RD-1:0] [DATA_WIDTH-1:0]  o_data,
		output logic [ENTRIES-1:0][DATA_WIDTH-1:0]  o_broadside_data,
		output logic [ADDR_SIZE:0]                  o_rdptr,
		output logic [ADDR_SIZE:0]                  o_wrptr,

		input logic [NUM_WR-1:0][DATA_WIDTH-1:0]    i_data,
		input logic [NUM_WR-1:0]                    i_psh,
		input logic [NUM_RD-1:0]                    i_pop,

		input logic [ENTRIES-1:0]                   i_clear,
		input logic                                 i_clk,
		input logic                                 i_reset_n
	);

	logic [ADDR_SIZE:0]                   rd_ptr;
	logic [ADDR_SIZE:0]                   wr_ptr;

	logic [ENTRIES-1:0] [DATA_WIDTH-1:0]  mem;
	logic [ENTRIES-1:0]                   wr_clk_en;
	logic [ENTRIES-1:0] [DATA_WIDTH-1:0]  wr_data;
	logic [DATA_WIDTH-1:0]                rd_mx_dat;
	logic [ADDR_SIZE:0]                   nxt_cnt;
	logic [ADDR_SIZE:0]                   psh_cnt,pop_cnt,clear_cnt;
	logic [ADDR_SIZE:0]                   nxt_wr_ptr_wrap,nxt_rd_ptr_wrap;

	`RV_ASSERT_ZERO_ONE_HOT(ERR_WR_CLR_ONE_HOT, i_clk, i_reset_n, ALLOW_CLEAR & !CLEAR_ALL, {|i_clear,|i_psh}, "Can't pushon clear")
	assign nxt_cnt     =  (CLEAR_ALL && (|{i_clear})) ? '0 : (ADDR_SIZE+1)'(o_cnt + ((ALLOW_CLEAR && (|{i_clear})) ? -clear_cnt : psh_cnt) - pop_cnt);
	assign o_rdptr     =  rd_ptr;
	assign o_wrptr     =  wr_ptr;

	// spyglass disable_block W415a
	always_comb begin
		psh_cnt = '0;
		for(int i=0;i<NUM_WR;i++)
			//psh_cnt+=(ADDR_SIZE+1)'(i_psh[i]);
			psh_cnt = (ADDR_SIZE+1)'(psh_cnt + (ADDR_SIZE+1)'(i_psh[i]));
	end

	always_comb begin
		pop_cnt = '0;
		for(int i=0;i<NUM_RD;i++)
			pop_cnt+={{ADDR_SIZE{1'b0}}, (i_pop[i] & ~(CLEAR_ALL & |i_clear))};
	end

	always_comb begin
		clear_cnt = '0;
		for(int i=0;i<ENTRIES;i++)
			//clear_cnt+=(ADDR_SIZE+1)'(i_clear[i]);
			clear_cnt =(ADDR_SIZE+1)'(clear_cnt + (ADDR_SIZE+1)'(i_clear[i]));
	end
	// spyglass enable_block W415a

	always_ff @ (posedge i_clk) begin
		if(~i_reset_n)
			o_cnt <= '0;
		else if(|i_psh || |i_pop || ALLOW_CLEAR && |i_clear )
			o_cnt <= nxt_cnt;
	end
	assign nxt_wr_ptr_wrap = (wr_ptr[ADDR_SIZE:0] + {psh_cnt} - ENTRIES[ADDR_SIZE:0]);
	always_ff @ (posedge i_clk) begin
		if(~i_reset_n)
			wr_ptr <= '0;
		else if(ALLOW_CLEAR && |i_clear)
			if(CLEAR_ALL && |i_clear)
				wr_ptr <= rd_ptr;
			else
				if(wr_ptr[ADDR_SIZE-1:0] - (ADDR_SIZE)'(clear_cnt) >= 0)
					wr_ptr <= (ADDR_SIZE+1)'(wr_ptr - clear_cnt);
				else
					wr_ptr <= wr_ptr - clear_cnt + ENTRIES[ADDR_SIZE:0];
		else if ((ADDR_SIZE+1)'(wr_ptr[ADDR_SIZE-1:0] + psh_cnt) > (ADDR_SIZE+1)'(ENTRIES-1))
			wr_ptr <= {~wr_ptr[ADDR_SIZE],nxt_wr_ptr_wrap[ADDR_SIZE-1:0]};
		else if(|i_psh)
			wr_ptr <= (ADDR_SIZE+1)'(wr_ptr + psh_cnt);
	end
	assign nxt_rd_ptr_wrap = (rd_ptr[ADDR_SIZE:0] + {pop_cnt} - ENTRIES[ADDR_SIZE:0]);
	always_ff @ (posedge i_clk) begin
		if( ~i_reset_n )
			rd_ptr <= '0;
		else if ((ADDR_SIZE+1)'(rd_ptr[ADDR_SIZE-1:0] + pop_cnt) > (ADDR_SIZE+1)'(ENTRIES-1))
			rd_ptr <= {~rd_ptr[ADDR_SIZE],nxt_rd_ptr_wrap[ADDR_SIZE-1:0]};
		else if(|i_pop)
			rd_ptr <= (ADDR_SIZE+1)'(rd_ptr + pop_cnt);
	end

	dfd_rv_rotate #(.ROT_LEFT(1),.NUM_IN(NUM_WR),  .NUM_OUT(ENTRIES),.DATA_SIZE(1))          RotWrEn  (.DataIn(i_psh ),.DataOut(wr_clk_en),.PtrOut(wr_ptr[ADDR_SIZE-1:0]));
	dfd_rv_rotate #(.ROT_LEFT(1),.NUM_IN(NUM_WR),  .NUM_OUT(ENTRIES),.DATA_SIZE(DATA_WIDTH)) RotWrDat (.DataIn(i_data),.DataOut(wr_data)  ,.PtrOut(wr_ptr[ADDR_SIZE-1:0]));

	//always_comb begin
	//   wr_clk_en         = '0;
	//   wr_data           = 'x;
	//   for(int i=0;i<NUM_WR;i++) begin
	//    wr_clk_en[ADDR_SIZE'(wr_ptr+i)] = i_psh[i];
	//    wr_data  [ADDR_SIZE'(wr_ptr+i)] = i_data[i];
	//   end
	//end
	logic [ADDR_SIZE:0] rd_ptr_wrap;
	// spyglass disable_block W415a
	always_comb
		for(int i=0;i<NUM_RD;i++)  begin
			rd_ptr_wrap = (({1'b0,rd_ptr[ADDR_SIZE-1:0]}+(ADDR_SIZE)'(i)) >= ENTRIES[ADDR_SIZE:0]) ?
				({1'b0,rd_ptr[ADDR_SIZE-1:0]+(ADDR_SIZE)'(i)}) - ENTRIES[ADDR_SIZE:0] :
				({1'b0,rd_ptr[ADDR_SIZE-1:0]+(ADDR_SIZE)'(i)});
			o_data[i] =  mem[ADDR_SIZE'(rd_ptr_wrap)];
		end
	// spyglass enable_block W415a

	always_ff @(posedge i_clk) begin
		for(int i = 0; i < ENTRIES ; i++)
			if(wr_clk_en[i])
				mem[i] <= wr_data[i];
	end

	//For CAM based  flush purposes
	assign o_broadside_data   = mem;
	`RV_ASSERT(WR_ON_FULL,  i_clk, i_reset_n, 1'b1 , (nxt_cnt <= ENTRIES[ADDR_SIZE:0]), "write on full")
	`RV_ASSERT(RD_ON_EMPTY, i_clk, i_reset_n, 1'b1 , (o_cnt >= pop_cnt) , "read on empty")

endmodule
// Local Variables:
// verilog-library-directories:(".")
// verilog-library-extensions:(".sv" ".h" ".v")
// verilog-typedef-regexp: "_[tseu]$"
// End:

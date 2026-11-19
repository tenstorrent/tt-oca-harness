<!--
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
SPDX-License-Identifier: CC-BY-4.0
-->

# tdr2axi: TDR to AXI through the System Bus Access

`tdr2axi` gives a JTAG debugger access to an AXI4 or AXI4-Lite bus through a single
41-bit test data register (TDR) of an existing TAP or IEEE 1687 (IJTAG) network.
Behind the TDR it reuses this repository's Debug Module registers (`dm_csrs`) and System
Bus Access engine (`dm_sba`), so the debugger drives it with the standard RISC-V debug
DMI protocol: OpenOCD and other RISC-V debuggers reach memory through `sbcs`,
`sbaddress*` and `sbdata*` without any custom tooling.

It is meant for systems that already own a TAP, for example a DFT or IJTAG network,
and want bus access without a second TAP or a core-side debug module.

The sources are in `src/tdr2axi/` and are compiled with the Bender target `tdr2axi`.
They are licensed under Apache-2.0, unlike the rest of this repository (see the SPDX
header of each file).

## Block diagram

```
          TCK domain                 |                 i_clk domain
                                     |
 TDR ---> dmi_tdr_bridge --- dmi_req_t ---> dm_csrs ---> dm_sba ---> axi_from_mem      ---> AXI4
 cell <---  (dmi_jtag FSM) <-- dmi_resp_t --  (DMI      (SBA        or                     or
                                     |       registers)  engine)   axi_lite_from_mem ---> AXI4-Lite
                       2 x cdc_2phase_clearable
```

* `dmi_tdr_bridge` is the DMI part of `dmi_jtag` and `dmi_cdc`, kept rule for rule:
  the same state machine, sticky busy and failed status, and read-data markers. It has
  no TAP, shift register or `dtmcs`; the external TAP owns the TDR cell and hands the
  bridge the parallel TDR value with an update strobe.
* `dm_csrs` and `dm_sba` are instantiated with one hart that always reports
  unavailable, so only the SBA registers are useful. Every abstract command fails with
  `cmderr` = 2 (not supported). `ndmreset` is not connected, so the debugger cannot
  reset the system through `tdr2axi`.
* The `dm_sba` memory port is converted to AXI by `axi_from_mem` or
  `axi_lite_from_mem` from the [PULP AXI](https://github.com/pulp-platform/axi) library,
  with one request in flight.

## Parameters

**Name**         | **Valid values**      | **Default**            | **Description**
---------------- | --------------------- | ---------------------- | -----------------------------------------------------------
`USE_AXI_LITE`   | 0, 1                  | 0                      | 1: AXI4-Lite manager, 0: AXI4 manager
`AXI_ADDR_WIDTH` | 2..64 / 3..64 (1)     | 64                     | AXI address width; also `sbcs.sbasize`
`AXI_DATA_WIDTH` | 32, 64                | 64                     | AXI data width; also the largest SBA access size
`AXI_PROT`       | 3 bits                | `3'b010`               | AxPROT of every transaction (non-secure, unprivileged, data)
`AXI_CACHE`      | 4 bits                | `4'b0000`              | AxCACHE of every transaction (AXI4 only)
`SYNC_STAGES`    | 3 or more             | 3                      | Synchroniser depth of the reset synchronisers and both CDCs
`axi_req_t`      | AXI4 / AXI4-Lite type | none (must be set)     | Request struct; its data width must be `AXI_DATA_WIDTH`
`axi_rsp_t`      | AXI4 / AXI4-Lite type | none (must be set)     | Response struct; its data width must be `AXI_DATA_WIDTH`

(1) `AXI_ADDR_WIDTH` must cover the byte offset within a data word: at least 2 for
32-bit data and at least 3 for 64-bit data (checked by `dm_sba`).

The address and data widths are independent, so for example a 32-bit data bus can
reach a 64-bit address space. This uses the `SbaAddrWidth` parameter of `dm_csrs` and
`dm_sba`.

`axi_req_t` and `axi_rsp_t` default to `logic`, as in PULP's `axi_from_mem`, so a
parent must always override them with its own AXI4 or AXI4-Lite types.

## Ports

**Name**            | **Direction** | **Clock** | **Description**
------------------- | ------------- | --------- | ------------------------------------------------------------------
`i_clk`             | input         |           | Bus clock
`i_arst_n`          | input         | async     | Reset, active low: power-on or system reset, never TRST
`i_test_mode`       | input         | async     | DFT test mode: selects `i_arst_scan_n` for the internal resets
`i_arst_scan_n`     | input         | async     | Reset used while `i_test_mode` = 1
`i_tck`             | input         |           | JTAG test clock
`i_dmi_tdr[40:0]`   | input         | `i_tck`   | Parallel (update-stage) value of the TDR
`i_dmi_tdr_capture` | input         | `i_tck`   | High for the TCK rising edge at which the TDR cell loads `o_dmi_tdr` (Capture-DR and this TDR selected)
`i_dmi_tdr_update`  | input         | `i_tck`   | High for one TCK rising edge after Update-DR of this TDR
`o_dmi_tdr[40:0]`   | output        | `i_tck`   | Capture value for the TDR cell
`o_axi_req`         | output        | `i_clk`   | AXI request
`i_axi_rsp`         | input         | `i_clk`   | AXI response

## TDR format

The TDR has the layout of the `dmi` register of the RISC-V debug specification.

**Bits** | **Update (`i_dmi_tdr`)**                            | **Capture (`o_dmi_tdr`)**
-------- | --------------------------------------------------- | ------------------------------------------------
`40:34`  | DMI address                                         | Address of the last operation
`33:2`   | Write data                                          | Read data of the last operation
`1:0`    | op: 0 NOP, 1 read, 2 write, 3 clear sticky status   | status: 0 success, 2 failed, 3 busy

op 3 is reserved in the specification. `tdr2axi` uses it in place of
`dtmcs.dmireset`, which a lone TDR does not have: it clears the sticky status.

The status follows `dmi_jtag`. It becomes busy and sticky when a scan updates the TDR
while an operation is still pending, when a scan captures while a read is still
pending, or when the DM answers busy. It becomes failed when the DM answers with an
error. While the sticky status is set, new operations are ignored; the debugger clears
it with op 3 and retries with more Run-Test/Idle cycles after each scan, as OpenOCD
does with `dtmcs.dmireset`.

As upstream, a read that was resent after a busy status may run twice. Avoid
side-effecting reads with `sbreadondata` unless enough Run-Test/Idle cycles are used.

## Timing and reset rules

* Both crossings are valid/ready handshakes, so correctness does not depend on the
  `i_clk` / `i_tck` ratio. TCK only runs during scans, so a result reaches `o_dmi_tdr`
  a few TCK cycles after the bus completes; Run-Test/Idle cycles after each operation
  scan give it time.
* The op field of `i_dmi_tdr` must be valid at the TCK rising edge that samples
  `i_dmi_tdr_update`.
* `i_arst_n` may be fully asynchronous. It is synchronised into `i_clk` and `i_tck`
  (asynchronous assertion, synchronous release, test-mode bypass). The TCK side leaves
  reset `SYNC_STAGES` TCK cycles after release.
* TRST does not reset `tdr2axi`. TRST must be asserted and released only while TCK is
  stopped; an operation in flight when TRST asserts completes normally. Software
  clears the bridge with op 3 and the DM with `dmcontrol.dmactive` = 0.
* If `i_arst_n` is a system reset, it must also reset the fabric `tdr2axi` accesses,
  so that an outstanding AXI transaction never survives on one side only.

## AXI transactions

* One transaction at a time, single beat, ID 0, user 0, `AxPROT` = `AXI_PROT`,
  `AxCACHE` = `AXI_CACHE`.
* AXI4: `AxSIZE` follows `sbcs.sbaccess`, so a narrow read does not fetch the whole bus
  word. `dm_sba` only issues naturally aligned accesses (`sberror` = 3 otherwise) and
  accesses up to the data width (`sberror` = 4 otherwise).
* `SLVERR` and `DECERR` responses set `sbcs.sberror` = 2.

## Programming examples

The DMI addresses are those of the RISC-V debug specification: `dmcontrol` 0x10,
`sbcs` 0x38, `sbaddress0` 0x39, `sbaddress1` 0x3A, `sbdata0` 0x3C, `sbdata1` 0x3D.
Each write or read below is one TDR scan with op 2 or op 1; a read returns its data in
the capture of the next scan (a NOP, or the next operation).

Enable the DM once: write `dmcontrol` = 0x0000_0001 (`dmactive`).

Single write of `size` (0: 8-bit, 1: 16-bit, 2: 32-bit, 3: 64-bit):

1. Write `sbcs` with `sbaccess` = `size`.
2. If `AXI_ADDR_WIDTH` > 32, write `sbaddress1` with address bits 63:32.
3. Write `sbaddress0` with address bits 31:0.
4. For 64-bit accesses, write `sbdata1` with data bits 63:32.
5. Write `sbdata0` with data bits 31:0. This starts the bus write.
6. Read `sbcs` until `sbbusy` = 0, then check `sberror` and `sbbusyerror`.

Single read:

1. Write `sbcs` with `sbaccess` = `size` and `sbreadonaddr` = 1.
2. Write `sbaddress1` (if needed), then `sbaddress0`. Writing `sbaddress0` starts the
   bus read.
3. For 64-bit accesses read `sbdata1` (it does not start a read), then read `sbdata0`.
4. Read `sbcs` until `sbbusy` = 0, then check `sberror` and `sbbusyerror`.

Block write: as a single write, with `sbautoincrement` = 1 in `sbcs`; each write of
`sbdata0` writes one element and advances the address.

Block read: write `sbcs` with `sbreadonaddr`, `sbreadondata` and `sbautoincrement` set,
then the address. Each read of `sbdata0` returns one element and starts the next read.
Before reading the last element, write `sbcs` again with `sbreadondata` = 0, so that
nothing past the end of the block is read.

## Verification

`tb/tdr2axi/` holds a cocotb testbench. Its TDR host models the TAP states and the
OpenOCD DMI flow (busy, op 3, longer Run-Test/Idle, resend); its AXI subordinate
checks every handshake, the address, size, strobes and byte lanes, and models memory.
It covers every access size and lane, block accesses, bus errors, busy SBA accesses,
refused and pipelined operations, resets with an operation in flight, and AXI4 and
AXI4-Lite at several address and data widths.

```sh
cd tb/tdr2axi
make                       # 64-bit AXI4 with Verilator
make CONFIG=axil_a64_d32   # one configuration
make sim_all               # every configuration
make SIM=vcs               # Synopsys VCS
```

It needs [cocotb](https://www.cocotb.org) 1.9, [Bender](https://github.com/pulp-platform/bender)
and Verilator 5.036 or later.

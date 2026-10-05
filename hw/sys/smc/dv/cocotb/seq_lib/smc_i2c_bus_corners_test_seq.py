# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target, bus monitor, wrapper decode and pad ownership at their edges.

Five things around the I2C0 target that the target leaves never do, each with
the bench controller (`SmcI2cMasterVip`) on the pads:

* **A STOP where a NACK belongs.** `i2c.rdl` raises `INTR_STATE.UNEXP_STOP`
  "when the controller sends this target a STOP before this target NACKs". A
  read from the target whose controller sends the STOP in the byte's
  acknowledge slot, where the controller rather than the target owns SDA, must
  raise it. The same read is then made with `CTRL.ENABLETARGET` cleared before
  the STOP, the controller kept enabled so the bus monitor still sees it; that
  STOP must not raise it.
* **A NACK request that does not apply.** `TARGET_ACK_CTRL.NACK` takes effect
  "when `STATUS.ACK_CTRL_STRETCH = 1`". With ACK Control Mode off, the target
  is made to stretch because its acquisition FIFO is full, and `NACK` is
  written during that stretch. It must have no effect: once software drains
  the FIFO, every byte of the write has to be acknowledged and read out in
  order.
* **SCL taken during the bus-free time.** After a STOP the bus monitor waits
  `TIMING4.T_BUF` before calling the bus free. `T_BUF` is lengthened, and the
  bench controller pulls SCL low inside that wait. The target has to answer
  the next transfer as before.
* **An access the wrapper decodes to nothing.** The I2C wrapper decodes its
  three instances and its control registers; an address inside the wrapper's
  window that lies above the last instance stride and below the control
  registers belongs to neither and must be refused on the bus for both a read
  and a write. The window extent, the instance strides and the control
  register base all come from the generated address map.
* **LSIO ownership withdrawn from the SCL pad.** `gpio_intf.rdl`:
  `DATA_CTRL.lsio_disable` "blocks LSIO accesses from the GPIO interface", and
  `lsio_enable` is "set while `lsio_interface_select_i` is asserted and
  `lsio_disable` is clear". With I2C0 enabled its SCL pad reports
  `lsio_enable`; with `lsio_disable` set it must read clear, also with
  `lsio_select` forced, and clearing `lsio_disable` must bring it back.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge, Timer
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_ACQFULL,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_master_target_test_seq import I2C_CTRL_ENABLEHOST, _i2c_u32
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_target_ack_ctrl_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_ACQDATA,
    I2C0_CTRL,
    I2C0_FIFO_CTRL,
    I2C0_OVRD,
    I2C0_STATUS,
    I2C0_TARGET_ACK_CTRL,
    I2C0_TARGET_ID,
    I2C0_TIMING0,
    I2C0_TIMING1,
    I2C0_TIMING2,
    I2C0_TIMING3,
    I2C0_TIMING4,
    I2C0_WRAP_CTRL,
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)


def _i2c0(register: str) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", 0)


I2C0_INTR_STATE = _i2c0("INTR_STATE")
I2C0_TXDATA = _i2c0("TXDATA")
INTR_UNEXP_STOP = _i2c_u32("I2C__INTR_STATE__UNEXP_STOP_bm")
ACK_CTRL_NACK = _i2c_u32("I2C__TARGET_ACK_CTRL__NACK_bm")
#: Inside the wrapper's window, above its last instance stride and below its
#: control registers: no register map covers it.
WRAP_BASE = smc_addr("SMC_TOP_SMC_I2C_WRAP_BASE_ADDR")
WRAP_END = WRAP_BASE + smc_addr("SMC_TOP_SMC_I2C_WRAP_SIZE")
INSTANCES_END = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR", 0) + smc_addr(
    "SMC_TOP_SMC_I2C_WRAP_I2C_TOTAL_SIZE"
)
CTRL_REGS_BASE = smc_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_BASE_ADDR")
UNMAPPED_IN_WRAP = INSTANCES_END
assert WRAP_BASE <= INSTANCES_END <= UNMAPPED_IN_WRAP < CTRL_REGS_BASE < WRAP_END, (
    f"0x{UNMAPPED_IN_WRAP:08x} is not between the I2C instances (end 0x{INSTANCES_END:08x}) "
    f"and the control registers (0x{CTRL_REGS_BASE:08x}) inside the wrapper window "
    f"0x{WRAP_BASE:08x}..0x{WRAP_END:08x}"
)
#: The I2C0 SCL pad in `smc_padring.sv` (37 + 4 * instance).
SCL_PAD = 37
DATA_CTRL_SCL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", SCL_PAD)
LSIO_SELECT = 1 << 17
LSIO_DISABLE = 1 << 19
LSIO_ENABLE = 1 << 25

TARGET_ADDR = 0x2E
VIP_SPEED = 2_000_000
TX_BYTES = bytes((0x5C, 0xA3))
#: More bytes than the acquisition FIFO holds, so the target has to stretch.
FILL_BYTES = bytes((0x40 + i) & 0xFF for i in range(72))
#: `TIMING4.T_BUF` for the bus-free leg, in controller clocks.
LONG_T_BUF = 3000
#: Waits in time rather than core clocks: the traffic they wait for runs at the
#: controller's SCL rate and the target's peripheral clock, neither of which
#: follows the core clock.
SETTLE_NS = 1_000
POLL_INTERVAL_NS = 250
POLL_LIMIT = 4000


class smc_i2c_bus_corners_test_seq(SmcCsrSeq):
    """Unexpected STOP, a NACK that does not apply, bus-free SCL, wrapper decode, pad ownership."""

    def __init__(self, name: str = "smc_i2c_bus_corners_test_seq") -> None:
        super().__init__(name)
        self.master: SmcI2cMasterVip | None = None

    async def _target_up(self, label: str, t_buf: int = 5) -> None:
        await self.csr_write(f"{label}_DISABLE", I2C0_CTRL, 0)
        await self.csr_write(f"{label}_OVRD_OFF", I2C0_OVRD, 0)
        await self.csr_write(f"{label}_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write(f"{label}_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write(f"{label}_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write(f"{label}_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write(f"{label}_TIMING4", I2C0_TIMING4, _pack_timing4(4, t_buf))
        await self.csr_write(
            f"{label}_FIFO_RST",
            I2C0_FIFO_CTRL,
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_ACQRST,
        )
        await self.csr_write(
            f"{label}_TARGET_ID", I2C0_TARGET_ID, _pack_target_id(TARGET_ADDR, 0x7F, 0, 0)
        )
        await self.csr_write(f"{label}_INTR_CLR", I2C0_INTR_STATE, 0xFFFF_FFFF)
        await self.csr_write(f"{label}_CTRL", I2C0_CTRL, I2C_CTRL_ENABLETARGET)
        await Timer(100, unit="ns")

    async def _read_then_stop(self, label: str, disable_first: bool) -> int:
        """Read one byte from the target and send a STOP in its acknowledge slot."""
        master = self.master
        assert master is not None
        for index, byte in enumerate(TX_BYTES):
            await self.csr_write(f"{label}_TXDATA{index}", I2C0_TXDATA, byte)
        await master.send_start()
        nack = await master.send_byte(((TARGET_ADDR & 0x7F) << 1) | 1)
        assert not nack, f"{label}: the target did not acknowledge its read address"
        got = 0
        for _ in range(8):
            got = (got << 1) | await master.recv_bit()
        if disable_first:
            await self.csr_write(f"{label}_TARGET_OFF", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        # The STOP takes the acknowledge slot: the controller pulls SDA low for it,
        # releases SCL and then SDA, so the target is not driving the line when it
        # sees the STOP and has not been NACKed.
        await master.send_stop()
        await Timer(SETTLE_NS, unit="ns")

        assert got == TX_BYTES[0], f"{label}: read 0x{got:02x}, not 0x{TX_BYTES[0]:02x}"
        return await self.csr_read(f"{label}_INTR", I2C0_INTR_STATE)

    async def _unexpected_stop_leg(self) -> None:
        await self._target_up("UNEXP")
        intr = await self._read_then_stop("UNEXP", disable_first=False)
        assert intr & INTR_UNEXP_STOP, (
            f"UNEXP: a STOP in the acknowledge slot of a read byte left INTR_STATE.UNEXP_STOP clear "
            f"(0x{intr:08x})"
        )
        await self._target_up("UNEXP_OFF")
        intr = await self._read_then_stop("UNEXP_OFF", disable_first=True)
        assert not intr & INTR_UNEXP_STOP, (
            f"UNEXP_OFF: with the target disabled before the STOP, INTR_STATE=0x{intr:08x}; "
            f"a disabled target raises no target interrupt"
        )
        await self.csr_write("UNEXP_OFF_CTRL", I2C0_CTRL, 0)
        cocotb.log.info(
            "CHK-I2C-TGT-UNEXP-STOP: a STOP in the acknowledge slot of a read byte raised "
            "INTR_STATE.UNEXP_STOP, and the same STOP with the target disabled first did not"
        )

    async def _await_target_stretch(self, label: str) -> None:
        dut = cocotb.top
        for _ in range(POLL_LIMIT):
            await RisingEdge(dut.clk_periph_i)
            if int(dut.tb_i2c0_scl_dut_low.value):
                return
        raise AssertionError(f"{label}: the target never held SCL low with its ACQ FIFO full")

    async def _nack_ignored_leg(self) -> None:
        master = self.master
        assert master is not None
        await self._target_up("NACK_IGNORED")
        writer = cocotb.start_soon(master.write(TARGET_ADDR, FILL_BYTES))
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read("NACK_IGNORED_STATUS", I2C0_STATUS)
            if status & I2C_STATUS_ACQFULL:
                break
            await Timer(POLL_INTERVAL_NS, unit="ns")
        else:
            raise AssertionError(f"NACK_IGNORED: the ACQ FIFO never filled (0x{status:08x})")
        # A full FIFO is reported while the byte after it is still arriving; the
        # target stretches only once that byte reaches its acknowledge slot, so
        # the NACK is written once the target holds SCL low.
        await self._await_target_stretch("NACK_IGNORED")
        await self.csr_write("NACK_IGNORED_NACK", I2C0_TARGET_ACK_CTRL, ACK_CTRL_NACK)
        received = bytearray()
        for _ in range(POLL_LIMIT):
            status = await self.csr_read("NACK_IGNORED_DRAIN_STATUS", I2C0_STATUS)
            if not status & I2C_STATUS_ACQEMPTY:
                word = await self.csr_read("NACK_IGNORED_ACQDATA", I2C0_ACQDATA)
                if (word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP == I2C_ACQ_SIGNAL_NONE:
                    received.append(word & 0xFF)
                continue
            if writer.done():
                break
            await Timer(POLL_INTERVAL_NS, unit="ns")
        await writer
        assert bytes(received) == FILL_BYTES, (
            f"NACK_IGNORED: {len(received)} of {len(FILL_BYTES)} bytes came out of the ACQ "
            f"FIFO in order; TARGET_ACK_CTRL.NACK written outside an ACK Control stretch must "
            f"leave every byte acknowledged"
        )
        await self.csr_write("NACK_IGNORED_CTRL", I2C0_CTRL, 0)
        cocotb.log.info(
            "CHK-I2C-TGT-NACK-IGNORED: TARGET_ACK_CTRL.NACK written while the target stretched "
            "on a full ACQ FIFO, with ACK Control Mode off, left all %d bytes acknowledged and "
            "read out in order",
            len(FILL_BYTES),
        )

    async def _bus_free_leg(self) -> None:
        master = self.master
        assert master is not None
        await self._target_up("BUS_FREE", t_buf=LONG_T_BUF)
        await master.write(TARGET_ADDR, TX_BYTES[:1])
        master._pull_scl(True)
        await Timer(200, unit="ns")
        master._pull_scl(False)
        await Timer(1, unit="us")
        await master.write(TARGET_ADDR, TX_BYTES[1:])
        received = []
        for index in range(4):
            status = await self.csr_read(f"BUS_FREE_STATUS{index}", I2C0_STATUS)
            if status & I2C_STATUS_ACQEMPTY:
                break
            word = await self.csr_read(f"BUS_FREE_ACQ{index}", I2C0_ACQDATA)
            received.append(word & 0xFF)
        assert received == list(TX_BYTES), (
            f"BUS_FREE: the ACQ FIFO held {[hex(b) for b in received]} after SCL was taken "
            f"during the bus-free time; both writes have to arrive"
        )
        await self.csr_write("BUS_FREE_CTRL", I2C0_CTRL, 0)
        await self.csr_write("BUS_FREE_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        cocotb.log.info(
            "CHK-I2C-BUS-FREE-SCL: SCL pulled low inside a lengthened bus-free time after a "
            "STOP left the target answering the next write, and both bytes arrived"
        )

    async def _refused(self, label: str, op: SmcSysAxiOp) -> int:
        item = SmcSysAxiItem(f"{'wr' if op == SmcSysAxiOp.WRITE else 'rd'}_{label}")
        item.op = op
        item.addr = UNMAPPED_IN_WRAP
        item.length = 4
        item.wdata = 0
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label}: no response"
        return item.resp_code

    async def _decode_leg(self) -> None:
        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.add(UNMAPPED_IN_WRAP)
        read = await self._refused("WRAP_UNMAPPED_READ", SmcSysAxiOp.READ)
        write = await self._refused("WRAP_UNMAPPED_WRITE", SmcSysAxiOp.WRITE)
        assert read != 0 and write != 0, (
            f"an access at 0x{UNMAPPED_IN_WRAP:08x}, inside the I2C wrapper window "
            f"0x{WRAP_BASE:08x}..0x{WRAP_END:08x} but above its instances and below its "
            f"control registers, was answered OKAY (read {read}, write {write}); it belongs "
            f"to no register map"
        )
        cocotb.log.info(
            "CHK-I2C-WRAP-PAST-CTRL: a read and a write at 0x%08x, inside the I2C wrapper "
            "window ending at 0x%08x, above its instances (end 0x%08x) and below its control "
            "registers (0x%08x), were refused (responses %d and %d)",
            UNMAPPED_IN_WRAP,
            WRAP_END,
            INSTANCES_END,
            CTRL_REGS_BASE,
            read,
            write,
        )

    async def _pad_leg(self) -> None:
        await self._target_up("PAD")
        await self.csr_write("PAD_HOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        ctrl = await self.csr_read("PAD_DATA_CTRL", DATA_CTRL_SCL)
        assert ctrl & LSIO_ENABLE and not ctrl & LSIO_DISABLE, (
            f"DATA_CTRL[{SCL_PAD}]=0x{ctrl:08x} with I2C0 enabled; lsio_enable is set and "
            f"lsio_disable clear"
        )
        await self.csr_write("PAD_DISABLE", DATA_CTRL_SCL, ctrl | LSIO_DISABLE)
        off = await self.csr_read("PAD_DISABLED", DATA_CTRL_SCL)
        await self.csr_write("PAD_FORCE", DATA_CTRL_SCL, ctrl | LSIO_DISABLE | LSIO_SELECT)
        forced = await self.csr_read("PAD_FORCED", DATA_CTRL_SCL)
        await self.csr_write("PAD_RESTORE", DATA_CTRL_SCL, ctrl)
        back = await self.csr_read("PAD_BACK", DATA_CTRL_SCL)
        await self.csr_write("PAD_CTRL_OFF", I2C0_CTRL, 0)
        assert not off & LSIO_ENABLE, (
            f"PAD: with lsio_disable set DATA_CTRL=0x{off:08x}; lsio_enable is set only while "
            f"lsio_disable is clear"
        )
        assert not forced & LSIO_ENABLE and forced & LSIO_SELECT, (
            f"PAD: with lsio_select forced under lsio_disable DATA_CTRL=0x{forced:08x}"
        )
        assert back == ctrl, (
            f"PAD: DATA_CTRL reads 0x{back:08x} after lsio_disable was cleared, not the "
            f"0x{ctrl:08x} it held; lsio_enable returns with the hardware request"
        )
        cocotb.log.info(
            "CHK-I2C-PAD-LSIO-DISABLE: with I2C0 requesting its SCL pad, "
            "DATA_CTRL[%d].lsio_disable cleared lsio_enable, also with lsio_select forced, "
            "and clearing it returned the register to 0x%08x with lsio_enable set",
            SCL_PAD,
            ctrl,
        )

    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_TARGET", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready("I2C0_BUS_CORNERS")
        self.master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_corners_master")
        await Timer(1, unit="us")
        await self._unexpected_stop_leg()
        await self._nack_ignored_leg()
        await self._bus_free_leg()
        await self._decode_leg()
        await self._pad_leg()

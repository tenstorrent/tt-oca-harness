# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCCP unsecure boot across two real SMCs.

OCCP unsecure boot with two real SMC instances. Both halves are
real: no testbench model stands in for either side of the protocol.

  u_bfm  controller: the DV occp_unsecure_boot_test image, driving the real
         MIPI-HCI I3C controller driver
  u_dut  target:     the real production boot ROM, servicing OCCP through
         i3c_hci_driver.c

The testbench does three things: write the payload into the controller's SRAM
over its inbound AXI manager, seed the scratch 5-8 host protocol, and release
the two CPUs. Everything after that -- ENTDAA, the
chunked WRITEs, the JUMP -- is firmware talking to firmware over a shared I3C
bus.

Staging is a front-door AXI write. It needs the controller's cluster boundary
open, which needs all four of its cores released, so the staging window is held
open by keeping the controller parked on its target-ready handshake.
smc_dual_axi_sram_probe_test is the measurement that the AXI path into the
scratch window works at all.

Both the staging address and the transfer destination are drawn per run from the
OCCP window (see pick_payload_addresses). Fixed addresses would make "the ROM
honours the WRITE command's address field" and "the ROM ignores it and always
writes from the bottom of the window" indistinguishable, since the natural fixed
target address is the bottom of the window.

What a PASS requires, all of it:
  * the target ROM reaches its OCCP command loop (POST code phase OCCP_PROC)
  * the payload reads back from the controller's SRAM exactly as staged
  * the target's scratch 0 does NOT already hold TEST_PASS before the transfer
  * the controller's scratch 5-8 host protocol reads back exactly as seeded
  * real traffic on the shared I3C bus (SCL falls and START conditions counted
    by the testbench, not reported by firmware)
  * the standard pass magic in the target's scratch 0
  * the CONTROLLER never reporting TEST_FAIL -- checked every poll interval and
    for a grace window after the target passes, because the controller is still
    validating the JUMP response at that point and a rejection there would
    otherwise arrive after the test had declared success
  * the target's retired PC observed inside the transferred image, at an
    address that changes from run to run
  * a clean POST error field at the end

The retired PC check and the pre-transfer check on scratch 0 are what keep the
pass from being vacuous. The pass magic alone is the conventional signal and the
only thing the reference environment checks; requiring the core to have been seen
executing inside the transferred address range is stronger. See
smc_occp_dual_defs for why nothing else in this flow can write that scratch.

The payload's size and entry offset are read from the build's own artifacts
(.bin and .sym, staged next to the simulator cwd by the c_compile stage) rather
than hardcoded, so the test cannot drift from the image it transfers. The entry
offset resolves `main`, not `_enter`: the JUMP has to skip crt0, which would
otherwise re-run libc/BSP init underneath a live boot ROM.

Required plusargs:
  +rom_bin64=<prod_rom.bin64>                      target ROM
  +bfm_rom_hex=<occp_unsecure_boot_test.rom.hex>   controller ROM override
  +occp_payload_bin=<hello_world.sram.bin>         payload image, staged verbatim
  +occp_payload_sym=<hello_world.sram.sym>         payload symbol map, for the entry
"""

from __future__ import annotations

import logging
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_virt_console import VirtConsole
from smc_dual_base_test import DualCsr, SmcDualHarness, random_seed
from smc_occp_dual_defs import (
    CPU_RESET_VECTOR_ROM,
    CTRL_TARGET_READY_PAD,
    POST_CODE_BOOT_PHASE_ERROR,
    POST_CODE_BOOT_PHASE_OCCP_PROC,
    SCRATCH_BOOTCODE_ADDR,
    SCRATCH_BOOTCODE_SIZE,
    SCRATCH_ENTRY_OFFSET,
    SCRATCH_FW_SEED,
    SCRATCH_PASS_FAIL,
    SCRATCH_POST_CODE,
    SCRATCH_TARGET_ADDR,
    SMC_SRAM_BASE,
    TEST_FAIL,
    TEST_PASS,
    bus_activity,
    describe_post_code,
    format_activity,
    pick_payload_addresses,
    post_code_boot_phase,
    post_code_error,
    required_plusarg,
)

# Target ROM boot to its OCCP command loop; this bound is ~10x the boot time the
# single-instance path (smc_prod_rom_occp_ready_test) takes.
ROM_POLL_ITERS = 2000
ROM_POLL_CYCLES = 200

# The whole OCCP exchange: ENTDAA, then the payload in <=1024 B chunks, then
# JUMP. I3C at open-drain init rates dominates the run time: roughly 3.2 ms of
# sim time per 1024 B chunk on this top, so a 15 KB payload needs ~48 ms and the
# bound has to leave real headroom above that.
# The poll interval is coarse: each poll costs two CSR reads
# over SEP_IN AXI, and polling faster buys nothing when the thing being waited
# on takes milliseconds.
OCCP_POLL_ITERS = 40_000
OCCP_POLL_CYCLES = 2_000

# After the target reports PASS, keep watching the CONTROLLER for this many more
# poll intervals before accepting the result.
#
# The target passing does not mean the controller agrees. The payload writes
# TEST_PASS the moment it is entered, while the controller is still reading the
# JUMP response -- and if that response fails its header-CRC or status check the
# controller writes TEST_FAIL, which would otherwise land after this test had
# already declared success.
#
# 60 x 2000 clk_smc_i is 600 us of sim, roughly 20x the observed
# request-to-response round trip for a JUMP, and a negligible share of the
# test's wall clock.
CTRL_VERDICT_GRACE_ITERS = 60
# Log in-flight progress this often (here: every ~1 ms of sim time), so a stall
# shows up while it is happening rather than only in the timeout message.
PROGRESS_EVERY = 100


# The OCCP JUMP lands on main(), never on _enter. _enter is crt0: it zeroes
# sp/gp and re-runs libc/BSP init, which is not a valid thing to do to a machine
# whose boot ROM is still live and holding its own stack. main() in an
# sram-mode image is a leaf here -- see hello_world.sram.dis, nine instructions
# that materialise the scratch address and the pass magic from immediates and
# park in a relative branch -- so it runs correctly wherever it is transferred.
# entry_offset = &main - &_enter, resolved from the image's own symbol map.
PAYLOAD_ENTRY_SYMBOL = "main"
# The image's load base: the ELF entry point, hence byte 0 of the .bin.
PAYLOAD_LOAD_SYMBOL = "_enter"


def _payload_entry_offset(sym_path: str) -> int:
    """Offset of the payload's entry point within its own image.

    The OCCP JUMP target is target_addr + entry_offset, so this has to come from
    the image rather than being assumed. Measured against the image's own load
    base (`_enter`, the ELF entry point and therefore byte 0 of the .bin) rather
    than against the transfer destination, so it stays correct wherever the
    payload is transferred to. `nm -B -n` output is "<addr> <type> <name>".
    """
    addrs: dict[str, int] = {}
    for line in Path(sym_path).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in (PAYLOAD_ENTRY_SYMBOL, PAYLOAD_LOAD_SYMBOL):
            addrs[parts[2]] = int(parts[0], 16)
    for want in (PAYLOAD_LOAD_SYMBOL, PAYLOAD_ENTRY_SYMBOL):
        if want not in addrs:
            raise AssertionError(
                f"no {want} symbol in {sym_path}; cannot derive the OCCP JUMP entry offset"
            )
    offset = addrs[PAYLOAD_ENTRY_SYMBOL] - addrs[PAYLOAD_LOAD_SYMBOL]
    if offset < 0:
        raise AssertionError(
            f"{PAYLOAD_ENTRY_SYMBOL} ({addrs[PAYLOAD_ENTRY_SYMBOL]:#x}) is below "
            f"{PAYLOAD_LOAD_SYMBOL} ({addrs[PAYLOAD_LOAD_SYMBOL]:#x}); the entry "
            "point is not inside the transferred image"
        )
    return offset


async def _peek_target_scratch(dut, offset: int) -> tuple[int, int]:
    """Read one 64-bit word of the target's scratch SRAM, plus its ECC bits.

    CHK-OCCP-TRANSFER-LANDED asserts the first and last payload words returned
    here. It resolves the offset with smc_scratch_map_pkg, the same decode
    smc_dual_axi_sram_probe_test holds against AXI.

    Used to separate "the OCCP writes never landed" from "they landed and the
    core still would not execute them" when triaging a failure. An AXI read of
    the target's scratch window would be the better instrument -- SEP_IN does
    reach it, measured by smc_dual_axi_sram_probe_test -- but that needs the
    target's cluster boundary open, which is not guaranteed at the point a
    failure report is being assembled.
    """
    dut.tb_dut_scratch_peek_offset.value = offset
    # One delta plus a clock edge so the comb mux settles before sampling.
    await ClockCycles(dut.clk_smc_i, 2)
    return (
        int(dut.tb_dut_scratch_peek_data.value),
        int(dut.tb_dut_scratch_peek_ecc.value),
    )


def _payload_words(payload_bin: str) -> list[int]:
    """The payload as little-endian 64-bit words, straight from the image."""
    data = Path(payload_bin).read_bytes()
    return [int.from_bytes(data[i : i + 8], "little") for i in range(0, len(data), 8)]


async def _describe_landing(dut, target_offset: int, expect_words) -> str:
    """Word-by-word comparison of target SRAM against the payload image.

    This is the line that decides which half of the flow is at fault, so it
    reports actual vs expected rather than just a boolean.
    """
    lines = []
    mismatches = 0
    for idx, expected in enumerate(expect_words):
        got, ecc = await _peek_target_scratch(dut, target_offset + idx * 8)
        ok = got == expected
        if not ok:
            mismatches += 1
        if idx < 4 or not ok:
            lines.append(
                f"    [{idx:3d}] @{target_offset + idx * 8:#07x} "
                f"got={got:#018x} ecc={ecc:#04x} "
                f"exp={expected:#018x} {'ok' if ok else 'MISMATCH'}"
            )
    head = (
        f"  target SRAM vs payload image: {len(expect_words) - mismatches}"
        f"/{len(expect_words)} words match"
    )
    return "\n".join([head, *lines])


async def _scan_for_payload(dut, signature: int, limit: int = 0x10_0000) -> str:
    """Search the whole target scratch SRAM for the payload's first word.

    Answers a question the fixed-address check cannot: if the bytes are not at
    the requested address, are they anywhere at all?

      * found elsewhere  -> the ROM's OCCP WRITE path mishandled the address
      * found nowhere    -> the stores never reached the SRAM array. Note this
                            does NOT mean they never happened: this peek reads
                            the array directly and so bypasses the CPU
                            write-back data cache, where volatile byte stores
                            would still be sitting dirty.

    Distinguishing those last two needs a read that goes *through* the cache,
    which this peek cannot do.
    """
    hits = []
    for offset in range(0, limit, 8):
        word, _ = await _peek_target_scratch(dut, offset)
        if word == signature:
            hits.append(offset)
            if len(hits) >= 8:
                break
    if not hits:
        return (
            f"  scan: payload signature {signature:#018x} found NOWHERE in the "
            f"target's {limit // 1024} KB scratch SRAM"
        )
    return "  scan: payload signature found at offsets " + ", ".join(
        f"{h:#07x} (addr {SMC_SRAM_BASE + h:#010x})" for h in hits
    )


def _tx_snoop(dut) -> str:
    """What the controller actually pushed into the I3C TX port."""
    count = int(dut.tb_bfm_i3c_tx_count.value)
    # Flat scalars, not an unpacked-array handle -- see the note on the
    # per-channel counters in tb_top.sv (SMC_DUAL half).
    words = [int(getattr(dut, f"tb_bfm_i3c_tx_word_{i}").value) for i in range(8)]
    return (
        f"  controller I3C TX-port writes = {count} DWORD(s)\n"
        "  first words (LE bytes on the wire): " + ", ".join(f"{w:#010x}" for w in words)
    )


@cocotb.test()
async def smc_occp_dual_unsecure_boot_test(_dut) -> None:
    harness = SmcDualHarness()
    dut = harness.dut

    payload_bin = required_plusarg("occp_payload_bin", "smc_occp_dual_unsecure_boot_test")
    payload_sym = required_plusarg("occp_payload_sym", "smc_occp_dual_unsecure_boot_test")
    payload_bytes = Path(payload_bin).read_bytes()
    payload_size = len(payload_bytes)
    entry_offset = _payload_entry_offset(payload_sym)
    # Staged by cocotb into the controller's own scratch SRAM over AXI, then
    # read back out of it by the controller firmware with ordinary 64-bit loads.
    payload_addr, target_addr = pick_payload_addresses(random_seed(), payload_size)
    # Expected image contents, used both to verify staging in the controller and
    # to verify arrival in the target.
    expect_words = _payload_words(payload_bin)
    target_offset = target_addr - SMC_SRAM_BASE
    required_plusarg("rom_bin64", "smc_occp_dual_unsecure_boot_test")
    required_plusarg("bfm_rom_hex", "smc_occp_dual_unsecure_boot_test")

    assert payload_size > 0, f"payload image {payload_bin} is empty"
    # The controller firmware reads the payload with 64-bit loads only while
    # (i + 8) <= chunk_size, and byte-at-a-time after that. Those tail reads are
    # unaligned and wedge the core mid-transfer, which presents as the I3C bus
    # simply going quiet. Fail loudly here instead, because the hang is otherwise
    # a two-hour timeout with no explanation.
    assert payload_size % 8 == 0, (
        f"payload image {payload_bin} is {payload_size} bytes, which is not a "
        "multiple of 8. The OCCP controller firmware cannot read a non-8-aligned "
        "tail without issuing unaligned accesses that stall the transfer."
    )

    # Both addresses vary per run, so the log has to carry them and the seed
    # that produced them -- otherwise a failure is not reproducible.
    cocotb.log.info(
        "OCCP dual boot (RANDOM_SEED=%d): payload %d bytes staged at controller "
        "%#010x -> target %#010x, entry offset %#x. Both addresses drawn from "
        "the OCCP window; re-run with the same RANDOM_SEED to reproduce.",
        random_seed(),
        payload_size,
        payload_addr,
        target_addr,
        entry_offset,
    )

    # Both cores held at boot_stall from t=0 so their reset vectors can be set.
    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True)

    # Decode both firmware virtual consoles. The controller's simputs() trace is
    # the only window into the OCCP exchange -- without it a stalled transfer is
    # an unexplained timeout.
    bfm_console = VirtConsole(dut.bfm_scratch2, "ctrl-fw")
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(bfm_console.run())
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)

    # ------------------------------------------------------------------
    # 1. Bring the target up first. The controller polls the target-ready pad
    #    and then issues ENTDAA, so the target must already be
    #    servicing OCCP or the first transfer is lost.
    # ------------------------------------------------------------------
    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)

    phase_trace: list[int] = []
    post = 0
    for _ in range(ROM_POLL_ITERS):
        await ClockCycles(dut.clk_smc_i, ROM_POLL_CYCLES)
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        phase = post_code_boot_phase(post)
        if not phase_trace or phase_trace[-1] != phase:
            phase_trace.append(phase)
        if phase == POST_CODE_BOOT_PHASE_ERROR:
            raise AssertionError(
                f"target ROM entered its ERROR phase before any OCCP traffic: "
                f"{describe_post_code(post)} trace={[hex(p) for p in phase_trace]}"
            )
        if phase == POST_CODE_BOOT_PHASE_OCCP_PROC:
            break
    else:
        raise AssertionError(
            f"target ROM never reached its OCCP command loop within "
            f"{ROM_POLL_ITERS}x{ROM_POLL_CYCLES} clk_smc_i: "
            f"{describe_post_code(post)} trace={[hex(p) for p in phase_trace]} "
            f"rom_reads={int(dut.dut_rom_read_count.value)}"
        )
    cocotb.log.info(
        "CHK-OCCP-TARGET-READY: target ROM in its OCCP command loop, POST %s (trace=%s)",
        describe_post_code(post),
        [hex(p) for p in phase_trace],
    )

    # The pass register must be clean before the transfer, otherwise a stale
    # value could be mistaken for proof of execution later.
    pre_pass = await dut_csr.read("TARGET_PASS_PRE", SCRATCH_PASS_FAIL)
    assert pre_pass != TEST_PASS, (
        f"target scratch 0 already holds TEST_PASS {TEST_PASS:#010x} before the "
        "transfer; the pass check would be vacuous"
    )
    cocotb.log.info(
        "CHK-OCCP-PRECONDITION: target scratch0=%#010x, not the pass value",
        pre_pass,
    )

    baseline_activity = bus_activity(dut)

    # ------------------------------------------------------------------
    # 2. Stage the payload in the controller's SRAM, front door.
    #
    #    Two constraints pull in opposite directions. Staging over AXI needs the
    #    controller's cluster boundary open, which needs ALL FOUR cores out of
    #    reset -- so the controller cannot be held. But the staged bytes have to
    #    be in place before its firmware reads the host protocol out of
    #    scratch 5-8.
    #
    #    The target-ready pad resolves it. The firmware spins on it inside
    #    initialize_interface(), well before it looks at scratch 5-8, so holding
    #    it low gives an unbounded window with the cores running. Released again
    #    once staging and seeding are done.
    # ------------------------------------------------------------------
    harness.set_gpio_override("bfm", CTRL_TARGET_READY_PAD, 0)

    # Seed the controller firmware's RNG before its cores fetch, because
    # init_test() latches it in the first instructions of main(). An unseeded 0
    # is a fixed point of that LFSR, which silently pins two protocol choices for
    # the whole run: whether a body CRC is present, and which I3C channel to use.
    # Forced non-zero for the same reason.
    fw_seed = (random_seed() * 2_654_435_761) & 0xFFFF_FFFF or 0x1234_5678
    await bfm_csr.write("FW_SEED", SCRATCH_FW_SEED, fw_seed, length=8)
    seed_rdbk = await bfm_csr.read("FW_SEED_RDBK", SCRATCH_FW_SEED, length=8)
    assert seed_rdbk == fw_seed, (
        f"controller RNG seed readback {seed_rdbk:#x} != {fw_seed:#x}; the "
        "firmware would fall back to a frozen LFSR"
    )
    cocotb.log.info(
        "CHK-OCCP-FW-SEED: controller RNG seeded %#010x (from RANDOM_SEED=%d); "
        "body-CRC presence and I3C channel choice now vary per run",
        fw_seed,
        random_seed(),
    )

    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    await bfm_csr.write_bytes("PAYLOAD_STAGE", payload_addr, payload_bytes)

    # Read the whole image back rather than spot-checking the ends: this is the
    # one place where a staging bug is cheap to catch, and every later symptom
    # of a bad stage (the controller streaming zeros, the target refusing to
    # execute) is expensive to diagnose.
    staged = await bfm_csr.read_bytes("PAYLOAD_RDBK", payload_addr, payload_size)
    if staged != payload_bytes:
        first_bad = next(i for i, (a, b) in enumerate(zip(staged, payload_bytes)) if a != b)
        raise AssertionError(
            f"payload staged into the controller's SRAM at {payload_addr:#010x} "
            f"does not read back: first mismatch at byte {first_bad} "
            f"(+{first_bad:#x}), got {staged[first_bad]:#04x} expected "
            f"{payload_bytes[first_bad]:#04x}. The controller would stream "
            "garbage to the target."
        )
    cocotb.log.info(
        "CHK-OCCP-PAYLOAD-STAGED: %d bytes read back from the controller's SRAM "
        "at %#010x byte-for-byte",
        payload_size,
        payload_addr,
    )

    # ------------------------------------------------------------------
    # 3. Seed the controller's host protocol.
    # ------------------------------------------------------------------
    await bfm_csr.write("BOOTCODE_ADDR", SCRATCH_BOOTCODE_ADDR, payload_addr, length=8)
    await bfm_csr.write("BOOTCODE_SIZE", SCRATCH_BOOTCODE_SIZE, payload_size, length=8)
    await bfm_csr.write("TARGET_ADDR", SCRATCH_TARGET_ADDR, target_addr, length=8)
    await bfm_csr.write("ENTRY_OFFSET", SCRATCH_ENTRY_OFFSET, entry_offset, length=8)

    for name, addr, expected in (
        ("BOOTCODE_ADDR", SCRATCH_BOOTCODE_ADDR, payload_addr),
        ("BOOTCODE_SIZE", SCRATCH_BOOTCODE_SIZE, payload_size),
        ("TARGET_ADDR", SCRATCH_TARGET_ADDR, target_addr),
        ("ENTRY_OFFSET", SCRATCH_ENTRY_OFFSET, entry_offset),
    ):
        got = await bfm_csr.read(f"{name}_RDBK", addr, length=8)
        assert got == expected, f"controller scratch readback {name}: {got:#x} != {expected:#x}"
    cocotb.log.info(
        "CHK-OCCP-HOST-PROTOCOL: controller scratch 5-8 seeded and read back "
        "(addr=%#010x size=%d target=%#010x entry_offset=%#x)",
        payload_addr,
        payload_size,
        target_addr,
        entry_offset,
    )

    # ------------------------------------------------------------------
    # 4. Let the controller past its target-ready handshake. Its cores have
    #    been running since the staging step; this is the only thing still
    #    holding it, and from here on the two firmwares own the protocol.
    # ------------------------------------------------------------------
    harness.set_gpio_override("bfm", CTRL_TARGET_READY_PAD, None)
    cocotb.log.info(
        "released the controller's GPIO %d target-ready handshake",
        CTRL_TARGET_READY_PAD,
    )

    transfer_landed = False

    async def _fail_on_ctrl_verdict(when: str) -> None:
        """Fail if the CONTROLLER reported failure, whatever the target says.

        The controller firmware only ever writes its scratch 0 to say TEST_FAIL;
        on success it writes nothing there and leaves the verdict to
        the target. So a read that equals TEST_FAIL is unambiguous, and anything
        else is not a controller failure.

        Without this the controller's entire response-validation path is dead
        weight: it verifies every OCCP response's header CRC and status code and
        nobody looks at the result.
        """
        ctrl = await bfm_csr.read("CTRL_VERDICT", SCRATCH_PASS_FAIL)
        if ctrl != TEST_FAIL:
            return
        bfm_console.flush()
        dut_console.flush()
        raise AssertionError(
            f"the OCCP controller reported TEST_FAIL ({TEST_FAIL:#010x}) in its "
            f"own scratch 0, {when}.\n"
            "  It rejected something the target sent -- an OCCP response whose "
            "header CRC or status code failed its check, or a transfer it could "
            "not complete. The target's own result does not override this: the "
            "payload can be running while the protocol that delivered it was "
            "broken.\n"
            f"  target scratch0 = {passv:#010x}\n"
            f"  transfer landed  = {transfer_landed}\n"
            f"{_tx_snoop(dut)}\n"
            f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
            f"  controller wb_pc0={int(dut.bfm_wb_pc0.value):#x} "
            f"rom_reads={int(dut.bfm_rom_read_count.value)}\n"
            f"controller firmware trace:\n{bfm_console.tail()}\n"
            f"target firmware trace:\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    passv = 0
    pc_in_payload = False
    for iteration in range(OCCP_POLL_ITERS):
        await ClockCycles(dut.clk_smc_i, OCCP_POLL_CYCLES)

        # Checked every iteration, not only at the end: a controller-side
        # rejection can happen at any chunk, and the sooner it is caught the
        # smaller the log to read.
        await _fail_on_ctrl_verdict(f"at poll {iteration}/{OCCP_POLL_ITERS}")

        # Same reasoning for the target's POST error field. A single sample at
        # the end cannot see a mid-transfer error, because the ROM clears the
        # field on the next successful command -- one bad chunk followed by one
        # good one reads back clean.
        live_post = await dut_csr.read("TARGET_POST_LIVE", SCRATCH_POST_CODE)
        if post_code_error(live_post) != 0:
            bfm_console.flush()
            dut_console.flush()
            raise AssertionError(
                f"target latched a POST error during the transfer at poll "
                f"{iteration}/{OCCP_POLL_ITERS}: {describe_post_code(live_post)}\n"
                "  Caught live because the ROM clears this field on the next "
                "successful command, so an end-of-test sample would have missed "
                "it.\n"
                f"  transfer landed = {transfer_landed}\n"
                f"{_tx_snoop(dut)}\n"
                f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
                f"controller firmware trace:\n{bfm_console.tail()}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )

        # Has the image arrived in the target's SRAM yet? Checking the first and
        # last word is enough to tell "arrived" from "never arrived", and it
        # pins down which half of the flow to blame if the payload never runs.
        if not transfer_landed:
            first, first_ecc = await _peek_target_scratch(dut, target_offset)
            last, _ = await _peek_target_scratch(dut, target_offset + (len(expect_words) - 1) * 8)
            if first == expect_words[0] and last == expect_words[-1]:
                transfer_landed = True
                cocotb.log.info(
                    "CHK-OCCP-TRANSFER-LANDED: target SRAM at %#010x holds the "
                    "payload (first word %#018x ecc=%#04x, last word %#018x); "
                    "the OCCP WRITE stream reached the right address",
                    target_addr,
                    first,
                    first_ecc,
                    last,
                )

        passv = await dut_csr.read("TARGET_PASS", SCRATCH_PASS_FAIL)
        if passv == TEST_FAIL:
            post = await dut_csr.read("TARGET_POST_CODE_FAIL", SCRATCH_POST_CODE)
            landed_report = await _describe_landing(dut, target_offset, expect_words)
            scan_report = await _scan_for_payload(dut, expect_words[0])
            bfm_console.flush()
            dut_console.flush()
            raise AssertionError(
                f"target reported TEST_FAIL ({TEST_FAIL:#010x}) in scratch 0.\n"
                f"  transfer landed = {transfer_landed}\n"
                f"{landed_report}\n"
                f"{scan_report}\n"
                f"{_tx_snoop(dut)}\n"
                f"  target POST     = {describe_post_code(post)}\n"
                f"  target wb_pc0={int(dut.dut_wb_pc0.value):#x} "
                f"scratch_reads={int(dut.dut_scratch_read_count.value)} "
                f"scratch_writes={int(dut.dut_scratch_write_count.value)} "
                f"rom_reads={int(dut.dut_rom_read_count.value)}\n"
                f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
                f"controller firmware trace:\n{bfm_console.tail()}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )
        if passv == TEST_PASS:
            break
        # Track the target's retired PC so the pass can be tied to the core
        # actually executing inside the transferred image, not only to the
        # scratch values it left behind.
        pc_now = int(dut.dut_wb_pc0.value)
        if target_addr <= pc_now < target_addr + payload_size:
            pc_in_payload = True
        # Periodic progress so a stall is visible while it is happening, not
        # only in the timeout message an hour later.
        if iteration and iteration % PROGRESS_EVERY == 0:
            cocotb.log.info(
                "OCCP in flight (poll %d/%d): target pass=%#010x, bus [%s], ctrl wb_pc0=%#x",
                iteration,
                OCCP_POLL_ITERS,
                passv,
                format_activity(bus_activity(dut)),
                int(dut.bfm_wb_pc0.value),
            )
    else:
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        bfm_post = await bfm_csr.read("CTRL_SCRATCH0", SCRATCH_PASS_FAIL)
        landed_report = await _describe_landing(dut, target_offset, expect_words)
        bfm_console.flush()
        dut_console.flush()
        raise AssertionError(
            "OCCP unsecure boot did not complete within "
            f"{OCCP_POLL_ITERS}x{OCCP_POLL_CYCLES} clk_smc_i.\n"
            f"  target scratch0 (pass magic)    = {passv:#010x} "
            f"(expected {TEST_PASS:#010x})\n"
            f"  target POST                     = {describe_post_code(post)}\n"
            f"  transfer landed                 = {transfer_landed}\n"
            f"{landed_report}\n"
            f"{_tx_snoop(dut)}\n"
            f"  controller scratch0             = {bfm_post:#010x}\n"
            f"  target rom_reads={int(dut.dut_rom_read_count.value)} "
            f"scratch_writes={int(dut.dut_scratch_write_count.value)} "
            f"wb_pc0={int(dut.dut_wb_pc0.value):#x}\n"
            f"  controller rom_reads={int(dut.bfm_rom_read_count.value)} "
            f"wb_pc0={int(dut.bfm_wb_pc0.value):#x}\n"
            f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
            f"controller firmware trace (last lines):\n{bfm_console.tail()}\n"
            f"target firmware trace (last lines):\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    # ------------------------------------------------------------------
    # 5. Give the controller time to disagree.
    #
    #    The target reached TEST_PASS, which only proves the payload is running.
    #    The controller is still finishing the JUMP response at this point, and
    #    that is exactly where a rejection would surface. Keep watching it.
    # ------------------------------------------------------------------
    for grace in range(CTRL_VERDICT_GRACE_ITERS):
        await ClockCycles(dut.clk_smc_i, OCCP_POLL_CYCLES)
        await _fail_on_ctrl_verdict(
            f"{grace + 1}/{CTRL_VERDICT_GRACE_ITERS} poll intervals after the target reported PASS"
        )
    ctrl_scratch0 = await bfm_csr.read("CTRL_VERDICT_FINAL", SCRATCH_PASS_FAIL)
    cocotb.log.info(
        "CHK-OCCP-CONTROLLER-NO-FAIL: controller scratch0=%#010x (not TEST_FAIL "
        "%#010x) throughout the transfer and for %d poll intervals after the "
        "target passed; it rejected no OCCP response",
        ctrl_scratch0,
        TEST_FAIL,
        CTRL_VERDICT_GRACE_ITERS,
    )
    # What this check does NOT establish: the controller never signals success
    # while it is waiting for ROM completion, so there is no positive
    # confirmation that it finished cleanly, only the absence of a
    # rejection. Turning that into a positive gate means waiting for its
    # "Done, waiting for ROM to complete" console line, which changes when the
    # simulation ends.
    # bfm_console.lines is the full history; tail() is only the last 40.
    if any("Done, waiting for ROM" in line for line in bfm_console.lines):
        cocotb.log.info("controller also reached its own terminal state (console)")
    else:
        cocotb.log.info(
            "NOTE: controller had not printed its terminal line when the test "
            "ended; the grace window bounds how long the test waits for a "
            "rejection, not for completion."
        )

    # ------------------------------------------------------------------
    # The two halves must actually have talked on the wire.
    # ------------------------------------------------------------------
    activity = bus_activity(dut)
    # Both counters, not just SCL. A clocking artefact could move scl_falls
    # without a single framed transfer on the wire; a START delta is the
    # cheapest evidence that what moved was addressed I3C traffic.
    moved = [
        (ch, falls - base_falls, starts - base_starts)
        for (ch, falls, starts), (_, base_falls, base_starts) in zip(activity, baseline_activity)
        if falls > base_falls and starts > base_starts
    ]
    assert moved, (
        "target reported the pass magic, but no I3C channel saw both an SCL "
        f"fall and a START condition during the transfer: "
        f"[{format_activity(activity)}]. "
        "The pass cannot have come from an OCCP transfer."
    )
    used = ", ".join(
        f"I3C{ch} (+{falls} scl_falls, +{starts} starts)" for ch, falls, starts in moved
    )
    cocotb.log.info("CHK-OCCP-BUS-ACTIVITY: transfer seen on %s", used)

    # The SRAM peek gates this test, and what makes that sound is the decode
    # behind it.
    #
    # The peek resolves the offset with smc_scratch_map_pkg, whose geometry
    # comes from spm_memory.rdl and cpu.adoc and whose interleave is a DV-owned
    # table declared in its header -- held against AXI by
    # smc_dual_axi_sram_probe_test, which requires the backdoor to resolve to
    # the macro word AXI just wrote across six offsets: both stripe bits, the
    # entry low bits, the +0x100 wrap of the four-bank cycle, and the next
    # 128 KB group.
    #
    # That matters here specifically because pick_payload_addresses draws the
    # destination from anywhere in the OCCP window, so the peek is almost never
    # reading offset 0. A decode that is right only for the first 256 bytes
    # cannot tell a payload that never arrived from one it is looking for in
    # the wrong bank. With the decode measured, a "not landed" result is a
    # statement about the DUT, and CHK-OCCP-TRANSFER-LANDED is a pass criterion
    # in this testcase's VPLAN entry -- so it raises.
    #
    # The pass does not rest on the peek alone: the pass magic in the target's
    # scratch 0, which the pre-transfer check proved was not already there and
    # which nothing in this flow but the transferred image writes (see
    # smc_occp_dual_defs), and the retired-PC check below, are independent.
    assert transfer_landed, (
        f"CHK-OCCP-TRANSFER-LANDED: the target reported the pass magic, but its "
        f"SRAM never held the payload's first and last word at {target_addr:#010x}. "
        f"The backdoor decode is measured against AXI by "
        f"smc_dual_axi_sram_probe_test, so this is the OCCP WRITE stream landing "
        f"somewhere other than the address the ROM was given, not a wrong "
        f"instrument.\n"
        f"target firmware trace:\n{dut_console.tail()}"
    )
    cocotb.log.info(
        "target SRAM peek agrees with the payload image at %#010x",
        target_addr,
    )

    post = await dut_csr.read("TARGET_POST_CODE_FINAL", SCRATCH_POST_CODE)
    assert post_code_error(post) == 0, (
        f"target ROM latched a POST error during the transfer: {describe_post_code(post)}"
    )

    # Direct evidence that control actually transferred: the payload ends in a
    # wfi/park loop, so once the JUMP lands the target's retired PC stays inside
    # the transferred image. Sample it now rather than relying only on the
    # scratch values.
    final_pc = int(dut.dut_wb_pc0.value)
    harness.dump_cpu_trace(logging.INFO)
    pc_parked_in_payload = target_addr <= final_pc < target_addr + payload_size
    assert pc_in_payload or pc_parked_in_payload, (
        f"target scratch shows the payload's results, but its retired PC "
        f"({final_pc:#x}) was never observed inside the transferred image "
        f"[{target_addr:#x}, {target_addr + payload_size:#x}). "
        "Control transfer to the payload is not demonstrated."
    )
    cocotb.log.info(
        "CHK-OCCP-JUMP-EXECUTED: target retired PC %#x is inside the "
        "transferred image [%#x, %#x) -- the OCCP JUMP transferred control and "
        "the core is parked in the payload",
        final_pc,
        target_addr,
        target_addr + payload_size,
    )

    bfm_console.flush()
    dut_console.flush()
    cocotb.log.info(
        "CHK-OCCP-PAYLOAD-EXECUTED: target scratch0=%#010x (TEST_PASS); the "
        "transferred image ran on the target. Final target POST %s",
        passv,
        describe_post_code(post),
    )
    cocotb.log.info("smc_occp_dual_unsecure_boot_test PASS")

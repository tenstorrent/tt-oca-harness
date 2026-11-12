# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CPU writes the manifest modulus into OTBN DMEM; the Key Manager stays idle through BL0.

rom.adoc, Secure Boot, Signature Verification:

    [SEP-ROM-SB-110] The manifest's public key shall be delivered directly to OTBN, and the Key
    Manager shall take no part in secure-boot signature verification. A public key is not secret,
    so there is nothing for key-derivation hardware to protect, and routing it through the Key
    Manager would make secure boot depend on a block the ROM otherwise does not use. An earlier
    specification described provisioning the manifest's public key `(n, e)` into the Key Manager
    through its software write port; that description is withdrawn and should not be
    reintroduced.

rom.adoc, Signature Verification, which says what verification is:

    Verification runs on the OTBN coprocessor: the ROM loads the embedded RSA-3072
    modular-exponentiation program into OTBN IMEM/DMEM, supplies the modulus, signature, and
    expected digest, executes with a timeout, and compares the recovered PKCS#1 v1.5 encoding
    against the SHA-256 digest of the signed region.

rom.adoc, tbl:hw_blocks: "KMAC, key manager mailbox |`0x10913000`, `0x10920000` |Present in the
subsystem; not used by BL0."

The BL0 run is from the first retirement to the hand-off mret. Bus events are handshakes on the
PR-LSU-XBAR tap (CPU LSU port to the local crossbar) at the RDL addresses. The modulus buffer is
`rsa_n` of the OTBN application the ROM links; OTBN reads a DMEM buffer as a little-endian
integer. EXECUTE is the first OTBN BUSY_EXECUTE interval of the run, and its command write is the
last OTBN CMD AW before it. The Key Manager probes are tb_top copies of the five key-path port
requests of the crypto interconnect, of the eight engine sideload key valids and of the Key
Manager CPU fetch count. A strict per-clock recorder keeps an X or Z sample as unknown.

* CHK-NO-KM-TO-OTBN: across the BL0 run every key-path AW and AR valid (km_key_aw_valid_o,
  km_key_ar_valid_o: OTBN, AES, HMAC, KMAC, ABR) and every engine sideload key valid
  (km_engine_key_valid_o) stays a known 0, the Key Manager CPU fetch count stays a known
  constant, and the CPU makes no access to the Key Manager mailbox aperture.
* CHK-CPU-WRITES-MODULUS: before the EXECUTE command write every word of the 384-byte modulus
  buffer takes at least one 4-byte CPU write with BRESP OKAY; from the start of the run to the B
  of the command write the DMEM write count of the OTBN SRAM grows by exactly the number of CPU
  AWs into DMEM; the count does not change from the end of the last OTBN execution to the end of
  the read-back; the read-back of the buffer by the debug-module system-bus master after the
  run, as a little-endian integer, equals the nonzero modulus n of the RSA key that signed the
  accepted manifest.
* CTRL-RUN-WINDOW: the first retirement and the hand-off mret are recorded, every CPU-LSU OTBN
  beat and every OTBN execution lies between them, and no tap beat has an unknown address.
* CTRL-RSA-RAN: at least one OTBN execution in the run, its command write has BRESP OKAY, it
  ends before the hand-off mret, OTBN status is IDLE at the mret, and RSA_EXEC and RSA_VERIFY_OK
  are printed.
* CTRL-KM-PROBES-RECORDED: the strict recorder sampled from before the first retirement to after
  the hand-off mret.
* CTRL-SERVED-MODULUS: the console names only the primary manifest (MANIFEST_SRC=0x00001000),
  the flash served the primary key field byte for byte as the image holds it, and the field's
  SHA-256 matches a ROM key digest whose private key is in the tree (n is taken from that key).

Four conditions go beyond what the spec states and encode the shape of this ROM's boot: the CPU
is the only DMEM writer before EXECUTE; the first BUSY_EXECUTE interval is the RSA run; no DMEM
write happens between the end of the last execution and the read-back; OTBN is IDLE at the
hand-off. CHK-NO-KM-TO-OTBN grades more than its name says: every Key Manager key path, sideload
key valid, the Key Manager CPU and the mailbox. The Key Manager probes stay 0 because
SW_RESET_N.km_sw_rst_n resets to 0 (sep_reset_ctrl.rdl), and no positive control here shows them
toggle. Partial coverage. Not graded: the exponent, which SB-100 keeps out of OTBN; the data of
each CPU write, which the tap does not carry (the read-back stands for it); the addresses of the
OTBN core's own DMEM writes during EXECUTE (OBS-OTBN-DMEM-WRITES); the byte order of the
manifest key field (OBS-SERVED-ENCODING); mailbox accesses by masters other than the CPU LSU;
the sentence on the withdrawn text. Verilator is 2-state, so the X part of CHK-NO-KM-TO-OTBN can
fail only on VCS. The leaf runs `sep_rom_ot_secure_boot_test` and keeps its checks.
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from env.sep_chk_log import SepChkLog
from env.sep_fabric_tap import SepFabricTap
from env.sep_jtag_dmi import (
    DM_DMCONTROL,
    DMCONTROL_DMACTIVE,
    IR_DMI,
    IR_WIDTH,
    PIN_MAP,
    SepJtagDmi,
)
from env.sep_rom_observer import SepRomObserver
from ocah_jtag_vip import OcahJtagMasterDriver
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test as _Base
from sep_reg_meta import sym


def _aperture(key: str) -> tuple[int, int]:
    """[base, end) of one node of the generated memory map."""
    # On sys.path only after sep_reg_meta has added the generated register directory.
    import sep_memory_map

    for view in sep_memory_map.VIEWS.values():
        for row in view["rows"]:
            if row["key"] == key:
                return row["base"], row["end"] + 1
    raise KeyError(f"{key} not in sep_memory_map.py; regenerate the register collateral")


_OTBN_BASE = sym("OTBN_REG_MAP_BASE_ADDR")
_OTBN_END = _OTBN_BASE + sym("OTBN_REG_MAP_SIZE")
_DMEM_BASE = sym("OTBN_DMEM_MEM_BASE_ADDR")
_DMEM_END = _DMEM_BASE + sym("OTBN_DMEM_MEM_SIZE")
_OTBN_CMD = sym("OTBN_CMD_REG_ADDR")
_KM_MBOX_BASE, _KM_MBOX_END = _aperture("main:km_mailbox_sep")
_APP_H = (
    Path(__file__).resolve().parents[3]
    / "fw"
    / "build"
    / "otbn"
    / "rsa_3072_app"
    / "rsa_3072_app_otbn.h"
)
_RSA_N_RE = re.compile(
    r"_otbn_remote_app_rsa_3072_app_rsa_n \(\(const uint32_t\*\)(0x[0-9a-fA-F]+)\)"
)
_MOD_WORDS = mm.MODULUS_LEN // 4
# OTBN STATUS encodings of otbn_pkg (vendor OpenTitan otbn).
_STATUS_IDLE, _STATUS_BUSY_EXECUTE = 0x00, 0x01

_KM_AW, _KM_AR, _KM_KEY_VALID = "km_key_aw_valid_o", "km_key_ar_valid_o", "km_engine_key_valid_o"
_KM_AW_RDY, _KM_AR_RDY = "km_key_aw_ready_o", "km_key_ar_ready_o"
_KM_FETCH = "km_cpu_fetch_count_o"
_DMEM_WR = "otbn_dmem_write_count_o"
_KM_VALIDS = (_KM_AW, _KM_AR, _KM_KEY_VALID)
_KM_GRADED = (*_KM_VALIDS, _KM_FETCH)
_STRICT = (*_KM_GRADED, _KM_AW_RDY, _KM_AR_RDY, _DMEM_WR)
_OTBN_STATUS = "otbn_status_probe_o"

_TCK_CLKS = 4
_TRST_TCK = 4
_SB_BUSY_READS = 1024


def _ps(t: int | None) -> int:
    return -1 if t is None else int(t)


def _rsa_n_offset() -> int:
    m = _RSA_N_RE.search(_APP_H.read_text())
    if m is None:
        raise AssertionError(f"no rsa_n symbol in {_APP_H}; build the boot_rom firmware first")
    return int(m.group(1), 16)


def _value_at(obs: SepRomObserver, name: str, t: int) -> int:
    return next((v for tv, v in reversed(obs.watched[name]) if tv <= t), 0)


class _StrictProbes:
    """Per-clock change record of probes that keeps an X or Z sample as None instead of 0."""

    def __init__(self, names: tuple[str, ...]) -> None:
        self.changes: dict[str, list[tuple[int, int | None]]] = {n: [] for n in names}
        self.first_t: int | None = None
        self.last_t: int | None = None
        self._task = None

    def start(self) -> _StrictProbes:
        self._task = cocotb.start_soon(self._run())
        return self

    def stop(self) -> None:
        self._task.cancel()

    async def _run(self) -> None:
        dut = cocotb.top
        sigs = [(n, getattr(dut, n)) for n in self.changes]
        last: dict[str, object] = dict.fromkeys(self.changes, object())
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            t = int(get_sim_time("ps"))
            if self.first_t is None:
                self.first_t = t
            self.last_t = t
            for n, s in sigs:
                v = s.value
                val = int(v) if v.is_resolvable else None
                if val != last[n]:
                    last[n] = val
                    self.changes[n].append((t, val))

    def at(self, name: str, t: int | None) -> int | None:
        if t is None:
            return None
        return next((v for tv, v in reversed(self.changes[name]) if tv <= t), None)

    def values_in(self, name: str, lo: int, hi: int) -> list[int | None]:
        """The value held at lo and every value taken in (lo, hi]."""
        return [self.at(name, lo)] + [v for t, v in self.changes[name] if lo < t <= hi]

    def covers(self, lo: int, hi: int) -> bool:
        return None not in (self.first_t, self.last_t) and self.first_t <= lo and hi <= self.last_t


@pyuvm.test()
class sep_rom_rsa_key_direct_otbn_test(_Base):
    required_evidence = (
        "CHK-NO-KM-TO-OTBN",
        "CHK-CPU-WRITES-MODULUS",
        "CHK-ROM-PATH",
        "CHK-OTBN-EDN",
    )

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        self._flash_txns: list = []
        xbar = SepFabricTap("PR-LSU-XBAR").start()
        obs = SepRomObserver(
            self, keep=lambda _insn: False, tracker=False, watch=(_OTBN_STATUS,)
        ).start()
        strict = _StrictProbes(_STRICT).start()
        try:
            await super().run_scenario()
        finally:
            dmem = await self._read_dmem(_DMEM_BASE + _rsa_n_offset(), _MOD_WORDS)
            await obs.stop()
            # Stopped after the observer's clock edges, so it holds a sample past the read-back.
            strict.stop()
            await xbar.stop()
        self._grade(obs, xbar, strict, dmem)
        self.chk.finish()

    def log_transport(self, flash) -> None:
        self._flash_txns = flash.get_transactions()

    async def _read_dmem(self, addr: int, words: int) -> dict:
        """DMEM words read by the debug-module system-bus master, not by the ROM."""
        dut = cocotb.top
        out: dict = {"error": "none", "words": [], "sberr": [], "end_ps": None}
        tap = OcahJtagMasterDriver(
            dut,
            name="sep_core_tap",
            tck_period_ns=int(round(_TCK_CLKS * self.cfg.sys_clk_period_ns * 1000)),
            ir_width=IR_WIDTH,
            tap_type="dtm",
            signal_map=dict(PIN_MAP),
            time_unit="ps",
        )
        dmi = SepJtagDmi(tap, dut=dut, log=self.logger, busy_bound=_SB_BUSY_READS)
        dut.dmi_core_enable_i.value = 1
        dmi.take_pins()
        try:
            await dmi.trst_pulse(tck_cycles=_TRST_TCK)
            await tap.goto_state("RUN_TEST_IDLE")
            await tap.shift_ir(IR_DMI, IR_WIDTH, back_to_rti=True)
            await dmi.dmi_write(DM_DMCONTROL, DMCONTROL_DMACTIVE)
            for i in range(words):
                data, sberr = await dmi.sba_read(addr + 4 * i, size=4)
                out["words"].append(data)
                out["sberr"].append(sberr)
            out["end_ps"] = int(get_sim_time("ps"))
        except Exception as exc:
            # A failure of the debug path fails the content part instead of skipping it.
            out["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            dmi.release_pins()
            dut.dmi_core_enable_i.value = 0
        return out

    def _served_key_field(self) -> tuple[bytes | None, int]:
        """Key-field bytes the flash returned for the primary manifest, and the read count."""
        rds = ev.reads(self._flash_txns)
        base = mm.slot_base("primary") + mm.OFF_PUBLIC_KEY
        out = bytearray()
        for a in range(base, base + mm.MODULUS_LEN):
            hit = ev.covering_read(rds, a)
            if hit is None:
                return None, len(rds)
            out += ev.bytes_at(hit[1], a, 1)
        return bytes(out), len(rds)

    def _grade(
        self, obs: SepRomObserver, xbar: SepFabricTap, strict: _StrictProbes, dmem: dict
    ) -> None:
        chk = self.chk
        lo = obs.first[0].t_ps if obs.first else None
        hi = obs.pre_mret[-1].t_ps if obs.pre_mret else None
        win = None not in (lo, hi) and lo < hi

        def in_win(t: int) -> bool:
            return win and lo <= t <= hi

        beats = xbar.beats
        aw = [b for b in beats if b.ch == "aw"]
        ar = [b for b in beats if b.ch == "ar"]
        # B of each AW: AXI returns the responses of one ID in AW order.
        resp_of: dict[int, object] = {}
        queues: dict[int | None, list] = {}
        for b in beats:
            if b.ch == "aw":
                queues.setdefault(b.id, []).append(b)
            elif b.ch == "b" and queues.get(b.id):
                resp_of[queues[b.id].pop(0).seq] = b

        def bresp(beat) -> int | None:
            rsp = resp_of.get(beat.seq)
            return None if rsp is None else rsp.resp

        otbn = [b for b in aw + ar if b.addr is not None and _OTBN_BASE <= b.addr < _OTBN_END]
        unknown = [b for b in aw + ar if b.addr is None]
        st = obs.watched[_OTBN_STATUS]
        execs = [
            (t, next((t2 for t2, v2 in st[i + 1 :] if v2 != _STATUS_BUSY_EXECUTE), None))
            for i, (t, v) in enumerate(st)
            if v == _STATUS_BUSY_EXECUTE
        ]
        chk.ctrl(
            "RUN-WINDOW",
            win
            and bool(otbn)
            and all(in_win(b.t_ps) for b in otbn)
            and bool(execs)
            and all(in_win(t0) and t1 is not None and in_win(t1) for t0, t1 in execs)
            and not unknown,
            first_retire_ps=_ps(lo),
            handoff_mret_ps=_ps(hi),
            lsu_otbn_beats=len(otbn),
            lsu_otbn_beats_outside=sum(1 for b in otbn if not in_win(b.t_ps)),
            executions=[(int(t0), _ps(t1)) for t0, t1 in execs],
            xbar_aw=len(aw),
            xbar_ar=len(ar),
            unknown_addr=len(unknown),
        )

        run = execs[0] if execs else None
        cmds = [b for b in aw if b.addr == _OTBN_CMD and run is not None and b.t_ps < run[0]]
        cmd = cmds[-1] if cmds else None
        cmd_rsp = None if cmd is None else resp_of.get(cmd.seq)
        t_cmd = None if cmd is None else cmd.t_ps
        t_cmd_b = None if cmd_rsp is None else cmd_rsp.t_ps
        t_exec_ok, t_vok = obs.line_t("RSA_EXEC"), obs.line_t("RSA_VERIFY_OK")
        chk.ctrl(
            "RSA-RAN",
            cmd is not None
            and bresp(cmd) == 0
            and run[1] is not None
            and in_win(run[1])
            and _value_at(obs, _OTBN_STATUS, hi or 0) == _STATUS_IDLE
            and None not in (t_exec_ok, t_vok),
            cmd_aw_ps=_ps(t_cmd),
            cmd_b_ps=_ps(t_cmd_b),
            cmd_bresp=-1 if cmd_rsp is None else cmd_rsp.resp,
            cmd_aw_before_execute=len(cmds),
            busy_execute_ps=_ps(run and run[0]),
            busy_execute_end_ps=_ps(run and run[1]),
            status_at_handoff=f"0x{_value_at(obs, _OTBN_STATUS, hi or 0):02x}",
            rsa_exec_line_ps=_ps(t_exec_ok),
            rsa_verify_ok_line_ps=_ps(t_vok),
        )

        chk.ctrl(
            "KM-PROBES-RECORDED",
            win and strict.covers(lo, hi),
            first_sample_ps=_ps(strict.first_t),
            last_sample_ps=_ps(strict.last_t),
            first_retire_ps=_ps(lo),
            handoff_mret_ps=_ps(hi),
        )
        held = {n: strict.values_in(n, lo, hi) if win else [None] for n in _STRICT}
        km_unknown = {n: sum(1 for v in held[n] if v is None) for n in _KM_GRADED}
        km_set = {n: sorted({v for v in held[n] if v}) for n in _KM_VALIDS}
        fetch = held[_KM_FETCH]
        mbox = [
            b
            for b in aw + ar
            if in_win(b.t_ps) and b.addr is not None and _KM_MBOX_BASE <= b.addr < _KM_MBOX_END
        ]
        chk.ok(
            "NO-KM-TO-OTBN",
            win
            and strict.covers(lo, hi)
            and not any(km_unknown.values())
            and not any(km_set.values())
            and len(fetch) == 1
            and not mbox
            and not unknown,
            first_retire_ps=_ps(lo),
            handoff_mret_ps=_ps(hi),
            unknown_samples=km_unknown,
            nonzero_values=km_set,
            km_cpu_fetch_count=[-1 if v is None else v for v in fetch],
            km_mailbox=f"0x{_KM_MBOX_BASE:08x}..0x{_KM_MBOX_END:08x}",
            km_mailbox_accesses=len(mbox),
        )
        chk.obs(
            "KM-READY",
            aw_ready=[-1 if v is None else v for v in held[_KM_AW_RDY]],
            ar_ready=[-1 if v is None else v for v in held[_KM_AR_RDY]],
            changes_in_run={n: max(len(strict.changes[n]) - 1, 0) for n in _STRICT[:-1]},
        )

        n_base = _DMEM_BASE + _rsa_n_offset()
        n_end = n_base + mm.MODULUS_LEN
        span = [b for b in aw if in_win(b.t_ps) and t_cmd is not None and b.t_ps < t_cmd]
        dmem_aw = [b for b in span if b.addr is not None and _DMEM_BASE <= b.addr < _DMEM_END]
        cnt_lo, cnt_cmd = strict.at(_DMEM_WR, lo), strict.at(_DMEM_WR, t_cmd_b)
        sole = None not in (cnt_lo, cnt_cmd) and cnt_cmd - cnt_lo == len(dmem_aw)
        mod_aw = [
            b
            for b in dmem_aw
            if n_base <= b.addr < n_end
            and b.addr % 4 == 0
            and b.size == 2
            and b.len == 0
            and bresp(b) == 0
        ]
        words_written = {(b.addr - n_base) // 4 for b in mod_aw}
        t_last_exec = execs[-1][1] if execs else None
        cnt_exec_end = strict.at(_DMEM_WR, t_last_exec)
        cnt_read_end = strict.at(_DMEM_WR, dmem.get("end_ps"))
        settled = (
            None not in (cnt_exec_end, cnt_read_end, dmem.get("end_ps"))
            and strict.last_t >= dmem["end_ps"]
            and all(
                v == cnt_exec_end for v in strict.values_in(_DMEM_WR, t_last_exec, dmem["end_ps"])
            )
        )

        served, n_reads = self._served_key_field()
        image = Path(self.flash_image).read_bytes()
        on_disk = mm.public_key_modulus(image, "primary")
        try:
            n_key = pm.load_rsa_private_key(
                pm.rom_signing_key(pm.signing_key_for_slot(image, "primary"))
            )[0]
        except (AssertionError, ValueError) as exc:
            n_key = None
            self.logger.error("signing key of the primary manifest not found: %s", exc)
        srcs = sorted(
            {ln.split("MANIFEST_SRC=")[1].split()[0] for ln in obs.lines() if "MANIFEST_SRC=" in ln}
        )
        chk.ctrl(
            "SERVED-MODULUS",
            served is not None
            and served == on_disk
            and n_key is not None
            and srcs == ["0x00001000"],
            flash_reads=n_reads,
            served=int(served is not None),
            equals_image=int(served == on_disk),
            signing_key_found=int(n_key is not None),
            manifest_src=srcs,
        )
        chk.obs(
            "SERVED-ENCODING",
            big_endian_is_n=int(served is not None and int.from_bytes(served, "big") == n_key),
            little_endian_is_n=int(
                served is not None and int.from_bytes(served, "little") == n_key
            ),
        )
        words = dmem.get("words", [])
        n_dmem = (
            int.from_bytes(b"".join(w.to_bytes(4, "little") for w in words), "little")
            if len(words) == _MOD_WORDS
            else None
        )
        sberr = sorted(set(dmem.get("sberr", [])))
        chk.ok(
            "CPU-WRITES-MODULUS",
            len(words_written) == _MOD_WORDS
            and sole
            and settled
            and dmem.get("error") == "none"
            and sberr == [0]
            and n_key is not None
            and n_key != 0
            and n_dmem == n_key,
            modulus_buf=f"0x{n_base:08x}..0x{n_end:08x}",
            words_written=len(words_written),
            words_expected=_MOD_WORDS,
            cpu_buffer_writes=len(mod_aw),
            cpu_dmem_aw_before_cmd=len(dmem_aw),
            dmem_sram_writes_before_cmd_b=-1 if None in (cnt_lo, cnt_cmd) else cnt_cmd - cnt_lo,
            dmem_write_count_after_execute=-1 if cnt_exec_end is None else cnt_exec_end,
            dmem_write_count_after_readback=-1 if cnt_read_end is None else cnt_read_end,
            cmd_aw_ps=_ps(t_cmd),
            last_execute_end_ps=_ps(t_last_exec),
            readback_end_ps=_ps(dmem.get("end_ps")),
            dmem_read_error=dmem.get("error", "not-run"),
            dmem_sberr=sberr,
            dmem_words_read=len(words),
            dmem_equals_key_n=int(n_dmem is not None and n_dmem == n_key),
            dmem_low_word=f"0x{words[0]:08x}" if words else "none",
            key_n_low_word=f"0x{n_key & 0xFFFF_FFFF:08x}" if n_key is not None else "none",
        )
        chk.obs(
            "OTBN-DMEM-WRITES",
            during_first_execute=-1
            if None in (cnt_cmd, strict.at(_DMEM_WR, run and run[1]))
            else strict.at(_DMEM_WR, run[1]) - cnt_cmd,
        )
        chk.obs(
            "OTBN-STATUS",
            sequence=[f"{_ps(t)}:0x{v:02x}" for t, v in st][:16],
            records=len(st),
        )

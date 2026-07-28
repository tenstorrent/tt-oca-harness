# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
ocah_memory_image.py — firmware / ROM / SRAM / OTBN image loader for SEP.

``OcahMemoryImage`` is the single Python API that tests use to load images into
SEP memory banks.  Tests never need per-bank backdoor knowledge; they call one
loader and let the class route sections to the correct banks, then call
``write_plusargs()`` to obtain the simulator command-line fragment.

Supported image formats
-----------------------
- ELF (RISC-V 32/64-bit, little-endian) via ``load_elf(path)``
- Intel HEX via ``load_hex(bank, path)``
- Raw binary via ``load_bin(bank, path, base_offset=0)``

ELF parsing requires ``pyelftools`` (``pip install pyelftools``).
All other functionality uses Python stdlib only.

Hex file format (Task #9 INTERFACE.md)
---------------------------------------
- One word per line, most-significant nibble first.
- Line N → word address N.
- Lines beginning with ``#`` are comments; blank lines are skipped.
- If the file is shorter than the memory depth, remaining entries are
  zero-initialized.
- Word width (hex digit count per line) is determined by ``MemoryBank.data_width_bits``.

Wide-word ECC / parity policy
-------------------------------
This module stores and emits ECC / parity bits as **zero** unless the caller
pre-encodes them in the source image.  ECC syndrome generation and parity
calculation are out of scope.
"""

from __future__ import annotations

import logging
import os
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .sep_memory_layout import MemoryBank, SepMemoryLayout

__all__ = ["OcahMemoryImage", "OcahMemoryImageError"]

log = logging.getLogger(__name__)


class OcahMemoryImageError(ValueError):
    """Raised when an image cannot be loaded or an address is out of range."""


# --------------------------------------------------------------------------- #
# Main class                                                                    #
# --------------------------------------------------------------------------- #

class OcahMemoryImage:
    """Unified firmware / ROM / SRAM / OTBN image loader for SEP memory banks.

    Instantiate once per test (or per simulation), call the relevant load
    methods, then call ``write_plusargs()`` to obtain the simulator argument
    list.

    Parameters
    ----------
    layout:
        ``SepMemoryLayout`` instance describing the address windows, depths,
        and plusarg names for each bank.  Defaults to
        ``SepMemoryLayout.default()`` which reflects the Task #9
        ``INTERFACE.md`` values.
    run_dir:
        Directory where per-bank hex files will be written by
        ``write_plusargs()``.  Defaults to the current working directory.
        The directory is created if it does not exist.

    Example
    -------
    ::

        img = OcahMemoryImage()
        img.load_elf("fw/sep/tests/hello_world/hello_world.elf")
        plusargs = img.write_plusargs()
        # Pass plusargs to the cocotb runner or simulation command line.

    """

    def __init__(
        self,
        layout: Optional[SepMemoryLayout] = None,
        run_dir: Optional[str] = None,
    ) -> None:
        self._layout = layout if layout is not None else SepMemoryLayout.default()
        self._run_dir = Path(run_dir) if run_dir is not None else Path.cwd()

        # Per-bank image storage: dict[bank_name -> list[int|None]]
        # Index == word address; None == not-loaded (will be emitted as 0).
        self._banks: Dict[str, List[Optional[int]]] = {
            name: [None] * bank.depth
            for name, bank in self._layout.banks.items()
        }

    # ------------------------------------------------------------------ #
    # ELF loader                                                            #
    # ------------------------------------------------------------------ #

    def load_elf(self, path: str) -> None:
        """Parse an ELF file and route LOAD segments to banks by address.

        Only PT_LOAD segments with non-zero file size are processed.
        Sections that do not fall in any bank's address window are logged at
        WARNING level and skipped.

        Requires ``pyelftools``.  Raises ``ImportError`` if not available.

        Parameters
        ----------
        path:
            Path to an ELF file.  Mach-O, PE, and COFF are not supported.
        """
        try:
            from elftools.elf.elffile import ELFFile  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pyelftools is required for ELF loading: pip install pyelftools"
            ) from exc

        elf_path = Path(path)
        if not elf_path.exists():
            raise OcahMemoryImageError(f"ELF file not found: {elf_path}")

        log.info("[OcahMemoryImage] loading ELF: %s", elf_path)

        with open(elf_path, "rb") as fh:
            elf = ELFFile(fh)

            if elf.header.e_ident["EI_DATA"] != "ELFDATA2LSB":
                raise OcahMemoryImageError(
                    f"Only little-endian ELF is supported; got "
                    f"{elf.header.e_ident['EI_DATA']}"
                )

            for seg in elf.iter_segments():
                if seg.header.p_type != "PT_LOAD":
                    continue
                if seg.header.p_filesz == 0:
                    continue

                vaddr = seg.header.p_vaddr
                paddr = seg.header.p_paddr
                memsz = seg.header.p_memsz
                data = seg.data()

                # Use physical address for memory placement (standard practice
                # for embedded RISC-V firmware).
                load_addr = paddr if paddr != 0 else vaddr

                log.debug(
                    "[OcahMemoryImage] PT_LOAD paddr=0x%08X vaddr=0x%08X filesz=%d memsz=%d",
                    paddr, vaddr, seg.header.p_filesz, memsz,
                )

                self._place_bytes(load_addr, data, source=str(elf_path))

    # ------------------------------------------------------------------ #
    # Intel HEX loader                                                      #
    # ------------------------------------------------------------------ #

    def load_hex(self, bank: str, path: str) -> None:
        """Load a bank directly from a Task #9-format hex file.

        The hex file format is the one defined in INTERFACE.md:
        one word per line, MSN first, comments start with ``#``.
        This is **not** Intel HEX format — it is the custom OCAH memory
        hex format.  For Intel HEX (.ihex / .hex from objcopy), use
        ``load_ihex()`` instead.

        Parameters
        ----------
        bank:
            Bank name (e.g. ``"sep_sram"``).
        path:
            Path to the OCAH hex preload file.
        """
        bk = self._get_bank(bank)
        hex_path = Path(path)
        if not hex_path.exists():
            raise OcahMemoryImageError(f"Hex file not found: {hex_path}")

        log.info("[OcahMemoryImage] loading hex → bank %r: %s", bank, hex_path)

        store = self._banks[bank]
        word_idx = 0
        digits = bk.hex_digits_per_word

        with open(hex_path, "r") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if word_idx >= bk.depth:
                    raise OcahMemoryImageError(
                        f"Bank {bank!r}: hex file {hex_path} has more words than "
                        f"bank depth ({bk.depth})"
                    )
                hex_str = line.split()[0]
                if len(hex_str) != digits:
                    raise OcahMemoryImageError(
                        f"Bank {bank!r}: line {word_idx}: expected {digits} hex digits, "
                        f"got {len(hex_str)} in {hex_path}"
                    )
                store[word_idx] = int(hex_str, 16)
                word_idx += 1

        log.debug("[OcahMemoryImage] loaded %d words into bank %r", word_idx, bank)

    def load_ihex(self, bank: str, path: str) -> None:
        """Load a bank from an Intel HEX (.ihex) file.

        Uses Python stdlib only (no intelhex package required).  Extended
        linear address records (type 04) and extended segment address records
        (type 02) are supported.  The load address for each byte is resolved
        against the bank's ``base_addr``; bytes that fall outside the bank
        window raise ``OcahMemoryImageError``.

        Parameters
        ----------
        bank:
            Bank name (e.g. ``"sep_sram"``).
        path:
            Path to the Intel HEX file.
        """
        bk = self._get_bank(bank)
        if bk.base_addr is None:
            raise OcahMemoryImageError(
                f"Bank {bank!r} has no CPU base address; cannot route Intel HEX "
                f"records by address.  Use load_hex() or load_bin() instead."
            )

        ihex_path = Path(path)
        if not ihex_path.exists():
            raise OcahMemoryImageError(f"Intel HEX file not found: {ihex_path}")

        log.info("[OcahMemoryImage] loading Intel HEX → bank %r: %s", bank, ihex_path)

        # Assemble a flat byte buffer covering the bank window, zero-filled.
        buf = bytearray(bk.size_bytes)
        upper_base = 0  # extended linear address (shifted left 16)
        seg_base = 0    # extended segment address (shifted left 4)

        with open(ihex_path, "r") as fh:
            for lineno, raw_line in enumerate(fh, 1):
                line = raw_line.strip()
                if not line.startswith(":"):
                    continue
                rec = bytes.fromhex(line[1:])
                byte_count = rec[0]
                offset = (rec[1] << 8) | rec[2]
                rec_type = rec[3]
                data = rec[4: 4 + byte_count]
                checksum = rec[4 + byte_count]

                # Validate checksum.
                cs = (-sum(rec[:-1])) & 0xFF
                if cs != checksum:
                    log.warning(
                        "[OcahMemoryImage] ihex checksum mismatch at line %d (expected 0x%02X, got 0x%02X)",
                        lineno, cs, checksum,
                    )

                if rec_type == 0x00:  # data
                    abs_addr = upper_base + seg_base + offset
                    rel = abs_addr - bk.base_addr
                    if rel < 0 or rel + byte_count > bk.size_bytes:
                        raise OcahMemoryImageError(
                            f"Bank {bank!r}: Intel HEX address 0x{abs_addr:08X} "
                            f"(+{byte_count} bytes) is outside the bank window "
                            f"[0x{bk.base_addr:08X}..0x{bk.base_addr + bk.size_bytes:08X})"
                        )
                    buf[rel: rel + byte_count] = data
                elif rec_type == 0x01:  # end-of-file
                    break
                elif rec_type == 0x02:  # extended segment address
                    seg_base = ((data[0] << 8) | data[1]) << 4
                elif rec_type == 0x04:  # extended linear address
                    upper_base = ((data[0] << 8) | data[1]) << 16
                elif rec_type == 0x05:  # start linear address (ignored)
                    pass
                elif rec_type == 0x03:  # start segment address (ignored)
                    pass
                else:
                    log.warning(
                        "[OcahMemoryImage] unknown Intel HEX record type 0x%02X at line %d",
                        rec_type, lineno,
                    )

        self._bytes_to_bank(bank, bk, bytes(buf), base_offset=0)
        log.debug("[OcahMemoryImage] Intel HEX loaded into bank %r", bank)

    # ------------------------------------------------------------------ #
    # Raw binary loader                                                     #
    # ------------------------------------------------------------------ #

    def load_bin(self, bank: str, path: str, base_offset: int = 0) -> None:
        """Load a bank from a raw binary file.

        Parameters
        ----------
        bank:
            Bank name (e.g. ``"sep_boot_rom"``).
        path:
            Path to the raw binary file.
        base_offset:
            Byte offset within the bank at which loading begins.  Defaults
            to 0 (start of bank).
        """
        bk = self._get_bank(bank)
        bin_path = Path(path)
        if not bin_path.exists():
            raise OcahMemoryImageError(f"Binary file not found: {bin_path}")

        log.info(
            "[OcahMemoryImage] loading bin → bank %r (offset=%d): %s",
            bank, base_offset, bin_path,
        )

        data = bin_path.read_bytes()
        self._bytes_to_bank(bank, bk, data, base_offset=base_offset)

    # ------------------------------------------------------------------ #
    # Backdoor write (runtime patching)                                     #
    # ------------------------------------------------------------------ #

    def backdoor_write(self, bank: str, addr: int, data: int) -> None:
        """Patch a single word in the in-memory image *before* plusargs are emitted.

        This method operates on the Python-side image store, not on a live
        simulation handle.  Use it to override individual words between
        ``load_elf()``/``load_bin()`` and ``write_plusargs()``.

        For **runtime** patching of a running simulation (writing to a live
        HDL handle via cocotb peek/poke) the testbench must expose the memory
        backing array through a hierarchical cocotb handle.  See the
        ``backdoor_sim_write`` function at the bottom of this module for a
        helper that assumes the TB exposes arrays under names like
        ``dut.u_sep_sram.mem``.

        Parameters
        ----------
        bank:
            Bank name.
        addr:
            Word address within the bank (0-indexed).
        data:
            Integer word value to write.
        """
        bk = self._get_bank(bank)
        if addr < 0 or addr >= bk.depth:
            raise OcahMemoryImageError(
                f"Bank {bank!r}: word address {addr} out of range [0, {bk.depth})"
            )
        mask = (1 << bk.data_width_bits) - 1
        self._banks[bank][addr] = data & mask
        log.debug("[OcahMemoryImage] backdoor_write bank=%r addr=%d data=0x%X", bank, addr, data)

    # ------------------------------------------------------------------ #
    # Plusarg emission                                                      #
    # ------------------------------------------------------------------ #

    def write_plusargs(self, run_dir: Optional[str] = None) -> List[str]:
        """Write per-bank hex files and return the plusarg list.

        For each bank that has at least one non-None entry, a hex file is
        written to ``run_dir`` (or the ``run_dir`` supplied at construction)
        and the corresponding ``+<bank>_preload=<file>`` argument is appended
        to the returned list.

        Banks with no loaded data are skipped (no plusarg emitted).

        Parameters
        ----------
        run_dir:
            Override the output directory for this call only.  If None, the
            directory passed to ``__init__`` is used.

        Returns
        -------
        list[str]
            List of simulator plusarg strings, e.g.
            ``['+sep_sram_preload=/path/to/sim_run/sep_sram.hex', ...]``.
        """
        out_dir = Path(run_dir) if run_dir is not None else self._run_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        plusargs: List[str] = []

        for name, bank in self._layout.banks.items():
            store = self._banks[name]
            # Skip banks with no data loaded.
            if all(v is None for v in store):
                continue

            hex_path = out_dir / f"{name}.hex"
            self._write_hex_file(hex_path, bank, store)

            arg = f"{bank.plusarg}={hex_path}"
            plusargs.append(arg)
            log.info("[OcahMemoryImage] emitted plusarg: %s", arg)

        return plusargs

    def get_bank_content(self, bank: str) -> List[int]:
        """Return a copy of the word array for *bank*, with None→0 substitution.

        Useful for assertions in test code without needing to read a hex file
        back from disk.
        """
        self._get_bank(bank)
        return [v if v is not None else 0 for v in self._banks[bank]]

    def is_bank_loaded(self, bank: str) -> bool:
        """Return True if at least one word has been written to *bank*."""
        self._get_bank(bank)
        return any(v is not None for v in self._banks[bank])

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_bank(self, name: str) -> MemoryBank:
        try:
            return self._layout.bank(name)
        except KeyError:
            known = list(self._layout.banks)
            raise OcahMemoryImageError(
                f"Unknown bank {name!r}. Known banks: {known}"
            ) from None

    def _place_bytes(self, load_addr: int, data: bytes, source: str) -> None:
        """Route a byte stream starting at ``load_addr`` into the correct bank(s).

        Bytes that span a bank boundary are split across banks.  If no bank
        covers a byte address, a WARNING is emitted and the byte is discarded.
        """
        offset = 0
        while offset < len(data):
            byte_addr = load_addr + offset
            bank = self._layout.bank_for_addr(byte_addr)
            if bank is None:
                log.warning(
                    "[OcahMemoryImage] %s: address 0x%08X has no matching bank — skipping",
                    source, byte_addr,
                )
                offset += 1
                continue

            # How many bytes remain in this bank starting from byte_addr?
            end_of_bank = bank.base_addr + bank.size_bytes
            chunk_end = min(load_addr + len(data), end_of_bank)
            chunk_len = chunk_end - byte_addr

            chunk = data[offset: offset + chunk_len]
            self._bytes_to_bank(bank.name, bank, chunk, base_offset=byte_addr - bank.base_addr)
            offset += chunk_len

    def _bytes_to_bank(
        self,
        bank_name: str,
        bank: MemoryBank,
        data: bytes,
        base_offset: int,
    ) -> None:
        """Pack *data* into the word store for *bank*, starting at *base_offset* bytes.

        Zero-padding is added if ``data`` does not fill a complete word at the
        end.  Words already set by a previous load call are overwritten only if
        the new data covers the same word address.
        """
        bpw = bank.bytes_per_word
        if bpw == 0:
            raise OcahMemoryImageError(
                f"Bank {bank_name!r} has bytes_per_word=0; cannot pack bytes."
            )

        store = self._banks[bank_name]

        # Pad data to a whole number of words.
        remainder = len(data) % bpw
        if remainder:
            data = data + b"\x00" * (bpw - remainder)

        for i in range(0, len(data), bpw):
            word_byte_offset = base_offset + i
            word_idx = word_byte_offset // bpw
            if word_idx >= bank.depth:
                raise OcahMemoryImageError(
                    f"Bank {bank_name!r}: word index {word_idx} overflows depth {bank.depth}"
                )
            # Little-endian packing for the data portion.
            word_data = int.from_bytes(data[i: i + bpw], byteorder="little")

            # For wide words with ECC (39-bit, 312-bit), the upper bits
            # (ECC / parity) are zero unless the caller pre-encoded them.
            # The hex serialiser will zero-pad to the full word width.
            mask = (1 << bank.data_width_bits) - 1
            store[word_idx] = word_data & mask

    def _write_hex_file(
        self,
        path: Path,
        bank: MemoryBank,
        store: List[Optional[int]],
    ) -> None:
        """Write the word store to an INTERFACE.md-format hex file.

        Format:
        - One word per line, most-significant nibble first.
        - Comment header with bank name and depth.
        - Trailing None entries (after the last loaded word) are omitted to
          keep the file compact — the RTL shim zero-initialises missing lines.
        """
        digits = bank.hex_digits_per_word

        # Find the last non-None entry so we can trim trailing zeros.
        last_loaded = 0
        for idx in range(len(store) - 1, -1, -1):
            if store[idx] is not None:
                last_loaded = idx
                break

        with open(path, "w") as fh:
            fh.write(f"# {bank.name} — generated by OcahMemoryImage\n")
            fh.write(f"# depth={bank.depth} width={bank.data_width_bits} digits_per_word={digits}\n")
            for idx in range(last_loaded + 1):
                word = store[idx] if store[idx] is not None else 0
                fh.write(f"{word:0{digits}X}\n")

        log.debug(
            "[OcahMemoryImage] wrote %d words to %s (bank depth=%d)",
            last_loaded + 1, path, bank.depth,
        )


# --------------------------------------------------------------------------- #
# Runtime (live simulation) backdoor helper                                     #
# --------------------------------------------------------------------------- #

async def backdoor_sim_write(
    dut_handle,
    bank: str,
    word_addr: int,
    word_data: int,
    layout: Optional[SepMemoryLayout] = None,
) -> None:
    """Poke a single word into a live simulation memory array.

    This is a cocotb-native coroutine that uses hierarchical signal access to
    patch a memory word while the simulation is running.  It is separate from
    ``OcahMemoryImage.backdoor_write()`` which operates on the pre-simulation
    hex image.

    Requirements
    ------------
    The testbench must expose each bank's backing array as a hierarchical
    cocotb handle.  The expected handle path is::

        dut_handle.<array_handle_name>[word_addr]

    where ``<array_handle_name>`` is taken from the ``_BACKDOOR_HANDLE_MAP``
    below.  Update the map if your TB uses different signal paths.

    This requires cocotb with packed-array write support.  Verilator support
    for hierarchical array access may require ``--public-flat-rw``.

    Parameters
    ----------
    dut_handle:
        The cocotb DUT handle (``dut`` in a ``@cocotb.test()`` function).
    bank:
        Bank name (e.g. ``"sep_sram"``).
    word_addr:
        Word address within the bank.
    word_data:
        Integer value to write.
    layout:
        ``SepMemoryLayout`` instance; defaults to ``SepMemoryLayout.default()``.
    """
    # Hierarchical handle names for each bank's memory array in the testbench.
    # These must match the actual instantiation paths in the SV TB.
    # Adjust if your TB structure differs.
    _BACKDOOR_HANDLE_MAP: Dict[str, str] = {
        "sep_sram":     "u_sep_ip_integration.u_sep_sram.mem",
        "sep_boot_rom": "u_sep_ip_integration.u_sep_boot_rom.mem",
        "sep_tcm":      "u_sep_ip_integration.u_sep_tcm_wrapper.iccm_bank0.mem",
        "km_rom":       "u_sep_ip_integration.u_km_rom.mem",
        "km_sram":      "u_sep_ip_integration.u_km_sram.mem",
        "otbn_imem":    "u_sep_ip_integration.u_otbn_imem_sram.mem",
        "otbn_dmem":    "u_sep_ip_integration.u_otbn_dmem_sram.mem",
    }

    if layout is None:
        layout = SepMemoryLayout.default()

    bk = layout.bank(bank)
    if word_addr < 0 or word_addr >= bk.depth:
        raise OcahMemoryImageError(
            f"Bank {bank!r}: word address {word_addr} out of range [0, {bk.depth})"
        )

    handle_path = _BACKDOOR_HANDLE_MAP.get(bank)
    if handle_path is None:
        raise OcahMemoryImageError(
            f"No backdoor handle path registered for bank {bank!r}. "
            f"Known banks: {list(_BACKDOOR_HANDLE_MAP)}"
        )

    # Navigate the hierarchical handle from dut_handle.
    handle = dut_handle
    for part in handle_path.split("."):
        try:
            handle = getattr(handle, part)
        except AttributeError:
            raise OcahMemoryImageError(
                f"Could not traverse handle path {handle_path!r} at component {part!r}. "
                f"Ensure the TB exposes this path and the simulator supports "
                f"hierarchical access (Verilator: --public-flat-rw)."
            )

    # Index into the memory array and write the value.
    try:
        handle[word_addr].value = word_data
    except Exception as exc:
        raise OcahMemoryImageError(
            f"Failed to write to {handle_path}[{word_addr}]: {exc}"
        ) from exc

    log.debug(
        "[backdoor_sim_write] bank=%r word_addr=%d data=0x%X via %s[%d]",
        bank, word_addr, word_data, handle_path, word_addr,
    )

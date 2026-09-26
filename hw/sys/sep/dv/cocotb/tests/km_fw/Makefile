# SPDX-License-Identifier: Apache-2.0

GCC_PREFIX ?= riscv64-unknown-elf
RISCV_CC ?= $(GCC_PREFIX)-gcc
RISCV_OBJCOPY ?= $(GCC_PREFIX)-objcopy
PYTHON ?= python3

OUT_DIR := ..
ROMS := km_rom km_rom_entropy km_rom_coexist km_rom_vault km_rom_crc \
        km_rom_kpv_scrambler km_rom_iso

# The KM PicoRV32 is built with ENABLE_REGS_16_31=0, so an image that runs on
# it must be assembled for RV32E and may use x0-x15 only. Images that only feed
# the tb keep the wider base ISA.
RV32E_ROMS := km_rom_vault km_rom_crc km_rom_kpv_scrambler km_rom_iso
ARCH_FLAGS = -march=rv32i -mabi=ilp32
$(addprefix $(OUT_DIR)/,$(addsuffix .parhex,$(RV32E_ROMS))): \
        ARCH_FLAGS := -march=rv32e -mabi=ilp32e
PARHEX := $(addprefix $(OUT_DIR)/,$(addsuffix .parhex,$(ROMS)))

.PHONY: all clean rom_main verify

all: $(PARHEX)

# verify: the committed .parhex blobs still match what their .S assembles to.
#
# These images are committed artifacts, and no run_dv stage rebuilds them --
# a test boots the blob through `+km_rom_hex=<name>.parhex`, not through a
# `firmware = {...}` build declaration. So an edit to a .S reaches no
# simulation until somebody runs `make`, and the run that follows quietly
# executes the OLD image while a reader sees the NEW source.
#
# NOTHING RUNS THIS AUTOMATICALLY. No stage, testlist or CI job invokes it, so
# it does not by itself prevent the drift above -- it only lets you detect it.
# Run it after editing any .S, and commit the regenerated blob with the source
# change. It needs the RISC-V toolchain on PATH; without it every image reports BUILD FAILED, which is why a failed
# build is a distinct token from a mismatch.
#
# It rebuilds into a scratch OUT_DIR and never writes the tracked blob: the
# recipe redirects gen_parhex.py output at its target, so building at the
# tracked path would truncate the committed artifact before python ran, and a
# reported mismatch would leave the rebuild in the tree -- self-clearing on the
# next run and booting an uncommitted image in the meantime.
verify:
	@rc=0; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	for r in $(ROMS); do \
	    if [ ! -f $(OUT_DIR)/$$r.parhex ]; then \
	        echo "MISSING  $$r.parhex is not committed" >&2; rc=1; continue; \
	    fi; \
	    if ! $(MAKE) --no-print-directory OUT_DIR=$$tmp $$tmp/$$r.parhex \
	            >$$tmp/$$r.log 2>&1; then \
	        echo "BUILD FAILED  $$r ($$(tail -n1 $$tmp/$$r.log))" >&2; rc=1; continue; \
	    fi; \
	    if cmp -s $$tmp/$$r.parhex $(OUT_DIR)/$$r.parhex; then \
	        echo "ok       $$r.parhex"; \
	    else \
	        echo "STALE    $$r.parhex does not match $$r.S -- rebuild with" \
	             "\`make $$r.parhex\` and commit it" >&2; \
	        rc=1; \
	    fi; \
	done; \
	if [ $$rc -ne 0 ]; then echo "verify: FAILED" >&2; else echo "verify: all $(words $(ROMS)) blobs match their source"; fi; \
	exit $$rc

# rom_main: the KM application ROM from hw/ip/key_manager/approm/prod, built
# with the boot and unrecoverable-fault SRAM wipes disabled. A wipe shreds every
# engine's sideload key, and a boot wipe halts before RESP_KM_READY. The output
# is gitignored (not a committed blob). SEP DV tests that boot this image declare
# `firmware = { name = "rom_main", mode = "km_rom_main" }` so run_dv.py
# c_compile drives this target, already inside a picolibc-enabled toolchain; the
# ROM Makefile's `build` target therefore compiles directly, without re-entering
# the container.
#
# The variant gets its own BUILD_DIR so it never shares objects with a
# wipe-enabled build of the same ROM.
OCH_ROOT ?= $(abspath $(CURDIR)/../../../../../../..)
KM_APPROM_DIR := $(OCH_ROOT)/hw/ip/key_manager/approm/prod
KM_ROM_BUILD_DIR := $(KM_APPROM_DIR)/build/sep_dv

rom_main:
	$(MAKE) -C $(KM_APPROM_DIR) build BUILD_DIR=$(KM_ROM_BUILD_DIR) \
	    OCAH_ROOT=$(OCH_ROOT) KM_BOOT_WIPE=0 KM_UNREC_WIPE=0
	cp $(KM_ROM_BUILD_DIR)/rom_main.rom.parhex $(OUT_DIR)/rom_main.rom.parhex
	@echo "[km_fw] staged rom_main.rom.parhex -> $(OUT_DIR)/rom_main.rom.parhex"

# The images take their KM register addresses from the generated map rather
# than hand-typed literals: .S files run through the C preprocessor, so the
# PeakRDL raw-header is includable directly and a moved register becomes a
# build error instead of a silently stale constant.
KM_REG_INC := $(OCH_ROOT)/hw/ip/key_manager/regs/gen/c

# Field MASKS live in km_csr.h / km_kpv.h, C headers of structs and
# static_asserts an .S cannot include. This target lifts the plain #define
# lines an image needs into an assembler-safe include, so a field that moves
# at the next RDL regeneration changes the mask instead of leaving a
# hand-typed literal behind. The grep is the trace: if a name disappears,
# the build fails here.
KM_CSR_H := $(KM_REG_INC)/km_csr.h
KM_KPV_H := $(KM_REG_INC)/km_kpv.h
KM_FIELD_INC := km_fields.inc
KM_CSR_DEFS := KM_CSR__IRQ_STATUS_REG__(AXI_SLVERR|AXI_DECERR|SRAM_WRITE_LOCK_ERR|DRBG_ERR|ROM_PARITY_ERR|SRAM_PARITY_ERR|ROM_WRITE_ERR)_bm
KM_KPV_DEFS := KM_KPV__CTRL_REG__(LOCK_WRITE|LOCK_USE|ERASE|SEAL)_bm

$(KM_FIELD_INC): $(KM_CSR_H) $(KM_KPV_H) Makefile
	@printf '/* Generated from km_csr.h / km_kpv.h by km_fw/Makefile. Do not edit. */\n' > $@
	@grep -E '^#define ($(KM_CSR_DEFS)) ' $(KM_CSR_H) >> $@ || { \
	    echo "$(KM_CSR_H): expected field-mask defines matching $(KM_CSR_DEFS)" >&2; \
	    rm -f $@; exit 1; }
	@grep -E '^#define ($(KM_KPV_DEFS)) ' $(KM_KPV_H) >> $@ || { \
	    echo "$(KM_KPV_H): expected field-mask defines matching $(KM_KPV_DEFS)" >&2; \
	    rm -f $@; exit 1; }

$(OUT_DIR)/%.parhex: %.S gen_parhex.py $(KM_REG_INC)/key_manager_addr.h $(KM_FIELD_INC)
	$(RISCV_CC) -nostdlib $(ARCH_FLAGS) -I$(KM_REG_INC) -I. -Ttext=0 -o $*.elf $<
	$(RISCV_OBJCOPY) -O binary $*.elf $*.bin
	$(PYTHON) gen_parhex.py $*.bin > $@

clean:
	rm -f *.elf *.bin $(KM_FIELD_INC) $(PARHEX) $(OUT_DIR)/rom_main.rom.parhex
	rm -rf $(KM_ROM_BUILD_DIR)

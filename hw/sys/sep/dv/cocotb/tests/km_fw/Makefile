# SPDX-License-Identifier: Apache-2.0

GCC_PREFIX ?= riscv64-unknown-elf
RISCV_CC ?= $(GCC_PREFIX)-gcc
RISCV_OBJCOPY ?= $(GCC_PREFIX)-objcopy
PYTHON ?= python3

OUT_DIR := ..
# Intermediates (.S copy, .elf, .bin, km_fields.inc). `verify` points this at
# its private scratch directory, so concurrent verifies share no written path.
OBJ_DIR ?= $(CURDIR)
ROMS := km_rom km_rom_entropy km_rom_coexist km_rom_vault km_rom_crc \
        km_rom_kpv_scrambler km_rom_iso km_rom_otp_id

# The KM PicoRV32 is built with ENABLE_REGS_16_31=0, so an image that runs on
# it must be assembled for RV32E and may use x0-x15 only. Images that only feed
# the tb keep the wider base ISA.
RV32E_ROMS := km_rom_vault km_rom_crc km_rom_kpv_scrambler km_rom_iso km_rom_otp_id
ARCH_FLAGS = -march=rv32i -mabi=ilp32
$(addprefix $(OUT_DIR)/,$(addsuffix .parhex,$(RV32E_ROMS))): \
        ARCH_FLAGS := -march=rv32e -mabi=ilp32e
PARHEX := $(addprefix $(OUT_DIR)/,$(addsuffix .parhex,$(ROMS)))

.PHONY: all clean rom_main verify

all: $(PARHEX)

# verify: the committed .parhex blobs still match what their .S assembles to.
#
# These images are committed artifacts, and no run_dv stage rebuilds them. A
# test boots the blob through `+km_rom_hex=<name>.parhex`, so an edit to a .S
# reaches no simulation until somebody runs `make`, and a run that follows
# executes the OLD image while a reader sees the NEW source.
#
# The run_dv c_compile stage runs `verify ROMS=<name>` for every test that
# declares `firmware = { name = "<name>", mode = "km_rom_blob" }`
# (sep_sim_cfg.toml [c_build.km_rom_blob]). A nonzero exit fails c_compile,
# so a stale blob stops that test before sim. A test that boots a blob without
# that declaration is not checked. Run it by hand after editing any .S, and
# commit the regenerated blob with the source change. It needs the RISC-V
# toolchain (GCC_PREFIX); without it every image reports BUILD FAILED, which is
# why a failed build is a distinct token from a mismatch.
#
# It rebuilds into a private scratch directory (OUT_DIR and OBJ_DIR both point
# there) and never writes the tracked blob or any file in this directory, so
# concurrent verifies of the same blob do not share a written path, and a
# reported mismatch leaves no rebuild in the tree.
verify:
	@rc=0; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	for r in $(ROMS); do \
	    if [ ! -f $(OUT_DIR)/$$r.parhex ]; then \
	        echo "MISSING  $$r.parhex is not committed" >&2; rc=1; continue; \
	    fi; \
	    if ! $(MAKE) --no-print-directory OUT_DIR=$$tmp OBJ_DIR=$$tmp $$tmp/$$r.parhex \
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
# engine's sideload key, and a boot wipe halts before RESP_KM_READY. SEP DV tests
# that boot this image declare
# `firmware = { name = "rom_main", mode = "km_rom_main" }`, and run_dv.py
# c_compile drives this target ([c_build.km_rom_main] in sep_sim_cfg.toml),
# already inside a picolibc-enabled toolchain, so the ROM Makefile's `build`
# target compiles directly without re-entering the container.
#
# FW_BUILD_DIR is required and must be a directory private to the caller. The
# ROM Makefile builds objects and image under it (its BUILD_DIR), so this target
# writes nothing in the ROM tree or in this directory. c_compile passes a fresh
# per-run, per-test directory, so every run builds from source and no run writes
# a path another run reads. The image is $(FW_BUILD_DIR)/rom_main.rom.parhex.
OCH_ROOT ?= $(abspath $(CURDIR)/../../../../../../..)
KM_APPROM_DIR := $(OCH_ROOT)/hw/ip/key_manager/approm/prod

rom_main:
	@test -n "$(FW_BUILD_DIR)" || { echo "rom_main: set FW_BUILD_DIR to a private build directory" >&2; exit 1; }
	$(MAKE) -C $(KM_APPROM_DIR) build BUILD_DIR=$(FW_BUILD_DIR) \
	    OCAH_ROOT=$(OCH_ROOT) KM_BOOT_WIPE=0 KM_UNREC_WIPE=0
	@test -s $(FW_BUILD_DIR)/rom_main.rom.parhex
	@echo "[km_fw] built rom_main.rom.parhex -> $(FW_BUILD_DIR)/rom_main.rom.parhex"

# The images take their KM register addresses from the generated map rather
# than hand-typed literals: .S files run through the C preprocessor, so the
# PeakRDL raw-header is includable directly and a moved register becomes a
# build error instead of a silently stale constant.
KM_REG_INC := $(OCH_ROOT)/hw/ip/key_manager/regs/gen/c

# Field MASKS live in km_csr.h / km_kpv.h / km_mailbox_km.h, C headers of structs and
# static_asserts an .S cannot include. This target lifts the plain #define
# lines an image needs into an assembler-safe include, so a field that moves
# at the next RDL regeneration changes the mask instead of leaving a
# hand-typed literal behind. The grep is the trace: if a name disappears,
# the build fails here.
KM_CSR_H := $(KM_REG_INC)/km_csr.h
KM_KPV_H := $(KM_REG_INC)/km_kpv.h
KM_MBOX_KM_H := $(KM_REG_INC)/km_mailbox_km.h
KM_FIELD_INC := $(OBJ_DIR)/km_fields.inc
KM_CSR_DEFS := KM_CSR__(IRQ_STATUS_REG__(AXI_SLVERR|AXI_DECERR|SRAM_WRITE_LOCK_ERR|DRBG_ERR|ROM_PARITY_ERR|SRAM_PARITY_ERR|ROM_WRITE_ERR)|OTP_READ_LOCK_REG__SEP_(CHIPLET|SIP|SYS)_ID)_bm
KM_KPV_DEFS := KM_KPV__(CTRL_REG__(LOCK_WRITE|LOCK_USE|ERASE|SEAL)|KPV_SCRAMBLER_CTRL_REG__(ENABLE|LOCK))_bm
KM_MBOX_KM_DEFS := KM_MAILBOX_KM__STATUS_REG__(INBOUND_EMPTY|OUTBOUND_FULL)_bm

# Written to a temporary name, then moved into place, so a reader never sees a partial file.
$(KM_FIELD_INC): $(KM_CSR_H) $(KM_KPV_H) $(KM_MBOX_KM_H) Makefile
	@mkdir -p $(OBJ_DIR)
	@tmp=$@.tmp.$$$$; \
	printf '/* Generated from km_csr.h / km_kpv.h / km_mailbox_km.h by km_fw/Makefile. Do not edit. */\n' > $$tmp; \
	grep -E '^#define ($(KM_CSR_DEFS)) ' $(KM_CSR_H) >> $$tmp || { \
	    echo "$(KM_CSR_H): expected field-mask defines matching $(KM_CSR_DEFS)" >&2; \
	    rm -f $$tmp; exit 1; }; \
	grep -E '^#define ($(KM_KPV_DEFS)) ' $(KM_KPV_H) >> $$tmp || { \
	    echo "$(KM_KPV_H): expected field-mask defines matching $(KM_KPV_DEFS)" >&2; \
	    rm -f $$tmp; exit 1; }; \
	grep -E '^#define ($(KM_MBOX_KM_DEFS)) ' $(KM_MBOX_KM_H) >> $$tmp || { \
	    echo "$(KM_MBOX_KM_H): expected field-mask defines matching $(KM_MBOX_KM_DEFS)" >&2; \
	    rm -f $$tmp; exit 1; }; \
	mv -f $$tmp $@

# The .S is assembled from OBJ_DIR, next to the km_fields.inc generated there:
# a quoted #include searches the including file's directory first, so this is
# what makes a private OBJ_DIR use its own km_fields.inc. The blob is written
# to a temporary name, then moved into place, so the target is never left truncated.
$(OUT_DIR)/%.parhex: %.S gen_parhex.py $(KM_REG_INC)/key_manager_addr.h $(KM_FIELD_INC)
	@mkdir -p $(OBJ_DIR)
	@if [ "$(abspath $<)" != "$(abspath $(OBJ_DIR)/$*.S)" ]; then cp $< $(OBJ_DIR)/$*.S; fi
	$(RISCV_CC) -nostdlib $(ARCH_FLAGS) -I$(KM_REG_INC) -I$(CURDIR) -Ttext=0 \
	    -o $(OBJ_DIR)/$*.elf $(OBJ_DIR)/$*.S
	$(RISCV_OBJCOPY) -O binary $(OBJ_DIR)/$*.elf $(OBJ_DIR)/$*.bin
	$(PYTHON) gen_parhex.py $(OBJ_DIR)/$*.bin > $@.tmp.$$$$ && mv -f $@.tmp.$$$$ $@

clean:
	rm -f *.elf *.bin km_fields.inc $(PARHEX)

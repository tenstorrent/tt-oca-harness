# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Shared SMC test-image post-processing: linked ELF -> .bin/.hex/.spi, plus
# preload-address-rebased copies of the .hex/.spi for simulation.
#
# Included by both hw/sys/smc/dv/fw/fw.mk (regular tests) and
# hw/sys/smc/bootrom/dummy/Makefile (the standalone dummy boot ROM build) so
# the two SMC firmware build entry points share one definition of how a
# linked test image becomes the artifacts the testbench consumes, instead of
# hand-copying it. Artifact names fold in the link mode (cheshire-style),
# e.g. rom_sanity.sram.bin / dummy.rom.bin.
#
# Requires FW_DIR (for scripts/) and FW_TEST_BUILD_DIR to already be set by
# the including makefile.
define FW_TEST_POSTPROCESS
	$(OBJCOPY) -O binary $(1) "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).bin"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).bin" --data_width 64 --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).hex"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).bin" --data_width 1 --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).spi"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).hex" --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).preload.hex"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).spi" --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).spi_preload"
endef

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Shared SMC test-image post-processing: linked ELF -> .bin/.hex/.spi, plus
# preload-address-rebased copies of the .hex/.spi for simulation.
#
# Included by hw/sys/smc/dv/fw/fw.mk and hw/sys/smc/bootrom/dummy/Makefile.
# Requires FW_DIR and FW_TEST_BUILD_DIR to already be set.
define FW_TEST_POSTPROCESS
	$(OBJCOPY) -O binary $(1) "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).bin"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).bin" --data_width 64 --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).hex"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).bin" --data_width 1 --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).spi"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).hex" --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).preload.hex"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).spi" --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).$(3).spi_preload"
endef

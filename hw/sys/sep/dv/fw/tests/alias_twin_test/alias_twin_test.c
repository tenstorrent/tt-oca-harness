// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP CPU LSU local-alias twin test. The 768 MiB window at SEP_LOCAL_BASE_ADDR
// (reset 0xD000_0000) rewrites to 0x1000_0000 (hw/sys/sep/doc/fabric.adoc,
// "Address Remapping"), so an alias address answers as its direct twin. The
// window base stays at its reset value: the specification states no legal
// range for it.
//
// The firmware only drives the accesses and prints what it read. The cocotb
// test sep_cpu_lsu_alias_window_twin_test seeds the values, patches them into
// g_twin_params, and grades every printed value against them. main() returns
// a non-zero error count only when the parameter block is not the patched
// one, so a stale image cannot pass.
//
// Console lines (one per access group):
//   TWIN-PARAMS scratch=<v> csid=<v> sram_start=<v> sram_end=<v> marker=<v>
//               local_base=<v>
//   TWIN unit=<name> d1=<v> a=<v> d2=<v>   static word: direct, alias, direct
//   TWIN unit=<name> d1=<v> a=<v>          SRAM word: direct, alias
//   TWIN-WR alias=<addr> direct=<v>        marker write through the alias

#include <stdint.h>

#include "sep.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"

#define TWIN_PARAM_MAGIC 0xA7C1D3E5u

#define WINDOW_BASE SEP_CPU_CTRL__SEP_LOCAL_BASE_ADDR_reset
#define SRAM_BASE SEP_TOP_SEP_SRAM_BASE_ADDR
#define SRAM_SIZE SEP_TOP_SEP_SRAM_SIZE
// The alias window maps onto the local region (hw/sys/sep/doc/fabric.adoc, SEP
// CPU local-alias traffic). The test patches the first direct address of that
// region, SEP_TOP_REG_MAP_BASE_ADDR of the generated map, into g_twin_params[6].
#define ALIAS_OF(direct) ((direct) + (WINDOW_BASE - g_twin_params[6]))

// One static word per unit class. The cold scratch word and the SPI host CSID
// are writable; SEP_VERSION_ID and COMPONENT_ID are read-only; AES
// CTRL_SHADOWED is read only, because a write that AES ignores while it is
// not idle has no stated result.
#define SCRATCH_WORD SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(3)
#define AES_WORD SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR
#define SYS_CSR_WORD SEP_TOP_SEP_CPU_CTRL_SEP_VERSION_ID_BASE_ADDR
#define SPI_WORD SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR
#define ESRC_WORD SEP_TOP_ENTROPY_SOURCE_COMPONENT_ID_BASE_ADDR
#define SRAM_START_WORD SRAM_BASE
#define SRAM_END_WORD (SRAM_BASE + SRAM_SIZE - 4u)

// Layout: [0]=magic, [1]=scratch value, [2]=CSID value, [3]=SRAM start-word
// value, [4]=SRAM last-word value, [5]=marker, [6]=local region base. The test
// patches the block from the run seed and the generated map; the committed
// defaults keep a standalone directed image.
volatile uint32_t g_twin_params[7] = {
    TWIN_PARAM_MAGIC, 0x5C7A7C11u, 0x0000C51Du, 0x5A7A0001u, 0x5A7AFFFCu, 0x3A7CE7EDu, 0x10000000u,
};

static inline void wr32(uint32_t addr, uint32_t v) {
    *(volatile uint32_t *)addr = v;
}

static inline uint32_t rd32(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static void put_kv(const char *key, uint32_t v) {
    sep_mbx_puts(key);
    sep_mbx_puthex(v);
}

static void twin_static(const char *name, uint32_t direct) {
    uint32_t d1 = rd32(direct);
    uint32_t a = rd32(ALIAS_OF(direct));
    uint32_t d2 = rd32(direct);
    sep_mbx_puts("TWIN unit=");
    sep_mbx_puts(name);
    put_kv(" d1=", d1);
    put_kv(" a=", a);
    put_kv(" d2=", d2);
    sep_mbx_puts("\n");
}

static void twin_sram(const char *name, uint32_t direct) {
    uint32_t d1 = rd32(direct);
    uint32_t a = rd32(ALIAS_OF(direct));
    sep_mbx_puts("TWIN unit=");
    sep_mbx_puts(name);
    put_kv(" d1=", d1);
    put_kv(" a=", a);
    sep_mbx_puts("\n");
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP CPU LSU alias twin test\n");

    if (g_twin_params[0] != TWIN_PARAM_MAGIC) {
        sep_mbx_puts("FAIL: bad twin param magic\n");
        return 1;
    }
    sep_mbx_puts("TWIN-PARAMS");
    put_kv(" scratch=", g_twin_params[1]);
    put_kv(" csid=", g_twin_params[2]);
    put_kv(" sram_start=", g_twin_params[3]);
    put_kv(" sram_end=", g_twin_params[4]);
    put_kv(" marker=", g_twin_params[5]);
    put_kv(" local_base=", g_twin_params[6]);
    sep_mbx_puts("\n");

    // Seed each writable static word and both SRAM words at the direct address.
    wr32(SCRATCH_WORD, g_twin_params[1]);
    wr32(SPI_WORD, g_twin_params[2]);
    wr32(SRAM_START_WORD, g_twin_params[3]);
    wr32(SRAM_END_WORD, g_twin_params[4]);

    twin_static("scratch", SCRATCH_WORD);
    twin_static("aes_word", AES_WORD);
    twin_static("sys_csr", SYS_CSR_WORD);
    twin_static("spi_word", SPI_WORD);
    twin_static("esrc_word", ESRC_WORD);

    twin_sram("sram_start", SRAM_START_WORD);
    twin_sram("sram_end", SRAM_END_WORD);

    // Marker through the alias of the cold scratch word, read at the direct
    // address.
    wr32(ALIAS_OF(SCRATCH_WORD), g_twin_params[5]);
    uint32_t back = rd32(SCRATCH_WORD);
    put_kv("TWIN-WR alias=", ALIAS_OF(SCRATCH_WORD));
    put_kv(" direct=", back);
    sep_mbx_puts("\n");

    sep_mbx_puts("TWIN-DONE\n");
    return 0;
}

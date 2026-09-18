/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_addr_alias.c
 * @brief No KM fabric address reads back data unless it names a register
 *
 * The KM must fault reliably when software goes off the rails, whether through
 * a bug or an attack, so a bad address must never return plausible data. This
 * test sweeps every 4-byte-aligned address of each crossbar port and requires
 * one of three outcomes at each one:
 *
 *   - Below the block's register span, the access may retire cleanly (it names
 *     a register) or raise SLVERR (a gap between registers), but never DECERR.
 *   - Between the register span and the end of the block's decode window
 *     (2^MIN_ADDR_WIDTH, the low address bits the block actually keeps), the
 *     access must raise SLVERR: the register block is generated with
 *     --err-if-bad-addr, so it answers every unmapped offset it decodes.
 *   - Beyond the decode window the crossbar must not route the access at all,
 *     so it must raise DECERR from the crossbar's own error slave.
 *
 * A clean read inside a decode window can only come from the register block,
 * which decodes every offset in the window, so holding that invariant needs no
 * per-block register list.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_addr_alias
 */

#include "test_common.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* Bus error kinds, as reported by the sticky KMCSR IRQ_STATUS bits */
#define BUS_ERR_NONE 0x0U
#define BUS_ERR_SLVERR 0x1U
#define BUS_ERR_DECERR 0x2U

/* The map spaces peripheral ports 4KB apart, 8KB for the KPV. Sweeping a port's
 * whole slot covers the addresses above its decode window. */
#define SLOT_4KB 0x1000U
#define SLOT_8KB 0x2000U

/* Sweeping the whole map is ~9k probes, well past the 100k-cycle default */
#define TEST_TIMEOUT_CYCLES 4000000U

/* Values written by the write probes; distinct so a stray one is recognisable */
#define WRITE_PROBE_TRUE_VAL 0x0BAD0000U
#define WRITE_PROBE_ALIAS_VAL 0x0BAD1111U

typedef struct {
    const char *name;
    uint32_t base;      /* crossbar rule base */
    uint32_t span;      /* generated <BLOCK>_SIZE: bytes covered by registers */
    uint32_t slot;      /* bytes to the next port in the map; the sweep bound */
    uint32_t probe_min; /* first offset swept */
    uint32_t witness;   /* offset of a register that reads without side effects */
    const char *witness_name;
} km_port_t;

/* Every crossbar port except OTP/eFuse, whose rule is a full page because the
 * port remaps the low 12 bits of the address and its sub-regions run to 0x56F. */
static const km_port_t KM_PORTS[] = {
    /* The two FIFO portals below KM_STATUS pop and push on access, so the sweep
     * starts above them; the addresses higher in the slot that repeat their
     * offsets are still swept, and reach the register block instead. */
    {"mailbox_km", KEY_MANAGER_MAILBOX_KM_BASE_ADDR, KEY_MANAGER_MAILBOX_KM_SIZE, SLOT_4KB, 0x00CU,
     0x00CU, "KM_STATUS"},
    /* KEY_ENTRY[64] at 0x000-0xFFF is an external register file with its own
     * lock and erase policy, so the sweep starts at CTRL[0] rather than reading
     * key state. */
    {"kpv", KEY_MANAGER_KPV_BASE_ADDR, KEY_MANAGER_KPV_SIZE, SLOT_8KB, 0x1000U, 0x1000U, "CTRL[0]"},
    {"kmcsr", KEY_MANAGER_KMCSR_BASE_ADDR, KEY_MANAGER_KMCSR_SIZE, SLOT_4KB, 0x000U, 0x1FCU,
     "DEBUG"},
    /* Reading DATA at 0x000 starts a DRBG request, so the sweep starts at CFG;
     * the addresses that repeat its offset are swept and do start requests,
     * which is why main() seeds the testbench DRBG first. */
    {"drbg_sampler", KEY_MANAGER_DRBG_SAMPLER_BASE_ADDR, KEY_MANAGER_DRBG_SAMPLER_SIZE, SLOT_4KB,
     0x004U, 0x004U, "CFG"},
    {"otbn_wrapper_key", KEY_MANAGER_OTBN_WRAPPER_KEY_BASE_ADDR, KEY_MANAGER_OTBN_WRAPPER_KEY_SIZE,
     SLOT_4KB, 0x000U, 0x060U, "KEY_CTRL"},
    {"aes_wrapper_key", KEY_MANAGER_AES_WRAPPER_KEY_BASE_ADDR, KEY_MANAGER_AES_WRAPPER_KEY_SIZE,
     SLOT_4KB, 0x000U, 0x040U, "KEY_CTRL"},
    {"kmac_wrapper_key", KEY_MANAGER_KMAC_WRAPPER_KEY_BASE_ADDR, KEY_MANAGER_KMAC_WRAPPER_KEY_SIZE,
     SLOT_4KB, 0x000U, 0x040U, "KEY_CTRL"},
    {"hmac_wrapper_key", KEY_MANAGER_HMAC_WRAPPER_KEY_BASE_ADDR, KEY_MANAGER_HMAC_WRAPPER_KEY_SIZE,
     SLOT_4KB, 0x000U, 0x040U, "KEY_CTRL"},
    {"abr_wrapper_key", KEY_MANAGER_ABR_WRAPPER_KEY_BASE_ADDR, KEY_MANAGER_ABR_WRAPPER_KEY_SIZE,
     SLOT_4KB, 0x000U, 0x040U, "MLDSA_SEED.KEY_CTRL"},
};

#define KM_PORT_COUNT (sizeof(KM_PORTS) / sizeof(KM_PORTS[0]))

/**
 * A block keeps MIN_ADDR_WIDTH low address bits, which the generator sets to
 * clog2 of the register span.
 */
static uint32_t decode_window(uint32_t span) {
    uint32_t window = 1U;
    while (window < span) {
        window <<= 1;
    }
    return window;
}

static const km_port_t *port_by_base(uint32_t base) {
    for (uint32_t i = 0; i < KM_PORT_COUNT; i++) {
        if (KM_PORTS[i].base == base) {
            return &KM_PORTS[i];
        }
    }
    return 0;
}

static const char *bus_err_name(uint32_t err) {
    switch (err) {
    case BUS_ERR_NONE:
        return "no error";
    case BUS_ERR_SLVERR:
        return "SLVERR";
    case BUS_ERR_DECERR:
        return "DECERR";
    default:
        return "SLVERR and DECERR";
    }
}

/**
 * SLVERR and DECERR only set the sticky status bits and the access still
 * retires, so the sweep survives its own probes while the fault enables stay
 * clear.
 */
static uint32_t bus_err_take(void) {
    km_csr__irq_status_reg_t status;
    uint32_t err = BUS_ERR_NONE;

    status.w = rom_kmcsr_irq_status_read();
    if (status.f.axi_slverr) {
        err |= BUS_ERR_SLVERR;
    }
    if (status.f.axi_decerr) {
        err |= BUS_ERR_DECERR;
    }
    if (err != BUS_ERR_NONE) {
        km_csr__irq_status_reg_t clear_val = {0};
        clear_val.f.axi_slverr = 1;
        clear_val.f.axi_decerr = 1;
        rom_kmcsr_irq_status_clear(clear_val.w);
    }
    return err;
}

static uint32_t probe_read(uint32_t addr, uint32_t *data_out) {
    uint32_t data = *(volatile uint32_t *)addr;
    if (data_out != 0) {
        *data_out = data;
    }
    return bus_err_take();
}

static uint32_t probe_write(uint32_t addr, uint32_t data) {
    *(volatile uint32_t *)addr = data;
    return bus_err_take();
}

static void check_offset(const km_port_t *port, uint32_t window, uint32_t off) {
    uint32_t addr = port->base + off;
    uint32_t data = 0;
    uint32_t err = probe_read(addr, &data);

    if (off >= window) {
        if (err == BUS_ERR_NONE) {
            TEST_FAIL("%s+0x%04X (0x%08X) read 0x%08X without an error: it is outside the block's "
                      "0x%X-byte decode window and aliases offset 0x%04X",
                      port->name, off, addr, data, window, off & (window - 1U));
        }
        TEST_ASSERT(err == BUS_ERR_DECERR,
                    "%s+0x%04X (0x%08X) is beyond the block's 0x%X-byte decode window, so the "
                    "crossbar must answer DECERR; got %s",
                    port->name, off, addr, window, bus_err_name(err));
    } else if (off >= port->span) {
        TEST_ASSERT(err == BUS_ERR_SLVERR,
                    "%s+0x%04X (0x%08X) is an unmapped offset inside the block's decode window, so "
                    "the register block must answer SLVERR; got %s",
                    port->name, off, addr, bus_err_name(err));
    } else {
        TEST_ASSERT(err != BUS_ERR_DECERR,
                    "%s+0x%04X (0x%08X) is inside the block's register span, so the crossbar must "
                    "route it; got DECERR",
                    port->name, off, addr);
    }
}

static void check_bus_err_reporting_usable(void) {
    km_csr__irq_enable_reg_t enable;
    uint32_t err;

    enable.w = rom_kmcsr_irq_enable_read();
    TEST_ASSERT(!enable.f.axi_slverr_en && !enable.f.axi_decerr_en,
                "AXI error IRQ enables must be clear so the sweep survives its own probes "
                "(IRQ_ENABLE=0x%08X)",
                enable.w);

    err = bus_err_take();
    TEST_ASSERT(err == BUS_ERR_NONE, "bus error status must be clear at test start; got %s",
                bus_err_name(err));
}

/**
 * Each port's witness register reads cleanly; the address one decode window
 * above it must not.
 */
static void check_witnesses(void) {
    for (uint32_t i = 0; i < KM_PORT_COUNT; i++) {
        const km_port_t *port = &KM_PORTS[i];
        uint32_t window = decode_window(port->span);
        uint32_t addr = port->base + port->witness;
        uint32_t data = 0;
        uint32_t err = probe_read(addr, &data);

        TEST_ASSERT(err == BUS_ERR_NONE, "%s %s at 0x%08X must read without an error; got %s",
                    port->name, port->witness_name, addr, bus_err_name(err));
        TEST_LOG("  %s %s at 0x%08X reads 0x%08X, window 0x%X of slot 0x%X", port->name,
                 port->witness_name, addr, data, window, port->slot);

        if (window >= port->slot) {
            continue; /* the window fills the slot */
        }

        uint32_t alias = addr + window;
        uint32_t alias_data = 0;
        uint32_t alias_err = probe_read(alias, &alias_data);

        if (alias_err == BUS_ERR_NONE) {
            TEST_FAIL("0x%08X read 0x%08X without an error: it aliases %s %s at 0x%08X, which "
                      "holds 0x%08X",
                      alias, alias_data, port->name, port->witness_name, addr, data);
        }
        TEST_ASSERT(alias_err == BUS_ERR_DECERR,
                    "0x%08X is one decode window above %s %s and must answer DECERR; got %s", alias,
                    port->name, port->witness_name, bus_err_name(alias_err));
    }
}

/**
 * A write above a decode window must not reach the register it would repeat.
 */
static void check_write_probes(void) {
    const km_port_t *drbg = port_by_base(KEY_MANAGER_DRBG_SAMPLER_BASE_ADDR);
    const km_port_t *kpv = port_by_base(KEY_MANAGER_KPV_BASE_ADDR);

    TEST_ASSERT(drbg != 0 && kpv != 0, "write probe ports must be present in the port table");

    uint32_t cfg = drbg->base + drbg->witness;
    uint32_t window = decode_window(drbg->span);
    uint32_t alias = cfg + window;
    uint32_t original = 0;
    uint32_t data = 0;
    uint32_t err;

    err = probe_read(cfg, &original);
    TEST_ASSERT(err == BUS_ERR_NONE, "DRBG CFG at 0x%08X must read without an error; got %s", cfg,
                bus_err_name(err));

    err = probe_write(cfg, WRITE_PROBE_TRUE_VAL);
    TEST_ASSERT(err == BUS_ERR_NONE, "DRBG CFG at 0x%08X must accept a write; got %s", cfg,
                bus_err_name(err));
    (void)probe_read(cfg, &data);
    TEST_ASSERT_EQ(data, WRITE_PROBE_TRUE_VAL, "DRBG CFG after its own write");

    err = probe_write(alias, WRITE_PROBE_ALIAS_VAL);
    TEST_ASSERT(err == BUS_ERR_DECERR,
                "a write to 0x%08X, one decode window above DRBG CFG, must answer DECERR; got %s",
                alias, bus_err_name(err));
    (void)probe_read(cfg, &data);
    TEST_ASSERT(data == WRITE_PROBE_TRUE_VAL,
                "the write to 0x%08X must not reach DRBG CFG at 0x%08X, which now holds 0x%08X "
                "instead of 0x%08X",
                alias, cfg, data, WRITE_PROBE_TRUE_VAL);

    (void)probe_write(cfg, original);

    uint32_t kpv_hole = kpv->base + kpv->span;
    err = probe_write(kpv_hole, WRITE_PROBE_ALIAS_VAL);
    TEST_ASSERT(err == BUS_ERR_SLVERR,
                "a write to 0x%08X, unmapped inside the KPV decode window, must answer SLVERR; "
                "got %s",
                kpv_hole, bus_err_name(err));
}

int main(void) {
    TEST_INIT();

    printf("KM Fabric Address Alias Sweep\n");
    printf("=============================\n\n");

    /* Seeding the DRBG keeps the aliased DATA reads in the drbg_sampler sweep
     * from waiting out the sampler's timeout on an idle stream. */
    if (!tb_set_timeout(TEST_TIMEOUT_CYCLES) || !tb_drbg_set_seed(0xFA12U, 5000)) {
        TEST_FAIL("TB setup failed");
    }

    TEST_SUBTEST_START("Bus error reporting is usable");
    check_bus_err_reporting_usable();

    TEST_SUBTEST_START("Witness registers and the addresses that mirror them");
    check_witnesses();

    TEST_SUBTEST_START("Writes above a decode window do not reach the register");
    check_write_probes();

    TEST_SUBTEST_START("Every address of every port");
    for (uint32_t i = 0; i < KM_PORT_COUNT; i++) {
        const km_port_t *port = &KM_PORTS[i];
        uint32_t window = decode_window(port->span);

        for (uint32_t off = port->probe_min; off < port->slot; off += 4U) {
            check_offset(port, window, off);
        }
        TEST_LOG("  %s: 0x%04X-0x%04X held the invariant", port->name, port->probe_min,
                 port->slot - 4U);
    }

    TEST_LOG("  No address outside a block's decode window returned data");
    TEST_PASS();
    return 0;
}

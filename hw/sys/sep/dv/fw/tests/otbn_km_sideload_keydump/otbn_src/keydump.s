/* SS-1.3 KM->OTBN sideload consume-proof program.
 *
 * Reads the sideloaded keymgr key (provided by the Key Manager) from the
 * OTBN KEY_S0/KEY_S1 WSRs, reconstructs key = share0 ^ share1, and writes the
 * 384-bit result to DMEM so the host (UVM) can compare it against the
 * independently backdoor-reconstructed wrapper key.
 *
 *   key[255:0]   = KEY_S0_L ^ KEY_S1_L  -> result_lo (dmem 0x00, 32 bytes)
 *   key[383:256] = KEY_S0_H ^ KEY_S1_H  -> result_hi (dmem 0x20, low 16 bytes)
 */
.section .text.start
.globl _start
.globl start
_start:
start:
  bn.wsrr  w0, KEY_S0_L      /* w0 = key share0[255:0]   */
  bn.wsrr  w1, KEY_S1_L      /* w1 = key share1[255:0]   */
  bn.xor   w2, w0, w1        /* w2 = key[255:0]          */
  bn.wsrr  w3, KEY_S0_H      /* w3 = key share0[383:256] */
  bn.wsrr  w4, KEY_S1_H      /* w4 = key share1[383:256] */
  bn.xor   w5, w3, w4        /* w5 = key[383:256]        */

  addi     x2, x0, 2         /* WDR index 2 (w2) */
  addi     x5, x0, 5         /* WDR index 5 (w5) */
  la       x6, result_lo
  la       x7, result_hi
  bn.sid   x2, 0(x6)         /* dmem[result_lo] = w2 */
  bn.sid   x5, 0(x7)         /* dmem[result_hi] = w5 */
  ecall

.data
.globl result_lo
result_lo:
  .zero 32
.globl result_hi
result_hi:
  .zero 32

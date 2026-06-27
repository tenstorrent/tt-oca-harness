# SRAM Data and Address Scrambler

The goal of the scrambler is not secure data encryption but rather
basic obfuscation to impede simple memory dumping to find secrets.
The algorithm would be straight forward to break by a trained cryptanalyst.

The scrambling algorithm is an extremely rudimentary, round reduced,
block cipher inspired by the PRESENT cipher. PRESENT works on 64 bit
blocks, while this scrambler works on 32-bit blocks. PRESENT operates
on 32 repeated rounds, while this scrambler performs only a single round.
The player (permutation function) is also altered to accommodate the
reduced block size i.e. word length.

Address tweaking is necessary so that the same data at different addresses
scrambles to uniques values.
Tweaking is performed by simply xor mixing the address with
the random scrambler key to form the round key. If the address is
less than 32 bits wide, then we just repeatedly concatenate the address
with itself until we have 32 bits, truncating any excess bits.

Address scrambling is done in a similar fashion as data scrambling.
The address bits are first xor'ed with the key bits according to the address width.
The result is then split into 3 or 4 bit lanes, and passed through one sbox per lane.
Finally the sbox results are concatenated and fed through a linear
permutation network. There is no descrambling operation on the address, only scrambling.

Scrambling procedure:
There are two modes of scrambling operation, determined by the BYTE_WISE parameter.
In the first mode, when BYTE_WISE=0, the scrambler operates on complete 32-bit data
words. The second mode, when BYTE_WISE=1, operates on a byte-wise basis, scrambling
individual byte lanes independently. The 4-bit byte_mask_i input which accompanies the address
input determines which lanes are scrambled. Each bit corresponds to a byte lane with
bit 0 corresponding to the byte in data[7:0], bit 1 with data[15:8] and so on. The
byte_mask is ignored in BYTE_WISE=0 mode.

First the tweaked key i.e. the first (and only) round key, is xor'ed with the
input write data. The output is split into 8 4-bit nibble lanes and is fed into 16 sbox4
functions. The resulting values are concatenated and fed into the player permutation
function.

Descrambling procedure:
The process is exactly the reverse, first performing the iplayer inverse
permutation followed by 8 ibox invers sbox functions and lastly xor'ed with the
tweaked key to recover the unscrambled read data.

The sbox4 (substitution box) is a constant 4 input to 4 output mapping function.
The ibox is just the inverse function. The sbox functions are directly taken from
the PRESENT lightweight ciper standard. We also have a 3 bit version called sbox3
which is derived from the pyjamask lightweight block cipher.
The permutation layer are constructed in the same
manner as for standard PRESENT except that the bit offset increments
are 8 rather than 16 for the 32-bit word rather than for a 64-bit word. We also
have a set of shorter wordlength permutation functions used in the address scrambler
constructed with a similar methodology.
import argparse
import logging
logger = logging.getLogger(__name__.strip('_'))

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.hazmat.backends import default_backend

from .pack_images_constants import *

AES_BLOCK_SIZE_BYTES = 16
assert AES_BLOCK_SIZE_BYTES == algorithms.AES.block_size // 8

parser = argparse.ArgumentParser(description = \
            f'Encrypt and decrypt a file with AES128CBC.')
parser.add_argument('--plaintext_in', type = str, required = True, help = \
            f'Plaintext input file.')
parser.add_argument('--ciphertext_out', type = str, required = True, help = \
            f'Ciphertext output file.')
parser.add_argument('--plaintext_out', type = str, required = True, help = \
            f'Plaintext (decrypted ciphertext) output file.')
parser.add_argument('--kdf_in', type = str, required = True, help = \
            f'KDF input from manifest, {AES_ENC_SALT_SIZE_BYTES} bytes hex-string.')
parser.add_argument('--key', type = str, required = True, help = \
            f'Key key from register, {AES_ENC_KEY_SIZE_BYTES} bytes hex-string.')
parser.add_argument('--iv', type = str, required = True, help = \
            f'Encryption IV, {AES_ENC_IV_SIZE_BYTES} bytes hex-string.')
parser.add_argument("-v", "--verbose", action='store_true')

def aes128cbc_encrypt(key, iv, plaintext):
    # logger.debug(f"Plaintext: {plaintext.hex()}")
    logger.debug(f"Plaintext len: {len(plaintext)}")
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    padder = PKCS7(algorithms.AES.block_size).padder()
    padded_plaintext = padder.update(plaintext) + padder.finalize()
    # logger.debug(f"Padded plaintext: {padded_plaintext.hex()}")
    logger.debug(f"Padded plaintext len: {len(padded_plaintext)}")
    ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()
    # logger.debug(f"Ciphertext: {ciphertext.hex()}")
    logger.debug(f"Ciphertext len: {len(ciphertext)}")
    return ciphertext

def aes128cbc_decrypt(key, iv, ciphertext):
    # logger.debug(f"Ciphertext: {ciphertext.hex()}")
    logger.debug(f"Ciphertext len: {len(ciphertext)}")
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    unpadder = PKCS7(algorithms.AES.block_size).unpadder()
    padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    # logger.debug(f"Padded plaintext: {padded_plaintext.hex()}")
    logger.debug(f"Padded plaintext len: {len(padded_plaintext)}")
    plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
    # logger.debug(f"Plaintext: {plaintext.hex()}")
    logger.debug(f"Plaintext len: {len(plaintext)}")
    return plaintext

def setup_logging(verbose):
    """ Setup logging, at INFO level by default, or DEBUG if verbose is true."""
    level = logging.INFO
    if verbose:
        level = logging.DEBUG
    logging.basicConfig(level=level, format='pbkdf2: %(levelname)s: %(message)s')

def main():
    args = parser.parse_args()

    setup_logging(args.verbose)

    input_file = args.plaintext_in
    encrypted_file = args.ciphertext_out
    decrypted_file = args.plaintext_out
    try:
        kdf_in = bytearray.fromhex(args.kdf_in)
        key = bytearray.fromhex(args.password)
        iv = bytearray.fromhex(args.iv)
        assert len(kdf_in) == AES_ENC_SALT_SIZE_BYTES, f'KDF Input length is {len(salt)}, must be {AES_ENC_SALT_SIZE_BYTES} bytes long'
        assert len(key) == AES_ENC_KEY_SIZE_BYTES, f'Key length is {len(key)}, must be {AES_ENC_KEY_SIZE_BYTES} bytes long'
        assert len(iv) == AES_ENC_IV_SIZE_BYTES, f'IV length is {len(iv)}, must be {AES_ENC_IV_SIZE_BYTES} bytes long'
    except Exception as e:
        logger.debug(f"Error: {e}")
        return

    logger.debug(f"Key: {key.hex()}")

    logger.debug("\nEncrypt:")
    with open(input_file, 'rb') as f:
        plaintext = f.read()
    ciphertext = aes128cbc_encrypt(key, iv, plaintext)
    with open(encrypted_file, 'wb') as f:
        f.write(ciphertext)
    logger.debug(f'File encrypted successfully and saved to {encrypted_file}')

    logger.debug("\nDecrypt:")
    with open(encrypted_file, 'rb') as f:
        ciphertext = f.read()
    plaintext = aes128cbc_decrypt(key, iv, ciphertext)
    with open(decrypted_file, 'wb') as f:
        f.write(plaintext)
    logger.debug(f'File decrypted successfully and saved to {decrypted_file}')

if __name__ == '__main__':
    main()

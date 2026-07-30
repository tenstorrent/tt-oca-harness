#!/usr/bin/env python3

import logging
import os
from abc import ABC, abstractmethod
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding, utils
from cryptography.hazmat.backends import default_backend
from .pack_images_constants import *
from .utils import int_to_bytes_be, check

logger = logging.getLogger(__name__)

class SigningError(Exception): ...

class SigningKey(ABC):
    def __init__(self, manifest, secure_boot):
        self.name = manifest['signing_key_name']
        self.signature_type = manifest['signature_type']
        self.signing_authority = manifest['signing_authority']
        self.keyID = manifest['signing_key_id']
        self.public_key = None  # each subclass will populate this with either an EllipticCurvePublicKey or RSAPublicKey
        self.public_key_bytes = b''
        self.signature_digest = b''
        self.signature = None
        self.signature_bytes = b''
        self.signature_verified = False
        self.hash_func = hashes.SHA256  # as of right now all signatures use SHA-256 as the digest function
        self.min_pub_key_size = 0
        self.min_signature_size = 0
        self.secure_boot = secure_boot
        self.no_signature = False  # support generation of manifests with broken/bad signature related values for testing
        if self.secure_boot == 1:
            if self.signature_type == ManifestSignatureType.RSA_3072.value:
                self.min_pub_key_size = RSA_3072_KEY_SZ_BYTES
                self.min_signature_size = RSA_3072_KEY_SZ_BYTES
            elif self.signature_type == ManifestSignatureType.ECC_P_256.value:
                self.min_pub_key_size = EC_256_KEY_SZ_BYTES*2
                self.min_signature_size = EC_256_KEY_SZ_BYTES*2
            else:
                self.no_signature = check(self.signature_type in [ManifestSignatureType.ECC_P_256.value, ManifestSignatureType.RSA_3072.value],
                                          f'invalid signature type {self.signature_type} for secure boot being enabled')
        else:
            self.signature_type = ManifestSignatureType.NO_SIGNATURE.value
            self.no_signature = True

    def validate_signature_size(self):
        # the signature bytes to be written into a manifest can never be larger than the designated size of the signature manifest field
        max_sz = SIGNATURE_FIELD_SIZE
        if len(self.signature_bytes) > max_sz or len(self.signature_bytes) < self.min_signature_size:
            raise ValueError(f"Invalid signature length: {len(self.signature_bytes)}. \
                            Max size for type {self.signature_type} is {max_sz}, min size is {self.min_signature_size}.")

    def validate_public_key_size(self):
        max_sz = PUBLIC_KEY_FIELD_SIZE
        if len(self.public_key_bytes) > max_sz or len(self.public_key_bytes) < self.min_pub_key_size:
            raise ValueError(f"Invalid public key length: {len(self.public_key_bytes)}. \
                            Max size for type {self.signature_type} is {max_sz}, min size is {self.min_pub_key_size}.")

    def generate_verified_signature(self, data) -> bytes:
        # For test cases where secure boot is enabled but signature verification is disable; use this path
        if self.no_signature:
            self.signature_bytes = b''
            self.signature_verified = True
            return self.signature_bytes
        try:
            self.sign_data(data)
            if not self.verify_signature(data):
                raise SigningError(f'failed to verify generated signature with public key material')
            return self.signature_bytes
        except Exception as e:
            raise SigningError(f'failed to generate signature for data using {self.name} private key via {self.signing_authority}: {e}')

    def digest_message(self, data):
        hasher = hashes.Hash(self.hash_func())
        hasher.update(data)
        self.signature_digest = hasher.finalize()

    def add_signature(self, signature_value):
        self.signature = signature_value
        if self.signature_type == ManifestSignatureType.RSA_3072.value:
            # Pad out the provided signature value to the maximum size of 384 bytes for insertion into manifests)
            self.signature_bytes = self.signature.rjust(SIGNATURE_FIELD_SIZE, b'\x00')
        elif self.signature_type == ManifestSignatureType.ECC_P_256.value:
            # ECDSA Signatures are returned in DER-encoded format specified in RFC 3279
            # The signature needs to be decoded into r/s values it can be padded for in
            # Decode the DER-encoded signature to obtain r and s values
            r, s = utils.decode_dss_signature(self.signature)
            # Convert r and s to bytes and concatenate them
            r_bytes = r.to_bytes(EC_256_KEY_SZ_BYTES, byteorder='big')
            s_bytes = s.to_bytes(EC_256_KEY_SZ_BYTES, byteorder='big')
            self.signature_bytes = r_bytes + s_bytes
        self.signature_verified = False

    @abstractmethod
    def sign_data(self, data: bytes):
        """Generate a cryptographic signature for the provided data.

        This method must be implemented by subclasses to provide signing functionality
        specific to their signing authority (local keys, AWS KMS, HSM, etc.).

        Args:
            data: The data to be signed

        Returns:
            The signature bytes
        """
        pass

    @abstractmethod
    def verify_signature(self, data: bytes) -> bool:
        """Verify a signature against the provided data.

        This method must be implemented by subclasses to provide verification functionality
        specific to their signing authority (local keys, AWS KMS, HSM, etc.).

        Args:
            data: The data that was signed

        Returns:
            True if signature is valid, False otherwise
        """
        pass

#######################################################################
################ Non-secure boot empty key object #####################
#######################################################################
class NoSigningKey(SigningKey):
    def __init__(self, manifest, secure_boot):
        super().__init__(manifest, secure_boot)

    def sign_data(self, data: bytes):
        logger.debug(f'passing through signing method and returning empty signature')
        return bytearray()

    def verify_signature(self, data: bytes):
        logger.debug(f'passing through verification method and signature check was successful')
        self.signature_verified = True
        return self.signature_verified


#######################################################################
################ Local Key File Management and Signing ################
#######################################################################
class LocalKey(SigningKey):
    def __init__(self, manifest, secure_boot):
        super().__init__(manifest, secure_boot)

        if self.signature_type == ManifestSignatureType.NO_SIGNATURE.value:
            return

        # Local private key loading
        with open(os.path.expandvars(manifest['signing_key_file']), "rb") as key_file:
            self.private_key = serialization.load_pem_private_key(key_file.read(), password=None)

        # Populate the cryptography compatible PublicKey object and the manifest friendly byes representation
        self.public_key = self.private_key.public_key()
        if self.signature_type == ManifestSignatureType.RSA_3072.value:
            check_rsa_private_key(self.private_key)
            self.public_key_bytes = get_rsa_public_key_bytes(self.private_key)
        elif self.signature_type == ManifestSignatureType.ECC_P_256.value:
            check_ec_private_key(self.private_key)
            self.public_key_bytes = get_ec_public_key_bytes(self.private_key)


    def sign_data(self, data):
        """Generate signature for appropriate """
        logger.debug(f'sig generation for data len {len(data)} with key {self.name}')
        if self.signature_type == ManifestSignatureType.ECC_P_256.value and\
            isinstance(self.private_key, ec.EllipticCurvePrivateKey):
            # ECDSA signature
            ecdsa_signature = self.private_key.sign(
                data,
                ec.ECDSA(self.hash_func(), deterministic_signing=True)
            )
            self.add_signature(ecdsa_signature)
            return self.signature_bytes

        if self.signature_type == ManifestSignatureType.RSA_3072.value and\
                isinstance(self.private_key, rsa.RSAPrivateKey):
            # RSA signature
            signature_result = self.private_key.sign(
                data,
                padding.PKCS1v15(),
                self.hash_func()
            )
            # Ensure the signature is the same size as the RSA modulus (in bytes)
            # use rjust to pad with zeroes if necessary since the signature is big-endian
            self.add_signature(signature_result)
            return self.signature_bytes

        if self.signature_type == ManifestSignatureType.NO_SIGNATURE.value:
            return bytearray()

        raise ValueError(f"Unsupported signature type {self.signature_type} private key {self.private_key.__class__}")

    def verify_signature(self, data):
        """signature check against  for appropriate signing primitive"""
        logger.debug(f'sig verification for data len {len(data)} with key {self.name}')
        if self.signature_type == ManifestSignatureType.ECC_P_256.value and\
            isinstance(self.public_key, ec.EllipticCurvePublicKey):
            # ECDSA signature
            self.public_key.verify(
                self.signature,
                data,
                ec.ECDSA(self.hash_func(), deterministic_signing=True)
            )
            self.signature_verified = True
            return self.signature_verified

        if self.signature_type == ManifestSignatureType.RSA_3072.value and\
                isinstance(self.public_key, rsa.RSAPublicKey):
            # RSA signature
            self.public_key.verify(
                self.signature,
                data,
                padding.PKCS1v15(),
                self.hash_func()
            )
            self.signature_verified = True
            return self.signature_verified

        if self.signature_type == ManifestSignatureType.NO_SIGNATURE.value:
            return self.signature_verified

        raise ValueError(f"Unsupported signature type {self.signature_type} public key {self.public_key.__class__}")

#######################################################################
################# AWS KMS Management and Signing #####################
#######################################################################
def aws_credentials_verify():
    """
    This function attempts to confirm valid AWS credentials are present in a path
    the boto3 AWS API package can use to reach out to AWS
    **NOTE** This function does not verify the available credentials provide access to signing key
    material that may be requested later. Each key has it's own permission where a user may have access to
    the public, signing using the private key, or neither/both of those.
    """
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        raise SigningError("boto3 is required for AWS KMS signing. Install it with: pip install tt-boot-manifest[aws]")

    try:
        sts = boto3.client('sts')
        response = sts.get_caller_identity()
        logger.debug(f"Credentials are valid. Account ID: {response['Account']}")
    except ClientError as e:
        raise SigningError(f"credentials are invalid. Error: {e}")


class AWSKey(SigningKey):
    def __init__(self, manifest, secure_boot):
        '''Init function for AWS KMS signing key key object'''
        super().__init__(manifest, secure_boot)
        try:
            import boto3
        except ImportError:
            raise SigningError("boto3 is required for AWS KMS signing. Install it with: pip install tt-boot-manifest[aws]")

        # Before we attempt to load any key material, check the available AWS credentials are valid
        # Make sure to run `eval $(python3 aws_sso_emulation_secure.py)` to setup your AWS credentials
        # on this host if you are working with this code manually
        client = boto3.client('kms')
        aws_credentials_verify()

        # Read the public key
        try:
            response = client.get_public_key(
                KeyId=self.keyID
            )
        except Exception as e:
            raise SigningError(f'unable to read public key for {self.name}({self.keyID}) - check credentials or key permission: {e}')

        # Create a working public key object from the public response
        self.public_key = serialization.load_der_public_key(response['PublicKey'], backend=default_backend)
        if self.signature_type == ManifestSignatureType.RSA_3072.value:
            check_rsa_public_key(self.public_key)
            rsa_modulus = self.public_key.public_numbers().n
            self.public_key_bytes = int_to_bytes_be(rsa_modulus, RSA_3072_KEY_SZ_BYTES)
        elif self.signature_type == ManifestSignatureType.ECC_P_256.value:
            check_ec_public_key(self.public_key)
            ec_x = self.public_key.public_numbers().x
            ec_y = self.public_key.public_numbers().y
            ec_x_bytes = int_to_bytes_be(ec_x, EC_256_KEY_SZ_BYTES)
            ec_y_bytes = int_to_bytes_be(ec_y, EC_256_KEY_SZ_BYTES)
            logger.debug(f"ECDSA Public Key:\n\
                X: {ec_x}\n{ec_x_bytes.hex()} {len(ec_x_bytes)} bytes\n\
                Y: {ec_y}\n{ec_y_bytes.hex()} {len(ec_y_bytes)} bytes")
            self.public_key_bytes =  ec_x_bytes + ec_y_bytes

        self.validate_public_key_size()
        self.get_signing_algorithm()


    def get_signing_algorithm(self):
        ''' Set the AWS KMS specific names for each signing primitive'''
        if self.signature_type == ManifestSignatureType.ECC_P_256.value:
            self.signing_algorithm = 'ECDSA_SHA_256'
            return
        if self.signature_type == ManifestSignatureType.RSA_3072.value:
            self.signing_algorithm = 'RSASSA_PKCS1_V1_5_SHA_256'
            return
        raise ValueError(f"Unsupported signing type {self.signature_type} for AWS KMS signing")


    def sign_data(self, data):
        '''Generate a cryptographic signature for the provided data given the key/signing type
        specified in this signing key object'''

        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError:
            raise SigningError("boto3 is required for AWS KMS signing. Install it with: pip install tt-boot-manifest[aws]")


        logger.debug(f'AWS KMS sig generation for data len {len(data)} with key {self.name}')
        if self.signature_digest == b'':
            # if no digest of the message has already been generated, calculate it now
            self.digest_message(data)
        logger.debug(f'digest of message to be signed: {self.signature_digest}')

        # Make AWS KMS signing request
        client = boto3.client('kms')
        response = client.sign(
            # The asymmetric KMS key to be used to generate the digital signature. This example uses an alias of the KMS key.
            KeyId=self.keyID,
            # Message to be signed. Use Base-64 for the CLI.
            Message=self.signature_digest,
            # Indicates whether the message is RAW or a DIGEST.
            MessageType='DIGEST',
            # The requested signing algorithm. This must be an algorithm that the KMS key supports.
            SigningAlgorithm=self.signing_algorithm,
        )
        logger.debug(f'signing request for key {response["KeyId"]} returned {response["ResponseMetadata"]}')
        if response["ResponseMetadata"]['HTTPStatusCode'] != 200:
            raise SigningError(f'signing request for key {response["KeyId"]} has invalid return code {response["ResponseMetadata"]["HTTPStatusCode"]}')

        self.add_signature(response['Signature'])
        self.validate_signature_size()
        self.signature_verified = False
        return self.signature_bytes


    def verify_signature(self, data):
        if self.signature_digest == b'':
            # if no digest of the message has already been generated, calculate it now
            self.digest_message(data)
        logger.debug(f'digest of message to be signed: {self.signature_digest}')

        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError:
            raise SigningError("boto3 is required for AWS KMS signing. Install it with: pip install tt-boot-manifest[aws]")

        # Make AWS KMS signature verification request
        client = boto3.client('kms')
        response = client.verify(
            KeyId=self.keyID,
            Message=self.signature_digest,
            MessageType='DIGEST',
            Signature=self.signature,
            SigningAlgorithm=self.signing_algorithm,
            DryRun=False
        )
        logger.debug(f'signature verify request for key {response["KeyId"]} returned {response["ResponseMetadata"]}')
        if response["ResponseMetadata"]['HTTPStatusCode'] != 200:
            raise SigningError(f'signature verify request for key {response["KeyId"]} has invalid return code {response["ResponseMetadata"]["HTTPStatusCode"]}')

        self.signature_verified = response['SignatureValid']
        return self.signature_verified

#######################################################################
################## Internal HSM Management and Signing ################
#######################################################################
class HSMKey(SigningKey):
    def __init__(self, manifest, secure_boot):
        super().__init__(manifest, secure_boot)

    def sign_data(self, data):
        raise SigningError("HSM Signing Not Yet Supported")

    def verify_signature(self, data):
        raise SigningError("HSM Signing Not Yet Supported")



def prepare_signing_key(manifest: dict, secure_boot: int) -> SigningKey:
    """
    This is our factory function for building the correct signing key object based on the
    signing authority specified in the manifest YAML. The signing authority is were
    """

    # If secure boot is not used, return an empty key object
    if secure_boot != 1:
        return NoSigningKey(manifest, secure_boot)

    #### Secure boot is enabled - select the appropriate signing key oracle ####
    # We use a dictionary to map the input strings to the class constructors.
    # Note that we are storing the classes themselves, not instances of them.
    key_authority_mapping = {
        "local": LocalKey,
        "aws": AWSKey,
        "hsm": HSMKey,
    }

    ####################
    # Check for restrictions on signing configuration
    # before assembling the key object
    ####################
    sig_type = manifest['signature_type']
    manifest_identifier = manifest['manifest_identifier']
    # Check for valid signature types
    check(sig_type in [ManifestSignatureType.ECC_P_256.value, ManifestSignatureType.RSA_3072.value],
        f'invalid signature type {sig_type} for secure boot being enabled')
    # BL0 only support RSA signatures for secure boot authentication
    # Reject any request to sign BL1 manifests with other signature algos (ECC for example)
    if manifest_identifier == 0x314c4254:
        check(sig_type == ManifestSignatureType.RSA_3072.value,
            f'BL1 manifest signing is only allowed to use RSA-3072 signatures - signature type requested: {sig_type}')

    # Look up the class in our mapping. The .get() method is used to
    # safely retrieve the value, returning None if the key doesn't exist.
    signing_authority = manifest["signing_authority"]
    signing_class = key_authority_mapping.get(signing_authority)

    # If a class was found in our mapping, instantiate it and return it.
    if signing_class:
        # The () calls the constructor (e.g., SubclassX())
        return signing_class(manifest, secure_boot)
    else:
        # If the key was not found, raise a ValueError exception.
        raise ValueError(f"Unknown object type: '{signing_authority}'. Valid types are 'local', 'aws', 'hsm'.")


def check_rsa_private_key(key, expected_size=RSA_3072_KEY_SZ_BITS):
    check(isinstance(key, rsa.RSAPrivateKey), f"Key {key} is not an RSA private key")
    check(key.key_size == expected_size, f"RSA key size {key.key_size} is not {expected_size} bits")

def check_ec_private_key(key, expected_curve=ec.SECP256R1):
    check(isinstance(key, ec.EllipticCurvePrivateKey), f"Key {key.__class__} is not an EC private key")
    check(isinstance(key.curve, expected_curve), f"EC key {key.curve} is not using the {expected_curve.name}")

def check_rsa_public_key(key, expected_size=RSA_3072_KEY_SZ_BITS):
    check(isinstance(key, rsa.RSAPublicKey), f"Key {key} is not an RSA public key")
    check(key.key_size == expected_size, f"RSA key size {key.key_size} is not {expected_size} bits")

def check_ec_public_key(key, expected_curve=ec.SECP256R1):
    check(isinstance(key, ec.EllipticCurvePublicKey), f"Key {key.__class__} is not an EC public key")
    check(isinstance(key.curve, expected_curve), f"EC key {key.curve} is not using the {expected_curve.name}")

def get_ec_public_key_bytes(ec_private_key):
    check_ec_private_key(ec_private_key)
    # Extract the X and Y coordinates of the ECDSA public key
    ec_public_key = ec_private_key.public_key()
    ec_x = ec_public_key.public_numbers().x
    ec_y = ec_public_key.public_numbers().y
    ec_x_bytes = int_to_bytes_be(ec_x, EC_256_KEY_SZ_BYTES)
    ec_y_bytes = int_to_bytes_be(ec_y, EC_256_KEY_SZ_BYTES)
    logger.debug(f"ECDSA Public Key:\n\
          X: {ec_x}\n{ec_x_bytes.hex()} {len(ec_x_bytes)} bytes\n\
          Y: {ec_y}\n{ec_y_bytes.hex()} {len(ec_y_bytes)} bytes")
    return ec_x_bytes + ec_y_bytes

def get_rsa_public_key_bytes(rsa_private_key):
    check_rsa_private_key(rsa_private_key)
    # Extract the modulus of the RSA public key
    rsa_public_key = rsa_private_key.public_key()
    rsa_modulus = rsa_public_key.public_numbers().n
    rsa_modulus_bytes = int_to_bytes_be(rsa_modulus, RSA_3072_KEY_SZ_BYTES)
    logger.debug(f"RSA Public Key:\n\
          Modulus: {rsa_modulus}\n{rsa_modulus_bytes.hex()} {len(rsa_modulus_bytes)} bytes")
    return rsa_modulus_bytes

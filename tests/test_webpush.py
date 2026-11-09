"""Web Push: the encrypted body decrypts exactly as a browser would (RFC 8291), VAPID JWT is valid."""

import json
import struct
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import webpush


def browser_decrypt(body, ua_private, auth_secret):
    """The receiving side of RFC 8291, written independently of webpush.encrypt."""
    salt, record_size, id_len = body[:16], struct.unpack(">I", body[16:20])[0], body[20]
    as_public_bytes = body[21:21 + id_len]
    ciphertext = body[21 + id_len:]
    ua_public_bytes = webpush._public_bytes(ua_private.public_key())
    as_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public_bytes)
    shared = ua_private.exchange(ec.ECDH(), as_public)
    prk_key = webpush._hkdf_extract(auth_secret, shared)
    ikm = webpush._hkdf_expand(prk_key, b"WebPush: info\x00" + ua_public_bytes + as_public_bytes, 32)
    prk = webpush._hkdf_extract(salt, ikm)
    cek = webpush._hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = webpush._hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    plaintext = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert record_size == 4096 and plaintext.endswith(b"\x02")
    return plaintext[:-1]


class WebPushTest(unittest.TestCase):
    def test_round_trip_matches_the_browser_side(self):
        ua_private = ec.generate_private_key(ec.SECP256R1())
        auth = b"0123456789abcdef"
        payload = json.dumps({"title": "Roof Signals", "body": "v0: AAPL, MSFT"}).encode()
        body = webpush.encrypt(payload, webpush.b64url_encode(webpush._public_bytes(ua_private.public_key())),
                               webpush.b64url_encode(auth))
        self.assertEqual(browser_decrypt(body, ua_private, auth), payload)

    def test_vapid_header_signature_verifies_with_the_public_key(self):
        private, public = webpush.generate_vapid_keys()
        header = webpush.vapid_authorization("https://fcm.googleapis.com/fcm/send/abc", private)
        token = header.split("t=")[1].split(",")[0]
        key = header.split("k=")[1]
        self.assertEqual(key, public)
        signing_input, signature = token.rsplit(".", 1)
        raw = webpush.b64url_decode(signature)
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        verifier = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.b64url_decode(public))
        verifier.verify(der, signing_input.encode(), ec.ECDSA(hashes.SHA256()))   # raises if invalid
        claims = json.loads(webpush.b64url_decode(signing_input.split(".")[1]))
        self.assertEqual(claims["aud"], "https://fcm.googleapis.com")
        self.assertTrue(claims["sub"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()

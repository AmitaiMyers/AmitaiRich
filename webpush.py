"""Minimal Web Push sender (RFC 8291 aes128gcm encryption + RFC 8292 VAPID), no extra packages.

Used by notify.py in the daily GitHub job to send the "new stocks today" push to the owner's
installed PWA. Keys:
  * VAPID private key (base64url of the raw 32-byte P-256 scalar) — a GitHub secret, never in git;
  * VAPID public key (base64url of the 65-byte uncompressed point) — in pwa/js/push-config.js;
  * the browser's subscription JSON ({endpoint, keys: {p256dh, auth}}) — a GitHub secret.
"""

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RECORD_SIZE = 4096
CONTACT = "https://amitaimyers.github.io/AmitaiRich/"   # VAPID 'sub': a URL, not a personal email


def b64url_decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _public_bytes(public_key):
    return public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def generate_vapid_keys():
    """(private_b64url, public_b64url) for a new VAPID key pair."""
    private = ec.generate_private_key(ec.SECP256R1())
    scalar = private.private_numbers().private_value.to_bytes(32, "big")
    return b64url_encode(scalar), b64url_encode(_public_bytes(private.public_key()))


def _private_key(private_b64url):
    return ec.derive_private_key(int.from_bytes(b64url_decode(private_b64url), "big"), ec.SECP256R1())


def _hkdf_extract(salt, ikm):
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def _hkdf_expand(prk, info, length):
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]   # length <= 32: one block


def encrypt(payload, p256dh_b64url, auth_b64url, salt=None, sender_private=None):
    """RFC 8291 aes128gcm body for one record. `salt`/`sender_private` are injectable for tests."""
    ua_public_bytes = b64url_decode(p256dh_b64url)
    auth_secret = b64url_decode(auth_b64url)
    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public_bytes)
    sender_private = sender_private or ec.generate_private_key(ec.SECP256R1())
    as_public_bytes = _public_bytes(sender_private.public_key())
    shared = sender_private.exchange(ec.ECDH(), ua_public)

    prk_key = _hkdf_extract(auth_secret, shared)
    ikm = _hkdf_expand(prk_key, b"WebPush: info\x00" + ua_public_bytes + as_public_bytes, 32)
    salt = salt or os.urandom(16)
    prk = _hkdf_extract(salt, ikm)
    cek = _hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    plaintext = payload + b"\x02"                     # padding delimiter: last (only) record
    if len(plaintext) + 16 > RECORD_SIZE:
        raise ValueError("push payload too large for one record")
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext, None)
    header = salt + struct.pack(">I", RECORD_SIZE) + bytes([len(as_public_bytes)]) + as_public_bytes
    return header + ciphertext


def vapid_authorization(endpoint, private_b64url, ttl_seconds=12 * 3600):
    """The `Authorization: vapid t=..., k=...` header value (ES256 JWT for the push service)."""
    private = _private_key(private_b64url)
    parsed = urlparse(endpoint)
    claims = {"aud": f"{parsed.scheme}://{parsed.netloc}", "exp": int(time.time()) + ttl_seconds, "sub": CONTACT}
    signing_input = (b64url_encode(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
                     + "." + b64url_encode(json.dumps(claims, separators=(",", ":")).encode()))
    r, s = decode_dss_signature(private.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    token = signing_input + "." + b64url_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    public = b64url_encode(_public_bytes(private.public_key()))
    return f"vapid t={token}, k={public}"


def send(subscription, payload_dict, private_b64url, ttl=86400):
    """POST one encrypted push. Raises on HTTP errors (410/404 = the subscription expired)."""
    body = encrypt(json.dumps(payload_dict).encode(), subscription["keys"]["p256dh"], subscription["keys"]["auth"])
    response = requests.post(subscription["endpoint"], data=body, timeout=30, headers={
        "Authorization": vapid_authorization(subscription["endpoint"], private_b64url),
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
        "TTL": str(ttl), "Urgency": "normal"})
    response.raise_for_status()
    return response.status_code


if __name__ == "__main__":
    private_key, public_key = generate_vapid_keys()
    print("VAPID_PRIVATE_KEY (GitHub secret, keep private):", private_key)
    print("VAPID public key (pwa/js/push-config.js):", public_key)

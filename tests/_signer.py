"""Test-only signer for throwaway keys. NOT part of the library: the shipped verifier never signs."""
import hashlib

import presigned_send as ps

_blake = lambda d: hashlib.blake2b(d, digest_size=64).digest()


def _expand(secret):
    h = _blake(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _compress(p):
    zinv = pow(p[2], ps._P - 2, ps._P)
    x, y = p[0] * zinv % ps._P, p[1] * zinv % ps._P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def public_key(secret):
    return _compress(ps._mul(_expand(secret)[0], ps._B))


def sign(secret, message):
    a, prefix = _expand(secret)
    A = _compress(ps._mul(a, ps._B))
    r = int.from_bytes(_blake(prefix + message), "little") % ps._L
    R = _compress(ps._mul(r, ps._B))
    k = int.from_bytes(_blake(R + A + message), "little") % ps._L
    return R + int.to_bytes((r + k * a) % ps._L, 32, "little")

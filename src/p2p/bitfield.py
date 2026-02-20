from __future__ import annotations


def bools_to_bitfield(values: list[bool]) -> bytes:
    if not values:
        return b""
    out = bytearray((len(values) + 7) // 8)
    for i, value in enumerate(values):
        if value:
            out[i // 8] |= 1 << (7 - (i % 8))
    return bytes(out)


def bitfield_to_bools(data: bytes, count: int) -> list[bool]:
    values = [False] * count
    for i in range(count):
        values[i] = bool(data[i // 8] & (1 << (7 - (i % 8))))
    return values

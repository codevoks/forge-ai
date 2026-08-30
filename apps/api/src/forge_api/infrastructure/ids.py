import secrets
import time
import uuid


def uuid7() -> str:
    unix_ms = int(time.time() * 1000)
    random_bits = secrets.randbits(74)
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0x0FFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    return str(uuid.UUID(int=value))

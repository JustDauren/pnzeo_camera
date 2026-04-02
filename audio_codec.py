"""Pure Python G.711 A-law codec for PNZEO camera audio.

Implements ITU-T G.711 A-law encoding and decoding using precomputed
lookup tables for zero per-sample arithmetic at runtime.
No external dependencies (Python 3.13 removed audioop).
"""
from __future__ import annotations

import struct

from .const import AUDIO_SAMPLE_RATE_MAP, AUDIO_SAMPLE_RATE_DEFAULT


# =============================================================================
# G.711 A-law decode table (256 entries)
# Maps A-law byte (0x00-0xFF) to signed 16-bit PCM value (-32768..32767)
# =============================================================================

def _build_decode_table() -> list[int]:
    """Build 256-entry A-law decode table per ITU-T G.711.

    Produces signed 16-bit PCM values (-32256..32256).
    The 13-bit A-law linear value is left-shifted by 3 to fill 16 bits.
    """
    table = [0] * 256
    for i in range(256):
        # Toggle even bits (XOR 0x55)
        ix = i ^ 0x55
        # Extract components
        sign = ix & 0x80      # sign bit (bit 7)
        exponent = (ix >> 4) & 0x07  # exponent (bits 4-6)
        mantissa = ix & 0x0F  # mantissa (bits 0-3)

        if exponent == 0:
            # Linear segment: 13-bit linear value
            linear = (mantissa * 2 + 1)
        else:
            # Companded segment: reconstruct 13-bit linear
            linear = (mantissa * 2 + 33) << (exponent - 1)

        # Left-shift by 3 to convert 13-bit to 16-bit range
        linear <<= 3

        # Apply sign: sign bit 0 means negative in A-law
        if sign == 0:
            linear = -linear

        # Clamp to 16-bit signed range
        if linear > 32767:
            linear = 32767
        elif linear < -32768:
            linear = -32768

        table[i] = linear
    return table


ALAW_DECODE_TABLE: list[int] = _build_decode_table()


# =============================================================================
# G.711 A-law encode table (65536 entries)
# Maps unsigned index (signed PCM + 32768) to A-law byte
# =============================================================================

def _build_encode_table() -> list[int]:
    """Build 65536-entry A-law encode table by inverting the decode table.

    For each possible 16-bit PCM value, find the A-law code whose decoded
    value is closest. This guarantees perfect roundtrip consistency.
    """
    # First build a sorted list of (decoded_value, alaw_code) pairs
    pairs = [(ALAW_DECODE_TABLE[code], code) for code in range(256)]
    pairs.sort(key=lambda x: x[0])
    decoded_values = [p[0] for p in pairs]
    alaw_codes = [p[1] for p in pairs]

    table = [0] * 65536
    for i in range(65536):
        pcm = i - 32768  # range: -32768..32767

        # Binary search for closest decoded value
        lo, hi = 0, 255
        while lo < hi:
            mid = (lo + hi) // 2
            if decoded_values[mid] < pcm:
                lo = mid + 1
            else:
                hi = mid

        # Check neighbors to find true closest
        best_idx = lo
        best_diff = abs(decoded_values[lo] - pcm)
        if lo > 0:
            diff = abs(decoded_values[lo - 1] - pcm)
            if diff < best_diff:
                best_idx = lo - 1
                best_diff = diff
        if lo < 255:
            diff = abs(decoded_values[lo + 1] - pcm)
            if diff < best_diff:
                best_idx = lo + 1

        table[i] = alaw_codes[best_idx]

    return table


ALAW_ENCODE_TABLE: list[int] = _build_encode_table()


# =============================================================================
# Codec functions
# =============================================================================

def alaw_decode(data: bytes) -> bytes:
    """Decode A-law bytes to 16-bit signed LE PCM.

    Returns bytes with 2x input length (each A-law byte -> 2 PCM bytes).
    """
    result = bytearray(len(data) * 2)
    for i, byte in enumerate(data):
        pcm = ALAW_DECODE_TABLE[byte]
        struct.pack_into("<h", result, i * 2, pcm)
    return bytes(result)


def alaw_encode(pcm_data: bytes) -> bytes:
    """Encode 16-bit signed LE PCM to A-law bytes.

    Returns bytes with half input length (each 2 PCM bytes -> 1 A-law byte).
    """
    num_samples = len(pcm_data) // 2
    result = bytearray(num_samples)
    for i in range(num_samples):
        pcm = struct.unpack_from("<h", pcm_data, i * 2)[0]
        # Convert signed PCM to unsigned index
        result[i] = ALAW_ENCODE_TABLE[pcm + 32768]
    return bytes(result)


def detect_audio_format(drw_payload: bytes) -> dict:
    """Detect audio format from DRW audio packet header.

    Camera audio DRW inner header (inferred from APK RTNativeCaller):
      byte 0: codec type (0=PCM, 1=A-law, 2=u-law, 3=ADPCM)
      byte 1: sample_rate indicator (0=8000, 1=16000, 2=32000)
      byte 2: channels (1=mono, 2=stereo)
      byte 3: bits per sample (8 or 16)

    Returns dict with keys: codec, sample_rate, channels, bits_per_sample.
    If header is not recognizable, defaults to A-law, 8000Hz, mono, 8-bit.
    """
    codec_names = {0: "pcm", 1: "alaw", 2: "ulaw", 3: "adpcm"}

    # Default format
    defaults = {
        "codec": "alaw",
        "sample_rate": AUDIO_SAMPLE_RATE_DEFAULT,
        "channels": 1,
        "bits_per_sample": 8,
    }

    if len(drw_payload) < 4:
        return defaults

    codec_byte = drw_payload[0]
    rate_byte = drw_payload[1]
    channels_byte = drw_payload[2]
    bits_byte = drw_payload[3]

    # Validate header bytes are in expected ranges
    if codec_byte > 3 or rate_byte > 2 or channels_byte not in (1, 2) or bits_byte not in (8, 16):
        return defaults

    return {
        "codec": codec_names.get(codec_byte, "alaw"),
        "sample_rate": AUDIO_SAMPLE_RATE_MAP.get(rate_byte, AUDIO_SAMPLE_RATE_DEFAULT),
        "channels": channels_byte,
        "bits_per_sample": bits_byte,
    }

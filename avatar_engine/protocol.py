"""Binary framing for /stream. Every binary WebSocket message starts with a 9-byte little-endian header:
   u8 type | u32 sequence | u32 timestamp_ms (stream clock, ms since the session's first message)
 type 1 = video frame: payload is a JPEG.
 type 2 = audio chunk: payload is u32 sample_rate followed by 16-bit signed little-endian mono PCM.
Text messages are JSON events ({type: state|caption|metrics|error|pong, ...})."""
import struct

VIDEO, AUDIO = 1, 2
HEADER = struct.Struct("<BII")


def pack_video(seq: int, ts_ms: int, jpeg: bytes) -> bytes:
    return HEADER.pack(VIDEO, seq, ts_ms & 0xFFFFFFFF) + jpeg


def pack_audio(seq: int, ts_ms: int, pcm16: bytes, sample_rate: int) -> bytes:
    return HEADER.pack(AUDIO, seq, ts_ms & 0xFFFFFFFF) + struct.pack("<I", sample_rate) + pcm16


def unpack(msg: bytes):
    """-> (type, seq, ts_ms, payload) where an audio payload is (sample_rate, pcm bytes)."""
    t, seq, ts = HEADER.unpack_from(msg)
    body = msg[HEADER.size:]
    if t == AUDIO:
        return t, seq, ts, (struct.unpack_from("<I", body)[0], body[4:])
    return t, seq, ts, body

"""Split text into speakable pieces. The first piece is kept short so speech starts early; later ones are whole sentences,
long sentences are cut at clause punctuation."""
import re

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_CLAUSE = re.compile(r"(?<=[,;:])\s+")


def split_text(text: str, first_max: int = 24, max_len: int = 160) -> list[str]:
    out: list[str] = []
    for sent in _SENT.split((text or "").strip()):
        sent = sent.strip()
        if not sent:
            continue
        limit = first_max if not out else max_len
        if len(sent) <= limit:
            out.append(sent)
            continue
        cur = ""
        for part in _CLAUSE.split(sent):
            if not out and not cur and len(part) > 2 * first_max:   # a long first clause would delay the first word: cut it early
                cut = part.rfind(" ", 0, int(first_max * 1.5))
                if cut > 0:
                    out.append(part[:cut])
                    part = part[cut + 1:]
            limit = first_max if not out else max_len
            if cur and len(cur) + 1 + len(part) > limit:
                out.append(cur)
                cur = part
            else:
                cur = f"{cur} {part}".strip()
        while len(cur) > max_len:  # no punctuation at all: cut at a space
            cut = cur.rfind(" ", 0, max_len)
            if cut <= 0:
                cut = max_len
            out.append(cur[:cut].strip())
            cur = cur[cut:].strip()
        if cur:
            out.append(cur)
    return out

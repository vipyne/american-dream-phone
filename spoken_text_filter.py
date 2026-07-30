"""spoken_text_filter.py — make LLM text sound right when spoken.

Kokoro (like most TTS) mangles written money/percent/large numbers: it reads
"$3,000" as "dollar three zero zero zero" and "45%" as "forty five percent sign".
Instructing the LLM to spell things out is unreliable — small local models ignore
it. So we normalize deterministically in the pipeline instead, as a Pipecat
`BaseTextFilter` wired into the TTS service (`text_filters=[SpokenTextFilter()]`).

It runs on aggregated sentence text just before synthesis and rewrites:
    $3,000        -> "three thousand dollars"
    $1.50         -> "one dollar and fifty cents"
    45%           -> "forty-five percent"
    0.45%         -> "zero point four five percent"
    1,250,000     -> "one million two hundred and fifty thousand"

Plain small numbers (e.g. "300") are left alone — Kokoro handles those fine.
"""

import re

from num2words import num2words
from pipecat.utils.text.base_text_filter import BaseTextFilter

# $3,000  |  $1.50  |  $3,000.50  |  $5
_CURRENCY_RE = re.compile(r"\$(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{1,2}))?")
# 45%  |  0.45%  |  45 %
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?%")
# comma-grouped integers not attached to a $ (already handled): 1,250,000
_GROUPED_INT_RE = re.compile(r"(?<![\w$.])\d{1,3}(?:,\d{3})+(?![\d.])")


def _int_to_words(n: int) -> str:
    return num2words(n)


def _decimal_to_words(s: str) -> str:
    """'0.45' -> 'zero point four five' (digit-by-digit after the point)."""
    whole, _, frac = s.partition(".")
    words = num2words(int(whole))
    if frac:
        digits = " ".join(num2words(int(d)) for d in frac)
        words += " point " + digits
    return words


def _money(m: re.Match) -> str:
    dollars = int(m.group(1).replace(",", ""))
    cents = m.group(2)
    unit = "dollar" if dollars == 1 else "dollars"
    words = f"{_int_to_words(dollars)} {unit}"
    if cents:
        c = int(cents.ljust(2, "0"))
        if c:
            words += f" and {_int_to_words(c)} {'cent' if c == 1 else 'cents'}"
    return words


def _percent(m: re.Match) -> str:
    num = m.group(1)
    words = _decimal_to_words(num) if "." in num else _int_to_words(int(num))
    return f"{words} percent"


def _grouped_int(m: re.Match) -> str:
    return _int_to_words(int(m.group(0).replace(",", "")))


class SpokenTextFilter(BaseTextFilter):
    """Normalize money, percentages, and large numbers to spoken words for TTS."""

    async def filter(self, text: str) -> str:
        """Rewrite written numerics into speakable words (order matters)."""
        text = _CURRENCY_RE.sub(_money, text)   # consume $ first
        text = _PERCENT_RE.sub(_percent, text)  # then %
        text = _GROUPED_INT_RE.sub(_grouped_int, text)  # remaining comma numbers
        return text

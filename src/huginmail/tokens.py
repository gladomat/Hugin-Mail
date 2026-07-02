"""Deterministic token estimation. No network, no heavy tokenizer dependency.

Approximation: ~4 chars/token (English/German prose). Used only for the taxonomy
budget check (§9.1), which needs a stable, offline upper-bound proxy — not exact
model tokenization. Conservative by design: rounds up.
"""

from __future__ import annotations

import math


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)

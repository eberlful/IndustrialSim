from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Sequence


PHILOX_M0: int = 0xD2511F53
PHILOX_M1: int = 0xCD9E8D57
PHILOX_W0: int = 0x9E3779B9
PHILOX_W1: int = 0xBB67AE85
MASK32: int = 0xFFFFFFFF
TWO_POW_53: float = 9007199254740992.0


class Philox4x32:
    """Pure-Python implementation of standard Philox 4x32-10 counter-based PRNG."""

    def __init__(self, key: tuple[int, int], rounds: int = 10) -> None:
        self.key = (key[0] & MASK32, key[1] & MASK32)
        self.rounds = rounds

    def generate(self, counter: Sequence[int]) -> tuple[int, int, int, int]:
        c0 = counter[0] & MASK32
        c1 = counter[1] & MASK32
        c2 = counter[2] & MASK32
        c3 = counter[3] & MASK32
        k0, k1 = self.key

        for _ in range(self.rounds):
            prod0 = c0 * PHILOX_M0
            hi0 = (prod0 >> 32) & MASK32
            lo0 = prod0 & MASK32

            prod1 = c2 * PHILOX_M1
            hi1 = (prod1 >> 32) & MASK32
            lo1 = prod1 & MASK32

            next_c0 = (hi1 ^ c1 ^ k0) & MASK32
            next_c1 = lo1
            next_c2 = (hi0 ^ c3 ^ k1) & MASK32
            next_c3 = lo0

            c0, c1, c2, c3 = next_c0, next_c1, next_c2, next_c3
            k0 = (k0 + PHILOX_W0) & MASK32
            k1 = (k1 + PHILOX_W1) & MASK32

        return (c0, c1, c2, c3)


@dataclass
class SemanticRandomStream:
    """Named, checkpointable random stream with semantic addressing.

    Each draw is addressed by (stream_kind, entity_id, mode, occurrence).
    Occurrences are tracked in the provided occurrence_counters dictionary so that
    draws can be checkpointed and restored reproducibly.
    """

    root_seed: int
    occurrence_counters: dict[str, int]

    @staticmethod
    def format_semantic_key(
        stream_kind: str,
        entity_id: str,
        mode: str,
        occurrence: int,
    ) -> str:
        """Format semantic key: stream_kind:entity_id:mode:occurrence."""
        return f"{stream_kind}:{entity_id}:{mode}:{occurrence}"

    def get_semantic_key(
        self,
        stream_kind: str,
        entity_id: str,
        mode: str,
        occurrence: int | None = None,
    ) -> str:
        """Get semantic key for the next (or specified) occurrence index."""
        if occurrence is None:
            occurrence = self.occurrence_counters.get(f"{stream_kind}:{entity_id}:{mode}", 0)
        return self.format_semantic_key(stream_kind, entity_id, mode, occurrence)

    def draw_float(
        self,
        stream_kind: str,
        entity_id: str,
        mode: str,
        occurrence: int | None = None,
    ) -> float:
        semantic_address = f"{stream_kind}:{entity_id}:{mode}"
        if occurrence is None:
            occ = self.occurrence_counters.get(semantic_address, 0)
            self.occurrence_counters[semantic_address] = occ + 1
        else:
            occ = occurrence

        # Derive 64-bit key from root_seed and semantic address
        seed_material = f"{self.root_seed}:{semantic_address}".encode("utf-8")
        hash_bytes = hashlib.sha256(seed_material).digest()
        k0 = int.from_bytes(hash_bytes[0:4], byteorder="little")
        k1 = int.from_bytes(hash_bytes[4:8], byteorder="little")

        rng = Philox4x32(key=(k0, k1))
        c0 = occ & MASK32
        c1 = (occ >> 32) & MASK32
        words = rng.generate(counter=(c0, c1, 0, 0))

        # Form 53-bit uniform float in [0.0, 1.0)
        hi = words[0]
        lo = words[1] >> 11
        bits53 = (hi << 21) | lo
        return bits53 / TWO_POW_53


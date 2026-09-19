from __future__ import annotations

import pytest

from industrialsim.random import Philox4x32, SemanticRandomStream


def test_philox4x32_determinism() -> None:
    rng1 = Philox4x32(key=(12345, 67890))
    res1 = rng1.generate(counter=(0, 0, 0, 0))

    rng2 = Philox4x32(key=(12345, 67890))
    res2 = rng2.generate(counter=(0, 0, 0, 0))

    assert res1 == res2
    assert len(res1) == 4
    for word in res1:
        assert 0 <= word < (1 << 32)


def test_philox4x32_different_counter() -> None:
    rng = Philox4x32(key=(12345, 67890))
    res1 = rng.generate(counter=(0, 0, 0, 0))
    res2 = rng.generate(counter=(1, 0, 0, 0))

    assert res1 != res2


def test_semantic_random_stream_draw() -> None:
    counters: dict[str, int] = {}
    stream = SemanticRandomStream(root_seed=42, occurrence_counters=counters)

    # First draw for entity "op-weld", mode "defect"
    val1 = stream.draw_float(stream_kind="quality", entity_id="op-weld", mode="defect")
    assert 0.0 <= val1 < 1.0
    assert counters["quality:op-weld:defect"] == 1

    # Second draw advances occurrence counter
    val2 = stream.draw_float(stream_kind="quality", entity_id="op-weld", mode="defect")
    assert 0.0 <= val2 < 1.0
    assert val1 != val2
    assert counters["quality:op-weld:defect"] == 2

    # A separate stream/entity draw is independent and reproducible
    counters_b: dict[str, int] = {}
    stream_b = SemanticRandomStream(root_seed=42, occurrence_counters=counters_b)
    val1_b = stream_b.draw_float(stream_kind="quality", entity_id="op-weld", mode="defect")
    assert val1 == val1_b

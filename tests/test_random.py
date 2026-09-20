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


def test_semantic_key_components_and_format() -> None:
    key = SemanticRandomStream.format_semantic_key(
        stream_kind="machine_failure",
        entity_id="mach-01",
        mode="ttf",
        occurrence=3,
    )
    assert key == "machine_failure:mach-01:ttf:3"

    counters: dict[str, int] = {}
    stream = SemanticRandomStream(root_seed=123, occurrence_counters=counters)
    assert stream.get_semantic_key("machine_repair", "mach-02", "duration") == "machine_repair:mach-02:duration:0"
    stream.draw_float("machine_repair", "mach-02", "duration")
    assert stream.get_semantic_key("machine_repair", "mach-02", "duration") == "machine_repair:mach-02:duration:1"


def test_extra_draw_in_one_branch_does_not_shift_unrelated_outcomes() -> None:
    # Simulate common randomness checkpoint
    base_counters: dict[str, int] = {
        "machine_failure:mach-01:ttf": 2,
        "machine_failure:mach-02:ttf": 1,
    }

    # Branch A and Branch B start with independent copies of base_counters
    counters_a = dict(base_counters)
    counters_b = dict(base_counters)

    stream_a = SemanticRandomStream(root_seed=999, occurrence_counters=counters_a)
    stream_b = SemanticRandomStream(root_seed=999, occurrence_counters=counters_b)

    # In Branch A, mach-01 suffers an extra degradation/failure draw
    draw_a_mach1_extra = stream_a.draw_float("machine_failure", "mach-01", "ttf")
    # In Branch A, an extra repair duration draw occurs
    draw_a_repair = stream_a.draw_float("machine_repair", "mach-01", "duration")

    # In Branch B, mach-01 is NOT drawn again.
    # Now BOTH branches draw for unrelated external machine mach-02:
    draw_a_mach2 = stream_a.draw_float("machine_failure", "mach-02", "ttf")
    draw_b_mach2 = stream_b.draw_float("machine_failure", "mach-02", "ttf")

    # The extra draws on mach-01 and repair in Branch A must NOT shift mach-02 in Branch A or Branch B!
    assert draw_a_mach2 == draw_b_mach2
    # Branch B draws for mach-01 later: it should receive the exact draw that Branch A received on its 3rd draw
    draw_b_mach1 = stream_b.draw_float("machine_failure", "mach-01", "ttf")
    assert draw_b_mach1 == draw_a_mach1_extra


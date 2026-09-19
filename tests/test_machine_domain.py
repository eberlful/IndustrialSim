import pytest
from industrialsim.domain import Machine


def test_machine_domain_initial_state() -> None:
    m = Machine(
        id="m1",
        health=0.95,
        operating_mode="fast",
        physical_state={"temp": 30.0},
    )
    assert m.id == "m1"
    assert m.health == 0.95
    assert m.operating_mode == "fast"
    assert m.physical_state == {"temp": 30.0}
    assert m.is_available(0)
    assert not m.is_failed
    assert not m.is_in_maintenance


def test_machine_domain_degradation_over_time() -> None:
    # 10 seconds of busy time at use_rate_per_s = 0.01 with mode multiplier = 2.0
    # Expected health drop = 10 * 0.01 * 2.0 = 0.20 -> 1.0 - 0.20 = 0.80
    m = Machine(
        id="m1",
        health=1.0,
        operating_mode="overclock",
        modes={"overclock": {"degradation_multiplier": 2.0}},
        degradation_policy={
            "use_rate_per_s": 0.01,
            "idle_rate_per_s": 0.002,
            "physical_rates_per_s": {"temp": 1.5},
            "physical_idle_rates_per_s": {"temp": -0.5},
        },
        physical_state={"temp": 20.0},
    )

    # Simulate allocate and 10s of busy time
    m.allocate("st1", "u1", "op1", time_ns=0)
    m.update_metrics(10_000_000_000)

    assert pytest.approx(m.health, rel=1e-4) == 0.80
    assert m.total_busy_time_ns == 10_000_000_000
    assert pytest.approx(m.physical_state["temp"], rel=1e-4) == 35.0  # 20 + 10 * 1.5

    # Release and simulate 10s of idle time (idle_rate_per_s = 0.002)
    # Expected health drop = 10 * 0.002 = 0.02 -> 0.80 - 0.02 = 0.78
    m.release("st1", "u1", "op1", time_ns=10_000_000_000)
    m.update_metrics(20_000_000_000)

    assert pytest.approx(m.health, rel=1e-4) == 0.78
    assert m.total_idle_time_ns == 10_000_000_000
    assert pytest.approx(m.physical_state["temp"], rel=1e-4) == 30.0  # 35 - 10 * 0.5


def test_machine_domain_failure_and_maintenance_state_and_restoration() -> None:
    m = Machine(id="m1", health=0.5)

    assert m.is_available(0)

    # Machine fails
    m.start_failure(time_ns=5_000_000_000)
    assert m.is_failed
    assert not m.is_available(5_000_000_000)
    assert m.failure_count == 1

    # Time passes while failed
    m.update_metrics(15_000_000_000)
    assert m.total_failed_time_ns == 10_000_000_000

    # Repair completes, restoring health to configured 0.80 (not 1.0)
    m.end_failure(time_ns=15_000_000_000, restored_health=0.80)
    assert not m.is_failed
    assert m.is_available(15_000_000_000)
    assert pytest.approx(m.health, rel=1e-4) == 0.80

    # Machine undergoes maintenance
    m.start_maintenance(time_ns=20_000_000_000)
    assert m.is_in_maintenance
    assert not m.is_available(20_000_000_000)
    assert m.maintenance_count == 1

    m.update_metrics(25_000_000_000)
    assert m.total_maintenance_time_ns == 5_000_000_000

    # Maintenance completes, restoring health to configured 0.90
    m.end_maintenance(time_ns=25_000_000_000, restored_health=0.90)
    assert not m.is_in_maintenance
    assert m.is_available(25_000_000_000)
    assert pytest.approx(m.health, rel=1e-4) == 0.90


def test_machine_domain_snapshot_and_restore() -> None:
    m = Machine(
        id="m1",
        health=0.75,
        operating_mode="eco",
        physical_state={"vibration": 0.25},
        total_maintenance_time_ns=12_000_000_000,
        total_failed_time_ns=8_000_000_000,
        maintenance_count=2,
        failure_count=1,
        is_failed=True,
    )
    snap = m.to_snapshot()
    assert snap["health"] == 0.75
    assert snap["operating_mode"] == "eco"
    assert snap["physical_state"] == {"vibration": 0.25}
    assert snap["total_maintenance_time_ns"] == 12_000_000_000
    assert snap["total_failed_time_ns"] == 8_000_000_000
    assert snap["maintenance_count"] == 2
    assert snap["failure_count"] == 1
    assert snap["is_failed"] is True

    m2 = Machine(id="m1")
    m2.restore_state(snap)
    assert m2.health == 0.75
    assert m2.operating_mode == "eco"
    assert m2.physical_state == {"vibration": 0.25}
    assert m2.total_maintenance_time_ns == 12_000_000_000
    assert m2.total_failed_time_ns == 8_000_000_000
    assert m2.maintenance_count == 2
    assert m2.failure_count == 1
    assert m2.is_failed is True


def test_machine_domain_inspection() -> None:
    m = Machine(id="m1", health=0.70)
    m.inspect(time_ns=1_000_000_000, restored_health=0.95)
    assert pytest.approx(m.health, rel=1e-4) == 0.95

    m.inspect(time_ns=2_000_000_000, health_delta=-0.05)
    assert pytest.approx(m.health, rel=1e-4) == 0.90

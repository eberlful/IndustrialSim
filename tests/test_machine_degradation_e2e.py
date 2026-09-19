import pytest
from industrialsim.application import run_episode, EpisodeEngine, create_checkpoint, restore_checkpoint


def test_cycle_time_slowdown_due_to_degraded_health() -> None:
    # Machine with health 0.5 and cycle_time_factor = 1.0
    # Expected multiplier = 1 + 1.0 * (1 - 0.5) = 1.5 -> 10s becomes 15s
    yaml_healthy = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
machines:
  - id: "m1"
    initial_health: 1.0
    degradation:
      cycle_time_factor: 1.0
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "10s"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    yaml_degraded = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
machines:
  - id: "m1"
    initial_health: 0.5
    degradation:
      cycle_time_factor: 1.0
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "10s"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    res_healthy = run_episode(yaml_healthy)
    assert res_healthy.simulated_time_ns == 10_000_000_000

    res_degraded = run_episode(yaml_degraded)
    assert res_degraded.simulated_time_ns == 15_000_000_000


def test_defect_probability_increase_due_to_degraded_health() -> None:
    # At health 0.0, defect_probability_factor 1.0 raises defect prob from 0.0 to 1.0
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
machines:
  - id: "m1"
    initial_health: 0.0
    degradation:
      defect_probability_factor: 1.0
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "5s"
        defect_probability: 0.0
        defect_name: "wear_defect"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    res = run_episode(yaml_content)
    unit = res.production_units[0]
    assert unit.quality_state == "wear_defect"


def test_planned_disruption_interruption_resume_and_partial_restoration() -> None:
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
workers:
  - id: "tech-1"
    qualifications: ["maintenance"]
machines:
  - id: "m1"
    initial_health: 0.5
    planned_disruptions:
      - start_time: "3s"
        duration: "5s"
        repaired_health: 0.85
        required_workers:
          - qualification: "maintenance"
            count: 1
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "10s"
        interruption_policy: "resume"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    # Operation starts at 0s, runs until 3s (3s elapsed, 7s remaining).
    # Disruption from 3s to 8s (5s duration). Technician works 3s..8s.
    # Disruption ends at 8s, health restored to 0.85 (not 1.0!).
    # Operation resumes at 8s for 7s remaining -> completes at 15s.
    res = run_episode(yaml_content)
    assert res.status == "completed"
    assert res.simulated_time_ns == 15_000_000_000

    m1 = next(m for m in res.machines if m.id == "m1")
    assert m1.failure_count == 1
    assert m1.total_failed_time_ns == 5_000_000_000
    assert pytest.approx(m1.health, rel=1e-4) == 0.85

    st1 = res.stations[0]
    assert st1.interrupted_count == 1
    assert st1.resumed_count == 1
    assert st1.operations_completed == 1

    tech = next(w for w in res.workers if w.id == "tech-1")
    assert tech.total_busy_time_ns == 5_000_000_000


def test_planned_disruption_interruption_restart() -> None:
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
machines:
  - id: "m1"
    planned_disruptions:
      - start_time: "3s"
        duration: "4s"
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "10s"
        interruption_policy: "restart"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    # Operation starts at 0s, disrupted at 3s. Disruption ends at 7s.
    # Restarts from 0 duration at 7s for full 10s -> completes at 17s.
    res = run_episode(yaml_content)
    assert res.status == "completed"
    assert res.simulated_time_ns == 17_000_000_000
    st1 = res.stations[0]
    assert st1.interrupted_count == 1
    assert st1.restarted_count == 1


def test_planned_disruption_interruption_scrap() -> None:
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
machines:
  - id: "m1"
    planned_disruptions:
      - start_time: "3s"
        duration: "4s"
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "10s"
        interruption_policy: "scrap"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    # Operation starts at 0s, disrupted at 3s. Unit is scrapped immediately at 3s!
    res = run_episode(yaml_content)
    assert res.status == "completed"
    assert res.simulated_time_ns == 3_000_000_000
    unit = res.production_units[0]
    assert unit.quality_state == "scrapped"
    assert unit.state == "terminal"


def test_preventive_maintenance_condition_threshold() -> None:
    # Machine degrades by 0.02 per second of use.
    # Initial health is 0.70.
    # After op1 for u1 (duration 10s), health decreases by 10 * 0.02 = 0.20 -> health becomes 0.50.
    # Maintenance policy has health_threshold = 0.60, duration = 10s, restored_health = 0.90.
    # After op1 finishes at 10s, health is 0.50 <= 0.60, triggering preventive maintenance.
    # Maintenance takes 10s (from 10s to 20s) with technician.
    # At 20s, machine is restored to 0.90 health.
    # Second unit then executes op1 from 20s to 30s.
    # After op1 for u2 (duration 10s), health decreases by 10 * 0.02 = 0.20 -> health becomes 0.70.
    # 0.70 > 0.60 so no further maintenance is triggered.
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
workers:
  - id: "tech-1"
    qualifications: ["maintenance"]
machines:
  - id: "m1"
    initial_health: 0.70
    degradation:
      use_rate_per_s: 0.02
    maintenance:
      trigger: "condition_threshold"
      health_threshold: 0.60
      duration: "10s"
      restored_health: 0.90
      required_workers:
        - qualification: "maintenance"
          count: 1
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "10s"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
    release_time: "0s"
  - id: "u2"
    variant: "sedan"
    release_time: "0s"
"""
    res = run_episode(yaml_content)
    assert res.status == "completed"
    assert res.simulated_time_ns == 30_000_000_000

    m1 = next(m for m in res.machines if m.id == "m1")
    assert m1.maintenance_count == 1
    assert m1.total_maintenance_time_ns == 10_000_000_000
    assert pytest.approx(m1.health, rel=1e-4) == 0.70


def test_repair_contention_multiple_machines() -> None:
    # Two stations/machines both have planned disruptions starting at 2s, each taking 5s.
    # There is only 1 maintenance technician.
    # Technician repairs m1 first (2s..7s), then m2 (7s..12s).
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
workers:
  - id: "tech-single"
    qualifications: ["maintenance"]
machines:
  - id: "m1"
    planned_disruptions:
      - id: "dis-1"
        start_time: "2s"
        duration: "5s"
        required_workers:
          - qualification: "maintenance"
            count: 1
  - id: "m2"
    planned_disruptions:
      - id: "dis-2"
        start_time: "2s"
        duration: "5s"
        required_workers:
          - qualification: "maintenance"
            count: 1
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "10s"
        required_machines: ["m1"]
  - id: "st2"
    operations:
      - id: "op2"
        duration: "10s"
        required_machines: ["m2"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    # Run episode to 15s
    res = run_episode(yaml_content)
    m1 = next(m for m in res.machines if m.id == "m1")
    m2 = next(m for m in res.machines if m.id == "m2")
    tech = next(w for w in res.workers if w.id == "tech-single")

    assert m1.failure_count == 1
    assert m2.failure_count == 1
    assert tech.total_busy_time_ns == 10_000_000_000  # 5s for m1 + 5s for m2


def test_stochastic_failure_and_deterministic_replay() -> None:
    yaml_content = """
schema_version: "1.0"
seed: 98765
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
machines:
  - id: "m1"
    initial_health: 0.8
    failure:
      hazard_rate_per_s: 0.1
      repair_duration: "4s"
      repaired_health: 0.80
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "20s"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    run1 = run_episode(yaml_content)
    run2 = run_episode(yaml_content)

    assert run1.status == "completed"
    assert run1.result_hash == run2.result_hash
    assert run1.simulated_time_ns == run2.simulated_time_ns
    assert run1.events_processed == run2.events_processed


def test_checkpoint_restore_during_maintenance_or_failure() -> None:
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
workers:
  - id: "tech-1"
    qualifications: ["maintenance"]
machines:
  - id: "m1"
    planned_disruptions:
      - start_time: "5s"
        duration: "10s"
        repaired_health: 0.88
        required_workers:
          - qualification: "maintenance"
            count: 1
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "20s"
        interruption_policy: "resume"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    # Uninterrupted run
    baseline = run_episode(yaml_content)
    assert baseline.status == "completed"

    # Run with pause at 8s (mid-disruption/repair!)
    from industrialsim.application import validate_config
    val = validate_config(yaml_content)
    assert val.config is not None
    engine = EpisodeEngine.create(val.config)
    engine.run(pause_at_ns=8_000_000_000)

    # At 8s, machine is failed / under repair
    assert engine.machines["m1"].is_failed
    cp = engine.create_checkpoint()

    # Restore from checkpoint and run to completion
    resumed_engine = EpisodeEngine.restore(cp)
    resumed_summary = resumed_engine.run()

    assert resumed_summary.status == "completed"
    assert resumed_summary.simulated_time_ns == baseline.simulated_time_ns
    assert resumed_summary.result_hash == baseline.result_hash


def test_operating_mode_cycle_time_speedup_and_stochastic_mttr() -> None:
    # Operating mode "fast" has cycle_time_multiplier: 0.5.
    # Nominal duration is 10s, with perfect health and fast mode, effective duration is 5s.
    # Also tests stochastic failure with mttr: "5s".
    yaml_content = """
schema_version: "1.0"
seed: 12345
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
machines:
  - id: "m1"
    initial_health: 1.0
    operating_mode: "fast"
    modes:
      fast:
        cycle_time_multiplier: 0.5
    failure:
      mttf: "20s"
      mttr: "5s"
      repaired_health: 0.90
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "10s"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    res = run_episode(yaml_content)
    assert res.status == "completed"
    # op1 takes 5s because fast mode (0.5 * 10s = 5s)
    # Failure MTTF is 20s, so u1 completes at 5s before any failure
    assert res.simulated_time_ns == 5_000_000_000
    st1 = res.stations[0]
    assert st1.total_busy_time_ns == 5_000_000_000

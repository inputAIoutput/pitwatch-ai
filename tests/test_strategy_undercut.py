import pytest
from pitwatch.strategy.engine import DeterministicStrategyEngine, UndercutThreatLevel


def test_abu_dhabi_undercut_threat_vulnerability_high():
    # Abu Dhabi Yas Marina Circuit: 58 laps, 22.0s pit transit loss
    engine = DeterministicStrategyEngine(circuit_name="Abu Dhabi", total_laps=58)

    # Leader (e.g. Norris) leads Chaser (e.g. Verstappen) by 1.1s.
    # Leader on 19-lap old Mediums; Chaser pits for fresh Hards.
    # Out-lap gain is projected >= 1.2s -> Leader is under CRITICAL threat.
    assessment = engine.assess_undercut_threat(
        gap_to_chaser_seconds=1.1,
        leader_tyre_age=19,
        leader_compound="MEDIUM",
        chaser_compound="HARD",
    )

    assert assessment.threat_level == UndercutThreatLevel.CRITICAL
    assert assessment.undercut_feasible is True
    assert assessment.projected_outlap_gain >= 1.1


def test_abu_dhabi_undercut_threat_safe_large_gap():
    engine = DeterministicStrategyEngine(circuit_name="Abu Dhabi", total_laps=58)

    # Leader has 3.8s gap -> undercut not feasible on 1 lap
    assessment = engine.assess_undercut_threat(
        gap_to_chaser_seconds=3.8,
        leader_tyre_age=15,
        leader_compound="MEDIUM",
        chaser_compound="HARD",
    )

    assert assessment.threat_level == UndercutThreatLevel.LOW
    assert assessment.undercut_feasible is False


def test_abu_dhabi_pit_window_traffic_clearance():
    engine = DeterministicStrategyEngine(circuit_name="Abu Dhabi", total_laps=58)

    # Leader has 26.0s gap to 3rd place car. Pit loss is 22.0s.
    # Rejoin delta = 26.0 - 22.0 = +4.0s (rejoins ahead of 3rd place in clean air)
    clearance = engine.calculate_rejoin_clearance(gap_to_rejoin_car=26.0)
    assert clearance.rejoin_ahead is True
    assert pytest.approx(clearance.net_margin_seconds, abs=0.1) == 4.0

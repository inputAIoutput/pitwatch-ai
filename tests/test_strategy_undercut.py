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


def test_sepang_verstappen_pit_rejoin_simulation():
    # Issue #14: Sepang Grand Prix scenario with 22.5s pit transit loss
    # Leader Norris (NOR), Verstappen (VER) P2 (gap 0.8s) pits
    engine = DeterministicStrategyEngine(circuit_name="Sepang", total_laps=56)
    assert engine.pit_loss == 22.5

    running_order = [
        {"driver_number": 4, "driver_code": "NOR", "gap_to_leader": 0.0},
        {"driver_number": 1, "driver_code": "VER", "gap_to_leader": 0.8},
        {"driver_number": 16, "driver_code": "LEC", "gap_to_leader": 7.5},
        {"driver_number": 81, "driver_code": "PIA", "gap_to_leader": 15.0},
        {"driver_number": 6, "driver_code": "HAD", "gap_to_leader": 22.0},
        {"driver_number": 63, "driver_code": "RUS", "gap_to_leader": 26.5},
        {"driver_number": 44, "driver_code": "HAM", "gap_to_leader": 29.5},
        {"driver_number": 14, "driver_code": "ALO", "gap_to_leader": 35.0},
    ]

    rejoin = engine.simulate_pit_rejoin(
        driver_number=1,
        current_gap_to_leader=0.8,
        running_order=running_order,
    )

    # Projected gap: 0.8 + 22.5 = 23.3s
    assert pytest.approx(rejoin.projected_gap_to_leader, abs=0.01) == 23.3
    # 4 cars ahead (NOR 0.0, LEC 7.5, PIA 15.0, HAD 22.0) -> Rejoin in P5
    assert rejoin.projected_position == 5
    # Car immediately ahead is Hadjar (#6)
    assert rejoin.rejoin_behind_driver == 6
    assert rejoin.rejoin_behind_code == "HAD"
    assert pytest.approx(rejoin.gap_ahead, abs=0.01) == 1.3
    # Car immediately behind is Russell (#63)
    assert rejoin.rejoin_ahead_of_driver == 63
    assert rejoin.rejoin_ahead_of_code == "RUS"
    assert pytest.approx(rejoin.margin_behind, abs=0.01) == 3.2
    # 1.3s gap ahead > 1.2s threshold -> Not in dirty air traffic
    assert rejoin.in_traffic is False
    assert pytest.approx(rejoin.clean_air_window_seconds, abs=0.01) == 1.3


def test_sepang_hamilton_traffic_threat_scenario():
    # Issue #14: Hamilton P7 pits and emerges right behind a competitor within dirty air (<1.2s)
    engine = DeterministicStrategyEngine(circuit_name="Sepang", total_laps=56)

    running_order = [
        {"driver_number": 4, "driver_code": "NOR", "gap_to_leader": 0.0},
        {"driver_number": 1, "driver_code": "VER", "gap_to_leader": 0.8},
        {"driver_number": 16, "driver_code": "LEC", "gap_to_leader": 7.5},
        {"driver_number": 81, "driver_code": "PIA", "gap_to_leader": 15.0},
        {"driver_number": 6, "driver_code": "HAD", "gap_to_leader": 22.0},
        {"driver_number": 63, "driver_code": "RUS", "gap_to_leader": 26.5},
        {"driver_number": 44, "driver_code": "HAM", "gap_to_leader": 29.5},
        {"driver_number": 14, "driver_code": "ALO", "gap_to_leader": 35.0},
        {"driver_number": 12, "driver_code": "ANT", "gap_to_leader": 51.2},
        {"driver_number": 23, "driver_code": "ALB", "gap_to_leader": 53.0},
    ]

    rejoin = engine.simulate_pit_rejoin(
        driver_number=44,
        current_gap_to_leader=29.5,
        running_order=running_order,
    )

    # Projected gap: 29.5 + 22.5 = 52.0s
    assert pytest.approx(rejoin.projected_gap_to_leader, abs=0.01) == 52.0
    # Rejoin behind Antonelli (ANT, gap 51.2s). Gap ahead is 52.0 - 51.2 = 0.8s
    assert rejoin.rejoin_behind_driver == 12
    assert rejoin.rejoin_behind_code == "ANT"
    assert pytest.approx(rejoin.gap_ahead, abs=0.01) == 0.8
    # Because gap ahead 0.8s < 1.2s dirty air threshold:
    assert rejoin.in_traffic is True
    assert pytest.approx(rejoin.clean_air_window_seconds, abs=0.01) == 0.8
    # Rejoin ahead of Albon (ALB, gap 53.0s). Margin behind is 53.0 - 52.0 = 1.0s
    assert rejoin.rejoin_ahead_of_driver == 23
    assert rejoin.rejoin_ahead_of_code == "ALB"
    assert pytest.approx(rejoin.margin_behind, abs=0.01) == 1.0


def test_dominant_leader_rejoin_p1_clean_air():
    # Leader has huge gap (30.0s) and pits with 22.0s loss -> emerges in P1
    from pitwatch.strategy.engine import simulate_pit_rejoin

    running_order = [
        {"driver_number": 4, "driver_code": "NOR", "gap_to_leader": 0.0},
        {"driver_number": 1, "driver_code": "VER", "gap_to_leader": 30.0},
        {"driver_number": 16, "driver_code": "LEC", "gap_to_leader": 40.0},
    ]

    rejoin = simulate_pit_rejoin(
        driver_number=4,
        current_gap_to_leader=0.0,
        pit_transit_loss=22.0,
        running_order=running_order,
    )

    assert rejoin.projected_position == 1
    assert rejoin.rejoin_behind_driver is None
    assert rejoin.gap_ahead is None
    assert rejoin.in_traffic is False
    assert rejoin.clean_air_window_seconds >= 30.0
    assert rejoin.rejoin_ahead_of_driver == 1
    assert pytest.approx(rejoin.margin_behind, abs=0.01) == 8.0


def test_tail_end_rejoin_last():
    from pitwatch.strategy.engine import simulate_pit_rejoin

    running_order = [
        {"driver_number": 4, "driver_code": "NOR", "gap_to_leader": 0.0},
        {"driver_number": 1, "driver_code": "VER", "gap_to_leader": 10.0},
        {"driver_number": 77, "driver_code": "BOT", "gap_to_leader": 50.0},
    ]

    rejoin = simulate_pit_rejoin(
        driver_number=77,
        current_gap_to_leader=50.0,
        pit_transit_loss=22.0,
        running_order=running_order,
    )

    assert rejoin.projected_position == 3
    assert rejoin.rejoin_behind_driver == 1
    assert rejoin.rejoin_ahead_of_driver is None
    assert rejoin.margin_behind is None

import pytest
from datetime import datetime, timezone
from pitwatch.ingestion.livef1_source import LiveF1Source
from pitwatch.state.session import LiveSessionState


def test_livef1_record_transformation():
    source = LiveF1Source(session_key=11731, driver_numbers=[1, 44])
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    state.load_drivers([
        {"driver_number": 1, "name_acronym": "VER", "team_name": "Red Bull Racing"},
        {"driver_number": 44, "name_acronym": "HAM", "team_name": "Ferrari"},
    ])
    source.bind_state(state)

    # Ingest sample LiveF1 parsed batches
    records = {
        "Position.z": [
            {"SessionKey": 11731, "DriverNo": "1", "Status": "OnTrack", "X": 4200.0, "Y": -2100.0, "Z": 5.0},
            {"SessionKey": 11731, "DriverNo": "44", "Status": "OnTrack", "X": 3900.0, "Y": -2050.0, "Z": 4.5},
            {"SessionKey": 11731, "DriverNo": "63", "Status": "OnTrack", "X": 3500.0, "Y": -2000.0, "Z": 4.0}, # should be filtered out
        ],
        "CarData.z": [
            {"SessionKey": 11731, "DriverNo": "1", "speed": 315, "rpm": 11900, "n_gear": 7, "throttle": 100, "brake": 0, "drs": 1},
            {"SessionKey": 11731, "DriverNo": "44", "speed": 310, "rpm": 11750, "n_gear": 7, "throttle": 98, "brake": 0, "drs": 1},
        ],
        "WeatherData": [
            {"SessionKey": 11731, "AirTemp": "32.4", "TrackTemp": "56.8", "Humidity": "52.0", "Pressure": "1012.3", "WindSpeed": "3.1", "WindDirection": "140", "Rainfall": "0"}
        ],
        "RaceControlMessages": [
            {"SessionKey": 11731, "Utc": "2026-10-04T07:05:00Z", "Category": "Flag", "Flag": "GREEN", "Message": "TRACK CLEAR", "Scope": "Track"}
        ]
    }

    frame = source.process_records_batch(records)
    assert frame is not None
    assert len(frame.positions) == 2 # 1 and 44, 63 filtered
    assert len(frame.telemetry) == 2
    assert frame.weather is not None
    assert frame.weather.track_temperature == 56.8
    assert frame.weather.air_temperature == 32.4

    # Verify state ingestion
    assert 1 in state.drivers
    assert state.drivers[1].latest_telemetry.speed == 315
    norm_pos = state.get_normalized_position(1)
    assert norm_pos is not None
    assert -1.0 <= norm_pos["x"] <= 1.0


@pytest.mark.asyncio
async def test_livef1_stream_frames_generator():
    source = LiveF1Source(session_key=11731, driver_numbers=[1], poll_interval=0.01)
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    source.bind_state(state)

    # Queue mock records
    source.enqueue_batch({
        "Position.z": [{"SessionKey": 11731, "DriverNo": "1", "X": 100.0, "Y": 200.0}],
        "CarData.z": [{"SessionKey": 11731, "DriverNo": "1", "speed": 290, "n_gear": 6, "throttle": 95, "brake": 0, "drs": 0, "rpm": 11200}],
        "WeatherData": [{"SessionKey": 11731, "TrackTemp": "55.0", "AirTemp": "33.0", "Rainfall": "0"}],
    })

    frames = []
    async for frame in source.stream_frames():
        frames.append(frame)
        if len(frames) >= 1:
            source.stop()

    assert len(frames) == 1
    assert state.weather is not None
    assert state.weather.track_temperature == 55.0
    assert state.drivers[1].latest_telemetry.speed == 290

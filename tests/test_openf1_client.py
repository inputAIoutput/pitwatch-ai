import json
import pytest
from pathlib import Path
from pitwatch.ingestion.openf1_client import OpenF1Client


@pytest.mark.asyncio
async def test_openf1_client_disk_cache(tmp_path: Path):
    client = OpenF1Client(cache_dir=str(tmp_path))
    fake_data = [{"session_key": 9558, "circuit_short_name": "Silverstone"}]

    cache_file = tmp_path / "sessions_year-2024.json"
    cache_file.write_text(json.dumps(fake_data), encoding="utf-8")

    result = await client.get_sessions(year=2024)
    assert len(result) == 1
    assert result[0]["circuit_short_name"] == "Silverstone"


@pytest.mark.asyncio
async def test_openf1_team_radio_endpoint(tmp_path: Path):
    client = OpenF1Client(cache_dir=str(tmp_path))
    fake_radio = [
        {
            "session_key": 9558,
            "driver_number": 44,
            "date": "2024-07-07T14:24:12.000+00:00",
            "recording_url": "https://livetiming.formula1.com/static/2024/9558/teamradio/HAM.mp3",
        }
    ]
    cache_file = tmp_path / "team_radio_session_key-9558.json"
    cache_file.write_text(json.dumps(fake_radio), encoding="utf-8")

    result = await client.get_team_radio(session_key=9558)
    assert len(result) == 1
    assert result[0]["driver_number"] == 44
    assert result[0]["recording_url"].endswith(".mp3")


@pytest.mark.asyncio
async def test_openf1_laps_endpoint(tmp_path: Path):
    client = OpenF1Client(cache_dir=str(tmp_path))
    fake_laps = [
        {
            "session_key": 9558,
            "driver_number": 44,
            "lap_number": 1,
            "date_start": "2024-07-07T14:03:12.540000+00:00",
            "lap_duration": 96.402,
        }
    ]
    cache_file = tmp_path / "laps_driver_number-44_session_key-9558.json"
    cache_file.write_text(json.dumps(fake_laps), encoding="utf-8")

    result = await client.get_laps(session_key=9558, driver_number=44)
    assert len(result) == 1
    assert result[0]["lap_number"] == 1
    assert result[0]["lap_duration"] == 96.402


@pytest.mark.asyncio
async def test_openf1_stints_endpoint(tmp_path: Path):
    client = OpenF1Client(cache_dir=str(tmp_path))
    fake_stints = [
        {
            "session_key": 9558,
            "driver_number": 44,
            "stint_number": 1,
            "lap_start": 1,
            "lap_end": 27,
            "compound": "MEDIUM",
            "tyre_age_at_start": 0,
        }
    ]
    cache_file = tmp_path / "stints_session_key-9558.json"
    cache_file.write_text(json.dumps(fake_stints), encoding="utf-8")

    result = await client.get_stints(session_key=9558)
    assert len(result) == 1
    assert result[0]["driver_number"] == 44
    assert result[0]["compound"] == "MEDIUM"


@pytest.mark.asyncio
async def test_openf1_positions_endpoint(tmp_path: Path):
    client = OpenF1Client(cache_dir=str(tmp_path))
    fake_positions = [
        {
            "session_key": 9558,
            "driver_number": 4,
            "date": "2024-07-07T14:03:31.000+00:00",
            "position": 4,
        }
    ]
    cache_file = tmp_path / "position_session_key-9558.json"
    cache_file.write_text(json.dumps(fake_positions), encoding="utf-8")

    result = await client.get_positions(session_key=9558)
    assert len(result) == 1
    assert result[0]["driver_number"] == 4
    assert result[0]["position"] == 4


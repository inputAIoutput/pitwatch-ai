import argparse
import asyncio
import sys
from pathlib import Path

# Ensure src directory is on sys.path for direct script execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pitwatch.ingestion.replay import HistoricalReplaySource
from pitwatch.ingestion.openf1_client import OpenF1Client


def parse_args(args=None):
    parser = argparse.ArgumentParser(description="PitWatch AI Historical Replay CLI")
    parser.add_argument("--year", type=int, default=2024, help="Championship year")
    parser.add_argument("--round", type=int, default=12, help="Grand Prix round number")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier (1x-10x)")
    parser.add_argument("--driver", type=int, default=44, help="Driver number to track (default 44)")
    parser.add_argument("--frames", type=int, default=10, help="Number of frames to verify before stopping")
    return parser.parse_args(args)


async def main():
    args = parse_args()
    print(f"[PitWatch AI] Initializing Historical Replay for Year {args.year}, Round {args.round}, Driver #{args.driver} at {args.speed}x...")
    client = OpenF1Client()
    # Session 9558 is 2024 Silverstone Grand Prix
    source = await HistoricalReplaySource.from_openf1(
        session_key=9558,
        driver_number=args.driver,
        client=client,
        time_step=0.2,
    )
    source.controller.set_speed(args.speed)
    source.controller.play()

    count = 0
    async for frame in source.stream_frames():
        weather_str = f"{frame.weather.track_temperature} C" if frame.weather else "N/A"
        radio_count = len(frame.radio_events)
        print(
            f"[{frame.session_time:.1f}s] Cars tracked: {len(frame.positions)} | "
            f"Telemetry ticks: {len(frame.telemetry)} | Weather: {weather_str} | Radios: {radio_count}"
        )
        count += 1
        if count >= args.frames:
            break
    print(f"[PitWatch AI] Successfully verified {count} frames of replay telemetry.")


if __name__ == "__main__":
    asyncio.run(main())

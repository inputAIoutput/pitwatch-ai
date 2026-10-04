import argparse
import asyncio
import sys
from pathlib import Path
import uvicorn

# Ensure src directory is on sys.path for direct script execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pitwatch.api.app import create_app
from pitwatch.ingestion.replay import HistoricalReplaySource
from pitwatch.ingestion.live import LiveOpenF1Source
from pitwatch.ingestion.livef1_source import LiveF1Source
from pitwatch.ingestion.openf1_client import OpenF1Client
from pitwatch.state.driver import F1_2026_GRID
from pitwatch.state.session import LiveSessionState


def parse_driver_arg(val: str):
    if "," in str(val):
        return str(val)
    try:
        return int(val)
    except ValueError:
        return val


def parse_args(args=None):
    parser = argparse.ArgumentParser(description="PitWatch AI Historical Replay CLI")
    parser.add_argument("--year", type=int, default=2026, help="Championship year")
    parser.add_argument("--round", type=int, default=12, help="Grand Prix round number")
    parser.add_argument("--session", type=int, default=None, help="OpenF1 session key (e.g. 9662 for Abu Dhabi, 9558 for Silverstone, 11731 for Sepang)")
    parser.add_argument("--race", type=str, default=None, help="Grand Prix / circuit name alias (e.g. 'abu dhabi', 'silverstone', 'sepang')")
    parser.add_argument("--live", action="store_true", help="Stream from live race session instead of historical replay")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier (1x-10x)")
    parser.add_argument("--driver", type=parse_driver_arg, default=44, help="Driver number or comma-separated list of drivers (default 44)")
    parser.add_argument("--drivers", type=str, default=None, help="Comma-separated list of driver numbers (e.g. '44,1')")
    parser.add_argument("--frames", type=int, default=10, help="Number of frames to verify before stopping")
    parser.add_argument("--lap", type=int, default=1, help="Lap number to start replay from (default 1 for race start, 0 for pre-race garage)")
    parser.add_argument("--serve", action="store_true", help="Launch FastAPI REST & WebSocket server alongside replay")
    parser.add_argument("--source", type=str, choices=["openf1", "livef1", "livetiming", "f1tv"], default="openf1", help="Ingestion engine backend: 'openf1' (REST), 'livef1' (SignalR), or 'livetiming'/'f1tv' (F1 TV archives)")
    parser.add_argument("--token", type=str, default=None, help="OpenF1 OAuth2 / Bearer access token for live session streaming")
    parser.add_argument("--f1-cookie", type=str, default=None, help="Formula 1 TV authenticated session cookie for LiveF1 SignalR stream")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="API server host")
    parser.add_argument("--port", type=int, default=8000, help="API server port")
    return parser.parse_args(args)


async def run_server(app, host: str, port: int):
    config = uvicorn.Config(app=app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    args = parse_args()
    client = OpenF1Client(api_token=args.token)

    session_key = 11731 if args.live else 9558
    circuit_name = "Kuala Lumpur" if args.live else "Silverstone"

    if args.session is not None:
        session_key = args.session
        if session_key == 9662:
            circuit_name = "Yas Marina Circuit"
        elif session_key in (11730, 11731):
            circuit_name = "Kuala Lumpur"
        elif session_key == 9558:
            circuit_name = "Silverstone"
        elif session_key == 9538:
            circuit_name = "Circuit de Monaco"
        elif session_key == 9598:
            circuit_name = "Autodromo Nazionale Monza"
        else:
            circuit_name = f"Session {session_key}"
    elif args.race is not None:
        clean_race = args.race.lower().strip()
        if "abu" in clean_race or "yas" in clean_race:
            session_key = 9662
            circuit_name = "Yas Marina Circuit"
        elif "sepang" in clean_race or "kuala" in clean_race or "malaysia" in clean_race:
            session_key = 11731
            circuit_name = "Kuala Lumpur"
        elif "silverstone" in clean_race:
            session_key = 9558
            circuit_name = "Silverstone"
        elif "monaco" in clean_race:
            session_key = 9538
            circuit_name = "Circuit de Monaco"
        elif "monza" in clean_race:
            session_key = 9598
            circuit_name = "Autodromo Nazionale Monza"
    elif args.round == 24:
        session_key = 9662
        circuit_name = "Yas Marina Circuit"

    # Parse target drivers list upfront
    raw_drivers = str(args.drivers if args.drivers is not None else args.driver)
    if raw_drivers.strip().lower() in ("all", "grid", "none"):
        target_drivers = None
    elif "," in raw_drivers:
        target_drivers = [int(d.strip()) for d in raw_drivers.split(",") if d.strip().isdigit()]
    elif raw_drivers.strip().isdigit():
        target_drivers = [int(raw_drivers.strip())]
    else:
        target_drivers = None if args.live else [44]

    state = LiveSessionState(session_key=session_key, circuit_name=circuit_name, year=args.year)
    start_lap = args.lap if args.lap > 0 else None

    # Pre-populate driver metadata, tyre stints, and laps
    try:
        drivers_raw = await client.get_drivers(session_key=session_key)
        state.load_drivers(drivers_raw, active_driver_numbers=target_drivers)
        stints_raw = await client.get_stints(session_key=session_key)
        state.load_stints(stints_raw)
        try:
            positions_raw = await client.get_positions(session_key=session_key)
            state.load_positions(positions_raw)
        except Exception:
            pass
        for drv_id in target_drivers:
            try:
                laps_raw = await client.get_laps(session_key=session_key, driver_number=drv_id)
                state.load_laps(laps_raw)
            except Exception:
                pass
    except Exception as e:
        print(f"[PitWatch AI] Info: OpenF1 pre-population skipped ({e}). Using 2026 grid metadata.")
        GRID_2026 = [
            {
                "driver_number": num,
                "name_acronym": d["code"],
                "team_name": d["team"],
                "team_colour": d["colour"],
            }
            for num, d in F1_2026_GRID.items()
        ]
        state.load_drivers(GRID_2026, active_driver_numbers=target_drivers)

    driver_str = "All Drivers" if target_drivers is None else ", ".join(f"#{d}" for d in target_drivers)

    if args.live:
        if args.source == "livef1":
            print(f"[PitWatch AI] Initializing LiveF1 SignalR Ingestion for Session {session_key} ({circuit_name}), Driver(s) {driver_str}...")
            source = LiveF1Source(
                session_key=session_key,
                driver_numbers=target_drivers,
                token=args.token,
                f1_cookie=args.f1_cookie,
                poll_interval=0.2,
            )
            source.bind_state(state)
        else:
            print(f"[PitWatch AI] Initializing Live OpenF1 Polling for Session {session_key} ({circuit_name}), Driver(s) {driver_str} (400ms cadence)...")
            source = LiveOpenF1Source(
                session_key=session_key,
                driver_numbers=target_drivers,
                client=client,
                poll_interval_seconds=0.4,
            )
            source.bind_state(state)
    else:
        lap_msg = f"Lap #{args.lap}" if args.lap > 0 else "Pre-Race"
        print(f"[PitWatch AI] Initializing Historical Replay for Session {session_key} ({circuit_name}), Year {args.year}, Driver(s) {driver_str} starting at {lap_msg} ({args.speed}x)...")

        if args.source in ("livetiming", "f1tv"):
            max_f = None if args.serve else (args.frames if args.frames > 0 else None)
            source = await HistoricalReplaySource.from_livetiming(
                session_key=session_key,
                driver_number=target_drivers,
                time_step=0.2,
                max_frames=max_f,
            )
        else:
            source = await HistoricalReplaySource.from_openf1(
                session_key=session_key,
                driver_number=target_drivers,
                client=client,
                time_step=0.2,
                start_lap=start_lap,
            )
        source.bind_state(state)
        source.controller.set_speed(args.speed)
        source.controller.play()

    if args.serve:
        app = create_app(session_state=state)

        async def stream_background():
            async for _ in source.stream_frames():
                pass

        # Run background replay and uvicorn concurrently
        print(f"[PitWatch AI] Starting FastAPI Server on http://{args.host}:{args.port}...")
        replay_task = asyncio.create_task(stream_background())
        try:
            await run_server(app, args.host, args.port)
        finally:
            if hasattr(source, "stop"):
                source.stop()
            replay_task.cancel()
            try:
                await replay_task
            except asyncio.CancelledError:
                pass
    else:
        count = 0
        async for frame in source.stream_frames():
            weather_str = f"{frame.weather.track_temperature} C" if frame.weather else "N/A"
            pos_strs = []
            drivers_to_show = target_drivers if target_drivers else list(state.drivers.keys())[:3]
            for d in drivers_to_show:
                norm_pos = state.get_normalized_position(d)
                if norm_pos:
                    pos_strs.append(f"#{d}: ({norm_pos['x']:.2f}, {norm_pos['y']:.2f}) prog={norm_pos['progress']:.2f}")
            coord_str = " | ".join(pos_strs) if pos_strs else "norm=N/A"
            print(
                f"[{frame.session_time:.1f}s] {coord_str} | "
                f"Telemetry: {len(frame.telemetry)} ticks | Weather: {weather_str}"
            )
            count += 1
            if count >= args.frames:
                break
        print(f"[PitWatch AI] Successfully verified {count} frames with normalized coordinates.")


if __name__ == "__main__":
    asyncio.run(main())

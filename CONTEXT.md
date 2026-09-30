# pitwatch-ai

Real-time multimodal ingestion and intelligence API for Formula 1 racing telemetry, audio communications, weather, and tactical prediction.

## Language

**Live Session State**:
An in-memory, ring-buffered representation of the active session's telemetry, car track coordinates, weather metrics, and transcribed radio feeds.
_Avoid_: Database cache, session store, telemetry snapshot

**State Synchronization Engine**:
The asynchronous background ingestion worker that continuously polls and streams from upstream Formula 1 data providers to update the Live Session State.
_Avoid_: Proxy worker, polling loop, data scraper

**Tactical Context**:
The real-time operational state (gap intervals, lap index, tyre compound and age, weather metrics) attached to a radio transcription prior to inference.
_Avoid_: Prompt context, prompt payload, metadata block

**Tactical Intent**:
The structured machine-readable evaluation emitted by the AI Provider containing strategic classifications, coded message deciphering, and tactical predictions.
_Avoid_: LLM output, intent response, model prediction

**AI Provider**:
The pluggable inference abstraction layer that decouples prompting logic from the model backend (OpenRouter API or local inference engines).
_Avoid_: LLM client, model caller, wrapper

**Track Coordinate Frame**:
The normalized 2D Cartesian coordinate system calibrated to the circuit baseline, projecting car positions for visual map clients.
_Avoid_: GPS coordinates, raw telemetry points, track map dots

**Lap Progress Metric**:
The continuous scalar value (0.0 to 1.0) representing a vehicle's exact distance progression around the active lap.
_Avoid_: Lap percentage, lap distance, track fraction

**Strategic Prediction Horizon**:
The rolling forecast interval (1–5 laps ahead) predicting pit stop windows, undercut threats, and overtake likelihoods.
_Avoid_: Next laps, future prediction, AI guess

**Threat Window**:
The calculated time delta between competitors relative to pit lane transit loss, defining undercut vulnerability and track re-entry position.
_Avoid_: Gap calculation, pit gap, overtake time

**Degradation Curve**:
The mathematical progression of lap-time drop-off modeled as a function of tyre compound, stint age, and track temperature.
_Avoid_: Tyre wear line, tyre degradation chart, rubber loss

**Historical Archive Interface**:
The unified retrieval layer combining Jolpica-F1 championship records and FastF1 lap telemetry archives.
_Avoid_: History API, Ergast proxy, database search

**Telemetry Cache Store**:
The managed local filesystem cache persisting serialized FastF1 session data and telemetry curves to eliminate redundant upstream fetches.
_Avoid_: Local database, temp directory, raw file dump

**Environmental Evaluator**:
The operational component monitoring air/track temperatures, wind vectors, and rainfall indicators to compute thermal drift rates ($dT/dt$).
_Avoid_: Weather service, meteorology module, weather widget

**Crossover Threshold**:
The calculated lap-time condition where wet or intermediate tyres match or surpass slick compounds due to rainfall accumulation or track drying.
_Avoid_: Rain point, pit point, weather change

**Positional Stream**:
The high-frequency WebSocket channel (`/v1/stream/positions`) broadcasting 2D Cartesian vehicle coordinates and lap progress metrics at 2–5Hz.
_Avoid_: Coordinate socket, GPS channel, car websocket

**Intent Stream**:
The event-driven WebSocket channel (`/v1/stream/intents`) emitting transcribed driver radio messages, tactical intent classifications, and strategic predictions.
_Avoid_: Event bus, alert socket, radio stream







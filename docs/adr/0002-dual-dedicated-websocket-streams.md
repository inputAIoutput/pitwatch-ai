# 0002. Dual Dedicated WebSocket Streams

We decided to partition real-time streaming into two distinct WebSocket endpoints: `/v1/stream/positions` for high-frequency (2–5Hz) normalized 2D track coordinates, and `/v1/stream/intents` for event-driven radio transcriptions and tactical predictions. This isolates high-volume positional telemetry from high-priority strategic alerts, preventing message queue starvation on the client.

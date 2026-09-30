# PitWatch AI 🏎️🎙️

**Edge-first multimodal radio and competitor intent intelligence engine for Formula 1.**

PitWatch AI aggregates, processes, and correlates real-time Formula 1 communications and telemetry to surface strategic maneuvers, competitor tactics, and radio intent before they appear on standard timing screens.

---

## 🎯 Architecture Overview

PitWatch AI acts as an unified ingestion and intelligence API integrating:
- **[OpenF1](https://openf1.org/):** Live telemetry, lap intervals, sector times, and team radio feeds over WebSockets and REST.
- **[Jolpica-F1 (Ergast successor)](https://github.com/jolpica/jolpica-f1):** Historical race data, driver standings, results, and season records.
- **[FastF1](https://github.com/theOehrly/Fast-F1):** High-precision car telemetry (speed, throttle, brake, gear, DRS) and micro-sector delta calculations.
- **F1 TV / Live Feeds (BYOK):** Real-time onboard audio and stream synchronization with Bring-Your-Own-Key client-side authentication.

```
                  ┌──────────────────────────────────────────────┐
                  │            DUAL INGESTION LAYER              │
                  │  - Public: OpenF1 WebSocket / F1TV Stream    │
                  │  - Telemetry: FastF1 & Jolpica-F1 Endpoints  │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │          ACOUSTIC PRE-PROCESSING            │
                  │  - Noise Suppression: DeepFilterNet          │
                  │  - Voice Activity Detection (VAD): Silero    │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │          LOW-LATENCY INFERENCE CORE          │
                  │  - Speech-to-Text: Faster-Whisper with F1    │
                  │    terminology and callsign prompt mapping   │
                  │  - Intent Extraction: Quantized SLM          │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │     TELEMETRY & STRATEGY CORRELATION         │
                  │  - Micro-sector pace cross-validation        │
                  │  - Competitor bluff & threat matrix          │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │          DEVELOPER API & STREAMING           │
                  │  - WebSocket: /v1/stream/intents             │
                  │  - REST: /v1/telemetry /v1/radio /v1/archive │
                  └──────────────────────────────────────────────┘
```

---

## 🚀 Key Capabilities

- **Sub-Second Radio Transcription:** Strips engine whine and wind noise via DeepFilterNet, drops inactive silence via Silero VAD, and transcribes onboard team communications using Faster-Whisper.
- **Tactical Intent Extraction:** Classifies coded instructions (*"Box opposite 44"*, *"Scenario 7"*, *"Plan C+5"*, *"Tyres are gone"*) into structured tactical events.
- **Delta Cross-Validation:** Validates driver claims against live telemetry (microsector losses, throttle traces) to calculate bluff probability.
- **Unified F1 API:** Single endpoint interface uniting historical data (Jolpica), real-time timing (OpenF1), and deep telemetry (FastF1).

---

## 📡 API Interface Preview

### WebSocket: `/v1/stream/intents`
Emits real-time classified radio events and strategic evaluations:
```json
{
  "timestamp": "2026-06-28T14:24:12.182Z",
  "session_time": 3241.4,
  "driver": "NOR",
  "car_number": 4,
  "lap": 24,
  "raw_transcript": "Left front is crying, mate. Box opposite 44.",
  "intent_category": "TYRE_DEGRADATION_AND_BOX_CALL",
  "confidence": 0.96,
  "coded_elements": {
    "tyre_state": "CRITICAL_GRAINING",
    "tactical_instruction": "BOX_OPPOSITE_CAR_44"
  },
  "telemetry_verification": {
    "microsector_delta_loss": "+0.142s in Turn 9",
    "bluff_probability": 0.04
  }
}
```

---

## 🛡️ Fair Use & BYOK Model

PitWatch AI adheres to a strict client-side **Bring-Your-Own-Key (BYOK)** model. The open-source engine never hosts, resells, or stores proprietary F1TV broadcast media. It operates as a local processing pipeline on public open APIs and authenticated user feeds for fair-use analytical and educational research.

---

## 🛠️ Getting Started

### Prerequisites
- Python 3.11+
- FFmpeg (for audio stream processing)
- (Optional) NVIDIA GPU with CUDA for local Whisper acceleration

### Installation
```bash
git clone https://github.com/inputAIoutput/pitwatch-ai.git
cd pitwatch-ai
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 📜 License

Licensed under the GNU Affero General Public License v3.0 ([AGPL-3.0](LICENSE)).

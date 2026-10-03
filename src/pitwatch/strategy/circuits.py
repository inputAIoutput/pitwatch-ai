from typing import Dict

CIRCUIT_PIT_LOSSES: Dict[str, float] = {
    "Abu Dhabi": 22.0,
    "Yas Marina": 22.0,
    "Silverstone": 21.5,
    "Monaco": 19.5,
    "Monza": 24.0,
    "Spa-Francorchamps": 22.0,
    "Bahrain": 23.0,
    "Red Bull Ring": 20.0,
    "Suzuka": 22.5,
    "Interlagos": 21.0,
    "Zandvoort": 20.5,
    "Hungaroring": 21.0,
    "Marina Bay": 28.0,
    "Yas Marina Circuit": 22.0,
}

DEFAULT_PIT_TRANSIT_LOSS: float = 22.0


def get_circuit_pit_loss(circuit_name: str) -> float:
    """Returns pit lane time loss delta in seconds for the specified circuit."""
    name = circuit_name.strip()
    for k, v in CIRCUIT_PIT_LOSSES.items():
        if k.lower() in name.lower() or name.lower() in k.lower():
            return v
    return DEFAULT_PIT_TRANSIT_LOSS

from typing import Dict

CIRCUIT_PIT_LOSSES: Dict[str, float] = {
    # 2024-2026 FIA Formula 1 World Championship Calendar & Heritage Tracks
    "Bahrain": 23.0,
    "Sakhir": 23.0,
    "Bahrain International Circuit": 23.0,
    "Jeddah": 20.0,
    "Jeddah Corniche": 20.0,
    "Jeddah Corniche Circuit": 20.0,
    "Saudi Arabia": 20.0,
    "Melbourne": 20.0,
    "Albert Park": 20.0,
    "Albert Park Circuit": 20.0,
    "Australia": 20.0,
    "Suzuka": 22.5,
    "Suzuka Circuit": 22.5,
    "Japan": 22.5,
    "Shanghai": 23.0,
    "Shanghai International Circuit": 23.0,
    "China": 23.0,
    "Miami": 20.0,
    "Miami International Autodrome": 20.0,
    "Imola": 29.0,
    "Autodromo Enzo e Dino Ferrari": 29.0,
    "Emilia Romagna": 29.0,
    "Monaco": 19.5,
    "Circuit de Monaco": 19.5,
    "Monte Carlo": 19.5,
    "Montreal": 18.5,
    "Circuit Gilles Villeneuve": 18.5,
    "Canada": 18.5,
    "Barcelona": 22.0,
    "Catalunya": 22.0,
    "Circuit de Barcelona-Catalunya": 22.0,
    "Spain": 22.0,
    "Red Bull Ring": 20.0,
    "Spielberg": 20.0,
    "Austria": 20.0,
    "Silverstone": 21.5,
    "Silverstone Circuit": 21.5,
    "Great Britain": 21.5,
    "Hungaroring": 21.0,
    "Budapest": 21.0,
    "Hungary": 21.0,
    "Spa": 22.0,
    "Spa-Francorchamps": 22.0,
    "Circuit de Spa-Francorchamps": 22.0,
    "Belgium": 22.0,
    "Zandvoort": 20.5,
    "Circuit Zandvoort": 20.5,
    "Netherlands": 20.5,
    "Monza": 24.0,
    "Autodromo Nazionale Monza": 24.0,
    "Italy": 24.0,
    "Baku": 21.0,
    "Baku City Circuit": 21.0,
    "Azerbaijan": 21.0,
    "Marina Bay": 28.0,
    "Marina Bay Street Circuit": 28.0,
    "Singapore": 28.0,
    "Austin": 21.0,
    "COTA": 21.0,
    "Circuit of the Americas": 21.0,
    "United States": 21.0,
    "Mexico City": 22.0,
    "Autodromo Hermanos Rodriguez": 22.0,
    "Mexico": 22.0,
    "Interlagos": 21.0,
    "Autodromo Jose Carlos Pace": 21.0,
    "Sao Paulo": 21.0,
    "Brazil": 21.0,
    "Las Vegas": 20.5,
    "Las Vegas Strip Circuit": 20.5,
    "Lusail": 22.5,
    "Lusail International Circuit": 22.5,
    "Losail": 22.5,
    "Qatar": 22.5,
    "Yas Marina": 22.0,
    "Yas Marina Circuit": 22.0,
    "Abu Dhabi": 22.0,
    # Sepang (Malaysia)
    "Sepang": 22.5,
    "Sepang International Circuit": 22.5,
    "Kuala Lumpur": 22.5,
    "Malaysia": 22.5,
}

DEFAULT_PIT_TRANSIT_LOSS: float = 22.0


def get_circuit_pit_loss(circuit_name: str) -> float:
    """Returns pit lane time loss delta in seconds for the specified circuit.
    
    Matches against known calendar tracks with aliases, falling back to
    DEFAULT_PIT_TRANSIT_LOSS (22.0s) if unrecognised.
    """
    if not circuit_name:
        return DEFAULT_PIT_TRANSIT_LOSS

    name_clean = circuit_name.strip().lower()

    # Exact matches first
    for k, v in CIRCUIT_PIT_LOSSES.items():
        if k.lower() == name_clean:
            return v

    # Substring search, sorting keys by length descending to match specific names first
    for k in sorted(CIRCUIT_PIT_LOSSES.keys(), key=len, reverse=True):
        k_lower = k.lower()
        if k_lower in name_clean or name_clean in k_lower:
            return CIRCUIT_PIT_LOSSES[k]

    return DEFAULT_PIT_TRANSIT_LOSS

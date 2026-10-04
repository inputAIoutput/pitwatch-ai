import math
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel


class CircuitBounds(BaseModel):
    min_x: float
    max_x: float
    min_y: float
    max_y: float


# Calibrated coordinate bounds for popular Formula 1 circuits
CIRCUIT_PRESETS: Dict[str, CircuitBounds] = {
    "silverstone": CircuitBounds(min_x=-3500.0, max_x=3500.0, min_y=-2500.0, max_y=2500.0),
    "monza": CircuitBounds(min_x=-4500.0, max_x=4500.0, min_y=-2000.0, max_y=2000.0),
    "monaco": CircuitBounds(min_x=-1500.0, max_x=1500.0, min_y=-1500.0, max_y=1500.0),
    "spa": CircuitBounds(min_x=-5000.0, max_x=5000.0, min_y=-4000.0, max_y=4000.0),
    "yas marina": CircuitBounds(min_x=-4000.0, max_x=4000.0, min_y=-3000.0, max_y=3000.0),
    "abu dhabi": CircuitBounds(min_x=-4000.0, max_x=4000.0, min_y=-3000.0, max_y=3000.0),
    "kuala lumpur": CircuitBounds(min_x=-5500.0, max_x=6800.0, min_y=-6000.0, max_y=4200.0),
    "sepang": CircuitBounds(min_x=-5500.0, max_x=6800.0, min_y=-6000.0, max_y=4200.0),
}


class TrackCenterline:
    """Precomputed 2D circuit centerline loop with segment lengths and cumulative arc distances."""

    def __init__(
        self,
        waypoints: List[Tuple[float, float]],
        sector_splits: Optional[Tuple[float, float]] = (0.33, 0.66),
    ):
        if len(waypoints) < 3:
            raise ValueError("Track centerline requires at least 3 waypoints to form a loop.")

        self.waypoints: List[Tuple[float, float]] = waypoints
        self.sector_splits: Tuple[float, float] = sector_splits or (0.33, 0.66)

        # Precompute segment geometry
        n = len(waypoints)
        self.segments_dx: List[float] = []
        self.segments_dy: List[float] = []
        self.segments_len_sq: List[float] = []
        self.segments_len: List[float] = []
        self.cumulative_dist: List[float] = [0.0]

        total = 0.0
        for i in range(n):
            p1 = waypoints[i]
            p2 = waypoints[(i + 1) % n]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length_sq = dx * dx + dy * dy
            length = math.sqrt(length_sq)

            self.segments_dx.append(dx)
            self.segments_dy.append(dy)
            self.segments_len_sq.append(length_sq if length_sq > 0.0 else 1e-6)
            self.segments_len.append(length)

            total += length
            if i < n - 1:
                self.cumulative_dist.append(total)

        self.total_length: float = total if total > 0.0 else 1.0

    def project_point(self, x: float, y: float, sector: Optional[int] = None) -> float:
        """Projects (x, y) onto the closest track segment and returns lap progress in [0.0, 1.0]."""
        n = len(self.waypoints)

        # Determine segment search range based on sector anchoring if provided
        start_idx = 0
        end_idx = n
        if sector == 1:
            end_idx = int(n * (self.sector_splits[0] + 0.10)) + 1
        elif sector == 2:
            start_idx = max(0, int(n * (self.sector_splits[0] - 0.10)))
            end_idx = min(n, int(n * (self.sector_splits[1] + 0.10)) + 1)
        elif sector == 3:
            start_idx = max(0, int(n * (self.sector_splits[1] - 0.10)))

        best_dist_sq = float("inf")
        best_arc_dist = 0.0

        for i in range(start_idx, end_idx):
            ax, ay = self.waypoints[i]
            dx = self.segments_dx[i]
            dy = self.segments_dy[i]
            len_sq = self.segments_len_sq[i]

            # Parametric projection t
            ux = x - ax
            uy = y - ay
            t = (ux * dx + uy * dy) / len_sq
            t_clamped = max(0.0, min(1.0, t))

            # Nearest point on segment
            proj_x = ax + t_clamped * dx
            proj_y = ay + t_clamped * dy

            dist_sq = (x - proj_x) ** 2 + (y - proj_y) ** 2
            # Prefer earlier segments on tie (especially segment 0 over segment N-1 at start/finish)
            if dist_sq < best_dist_sq - 1e-5:
                best_dist_sq = dist_sq
                seg_arc = self.cumulative_dist[i] + t_clamped * self.segments_len[i]
                best_arc_dist = seg_arc

        progress = best_arc_dist / self.total_length
        if progress >= 0.999:
            w0 = self.waypoints[0]
            d0_sq = (x - w0[0]) ** 2 + (y - w0[1]) ** 2
            if d0_sq < 100.0:
                progress = 0.0
        return max(0.0, min(1.0, progress))


# Calibrated 2D Track Centerline Waypoints (ordered loop from Start/Finish through S1 -> S2 -> S3 -> S/F)
CIRCUIT_WAYPOINTS: Dict[str, List[Tuple[float, float]]] = {
    # Sepang International Circuit (Kuala Lumpur): 5.543 km, 15 turns
    # Main Straight -> T1/T2 Hairpin -> T3 -> T4 -> T5/T6 Sweeper -> T7/T8 -> T9 -> T10 -> T11 -> T12/T13 -> T14 -> Back Straight -> T15
    "sepang": [
        (0.0, -5200.0),       # Start / Finish line (progress ~ 0.0)
        (-1500.0, -5000.0),   # Main straight acceleration
        (-3500.0, -4900.0),   # Approaching Turn 1 braking zone
        (-4800.0, -4800.0),   # Turn 1 apex (tight downhill right hairpin)
        (-4500.0, -4200.0),   # Turn 2 apex (tight uphill left)
        (-3800.0, -3200.0),   # Turn 3 acceleration curve
        (-2500.0, -2000.0),   # Run down to Turn 4
        (-1400.0, -1100.0),   # Turn 4 apex (90-degree left hander)
        (-1800.0, -100.0),    # Acceleration out of Turn 4 (Sector 1 transition)
        (-2500.0, 1000.0),    # Turn 5 entry (fast sweeping left)
        (-2200.0, 2000.0),    # Turn 6 apex (high G right flick)
        (-1200.0, 2800.0),    # Short chute between Turns 6 and 7
        (-200.0, 3500.0),     # Turn 7 apex (medium speed right)
        (1000.0, 3400.0),     # Turn 8 apex (medium speed right)
        (2200.0, 2800.0),     # Descent towards Turn 9
        (3200.0, 1800.0),     # Turn 9 apex (steep uphill slow left hairpin)
        (3800.0, 1200.0),     # Acceleration out of Turn 9 (Sector 2 transition)
        (4400.0, 500.0),      # Turn 10 apex (fast downhill right)
        (5200.0, -600.0),     # Run down to Turn 11
        (5800.0, -1500.0),    # Turn 11 apex (fast off-camber right)
        (6200.0, -2500.0),    # Turn 12 fast sweeping left
        (5800.0, -3400.0),    # Turn 13 apex
        (5200.0, -4200.0),    # Turn 14 entry (tight right onto back straight)
        (4600.0, -4700.0),    # Turn 14 exit (Sector 3 transition)
        (3200.0, -5000.0),    # Back Straight (parallel to pit straight)
        (1500.0, -5300.0),    # Back Straight DRS zone
        (-800.0, -5600.0),    # Back Straight braking zone for final turn
        (-3800.0, -5800.0),   # Turn 15 entry (heavy braking hairpin)
        (-4600.0, -5600.0),   # Turn 15 apex (tight left hairpin onto main straight)
        (-2500.0, -5350.0),   # Exit of Turn 15 accelerating towards S/F line
    ],
    # Silverstone: 5.891 km, 18 turns
    # Hamilton Straight -> Abbey/Farm -> Village/Loop -> Wellington Straight -> Brooklands/Luffield -> Copse -> Maggotts/Becketts/Chapel -> Hangar Straight -> Stowe -> Vale/Club
    "silverstone": [
        (-1200.0, -1800.0),   # Hamilton Straight (Start / Finish)
        (-400.0, -2200.0),    # Abbey (Turn 1)
        (500.0, -2100.0),     # Farm Curve (Turn 2)
        (1300.0, -1600.0),    # Village (Turn 3)
        (1100.0, -900.0),     # The Loop (Turn 4 hairpin)
        (1500.0, -300.0),     # Aintree (Turn 5)
        (1800.0, 400.0),      # Wellington Straight (Sector 1 exit)
        (2100.0, 1500.0),     # Approaching Brooklands
        (1800.0, 2200.0),     # Brooklands (Turn 6)
        (1000.0, 2300.0),     # Luffield (Turn 7 long right)
        (200.0, 2100.0),      # Woodcote (Turn 8)
        (-600.0, 1900.0),     # National Pit Straight
        (-1600.0, 1600.0),    # Copse (Turn 9 high-speed right)
        (-2400.0, 1200.0),    # Maggotts (Turn 10)
        (-3000.0, 600.0),     # Becketts (Turns 11-12)
        (-2800.0, -100.0),    # Chapel (Turn 13 exit onto Hangar Straight, S2 exit)
        (-2600.0, -800.0),    # Hangar Straight
        (-2300.0, -1600.0),   # Hangar Straight DRS
        (-2100.0, -2200.0),   # Stowe (Turn 15)
        (-1800.0, -2400.0),   # Vale (Turn 16 chicane)
        (-1500.0, -2000.0),   # Club (Turn 17-18 onto Hamilton Straight)
    ],
    # Autodromo Nazionale Monza: 5.793 km, 11 turns
    # Rettifilo Tribune -> Prima Variante -> Curva Grande -> Variante della Roggia -> Lesmo 1 & 2 -> Serraglio -> Ascari -> Rettifilo Posteriore -> Parabolica
    "monza": [
        (-3000.0, -1200.0),   # Start / Finish line
        (-1200.0, -1200.0),   # Main Straight full throttle
        (500.0, -1200.0),     # Heavy braking zone for Variante del Rettifilo
        (1000.0, -1050.0),    # Turn 1-2 chicane
        (1800.0, -600.0),     # Exit into Curva Grande (Turn 3)
        (2600.0, 200.0),      # Sweeping Curva Grande
        (3200.0, 1100.0),     # Run to Variante della Roggia (Sector 1 exit)
        (3100.0, 1600.0),     # Variante della Roggia (Turns 4-5 chicane)
        (2500.0, 1800.0),     # Curva di Lesmo 1 (Turn 6)
        (1800.0, 1800.0),     # Chute to Lesmo 2
        (1200.0, 1700.0),     # Curva di Lesmo 2 (Turn 7)
        (200.0, 1500.0),      # Curva del Serraglio under railway bridge
        (-1000.0, 1200.0),    # Run to Variante Ascari
        (-2200.0, 800.0),     # Variante Ascari entry (Turn 8)
        (-2800.0, 600.0),     # Variante Ascari apex (Turn 9-10)
        (-3500.0, 100.0),     # Rettifilo Posteriore (Back Straight, Sector 2 exit)
        (-4100.0, -600.0),    # Approaching Parabolica
        (-4200.0, -1300.0),   # Curva Parabolica / Alboreto (Turn 11 entry)
        (-3800.0, -1500.0),   # Curva Parabolica apex
        (-3400.0, -1300.0),   # Parabolica exit onto main straight
    ],
    # Circuit de Spa-Francorchamps: 7.004 km, 19 turns
    # Start/Finish -> La Source -> Eau Rouge/Raidillon -> Kemmel -> Les Combes/Malmedy -> Bruxelles -> Pouhon -> Campus/Stavelot -> Blanchimont -> Bus Stop
    "spa": [
        (-2200.0, 800.0),     # Start / Finish line
        (-1800.0, 400.0),     # La Source (Turn 1 tight hairpin)
        (-1500.0, 600.0),     # Downhill descent to Eau Rouge
        (-1000.0, 1200.0),    # Eau Rouge compression (Turn 2)
        (-500.0, 1700.0),     # Raidillon uphill crest (Turn 3-4)
        (500.0, 2500.0),      # Kemmel Straight entry
        (1800.0, 3300.0),     # Kemmel Straight top speed
        (2700.0, 3600.0),     # Les Combes braking (Sector 1 exit)
        (3300.0, 3400.0),     # Les Combes chicane (Turns 5-6)
        (3600.0, 3000.0),     # Malmedy (Turn 7)
        (3800.0, 2200.0),     # Bruxelles (Turn 8 downhill right hairpin)
        (3400.0, 1500.0),     # Speaker's Corner / Turn 9
        (2600.0, 500.0),      # Double Gauche / Pouhon entry (Turn 10)
        (1700.0, -500.0),     # Pouhon exit (Turn 11)
        (1100.0, -1500.0),    # Fagnes / Pif-Paf chicane (Turns 12-13)
        (300.0, -2400.0),     # Campus (Turn 14)
        (-300.0, -3200.0),    # Stavelot (Turn 15, Sector 2 exit)
        (-1200.0, -3500.0),   # Courbe Paul Frère
        (-2200.0, -3100.0),   # Blanchimont high-speed flat-out left (Turns 16-17)
        (-3200.0, -1800.0),   # Run to Bus Stop chicane
        (-3200.0, -500.0),    # Bus Stop chicane (Turns 18-19)
        (-2600.0, 400.0),     # Bus Stop exit onto main straight
    ],
    # Circuit de Monaco: 3.337 km, 19 turns
    # Boulevard Albert 1er -> Sainte Dévote -> Beau Rivage -> Massenet -> Casino -> Mirabeau -> Hairpin -> Portier -> Tunnel -> Chicane -> Tabac -> Piscine -> Rascasse -> Noghès
    "monaco": [
        (-400.0, -1000.0),    # Boulevard Albert 1er (Start / Finish)
        (200.0, -900.0),      # Sainte Dévote (Turn 1 tight right)
        (500.0, -400.0),      # Beau Rivage uphill climb
        (750.0, 200.0),       # Massenet (Turn 2 long left)
        (650.0, 650.0),       # Casino Square (Turn 3, Sector 1 exit)
        (400.0, 850.0),       # Mirabeau Haute (Turn 4)
        (50.0, 1050.0),       # Grand Hotel Fairpin (Turn 5 slow hairpin)
        (-250.0, 950.0),      # Mirabeau Bas (Turn 6)
        (-550.0, 800.0),      # Portier (Turn 7 onto Tunnel entry)
        (-850.0, 500.0),      # Tunnel entry
        (-1150.0, -100.0),    # Tunnel exit / highest speed
        (-1100.0, -500.0),    # Nouvelle Chicane (Turns 8-9)
        (-800.0, -750.0),     # Tabac (Turn 10 left, Sector 2 exit)
        (-550.0, -850.0),     # Louis Chiron (Turn 11-12)
        (-300.0, -900.0),     # Piscine swimming pool chicane (Turns 13-14)
        (-100.0, -1050.0),    # La Rascasse (Turn 15 right hairpin)
        (-250.0, -1120.0),    # Antony Noghès (Turn 16 onto pit straight)
    ],
}
# Alias mapping for circuit name lookups
CIRCUIT_WAYPOINTS["kuala lumpur"] = CIRCUIT_WAYPOINTS["sepang"]


class CoordinateNormalizer:
    """Normalizes raw F1 Cartesian track coordinates into [-1.0, 1.0] and progress into [0.0, 1.0]."""

    def __init__(
        self,
        bounds: Optional[CircuitBounds] = None,
        centerline: Optional[TrackCenterline] = None,
    ):
        self.bounds = bounds or CircuitBounds(
            min_x=-5000.0,
            max_x=5000.0,
            min_y=-5000.0,
            max_y=5000.0,
        )
        self.centerline = centerline

    @classmethod
    def for_circuit(cls, circuit_name: str) -> "CoordinateNormalizer":
        key = circuit_name.lower().strip()
        bounds = CIRCUIT_PRESETS.get(
            key, CircuitBounds(min_x=-5000.0, max_x=5000.0, min_y=-5000.0, max_y=5000.0)
        )
        waypoints = CIRCUIT_WAYPOINTS.get(key)
        centerline = TrackCenterline(waypoints=waypoints) if waypoints else None
        return cls(bounds=bounds, centerline=centerline)

    def normalize_point(self, x: float, y: float) -> Tuple[float, float]:
        dx = self.bounds.max_x - self.bounds.min_x
        dy = self.bounds.max_y - self.bounds.min_y

        if dx <= 0.0:
            norm_x = 0.0
        else:
            norm_x = 2.0 * ((x - self.bounds.min_x) / dx) - 1.0

        if dy <= 0.0:
            norm_y = 0.0
        else:
            norm_y = 2.0 * ((y - self.bounds.min_y) / dy) - 1.0

        # Strict clamping within [-1.0, 1.0]
        clamped_x = max(-1.0, min(1.0, norm_x))
        clamped_y = max(-1.0, min(1.0, norm_y))
        return clamped_x, clamped_y

    def normalize_progress(self, progress: Optional[float]) -> float:
        if progress is None:
            return 0.0
        return max(0.0, min(1.0, float(progress)))

    def calculate_lap_progress(self, x: float, y: float, sector: Optional[int] = None) -> float:
        """Projects raw coordinates onto the circuit spline and returns normalized progress in [0.0, 1.0]."""
        if self.centerline is not None:
            return self.centerline.project_point(x, y, sector=sector)
        # Fallback: estimate from normalized bounding box diagonal if no centerline is defined
        nx, ny = self.normalize_point(x, y)
        angle = math.atan2(ny, nx)  # [-pi, pi]
        prog = (angle + math.pi) / (2.0 * math.pi)
        return max(0.0, min(1.0, prog))

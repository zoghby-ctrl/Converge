from dataclasses import dataclass


@dataclass(frozen=True)
class Rules:
    version: str = "phase1-rules-1.0"
    max_distance_m: float = 120
    window_hours: float = 6
    max_accuracy_m: float = 50
    max_time_uncertainty_minutes: float = 30
    clock_tolerance_minutes: float = 5
    # Explicit interpretation of 'same place/time' in the freeze.
    conflict_minutes: float = 30
    min_quality: float = 0.5
    tie_margin: float = 1


RULES = Rules()
RISK_WEIGHTS = {"water_extent": 0.35, "road_condition": 0.30,
                "persistence": 0.20, "exposure": 0.15}
HYPOTHESIS_WEIGHTS = {
    "H1": {"W": 2, "D": 1, "P": 2, "R": 2, "N": -1, "C": -2, "S": 0},
    "H2": {"W": 2, "D": 0, "P": -2, "R": 2, "N": -1, "C": 2, "S": 0},
    "H3": {"W": 2, "D": 0, "P": 1, "R": -1, "N": 2, "C": -1, "S": 2},
}

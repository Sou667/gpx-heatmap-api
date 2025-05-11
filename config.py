# config.py
import os

# Mindest- und Maximalwerte
MIN_SEGMENT_LENGTH_KM = float(os.getenv("MIN_SEGMENT_LENGTH_KM", 0.005))
MAX_POINTS = int(os.getenv("MAX_POINTS", 100000))
MAX_SEGMENTS = int(os.getenv("MAX_SEGMENTS", 1000))

# Default-Wetter
DEFAULT_WEATHER = {
    "temperature": 20,
    "wind_speed": 5,
    "precip": 0,
    "condition": "klar"
}

# Risikoschwellen
RISK_THRESHOLDS = {
    "slope": float(os.getenv("THRESH_SLOPE", 5.0)),            # in %
    "precipitation": float(os.getenv("THRESH_PRECIP", 1.0)),   # mm
    "wind_speed": float(os.getenv("THRESH_WIND", 20.0)),       # km/h
    "sharp_curve_angle": float(os.getenv("THRESH_CURVE", 30.0))# Grad
}

# CORS-Whitelist (Komma-separiert)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",")

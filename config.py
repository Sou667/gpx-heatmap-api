# config.py
# Configuration variables for the CycleDoc Heatmap API

# Segment and track point limits
MIN_SEGMENT_LENGTH_KM = 0.005  # Minimum segment length in kilometers (5 meters)
MAX_POINTS = 100000            # Maximum number of track points per request
MAX_SEGMENTS = 10000           # Maximum number of segments for route analysis (increased to accommodate finer segmentation)

# Heatmap configuration
HEATMAP_SIZE = (800, 800)      # Dimensions of the image-based heatmap (width, height)

# Default start time for risk analysis (ISO 8601 format)
DEFAULT_START_TIME = "2025-05-11T10:00:00Z"

# Default weather conditions
DEFAULT_WEATHER = {
    "temperature": 15,  # Default temperature in °C
    "wind_speed": 10,   # Default wind speed in km/h
    "precip": 0,        # Default precipitation in mm
    "condition": "klar" # Default weather condition
}

# Risk analysis thresholds
RISK_THRESHOLDS = {
    "slope": 5.0,         # Slope threshold for risk increase (in percent)
    "sharp_curve_angle": 60.0,  # Angle threshold for sharp curves (in degrees)
    "precipitation": 2.0,  # Precipitation threshold for risk increase (in mm)
    "wind_speed": 20.0     # Wind speed threshold for risk increase (in km/h)
}

# Valid rider profile options
VALID_FAHRER_TYPES = [
    "hobby", "c-lizenz", "anfänger", "a", "b", "elite", "profi"
]  # Valid rider types

VALID_RENNEN_ART = [
    "downhill", "freeride", "rennen", "road", "mtb", ""
]  # Valid race types, "" indicates none

VALID_GESCHLECHT = [
    "m", "mann", "male", "w", "frau", "female", "divers", "non-binary", ""
]  # Valid genders, "" indicates none

VALID_MATERIAL = [
    "carbon", "aluminium", "steel"
]  # Valid bicycle materials

VALID_STREET_SURFACE = [
    "asphalt", "cobblestone", "gravel", "dirt", "sand"
]  # Valid street surfaces

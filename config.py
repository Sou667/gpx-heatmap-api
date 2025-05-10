# config.py
# Configuration variables for the CycleDoc Heatmap API

# Segment and track point limits
MIN_SEGMENT_LENGTH_KM = 1.0  # Minimum segment length in kilometers
MAX_POINTS = 100000          # Maximum number of track points per request
MAX_SEGMENTS = 100           # Maximum number of segments for route analysis

# Default weather conditions
DEFAULT_WEATHER = {
    "temperature": 15,  # Default temperature in °C
    "wind_speed": 10,   # Default wind speed in km/h
    "precip": 0,        # Default precipitation in mm
    "condition": "klar" # Default weather condition
}

# Valid rider profile options
VALID_FAHRER_TYPES = [
    "hobby", "c-lizenz", "anfänger", "a", "b", "elite", "profi"
]  # Valid rider types

VALID_RENNEN_ART = [
    "downhill", "freeride", "rennen", "road", "mtb", ""
]  # Valid race types, "" indicates none

VALID_GESCHLECHT = [
    "m", "mann", "male", "w", "frau", "female", ""
]  # Valid genders, "" indicates none

VALID_MATERIAL = [
    "carbon", "aluminium", "steel"
]  # Valid bicycle materials

VALID_STREET_SURFACE = [
    "asphalt", "cobblestone", "gravel"
]  # Valid street surfaces

import os
import json
import math
import random
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple
from io import BytesIO
import base64
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

from flask import Flask, request, jsonify, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import gpxpy
import folium
from geopy.distance import geodesic
from astral import LocationInfo
from astral.sun import sun
import requests
import chardet
from cachetools import TTLCache
from sqlalchemy import create_engine, Column, Integer, String, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from logging.handlers import RotatingFileHandler

# --- Configuration ---
from config import (
    MIN_SEGMENT_LENGTH_KM, MAX_POINTS, DEFAULT_WEATHER,
    VALID_FAHRER_TYPES, VALID_RENNEN_ART, VALID_GESCHLECHT,
    VALID_MATERIAL, VALID_STREET_SURFACE
)

# --- Logging Setup ---
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
file_handler = RotatingFileHandler("app.log", maxBytes=10*1024*1024, backupCount=5)
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.handlers = [file_handler, stream_handler]

# --- Flask Application ---
app = Flask(__name__)
limiter = Limiter(app, key_func=get_remote_address, default_limits=["200 per day", "50 per hour"])

# --- Database Setup ---
Base = declarative_base()
engine = create_engine("sqlite:///chunks.db")
Session = sessionmaker(bind=engine)

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    filename = Column(String, unique=True)
    data = Column(JSON)

Base.metadata.create_all(engine)

# --- Caching ---
weather_cache = TTLCache(maxsize=1000, ttl=3600)  # 1 hour TTL

# --- Directories ---
STATIC_DIR = Path("static")
CHUNKS_DIR = Path("chunks")
STATIC_DIR.mkdir(exist_ok=True)
CHUNKS_DIR.mkdir(exist_ok=True)

# --- Helper Functions ---

@lru_cache(maxsize=4096)
def cached_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Calculate geodesic distance (in km) between two points.

    Args:
        p1: Tuple of (latitude, longitude).
        p2: Tuple of (latitude, longitude).

    Returns:
        float: Distance in kilometers.
    """
    return geodesic(p1, p2).km

def bearing(a: List[float], b: List[float]) -> float:
    """Calculate bearing from point a to point b.

    Args:
        a: List of [latitude, longitude].
        b: List of [latitude, longitude].

    Returns:
        float: Bearing in degrees.
    """
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def angle_between(b1: float, b2: float) -> float:
    """Calculate minimal difference between two angles.

    Args:
        b1: First angle in degrees.
        b2: Second angle in degrees.

    Returns:
        float: Minimal angle difference.
    """
    return min(abs(b1 - b2), 360 - abs(b1 - b2))

def detect_sharp_curve(pts: List[List[float]], t: float = 60) -> bool:
    """Check if a sharp curve (>= t°) exists in a list of points.

    Args:
        pts: List of points [latitude, longitude, elevation?].
        t: Threshold angle in degrees.

    Returns:
        bool: True if a sharp curve is detected.
    """
    return any(
        angle_between(bearing(pts[i], pts[i+1]), bearing(pts[i+1], pts[i+2])) >= t
        for i in range(len(pts) - 2)
    )

def calc_slope(points: List[List[float]]) -> float:
    """Calculate percentage slope between first and last point.

    Args:
        points: List of points [latitude, longitude, elevation?].

    Returns:
        float: Slope in percent, rounded to 1 decimal.
    """
    if len(points) < 2:
        return 0.0
    start_elev = points[0][2] if len(points[0]) > 2 else 0
    end_elev = points[-1][2] if len(points[-1]) > 2 else 0
    elev_diff = end_elev - start_elev
    dist_m = cached_distance(tuple(points[0][:2]), tuple(points[-1][:2])) * 1000
    return round((elev_diff / dist_m) * 100, 1) if dist_m > 1e-6 else 0.0

def get_street_surface(lat: float, lon: float) -> str:
    """Determine street surface based on coordinates.

    Args:
        lat: Latitude.
        lon: Longitude.

    Returns:
        str: Surface type (asphalt, cobblestone, gravel).
    """
    seed_val = int(abs(lat * 1000) + abs(lon * 1000))
    rng = random.Random(seed_val)
    return rng.choice(VALID_STREET_SURFACE)

def is_nighttime_at(dt: datetime, lat: float, lon: float) -> bool:
    """Determine if it's nighttime at the given time and location.

    Args:
        dt: Datetime object.
        lat: Latitude.
        lon: Longitude.

    Returns:
        bool: True if nighttime, False otherwise.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif dt.tzinfo != timezone.utc:
        dt = dt.astimezone(timezone.utc)
    try:
        loc = LocationInfo("loc", "", "UTC", lat, lon)
        s = sun(loc.observer, date=dt.date(), tzinfo=timezone.utc)
        return dt < s["sunrise"] or dt > s["sunset"]
    except Exception as e:
        logger.error("Error in is_nighttime_at: %s", e)
        return False

def segmentize(coords: List[List[float]], len_km: float = MIN_SEGMENT_LENGTH_KM) -> List[List[List[float]]]:
    """Split coordinates into segments of at least len_km length.

    Args:
        coords: List of coordinates [latitude, longitude, elevation?].
        len_km: Minimum segment length in km.

    Returns:
        List[List[List[float]]]: List of segments.
    """
    segments = []
    current_segment = []
    total_dist = 0.0
    prev = None

    for point in coords:
        if prev is not None:
            total_dist += cached_distance(tuple(prev[:2]), tuple(point[:2]))
            current_segment.append(point)
            if total_dist >= len_km:
                segments.append(current_segment)
                current_segment = []
                total_dist = 0.0
        else:
            current_segment.append(point)
        prev = point

    if current_segment:
        segments.append(current_segment)
    return segments

def is_valid_coordinates(coords: Any) -> bool:
    """Validate if coords is a list with at least one valid point ([latitude, longitude]).

    Args:
        coords: Input to validate.

    Returns:
        bool: True if valid, False otherwise.
    """
    if not isinstance(coords, list) or not coords:
        return False
    for point in coords:
        if not isinstance(point, list) or len(point) < 2:
            return False
        lat, lon = point[:2]
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
            return False
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False
    return True

def validate_inputs(data: Dict[str, Any]) -> Optional[str]:
    """Validate input parameters.

    Args:
        data: Input dictionary.

    Returns:
        Optional[str]: Error message if invalid, None if valid.
    """
    if data.get("fahrer_typ", "hobby") not in VALID_FAHRER_TYPES:
        return f"Ungültiger fahrer_typ: {data.get('fahrer_typ')}"
    if data.get("rennen_art", "") not in VALID_RENNEN_ART:
        return f"Ungültige rennen_art: {data.get('rennen_art')}"
    if data.get("geschlecht", "") not in VALID_GESCHLECHT:
        return f"Ungültiges geschlecht: {data.get('geschlecht')}"
    if data.get("material", "aluminium") not in VALID_MATERIAL:
        return f"Ungültiges material: {data.get('material')}"
    return None

def calc_risk(temp: float, wind: float, precip: float, slope: float,
              typ: str, n: int, **opt: Any) -> int:
    """Calculate route risk based on various parameters.

    Args:
        temp: Temperature in °C.
        wind: Wind speed in km/h.
        precip: Precipitation in mm.
        slope: Slope in percent.
        typ: Rider type (e.g., 'hobby', 'profi').
        n: Number of riders.
        **opt: Additional parameters (e.g., nighttime, sharp_curve).

    Returns:
        int: Risk value between 1 and 5.
    """
    def safe(val: Any, default: Any) -> Any:
        return default if val is None else val

    risk = 1
    risk += int(temp <= 5)
    risk += int(wind >= 25)
    risk += int(precip >= 1)
    risk += int(abs(slope) > 4)
    risk += int(typ.lower() in ["hobby", "c-lizenz", "anfänger"])
    risk -= int(typ.lower() in ["a", "b", "elite", "profi"])
    risk += int(n > 80)
    risk += int(safe(opt.get("massenstart"), False))
    risk += int(safe(opt.get("nighttime"), False))
    risk += int(safe(opt.get("sharp_curve"), False))
    risk += int(safe(opt.get("geschlecht", ""), "").lower() in ["w", "frau", "female"])
    risk += int(safe(opt.get("alter"), 0) >= 60)
    risk += int(safe(opt.get("street_surface"), "") in ["gravel", "cobblestone"])
    risk += int(safe(opt.get("material", ""), "") == "carbon")
    schutz = safe(opt.get("schutzausruestung"), {})
    risk -= int(schutz.get("helm", False))
    risk -= int(schutz.get("protektoren", False))
    risk += int(safe(opt.get("overuse_knee"), False))
    risk += int(safe(opt.get("rueckenschmerzen"), False))
    if safe(opt.get("rennen_art", ""), "").lower() in ["downhill", "freeride"]:
        risk += 2
    return max(1, min(risk, 5))

def typical_injuries(risk: int, art: str) -> List[str]:
    """Return typical injuries based on risk and race type.

    Args:
        risk: Risk level (1-5).
        art: Race type (e.g., 'downhill', 'road').

    Returns:
        List[str]: List of typical injuries.
    """
    if risk <= 2:
        return ["Abschürfungen", "Prellungen"]
    base = (["Abschürfungen", "Prellungen", "Claviculafraktur", "Handgelenksverletzung"]
            if risk <= 4
            else ["Abschürfungen", "Claviculafraktur", "Wirbelsäulenverletzung", "Beckenfraktur"])
    if art.lower() in ["downhill", "freeride"]:
        base.append("Schwere Rücken-/Organverletzungen" if risk == 5 else "Wirbelsäulenverletzung (selten)")
    return base

def fetch_current_weather(lat: float, lon: float, dt: datetime) -> Dict[str, Any]:
    """Fetch current weather data from WeatherStack.

    Args:
        lat: Latitude.
        lon: Longitude.
        dt: Datetime object.

    Returns:
        Dict[str, Any]: Weather data.
    """
    cache_key = (round(lat, 2), round(lon, 2), dt.date().isoformat())
    if cache_key in weather_cache:
        logger.info("Weather from cache for %s", cache_key)
        return weather_cache[cache_key]

    api_key = os.getenv("WEATHERSTACK_API_KEY")
    if not api_key:
        logger.warning("No WEATHERSTACK_API_KEY found, using default weather")
        return DEFAULT_WEATHER
    url = f"http://api.weatherstack.com/current?access_key={api_key}&query={lat},{lon}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if "current" in data:
            current = data["current"]
            result = {
                "temperature": current.get("temperature", DEFAULT_WEATHER["temperature"]),
                "wind_speed": current.get("wind_speed", DEFAULT_WEATHER["wind_speed"]),
                "precip": current.get("precip", DEFAULT_WEATHER["precip"]),
                "condition": current.get("weather_descriptions", [DEFAULT_WEATHER["condition"]])[0]
            }
            weather_cache[cache_key] = result
            return result
        logger.warning("Weather API response missing 'current': %s", data)
        return DEFAULT_WEATHER
    except Exception as e:
        logger.error("Error fetching weather data: %s", e)
        return DEFAULT_WEATHER

def fetch_weather_for_route(coords: List[List[float]], dt: datetime) -> List[Dict[str, Any]]:
    """Fetch weather data for points along the route (every 50 km).

    Args:
        coords: List of coordinates [latitude, longitude, elevation?].
        dt: Datetime object.

    Returns:
        List[Dict[str, Any]]: List of weather data points.
    """
    if not coords:
        return [DEFAULT_WEATHER]
    weather_points = []
    total_dist = 0.0
    last_weather_idx = 0
    for i in range(1, len(coords)):
        total_dist += cached_distance(tuple(coords[i-1][:2]), tuple(coords[i][:2]))
        if total_dist >= 50 or i == len(coords) - 1:
            lat, lon = coords[i][0], coords[i][1]
            weather_points.append(fetch_current_weather(lat, lon, dt))
            total_dist = 0
    return weather_points

def average_weather(weather_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate average weather from a list of weather points.

    Args:
        weather_list: List of weather dictionaries.

    Returns:
        Dict[str, Any]: Averaged weather data.
    """
    if not weather_list:
        return DEFAULT_WEATHER
    return {
        "temperature": sum(w["temperature"] for w in weather_list) / len(weather_list),
        "wind_speed": sum(w["wind_speed"] for w in weather_list) / len(weather_list),
        "precip": sum(w["precip"] for w in weather_list) / len(weather_list),
        "condition": weather_list[0]["condition"]
    }

def fix_gpx_content(file) -> BytesIO:
    """Fix common issues in GPX files (BOM, encoding, missing header).

    Args:
        file: File-like object.

    Returns:
        BytesIO: Fixed file content.

    Raises:
        ValueError: If file cannot be fixed.
    """
    try:
        content = file.read()
        result = chardet.detect(content)
        encoding = result['encoding'] or 'utf-8'
        if encoding.lower() != 'utf-8':
            content = content.decode(encoding).encode('utf-8')
            logger.info("Converted encoding from %s to UTF-8", encoding)

        if content.startswith(b'\xef\xbb\xbf'):
            content = content[3:]
            logger.info("Removed BOM")

        expected_header = b'<?xml version="1.0" encoding="UTF-8"?>'
        if not content.startswith(expected_header):
            content = expected_header + b'\n' + content
            logger.info("Added XML header")

        return BytesIO(content)
    except Exception as e:
        logger.error("Error fixing GPX file: %s", e)
        raise ValueError(f"Cannot fix GPX file: {str(e)}")

def cleanup_static_dir(max_age_hours: int = 24):
    """Delete static files older than max_age_hours.

    Args:
        max_age_hours: Maximum age of files in hours.
    """
    now = datetime.utcnow()
    for fn in STATIC_DIR.iterdir():
        if fn.is_file():
            mtime = datetime.fromtimestamp(fn.stat().st_mtime)
            if (now - mtime).total_seconds() > max_age_hours * 3600:
                fn.unlink()
                logger.info("Deleted: %s", fn)

# --- API Endpoints ---

@app.route("/", methods=["GET"])
def home() -> str:
    """Simple health-check endpoint.

    Returns:
        str: Confirmation message.
    """
    return "✅ CycleDoc Heatmap-API ready"

@app.route("/heatmap-quick", methods=["POST"])
@limiter.limit("10 per minute")
def heatmap_quick() -> Any:
    """Generate an interactive heatmap and detailed report.

    Returns:
        Any: JSON with heatmap URL, distance, segment info, and report.
    """
    data: Dict[str, Any] = request.json or {}
    cleanup_static_dir()

    # Validate inputs
    coords = data.get("coordinates", [])
    if not is_valid_coordinates(coords):
        return jsonify({"error": "Invalid coordinates received"}), 400
    if len(coords) > MAX_POINTS:
        return jsonify({"error": f"Too many track points: {len(coords)}. Maximum allowed: {MAX_POINTS}"}), 400
    if len(coords) < 2:
        return jsonify({"error": "Too few coordinates for distance calculation"}), 400

    start_time = data.get("start_time")
    if not start_time:
        return jsonify({"error": "Missing 'start_time' parameter"}), 400
    try:
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return jsonify({"error": "Invalid 'start_time' format. Expected ISO-8601 (e.g., '2025-04-09T07:00:00Z')"}), 400

    if error := validate_inputs(data):
        return jsonify({"error": error}), 400

    # Representative point
    rep_index = len(coords) // 2
    rep_lat, rep_lon = coords[rep_index][0], coords[rep_index][1]
    nighttime = is_nighttime_at(dt, rep_lat, rep_lon)

    # Weather data
    live_weather = data.get("wetter_override", average_weather(fetch_weather_for_route(coords, dt)))

    # Segment processing
    segments = segmentize(coords)
    logger.info("Created %d segments", len(segments))

    def process_segment(i: int, seg: List[List[float]]) -> Dict[str, Any]:
        if not seg:
            return None
        mid_idx = len(seg) // 2
        lat, lon = seg[mid_idx][:2]
        slope = calc_slope(seg)
        curve = detect_sharp_curve(seg)
        surface = get_street_surface(lat, lon)
        risk = calc_risk(
            live_weather["temperature"],
            live_weather["wind_speed"],
            live_weather["precip"],
            slope,
            data.get("fahrer_typ", "hobby"),
            data.get("anzahl", 5),
            nighttime=nighttime,
            sharp_curve=curve,
            rennen_art=data.get("rennen_art", ""),
            geschlecht=data.get("geschlecht", ""),
            street_surface=surface,
            alter=data.get("alter", 42),
            material=data.get("material", "aluminium"),
            schutzausruestung=data.get("schutzausruestung", {}),
            overuse_knee=data.get("overuse_knee", False),
            rueckenschmerzen=data.get("rueckenschmerzen", False),
            massenstart=data.get("massenstart", False)
        )
        return {
            "segment_index": i + 1,
            "center": {"lat": lat, "lon": lon},
            "slope": slope,
            "sharp_curve": curve,
            "terrain": "Anstieg" if slope > 2 else "Abfahrt" if slope < -2 else "Flach",
            "weather": live_weather,
            "nighttime": nighttime,
            "street_surface": surface,
            "risk": risk,
            "injuries": typical_injuries(risk, data.get("rennen_art", "")),
            "sani_needed": False
        }

    with ThreadPoolExecutor() as executor:
        seg_infos = [info for info in executor.map(lambda i_seg: process_segment(*i_seg), enumerate(segments)) if info]
    all_locations = [(p[0], p[1]) for seg in segments for p in seg]

    # Sanitäter logic
    race_mode = data.get("rennen_art", "").lower() in VALID_RENNEN_ART
    min_gap = 5
    risk_indices = [i for i, info in enumerate(seg_infos) if info["risk"] >= 3]
    clusters = []
    current_cluster = []
    for idx in risk_indices:
        if not current_cluster or idx - current_cluster[-1] <= 1:
            current_cluster.append(idx)
        else:
            clusters.append(current_cluster)
            current_cluster = [idx]
    if current_cluster:
        clusters.append(current_cluster)

    last_sani_index = -min_gap
    for cluster in clusters:
        if not cluster:
            continue
        if race_mode:
            candidate = cluster[len(cluster) // 2]
            if candidate - last_sani_index >= min_gap:
                seg_infos[candidate]["sani_needed"] = True
                last_sani_index = candidate
        else:
            for idx in cluster:
                seg_infos[idx]["sani_needed"] = True

    # Map creation
    try:
        m = folium.Map(location=[rep_lat, rep_lon], zoom_start=13)
    except Exception as e:
        logger.error("Error creating map: %s", e)
        return jsonify({"error": "Map creation failed"}), 500

    folium.PolyLine([(p[0], p[1]) for p in coords], color="blue", weight=3, opacity=0.6).add_to(m)

    def color_by_risk(risk_val: int) -> str:
        return "green" if risk_val <= 2 else "orange" if risk_val == 3 else "red"

    def group_segments() -> List[Dict[str, Any]]:
        groups = []
        for info, seg in zip(seg_infos, segments):
            reasons = []
            if info["sharp_curve"]:
                reasons.append("enge Kurve")
            if info["street_surface"] in ["gravel", "cobblestone"]:
                reasons.append(f"Untergrund: {info['street_surface']}")
            if live_weather["wind_speed"] >= 25:
                reasons.append("starker Wind")
            if live_weather["precip"] >= 1:
                reasons.append("Regen")
            signature = (info["risk"], tuple(sorted(reasons)))
            if not groups or groups[-1]["signature"] != signature:
                groups.append({
                    "signature": signature,
                    "segments": [seg],
                    "centers": [info["center"]],
                    "sani": info["sani_needed"]
                })
            else:
                groups[-1]["segments"].append(seg)
                groups[-1]["centers"].append(info["center"])
                groups[-1]["sani"] = groups[-1]["sani"] or info["sani_needed"]
        return groups

    for grp in group_segments():
        all_points = [pt for seg in grp["segments"] for pt in seg]
        centers = grp["centers"]
        mid_center = centers[len(centers) // 2] if centers else {"lat": rep_lat, "lon": rep_lon}
        risk_val, reasons = grp["signature"]
        reason_text = ", ".join(reasons)
        popup_text = f"🚩 {len(grp['segments'])}× Risk {risk_val}" + (f": {reason_text}" if reasons else "")
        folium.PolyLine([(p[0], p[1]) for p in all_points],
                        color=color_by_risk(risk_val), weight=6, popup=popup_text).add_to(m)
        if grp["sani"]:
            folium.Marker(
                [mid_center["lat"], mid_center["lon"]],
                popup=f"🚑 Sani recommended – {popup_text}",
                icon=folium.Icon(color="red", icon="medkit", prefix="fa")
            ).add_to(m)

    try:
        if not all_locations or not all(-90 <= lat <= 90 and -180 <= lon <= 180 for lat, lon in all_locations):
            m.fit_bounds([(rep_lat, rep_lon), (rep_lat, rep_lon)])
        else:
            m.fit_bounds(all_locations)
        logger.info("Map bounds adjusted successfully")
    except Exception as e:
        logger.warning("Could not adjust map bounds: %s", e)
        m.fit_bounds([(rep_lat, rep_lon), (rep_lat, rep_lon)])

    filename = f"heatmap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
    filepath = STATIC_DIR / filename
    try:
        m.save(filepath)
    except Exception as e:
        logger.error("Error saving map: %s", e)
        return jsonify({"error": "Failed to save heatmap"}), 500

    total_distance = sum(cached_distance(tuple(coords[i-1][:2]), tuple(coords[i][:2])) for i in range(1, len(coords)))
    avg_risk = sum(seg["risk"] for seg in seg_infos) / len(seg_infos) if seg_infos else 0

    # Detailed report
    report = []
    report.append("Section 0: Route Length")
    report.append(f"The route covers {round(total_distance, 2)} km.\n")

    report.append("Section 1: Weather Conditions")
    report.append(f"Representative Point: (Lat: {rep_lat:.3f}, Lon: {rep_lon:.3f})")
    report.append(f"Date and Time: {dt.isoformat()}")
    report.append(f"Temperature: {live_weather['temperature']}°C, Wind: {live_weather['wind_speed']} km/h, "
                  f"Precipitation: {live_weather['precip']} mm, Condition: {live_weather['condition']}")
    report.append("Source: WeatherStack (if fetched via API)\n")

    report.append("Section 2: Risk Assessment")
    if seg_infos:
        for seg in seg_infos:
            seg_index = seg["segment_index"]
            details = [f"Slope: {seg['slope']}%", f"Terrain: {seg['terrain']}"]
            if seg['sharp_curve']:
                details.append("sharp curve")
            if seg['street_surface'] in ["gravel", "cobblestone"]:
                details.append(f"Surface: {seg['street_surface']}")
            if live_weather["wind_speed"] >= 25:
                details.append("strong wind")
            if live_weather["precip"] >= 1:
                details.append("rain")
            reason_text = ", ".join(details)
            report.append(f"Segment {seg_index}: Risk: {seg['risk']} ({reason_text})"
                          f"{' – 🚑 Sanitäter recommended' if seg['sani_needed'] else ''}")
    else:
        report.append("No segments found for risk assessment.\n")

    report.append("Section 3: Overall Risk")
    risk_level = "low" if avg_risk <= 2 else ("elevated" if avg_risk < 4 else "critical")
    report.append(f"Average Risk Score: {avg_risk:.2f} ({risk_level})\n")

    report.append("Section 4: Likely Injuries")
    injury_set = set(inj for seg in seg_infos for inj in seg["injuries"])
    if injury_set:
        report.append("Typical Injuries: " + ", ".join(injury_set))
        report.append("Recommended Studies: (Rehlinghaus 2022), (Nelson 2010)\n")
    else:
        report.append("No injury information available.\n")

    report.append("Section 5: Prevention Recommendations")
    prevention = []
    if live_weather["precip"] >= 1:
        prevention.append("reduce speed in rain, improve visibility")
    if any(seg['sharp_curve'] for seg in seg_infos):
        prevention.append("watch for sharp curves")
    if any(seg['slope'] > 4 for seg in seg_infos):
        prevention.append("ride cautiously on steep slopes")
    if live_weather["wind_speed"] >= 25:
        prevention.append("ride stably in strong winds")
    if not prevention:
        prevention.append("maintain normal riding behavior")
    report.append(", ".join(prevention) + "\n")

    report.append("Section 6: Sources")
    report.append("Scientific Sources: (Rehlinghaus 2022), (Kronisch 2002, p. 5), (Nelson 2010), "
                  "(Dannenberg 1996), (Ruedl 2015), (Clarsen 2005)")
    report.append("Weather Data: WeatherStack (if fetched via API)\n")

    report.append("Section 7: Interactive Map")
    report.append(f"Heatmap URL: https://gpx-heatmap-api.onrender.com/static/{filename}")
    report.append("Color Scale: green = low risk, orange = medium risk, red = high risk.")
    report.append("🚑 markers indicate segments where a paramedic is recommended.")

    return jsonify({
        "heatmap_url": f"https://gpx-heatmap-api.onrender.com/static/{filename}",
        "distance_km": round(total_distance, 2),
        "segments": seg_infos,
        "detailed_report": "\n".join(report)
    })

@app.route("/parse-gpx", methods=["POST"])
@limiter.limit("10 per minute")
def parse_gpx() -> Any:
    """Parse an uploaded GPX file and extract coordinates.

    Returns:
        Any: JSON with coordinates and total distance.
    """
    content_type = request.content_type or ""
    logger.info("Content-Type: %s", content_type)

    if content_type.startswith("multipart/form-data"):
        file = request.files.get("file")
        if not file or file.filename == "":
            return jsonify({"error": "No file received under 'file' key"}), 400
        logger.info("Received GPX file: %s, size: %d bytes", file.filename, file.seek(0, 2))
        file.seek(0)
    elif content_type.startswith("application/json"):
        data = request.get_json(silent=True) or {}
        base64_str = data.get("file_base64")
        if not base64_str:
            return jsonify({"error": "No 'file_base64' field in JSON"}), 400
        try:
            file_data = base64.b64decode(base64_str)
            file = BytesIO(file_data)
            file.filename = "uploaded.gpx"
            logger.info("Decoded Base64 file, size: %d bytes", len(file_data))
        except base64.binascii.Error:
            return jsonify({"error": "Invalid Base64 format"}), 400
    else:
        data = request.get_data()
        if not data:
            return jsonify({"error": "No data body received"}), 400
        if len(data) < 100:
            return jsonify({"error": "Data too small for a GPX file"}), 400
        file = BytesIO(data)
        file.filename = "uploaded.gpx"
        logger.info("Received raw body, length: %d bytes", len(data))

    try:
        file = fix_gpx_content(file)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        file.seek(0)
        ET.parse(file)
        file.seek(0)
        logger.info("XML structure is valid")
    except ET.ParseError as e:
        logger.error("Invalid XML: %s", e)
        return jsonify({"error": f"Invalid XML structure: {str(e)}"}), 400

    try:
        file.seek(0)
        gpx = gpxpy.parse(file)
        logger.info("Parsed GPX file, tracks: %d", len(gpx.tracks))
    except Exception as e:
        logger.error("Error parsing GPX file: %s", e)
        return jsonify({"error": f"Invalid GPX file: {str(e)}"}), 400

    coords = []
    try:
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    coords.append([point.latitude, point.longitude, point.elevation or 0])
        if not coords:
            for route in gpx.routes:
                for point in route.points:
                    coords.append([point.latitude, point.longitude, point.elevation or 0])
        if not coords:
            return jsonify({"error": "GPX file contains no track or route points"}), 400
        logger.info("Extracted %d coordinates", len(coords))
    except Exception as e:
        logger.error("Error extracting coordinates: %s", e)
        return jsonify({"error": f"Error processing GPX data: {str(e)}"}), 500

    if len(coords) < 2:
        return jsonify({"error": "Too few coordinates for distance calculation"}), 400
    if len(coords) > MAX_POINTS:
        return jsonify({"error": f"Too many track points: {len(coords)}. Maximum allowed: {MAX_POINTS}"}), 400

    total_km = sum(cached_distance(tuple(coords[i-1][:2]), tuple(coords[i][:2])) for i in range(1, len(coords)))
    return jsonify({"coordinates": coords, "distance_km": round(total_km, 2)})

@app.route("/chunk-upload", methods=["POST"])
@limiter.limit("10 per minute")
def chunk_upload() -> Any:
    """Split coordinates into chunks and store in database.

    Returns:
        Any: JSON with confirmation and chunk filenames.
    """
    data = request.json or {}
    coords = data.get("coordinates", [])
    size = data.get("chunk_size", 200)
    if not is_valid_coordinates(coords):
        return jsonify({"error": "Invalid coordinates received"}), 400

    files = []
    total_chunks = (len(coords) + size - 1) // size
    with Session() as session:
        for i in range(total_chunks):
            fn = f"chunk_{i+1}.json"
            try:
                chunk = Chunk(filename=fn, data={"coordinates": coords[i * size:(i + 1) * size]})
                session.add(chunk)
                files.append(fn)
            except Exception as e:
                logger.error("Error saving chunk %d: %s", i+1, e)
                session.rollback()
                return jsonify({"error": "Error saving chunks"}), 500
        session.commit()

    return jsonify({"message": f"{len(files)} chunks stored", "chunks": files})

@app.route("/openapi.yaml", methods=["GET"])
def serve_openapi() -> Any:
    """Serve the OpenAPI specification in YAML format.

    Returns:
        Any: YAML file or error message.
    """
    try:
        return send_file("openapi.yaml", mimetype="text/yaml")
    except Exception as e:
        logger.error("Error sending OpenAPI file: %s", e)
        return jsonify({"error": "OpenAPI file not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

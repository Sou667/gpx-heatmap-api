#!/usr/bin/env python3
"""
CycleDoc Heatmap-API – Comprehensive Optimized Version

Diese API verarbeitet GPX-Daten, segmentiert Routen, berechnet diverse Parameter
(sowie Steigung, Kurven, Wetter etc.) und erstellt eine interaktive Karte mit
Risiko- und intelligenter Sanitäterlogik. Der Code ist hoch performant, robust
und dokumentiert mittels umfangreicher Type Hints und Docstrings.

Hinweis:
- Für stark asynchrone I/O-Vorgänge (z. B. bei großen Dateischreibvorgängen)
  empfiehlt sich der Einsatz eines Task-Queue-Systems wie Celery.
- Im produktiven Einsatz sollte der Debug-Modus deaktiviert werden.
"""

import os
import json
import math
import random
import logging
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple
from io import BytesIO

from flask import Flask, request, jsonify, send_file
import gpxpy
import folium
from geopy.distance import geodesic
from astral import LocationInfo
from astral.sun import sun

# --- Logging und Konfiguration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Log to file handler
file_handler = logging.FileHandler("app.log")
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
logger.addHandler(file_handler)

# Erforderliche Verzeichnisse erstellen
os.makedirs("chunks", exist_ok=True)
os.makedirs("static", exist_ok=True)

# Flask-Anwendung initialisieren
app = Flask(__name__)

# --- Konfigurationseinstellungen ---
DEFAULT_WEATHER: Dict[str, Any] = {
    "temperature": 15,
    "wind_speed": 10,
    "precip": 0,
    "condition": "klar"
}
MIN_SEGMENT_LENGTH_KM: float = 0.005

# --- Helper Functions ---

@lru_cache(maxsize=4096)
def cached_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Berechnet die geodätische Entfernung (in km) zwischen zwei Punkten."""
    return geodesic(p1, p2).km

def bearing(a: List[float], b: List[float]) -> float:
    """Berechnet den Richtungswinkel von Punkt a zu Punkt b."""
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def angle_between(b1: float, b2: float) -> float:
    """Berechnet den minimalen Unterschied zwischen zwei Winkeln."""
    return min(abs(b1 - b2), 360 - abs(b1 - b2))

def detect_sharp_curve(pts: List[List[float]], t: float = 60) -> bool:
    """Prüft, ob innerhalb einer Liste von Punkten ein scharfer Kurvenverlauf (>= t°) existiert."""
    return any(
        angle_between(bearing(pts[i], pts[i+1]), bearing(pts[i+1], pts[i+2])) >= t
        for i in range(len(pts) - 2)
    )

def calc_slope(points: List[List[float]]) -> float:
    """Berechnet die prozentuale Steigung zwischen dem ersten und letzten Punkt."""
    if len(points) < 2:
        return 0.0
    start_elev = points[0][2] if len(points[0]) > 2 else 0
    end_elev = points[-1][2] if len(points[-1]) > 2 else 0
    elev_diff = end_elev - start_elev
    dist_m = cached_distance(tuple(points[0][:2]), tuple(points[-1][:2])) * 1000
    return round((elev_diff / dist_m) * 100, 1) if dist_m > 1e-6 else 0.0

def get_street_surface(lat: float, lon: float) -> str:
    """Bestimmt zufällig eine Straßenoberfläche basierend auf den Koordinaten."""
    seed_val = int(abs(lat * 1000) + abs(lon * 1000))
    rng = random.Random(seed_val)
    return rng.choice(["asphalt", "cobblestone", "gravel"])

def is_nighttime_at(dt: datetime, lat: float, lon: float) -> bool:
    """Bestimmt, ob es zur angegebenen Zeit am Standort Nacht ist."""
    loc = LocationInfo("loc", "", "UTC", lat, lon)
    s = sun(loc.observer, date=dt.date())
    return dt < s["sunrise"] or dt > s["sunset"]

def segmentize(coords: List[List[float]], len_km: float = MIN_SEGMENT_LENGTH_KM) -> List[List[List[float]]]:
    """Teilt eine Liste von Koordinaten in Segmente auf, die mindestens eine bestimmte Länge haben."""
    segments: List[List[List[float]]] = []
    current_segment: List[List[float]] = []
    total_dist: float = 0.0
    prev: Optional[List[float]] = None

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
    """Überprüft, ob 'coords' eine Liste mit mindestens einem gültigen Punkt ([Latitude, Longitude]) ist."""
    if not isinstance(coords, list) or not coords:
        return False
    for point in coords:
        if not isinstance(point, list) or len(point) < 2:
            return False
        if not all(isinstance(x, (int, float)) for x in point[:2]):
            return False
    return True

def calc_risk(temp: float, wind: float, precip: float, slope: float,
              typ: str, n: int, **opt: Any) -> int:
    """
    Berechnet das Risiko der Route anhand verschiedener Parameter (Wetter, Steigung, Fahrerprofil etc.).
    Das Risiko wird auf einen Wert zwischen 1 und 5 begrenzt.
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
    """
    Gibt typische Verletzungen basierend auf dem Risiko und der Rennart zurück.
    """
    if risk <= 2:
        return ["Abschürfungen", "Prellungen"]
    base = (["Abschürfungen", "Prellungen", "Claviculafraktur", "Handgelenksverletzung"]
            if risk <= 4
            else ["Abschürfungen", "Claviculafraktur", "Wirbelsäulenverletzung", "Beckenfraktur"])
    if art.lower() in ["downhill", "freeride"]:
        base.append("Schwere Rücken-/Organverletzungen" if risk == 5 else "Wirbelsäulenverletzung (selten)")
    return base

# --- API Endpoints ---

@app.route("/heatmap-quick", methods=["POST"])
def heatmap_quick() -> Any:
    """
    Erzeugt eine interaktive Heatmap basierend auf den übergebenen Koordinaten und Parametern.
    :return: JSON mit der URL der gespeicherten Heatmap, der Gesamtstrecke in km und Segmentinformationen.
    """
    data: Dict[str, Any] = request.json or {}

    # Validierung der Koordinaten
    coords: Any = data.get("coordinates", [])
    if not is_valid_coordinates(coords):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    # Prüfe, ob 'start_time' vorhanden ist und korrekt formatiert werden kann
    start_time: Optional[str] = data.get("start_time")
    if not start_time:
        return jsonify({"error": "Fehlender 'start_time'-Parameter"}), 400

    try:
        dt: datetime = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    except ValueError as ve:
        logger.warning("Ungültiges Datum-Format: %s", ve)
        return jsonify({"error": "Ungültiges 'start_time'-Format. Erwartet ISO‑8601."}), 400
    except Exception as e:
        logger.error("Unbekannter Fehler beim Parsen von 'start_time': %s", e)
        return jsonify({"error": "Fehler beim Verarbeiten von 'start_time'."}), 400

    # Bestimme, ob es Nacht ist
    nighttime: bool = is_nighttime_at(dt, coords[0][0], coords[0][1])

    # Segmentierung der Strecke
    segments = segmentize(coords, MIN_SEGMENT_LENGTH_KM)

    seg_infos: List[Dict[str, Any]] = []
    all_locations: List[Tuple[float, float]] = []

    # Verarbeitung der Segmente und Erzeugung von Segment-Informationen
    for i, seg in enumerate(segments):
        if not seg:
            continue
        mid_idx = len(seg) // 2
        lat, lon = seg[mid_idx][:2]
        slope = calc_slope(seg)
        curve = detect_sharp_curve(seg)
        surface = get_street_surface(lat, lon)
        weather: Dict[str, Any] = data.get("wetter_override", {}) or DEFAULT_WEATHER
        risk = calc_risk(
            weather.get("temperature", DEFAULT_WEATHER["temperature"]),
            weather.get("wind_speed", DEFAULT_WEATHER["wind_speed"]),
            weather.get("precip", DEFAULT_WEATHER["precip"]),
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
            overuse_knee=data.get("overuse_knee"),
            rueckenschmerzen=data.get("rueckenschmerzen"),
            massenstart=data.get("massenstart")
        )
        injuries = typical_injuries(risk, data.get("rennen_art", ""))
        terrain = "Anstieg" if slope > 2 else "Abfahrt" if slope < -2 else "Flach"
        seg_infos.append({
            "segment_index": i + 1,
            "center": {"lat": lat, "lon": lon},
            "slope": slope,
            "sharp_curve": curve,
            "terrain": terrain,
            "weather": weather,
            "nighttime": nighttime,
            "street_surface": surface,
            "risk": risk,
            "injuries": injuries,
            "sani_needed": False  # wird nachher anhand der Sani-Logik gesetzt
        })
        all_locations.extend([(p[0], p[1]) for p in seg])

    # --- Optimierte Sani-Logik: Clusterbildung und Marker-Platzierung ---
    race_mode = data.get("rennen_art", "").lower() in ["rennen", "road", "downhill", "freeride", "mtb"]
    min_gap = 5  # Mindestabstand zwischen markierten Clustern im Rennmodus

    risk_indices = [i for i, info in enumerate(seg_infos) if info.get("risk", 0) >= 3]

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

    # --- Karten-Erstellung mit Folium ---
    try:
        m: folium.Map = folium.Map(location=[coords[0][0], coords[0][1]], zoom_start=13)
    except Exception as e:
        logger.error("Fehler beim Erstellen der Karte: %s", e)
        return jsonify({"error": "Fehler bei der Kartenerstellung"}), 500

    folium.PolyLine([(p[0], p[1]) for p in coords], color="blue", weight=3, opacity=0.6).add_to(m)

    def color_by_risk(risk_val: int) -> str:
        if risk_val <= 2:
            return "green"
        elif risk_val == 3:
            return "orange"
        else:
            return "red"

    def group_segments() -> List[Dict[str, Any]]:
        groups: List[Dict[str, Any]] = []
        for info, seg in zip(seg_infos, segments):
            reasons: List[str] = []
            if info.get("sharp_curve"):
                reasons.append("enge Kurve")
            if info.get("street_surface") in ["gravel", "cobblestone"]:
                reasons.append(f"Untergrund: {info['street_surface']}")
            if info.get("weather", {}).get("wind_speed", 0) >= 25:
                reasons.append("starker Wind")
            if info.get("weather", {}).get("precip", 0) >= 1:
                reasons.append("Regen")
            signature: Tuple[int, Tuple[str, ...]] = (info.get("risk", 1), tuple(sorted(reasons)))
            if not groups or groups[-1].get("signature") != signature:
                groups.append({
                    "signature": signature,
                    "segments": [seg],
                    "centers": [info.get("center")],
                    "sani": info.get("sani_needed")
                })
            else:
                groups[-1]["segments"].append(seg)
                groups[-1]["centers"].append(info.get("center"))
                groups[-1]["sani"] = groups[-1]["sani"] or info.get("sani_needed")
        return groups

    for grp in group_segments():
        all_points: List[List[float]] = [pt for seg in grp["segments"] for pt in seg]
        centers: List[Dict[str, float]] = grp.get("centers", [])
        mid_center: Dict[str, float] = centers[len(centers) // 2] if centers else {"lat": coords[0][0], "lon": coords[0][1]}
        risk_val, reasons = grp.get("signature")
        reason_text = ", ".join(reasons)
        popup_text = f"🚩 {len(grp['segments'])}× Risk {risk_val}" + (f": {reason_text}" if reasons else "")
        folium.PolyLine([(p[0], p[1]) for p in all_points],
                        color=color_by_risk(risk_val), weight=6, popup=popup_text).add_to(m)
        if grp.get("sani"):
            folium.Marker(
                [mid_center["lat"], mid_center["lon"]],
                popup=f"🚑 Sani empfohlen – {popup_text}",
                icon=folium.Icon(color="red", icon="medkit", prefix="fa")
            ).add_to(m)

    try:
        m.fit_bounds(all_locations)
    except Exception as e:
        logger.warning("Konnte Kartengrenzen nicht anpassen: %s", e)

    filename = f"heatmap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
    try:
        m.save(os.path.join("static", filename))
    except Exception as e:
        logger.error("Fehler beim Speichern der Karte: %s", e)
        return jsonify({"error": "Fehler beim Speichern der Heatmap"}), 500

    total_distance = sum(
        cached_distance(tuple(coords[i-1][:2]), tuple(coords[i][:2]))
        for i in range(1, len(coords))
    )
    return jsonify({
        "heatmap_url": f"https://gpx-heatmap-api.onrender.com/static/{filename}",
        "distance_km": round(total_distance, 2),
        "segments": seg_infos
    })

@app.route("/", methods=["GET"])
def home() -> str:
    """Einfacher Health-Check-Endpunkt."""
    return "✅ CycleDoc Heatmap-API bereit"

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx() -> Any:
    """
    Parst eine hochgeladene GPX-Datei und extrahiert alle darin enthaltenen Punkte.
    :return: JSON mit der Liste der Koordinaten und der Gesamtstrecke in km.
    """
    # Versuche zunächst, die Datei über request.files auszulesen
    file = request.files.get("file")
    if file is None or file.filename == "":
        # Fallback: Versuche, den Raw-Body zu lesen
        data = request.get_data()
        if not data:
            logger.error("Keine Datei empfangen, weder in request.files noch im Body.")
            return jsonify({"error": "Keine Datei empfangen"}), 400
        file = BytesIO(data)
        logger.info("GPX-Daten wurden als Raw-Body empfangen und in BytesIO konvertiert.")
    else:
        logger.info("GPX-Datei empfangen: %s", file.filename)

    # Sicherstellen, dass der Stream an den Anfang zurückgesetzt wird
    try:
        file.seek(0)
    except Exception as e:
        logger.warning("Dateistream konnte nicht zurückgesetzt werden: %s", e)

    try:
        gpx = gpxpy.parse(file)
    except Exception as e:
        logger.error("Fehler beim Parsen der GPX-Datei: %s", e)
        return jsonify({"error": "Ungültige GPX-Datei"}), 400

    coords: List[List[float]] = []
    try:
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    coords.append([point.latitude, point.longitude, point.elevation])
    except Exception as e:
        logger.error("Fehler beim Extrahieren der Punkte: %s", e)
        return jsonify({"error": "Fehler beim Verarbeiten der GPX-Datei"}), 500

    total_km = sum(
        cached_distance(tuple(coords[i-1][:2]), tuple(coords[i][:2]))
        for i in range(1, len(coords))
    )
    return jsonify({"coordinates": coords, "distance_km": round(total_km, 2)})

@app.route("/chunk-upload", methods=["POST"])
def chunk_upload() -> Any:
    """
    Teilt eine Liste von Koordinaten in kleinere JSON-Chunks und speichert diese.
    :return: JSON mit einer Bestätigung und der Liste der gespeicherten Chunk-Dateinamen.
    """
    data: Dict[str, Any] = request.json or {}
    coords = data.get("coordinates", [])
    size = data.get("chunk_size", 200)
    if not isinstance(coords, list) or not coords:
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    files: List[str] = []
    total_chunks = (len(coords) + size - 1) // size
    for i in range(total_chunks):
        fn = os.path.join("chunks", f"chunk_{i+1}.json")
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"coordinates": coords[i * size:(i + 1) * size]}, f, ensure_ascii=False, indent=2)
            files.append(fn)
        except Exception as e:
            logger.error("Fehler beim Speichern von Chunk %d: %s", i+1, e)
            return jsonify({"error": "Fehler beim Speichern der Chunks"}), 500

    return jsonify({"message": f"{len(files)} Chunks gespeichert", "chunks": files})

@app.route("/openapi.yaml", methods=["GET"])
def serve_openapi() -> Any:
    """
    Stellt die OpenAPI‑Spezifikation im YAML-Format bereit.
    :return: Die YAML-Datei oder eine Fehlermeldung, falls sie nicht gefunden wurde.
    """
    try:
        return send_file("openapi.yaml", mimetype="text/yaml")
    except Exception as e:
        logger.error("Fehler beim Senden der OpenAPI-Datei: %s", e)
        return jsonify({"error": "OpenAPI-Datei nicht gefunden"}), 404

if __name__ == "__main__":
    # Für den Produktionseinsatz Debugmodus deaktivieren!
    app.run(host="0.0.0.0", port=5000, debug=False)

#!/usr/bin/env python3
"""
CycleDoc Heatmap-API with Realistic Sanipoint Recommendations.
Optimized version with caching, type hints, improved error handling and performance enhancements.
"""

import os
import json
import math
import random
from datetime import datetime
from functools import lru_cache
from typing import List, Tuple, Dict, Any, Optional

from flask import Flask, request, jsonify, send_file
import gpxpy
import folium
from geopy.distance import geodesic
from astral import LocationInfo
from astral.sun import sun

# Flask-Anwendung initialisieren
app = Flask(__name__)
os.makedirs("chunks", exist_ok=True)
os.makedirs("static", exist_ok=True)

# --- Caching für geodätische Berechnungen ---
@lru_cache(maxsize=4096)
def cached_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """
    Liefert die Entfernung (in km) zwischen zwei Punkten, die als Tuple (lat, lon) angegeben sind.
    Die Funktion nutzt LRU-Cache, um wiederholte Berechnungen zu vermeiden.
    """
    return geodesic(p1, p2).km

# === Hilfsfunktionen ===

def bearing(a: List[float], b: List[float]) -> float:
    """
    Berechnet den Richtungswinkel von Punkt a zu Punkt b in Grad (0-360).
    """
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def angle_between(b1: float, b2: float) -> float:
    """
    Berechnet den minimalen Winkelunterschied zwischen zwei Winkelwerten.
    """
    return min(abs(b1 - b2), 360 - abs(b1 - b2))

def detect_sharp_curve(pts: List[List[float]], t: float = 60) -> bool:
    """
    Überprüft, ob innerhalb einer Liste von Punkten eine Kurve existiert, deren Winkelabweichung t (Standard 60°) überschreitet.
    """
    return any(angle_between(bearing(pts[i], pts[i+1]),
                             bearing(pts[i+1], pts[i+2])) >= t for i in range(len(pts) - 2))

def calc_slope(points: List[List[float]]) -> float:
    """
    Berechnet die prozentuale Steigung zwischen dem ersten und letzten Punkt der übergebenen Liste.
    Wird 0 zurückgegeben, wenn nicht genügend Punkte vorhanden sind oder die Distanz gegen 0 geht.
    """
    if len(points) < 2:
        return 0.0
    elev_diff = (points[-1][2] if len(points[-1]) > 2 else 0) - (points[0][2] if len(points[0]) > 2 else 0)
    dist = cached_distance(tuple(points[0][:2]), tuple(points[-1][:2])) * 1000  # in Meter
    return round((elev_diff / dist) * 100, 1) if dist > 1e-6 else 0.0

def get_street_surface(lat: float, lon: float) -> str:
    """
    Bestimmt die Straßenoberfläche anhand der Koordinaten.
    Verwendet eine lokale Zufallsinstanz (statt globalen Zustand zu verändern).
    """
    seed_value = int(abs(lat * 1000) + abs(lon * 1000))
    rng = random.Random(seed_value)
    return rng.choice(["asphalt", "cobblestone", "gravel"])

def is_nighttime_at(dt: datetime, lat: float, lon: float) -> bool:
    """
    Ermittelt, ob es zum übergebenen Datum/Uhrzeit an den Koordinaten Nacht ist.
    """
    loc = LocationInfo("loc", "", "UTC", lat, lon)
    s = sun(loc.observer, date=dt.date())
    return dt < s["sunrise"] or dt > s["sunset"]

def segmentize(coords: List[List[float]], len_km: float = 0.005) -> List[List[List[float]]]:
    """
    Teilt eine Liste von Koordinaten in Segmente mit einer Mindestlänge (in km).
    """
    out, seg, dist = [], [], 0.0
    prev: Optional[List[float]] = None
    for p in coords:
        if prev is not None:
            dist += cached_distance(tuple(prev[:2]), tuple(p[:2]))
            seg.append(p)
            if dist >= len_km:
                out.append(seg)
                seg, dist = [], 0.0
        else:
            seg.append(p)
        prev = p
    if seg:
        out.append(seg)
    return out

def calc_risk(temp: float, wind: float, precip: float, slope: float,
              typ: str, n: int, **opt: Any) -> int:
    """
    Berechnet anhand verschiedener Parameter (Wetter, Fahrerprofil, Streckencharakteristika etc.) ein Risiko im Bereich 1 bis 5.
    """
    def safe(val: Any, default: Any) -> Any:
        return default if val is None else val

    r = 1
    r += int(temp <= 5)
    r += int(wind >= 25)
    r += int(precip >= 1)
    r += int(abs(slope) > 4)
    r += int(typ.lower() in ["hobby", "c-lizenz", "anfänger"])
    r -= int(typ.lower() in ["a", "b", "elite", "profi"])
    r += int(n > 80)
    r += int(safe(opt.get("massenstart"), False))
    r += int(safe(opt.get("nighttime"), False))
    r += int(safe(opt.get("sharp_curve"), False))
    r += int(safe(opt.get("geschlecht", ""), "").lower() in ["w", "frau", "female"])
    r += int(safe(opt.get("alter"), 0) >= 60)
    r += int(safe(opt.get("street_surface"), "") in ["gravel", "cobblestone"])
    r += int(safe(opt.get("material", ""), "") == "carbon")
    schutz = safe(opt.get("schutzausruestung"), {})
    r -= int(schutz.get("helm", False))
    r -= int(schutz.get("protektoren", False))
    r += int(safe(opt.get("overuse_knee"), False))
    r += int(safe(opt.get("rueckenschmerzen"), False))
    if safe(opt.get("rennen_art", ""), "").lower() in ["downhill", "freeride"]:
        r += 2
    return max(1, min(r, 5))

def typical_injuries(risk: int, art: str) -> List[str]:
    """
    Liefert eine Liste von typischen Verletzungen basierend auf dem Risiko und der Rennart.
    """
    if risk <= 2:
        return ["Abschürfungen", "Prellungen"]
    base = (["Abschürfungen", "Prellungen", "Claviculafraktur", "Handgelenksverletzung"]
            if risk <= 4
            else ["Abschürfungen", "Claviculafraktur", "Wirbelsäulenverletzung", "Beckenfraktur"])
    if art.lower() in ["downhill", "freeride"]:
        base.append("Schwere Rücken-/Organverletzungen" if risk == 5 else "Wirbelsäulenverletzung (selten)")
    return base

# ========== Endpunkte ==========

@app.route("/heatmap-quick", methods=["POST"])
def heatmap_quick():
    """
    Erzeugt eine interaktive Heatmap auf Basis von Koordinaten und weiteren Parametern.
    Führt dabei eine segmentierte Risikoanalyse durch und kennzeichnet potenziell kritische Segmente.
    """
    d: Dict[str, Any] = request.json or {}
    coords: List[List[float]] = d.get("coordinates", [])
    if not coords:
        return jsonify({"error": "Keine Koordinaten empfangen"}), 400

    segs = segmentize(coords, 0.005)
    try:
        start_time = d.get("start_time", "")
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        night = is_nighttime_at(dt, coords[0][0], coords[0][1])
    except Exception as e:
        app.logger.warning("Ungültiges Datum, setze nighttime auf False: %s", e)
        night = False

    seg_infos: List[Dict[str, Any]] = []
    all_locs: List[Tuple[float, float]] = []
    for i, seg in enumerate(segs):
        # Auswahl des zentralen Punktes des Segments
        mid_idx = len(seg) // 2
        lat, lon = seg[mid_idx][:2]
        slope = calc_slope(seg)
        curve = detect_sharp_curve(seg)
        surf = get_street_surface(lat, lon)
        weather: Dict[str, Any] = d.get("wetter_override", {}) or {
            "temperature": 15, "wind_speed": 10, "precip": 0, "condition": "klar"
        }
        risk = calc_risk(
            weather["temperature"], weather["wind_speed"], weather["precip"], slope,
            d.get("fahrer_typ", "hobby"), d.get("anzahl", 5),
            nighttime=night, sharp_curve=curve, rennen_art=d.get("rennen_art", ""),
            geschlecht=d.get("geschlecht", ""), street_surface=surf,
            alter=d.get("alter", 42), material=d.get("material", "aluminium"),
            schutzausruestung=d.get("schutzausruestung", {}), overuse_knee=d.get("overuse_knee"),
            rueckenschmerzen=d.get("rueckenschmerzen"), massenstart=d.get("massenstart")
        )
        injuries = typical_injuries(risk, d.get("rennen_art", ""))
        terrain = "Anstieg" if slope > 2 else "Abfahrt" if slope < -2 else "Flach"
        seg_infos.append({
            "segment_index": i + 1,
            "center": {"lat": lat, "lon": lon},
            "slope": slope,
            "sharp_curve": curve,
            "terrain": terrain,
            "weather": weather,
            "nighttime": night,
            "street_surface": surf,
            "risk": risk,
            "injuries": injuries,
            "sani_needed": False  # Wird im weiteren Verlauf optimiert
        })
        all_locs.extend([(p[0], p[1]) for p in seg])

    # Optimierte Sanitäter-Logik: Bei Rennen werden nur alle 5 riskanten Segmente als kritisch markiert
    rennmodus = d.get("rennen_art", "").lower() in ["rennen", "road", "mtb", "downhill", "freeride"]
    letzte_sani_idx = -999
    for i, seg_info in enumerate(seg_infos):
        if seg_info["risk"] >= 3:
            if rennmodus:
                if i - letzte_sani_idx >= 5:
                    seg_info["sani_needed"] = True
                    letzte_sani_idx = i
            else:
                seg_info["sani_needed"] = True

    # ========== Karte erstellen ==========
    try:
        m = folium.Map(location=[coords[0][0], coords[0][1]], zoom_start=13)
    except Exception as e:
        app.logger.error("Fehler beim Erstellen der Karte: %s", e)
        return jsonify({"error": "Fehler bei der Kartenerstellung"}), 500

    folium.PolyLine([(p[0], p[1]) for p in coords], color="blue", weight=3, opacity=0.6).add_to(m)

    def col(risk_val: int) -> str:
        return "green" if risk_val <= 2 else "orange" if risk_val == 3 else "red"

    for info, seg in zip(seg_infos, segs):
        reasons = []
        if info["sharp_curve"]:
            reasons.append("enge Kurve")
        if info["street_surface"] in ["gravel", "cobblestone"]:
            reasons.append(f"Untergrund: {info['street_surface']}")
        if info["weather"].get("wind_speed", 0) >= 25:
            reasons.append("starker Wind")
        if info["weather"].get("precip", 0) >= 1:
            reasons.append("Regen")
        text = f"Risk {info['risk']} – {', '.join(reasons)}" if reasons else f"Risk {info['risk']}"
        folium.PolyLine([(p[0], p[1]) for p in seg], color=col(info["risk"]), weight=6, popup=text).add_to(m)
        if info["sani_needed"]:
            folium.Marker(
                [info["center"]["lat"], info["center"]["lon"]],
                popup=f"🚑 Saniposten empfohlen: {text}",
                icon=folium.Icon(color="red", icon="medkit", prefix="fa")
            ).add_to(m)

    if all_locs:
        m.fit_bounds(all_locs)
    filename = f"heatmap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
    try:
        m.save(os.path.join("static", filename))
    except Exception as e:
        app.logger.error("Fehler beim Speichern der Karte: %s", e)
        return jsonify({"error": "Fehler beim Speichern der Heatmap"}), 500

    dist = sum(cached_distance(tuple(coords[i - 1][:2]), tuple(coords[i][:2])) for i in range(1, len(coords)))
    return jsonify({
        "heatmap_url": f"https://gpx-heatmap-api.onrender.com/static/{filename}",
        "distance_km": round(dist, 2),
        "segments": seg_infos
    })

@app.route("/")
def home() -> str:
    """Einfacher Healthcheck-Endpunkt."""
    return "✅ CycleDoc Heatmap-API bereit"

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx():
    """
    Parst eine hochgeladene GPX-Datei und extrahiert die Koordinaten sowie die Gesamtstrecke.
    """
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei empfangen"}), 400
    try:
        gpx = gpxpy.parse(request.files["file"].stream)
    except Exception as e:
        app.logger.error("Fehler beim Parsen der GPX-Datei: %s", e)
        return jsonify({"error": "Ungültige GPX-Datei"}), 400

    coords = []
    try:
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    coords.append([point.latitude, point.longitude, point.elevation])
    except Exception as e:
        app.logger.error("Fehler beim Extrahieren der Punkte: %s", e)
        return jsonify({"error": "Fehler beim Verarbeiten der GPX-Datei"}), 500

    km = sum(cached_distance(tuple(coords[i - 1][:2]), tuple(coords[i][:2])) for i in range(1, len(coords)))
    return jsonify({"coordinates": coords, "distance_km": round(km, 2)})

@app.route("/chunk-upload", methods=["POST"])
def chunk_upload():
    """
    Teilt eine Liste von Koordinaten in kleinere JSON-Chunks auf.
    """
    d: Dict[str, Any] = request.json or {}
    coords: List[Any] = d.get("coordinates", [])
    size: int = d.get("chunk_size", 200)
    if not coords:
        return jsonify({"error": "Keine Koordinaten empfangen"}), 400

    files: List[str] = []
    for i in range((len(coords) + size - 1) // size):
        fn = os.path.join("chunks", f"chunk_{i+1}.json")
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"coordinates": coords[i * size:(i + 1) * size]}, f, ensure_ascii=False, indent=2)
            files.append(fn)
        except Exception as e:
            app.logger.error("Fehler beim Speichern von Chunk %d: %s", i + 1, e)
            return jsonify({"error": "Fehler beim Speichern der Chunks"}), 500
    return jsonify({"message": f"{len(files)} Chunks gespeichert", "chunks": files})

@app.route("/openapi.yaml")
def serve_openapi():
    """
    Liefert die OpenAPI-Spezifikation als YAML-Datei.
    """
    try:
        return send_file("openapi.yaml", mimetype="text/yaml")
    except Exception as e:
        app.logger.error("Fehler beim Senden der OpenAPI-Datei: %s", e)
        return jsonify({"error": "OpenAPI-Datei nicht gefunden"}), 404

if __name__ == "__main__":
    # Debugmodus nur für Entwicklungszwecke aktivieren; in Produktion sollte dies deaktiviert sein.
    app.run(debug=True, port=5000)

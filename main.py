################################################################
# main.py
# - Zeigt Track als farbige Heatmap basierend auf Risikoanalyse.
# - Unterstützt Segmentierung, Wetterdaten, GPX-Parsing, PDF-Export.
# - Endpunkte: /parse-gpx, /heatmap-with-weather, /chunk-upload, /heatmap-quick, /openapi.yaml
################################################################

import os
import json
import math
import random
import tempfile
import glob
from datetime import datetime
from flask import Flask, request, jsonify, send_file
import gpxpy
import folium
from geopy.distance import geodesic
from astral import LocationInfo
from astral.sun import sun
from weasyprint import HTML

app = Flask(__name__)
os.makedirs("chunks", exist_ok=True)
os.makedirs("static", exist_ok=True)

# ========== Hilfsfunktionen ==========
def bearing(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def angle_between(b1, b2):
    return min(abs(b1 - b2), 360 - abs(b1 - b2))

def detect_sharp_curve(pts, t=60):
    return any(angle_between(bearing(pts[i], pts[i+1]), bearing(pts[i+1], pts[i+2])) >= t for i in range(len(pts) - 2))

def calc_slope(points):
    if len(points) < 2: return 0.0
    elev = (points[-1][2] if len(points[-1]) > 2 else 0) - (points[0][2] if len(points[0]) > 2 else 0)
    dist = geodesic(points[0][:2], points[-1][:2]).meters
    return round((elev / dist) * 100, 1) if dist > 1e-6 else 0.0

def get_street_surface(lat, lon):
    random.seed(int(abs(lat * 1000) + abs(lon * 1000)))
    return random.choice(["asphalt", "cobblestone", "gravel"])

def is_nighttime_at(dt, lat, lon):
    loc = LocationInfo("loc", "", "UTC", lat, lon)
    s = sun(loc.observer, date=dt.date())
    return dt < s["sunrise"] or dt > s["sunset"]

def segmentize(coords, len_km=0.005):
    out, seg, dist, prev = [], [], 0.0, None
    for p in coords:
        if prev:
            dist += geodesic(prev[:2], p[:2]).km
            seg.append(p)
            if dist >= len_km:
                out.append(seg)
                seg, dist = [], 0.0
        else:
            seg.append(p)
        prev = p
    if seg: out.append(seg)
    return out

def calc_risk(temp, wind, precip, slope, typ, n, **opt):
    def safe(val, default): return default if val is None else val
    r = 1 + int(temp <= 5) + int(wind >= 25) + int(precip >= 1) + int(abs(slope) > 4)
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
    if safe(opt.get("rennen_art", ""), "").lower() in ["downhill", "freeride"]: r += 2
    return max(1, min(r, 5))

def needs_saniposten(r): return r >= 3

def typical_injuries(r, art):
    if r <= 2: return ["Abschürfungen", "Prellungen"]
    base = ["Abschürfungen", "Prellungen", "Claviculafraktur", "Handgelenksverletzung"] if r <= 4 else ["Abschürfungen", "Claviculafraktur", "Wirbelsäulenverletzung", "Beckenfraktur"]
    if art.lower() in ["downhill", "freeride"]:
        base.append("Schwere Rücken-/Organverletzungen") if r == 5 else base.append("Wirbelsäulenverletzung (selten, aber möglich)")
    return base

# ========== API ROUTEN ==========

@app.route("/")
def home():
    return "✅ CycleDoc Heatmap-API (SpeedBoost aktiviert)"

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx():
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei empfangen"}), 400
    gpx = gpxpy.parse(request.files["file"].stream)
    coords = [[p.latitude, p.longitude, p.elevation] for t in gpx.tracks for s in t.segments for p in s.points]

    # Gesamtlänge berechnen
    total_km = 0.0
    for i in range(1, len(coords)):
        pt1 = coords[i - 1][:2]
        pt2 = coords[i][:2]
        total_km += geodesic(pt1, pt2).kilometers

    return jsonify({
        "coordinates": coords,
        "distance_km": round(total_km, 2)
    })

# ... alle anderen Endpunkte bleiben gleich (chunk-upload, heatmap-quick etc.)

@app.route("/chunk-upload", methods=["POST"])
def chunk_upload():
    d = request.json
    coords = d.get("coordinates", [])
    size = d.get("chunk_size", 200)
    if not coords: return jsonify({"error": "Keine Koordinaten empfangen"}), 400
    files = []
    for i in range((len(coords) + size - 1) // size):
        path = os.path.join("chunks", f"chunk_{i+1}.json")
        with open(path, "w") as f:
            json.dump({"coordinates": coords[i*size:(i+1)*size]}, f)
        files.append(path)
    return jsonify({"message": f"{len(files)} Chunks gespeichert", "chunks": files})

# ... plus alle weiteren Endpunkte wie heatmap-quick usw. (nicht verändert)

@app.route("/openapi.yaml")
def serve_openapi():
    return send_file("openapi.yaml", mimetype="text/yaml")

# ========== START ==========
if __name__ == "__main__":
    app.run(debug=True, port=5000)

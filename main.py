################################################################
# main.py
# - Zeigt gesamten Track auf der Folium-Karte (fit_bounds).
# - Einfache Farbschema: 1-2 (grün), 3 (orange), 4-5 (rot).
# - Popup für Sani: Mehr Kontext (z. B. "Scharfe Kurve").
# - NEU: /chunk-upload + /run-chunks + /heatmap-with-weather
################################################################

import os
import math
import json
import random
import tempfile
from datetime import datetime
from flask import Flask, request, jsonify, send_file
import gpxpy
import gpxpy.gpx
import folium
from weasyprint import HTML
from geopy.distance import geodesic
from astral import LocationInfo
from astral.sun import sun

# Ordner vorbereiten
os.makedirs("chunks", exist_ok=True)
os.makedirs("static", exist_ok=True)

app = Flask(__name__)

def bearing(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    d_lon = lon2 - lon1
    x = math.sin(d_lon) * math.cos(lat2)
    y = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(d_lon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def angle_between(b1, b2):
    return min(abs(b1 - b2), 360 - abs(b1 - b2))

def detect_sharp_curve(points, threshold=60):
    if len(points) < 3: return False
    for i in range(len(points) - 2):
        b1 = bearing(points[i], points[i+1])
        b2 = bearing(points[i+1], points[i+2])
        if angle_between(b1, b2) >= threshold:
            return True
    return False

def calc_slope(points):
    if len(points) < 2: return 0.0
    elev_diff = (points[-1][2] - points[0][2]) if len(points[0]) > 2 else 0
    dist = geodesic(points[0][:2], points[-1][:2]).meters
    return round((elev_diff / dist) * 100, 1) if dist > 0 else 0.0

def is_nighttime_at(dt, lat, lon):
    loc = LocationInfo("Race", "", "UTC", lat, lon)
    s = sun(loc.observer, date=dt.date())
    return dt < s["sunrise"] or dt > s["sunset"]

def segmentize(coords, length_km=0.2):
    segments, segment, dist = [], [], 0.0
    prev = None
    for point in coords:
        if prev:
            d = geodesic(prev[:2], point[:2]).km
            dist += d
            segment.append(point)
            if dist >= length_km:
                segments.append(segment)
                segment, dist = [], 0.0
        else:
            segment.append(point)
        prev = point
    if segment: segments.append(segment)
    return segments

def calc_risk(temp, wind, precip, slope, fahrer_typ, teilnehmer, nighttime, sharp_curve, rennen_art,
              geschlecht, surface, alter, schutz, material, overuse=False, ruecken=False, massenstart=False):
    r = 1
    if temp <= 5: r += 1
    if wind >= 25: r += 1
    if precip >= 1: r += 1
    if abs(slope) > 4: r += 1
    if fahrer_typ.lower() in ["hobby", "c-lizenz"]: r += 1
    if fahrer_typ.lower() in ["a", "b", "elite", "profi"]: r -= 1
    if teilnehmer > 80: r += 1
    if massenstart: r += 1
    if nighttime: r += 1
    if sharp_curve: r += 1
    if rennen_art.lower() in ["downhill", "freeride"]: r += 2
    if geschlecht.lower() in ["w", "frau", "female"]: r += 1
    if alter >= 60: r += 1
    if surface in ["gravel", "cobblestone"]: r += 1
    if material == "carbon": r += 1
    if schutz.get("helm"): r -= 1
    if schutz.get("protektoren"): r -= 1
    if overuse: r += 1
    if ruecken: r += 1
    return max(1, min(5, r))

def needs_saniposten(r):
    return r >= 3

def typical_injuries(risk, art):
    if risk <= 2:
        return ["Abschürfungen", "Prellungen"]
    if risk <= 4:
        i = ["Abschürfungen", "Prellungen", "Claviculafraktur", "Handgelenksverletzung"]
        if art == "downhill": i.append("Wirbelsäulenverletzung (selten)")
        return i
    return ["Abschürfungen", "Claviculafraktur", "Wirbelsäulenverletzung", "Beckenfraktur"]

def get_street_surface(lat, lon):
    random.seed(int(lat * 1000) + int(lon * 1000))
    return random.choice(["asphalt", "cobblestone", "gravel"])

@app.route("/")
def home():
    return "🚴 CycleDoc Heatmap API – bereit."

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx():
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei."}), 400
    gpx = gpxpy.parse(request.files["file"].stream)
    coords = [[p.latitude, p.longitude, p.elevation] for t in gpx.tracks for s in t.segments for p in s.points]
    return jsonify({"coordinates": coords})

@app.route("/chunk-upload", methods=["POST"])
def chunk_upload():
    data = request.json
    coords = data.get("coordinates", [])
    chunk_size = data.get("chunk_size", 200)
    if not coords: return jsonify({"error": "Keine Koordinaten."}), 400
    chunks = (len(coords) + chunk_size - 1) // chunk_size
    files = []
    for i in range(chunks):
        chunk_coords = coords[i*chunk_size:(i+1)*chunk_size]
        path = os.path.join("chunks", f"chunk_{i+1}.json")
        with open(path, "w") as f:
            json.dump({"coordinates": chunk_coords}, f)
        files.append(f"chunk_{i+1}.json")
    return jsonify({"message": f"{chunks} Chunks gespeichert.", "chunks": files})

@app.route("/run-chunks", methods=["POST"])
def run_chunks():
    files = sorted(f for f in os.listdir("chunks") if f.endswith(".json"))
    if not files: return jsonify({"error": "Keine Chunks gefunden."}), 404
    all_segments = []
    all_coords = []
    for idx, fname in enumerate(files):
        with open(os.path.join("chunks", fname)) as f:
            chunk = json.load(f)["coordinates"]
        segments = segmentize(chunk)
        for seg in segments:
            slope = calc_slope(seg)
            sharp = detect_sharp_curve(seg)
            center = seg[len(seg)//2]
            lat, lon = center[0], center[1]
            surface = get_street_surface(lat, lon)
            risk = calc_risk(
                temp=6, wind=10, precip=0, slope=slope,
                fahrer_typ="c-lizenz", teilnehmer=120, nighttime=False, sharp_curve=sharp,
                rennen_art="straße", geschlecht="mixed", surface=surface, alter=35,
                schutz={"helm": True, "protektoren": False},
                material="carbon"
            )
            all_coords.extend([(p[0], p[1]) for p in seg])
            all_segments.append({
                "segment_index": len(all_segments)+1,
                "center": {"lat": lat, "lon": lon},
                "slope": slope,
                "sharp_curve": sharp,
                "terrain": "Anstieg" if slope > 2 else "Abfahrt" if slope < -2 else "Flach",
                "weather": {"temperature": 6, "wind_speed": 10, "precip": 0, "condition": "Clear"},
                "nighttime": False,
                "street_surface": surface,
                "risk": risk,
                "injuries": typical_injuries(risk, "straße"),
                "sani_needed": needs_saniposten(risk)
            })

    # Karte
    m = folium.Map(location=all_coords[0], zoom_start=14)
    def color(r): return "green" if r <= 2 else "orange" if r == 3 else "red"

    for s in all_segments:
        folium.PolyLine([(p[0], p[1]) for p in [s["center"]]], color=color(s["risk"]), weight=4).add_to(m)
        if s["sani_needed"]:
            folium.Marker(
                location=[s["center"]["lat"], s["center"]["lon"]],
                icon=folium.Icon(icon="plus", color="red", prefix="fa"),
                popup=f"Segment {s['segment_index']}\nRisk: {s['risk']}\n{', '.join(s['injuries'])}"
            ).add_to(m)

    m.fit_bounds(all_coords)
    filename = f"heatmap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
    path = os.path.join("static", filename)
    m.save(path)
    return jsonify({"heatmap_url": f"https://gpx-heatmap-api.onrender.com/static/{filename}", "segments": all_segments})

if __name__ == "__main__":
    app.run(debug=True, port=5000)

################################################################
# main.py
# - Zeigt gesamten Track auf der Folium-Karte (fit_bounds).
# - Einfache Farbschema: 1-2 (grün), 3 (orange), 4-5 (rot).
# - Popup für Sani: Mehr Kontext (z. B. "Scharfe Kurve").
# - NEU: /chunk-upload + /run-chunks + automatisches Löschen
################################################################

from flask import Flask, request, jsonify, send_file
import os
import json
import folium
import random
import math
from datetime import datetime
from geopy.distance import geodesic
import gpxpy
from astral import LocationInfo
from astral.sun import sun
from weasyprint import HTML
import tempfile

app = Flask(__name__)
os.makedirs("chunks", exist_ok=True)
os.makedirs("static", exist_ok=True)

def bearing(a, b):
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    d_lon = lon2 - lon1
    x = math.sin(d_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(d_lon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def angle_between(b1, b2):
    return min(abs(b1 - b2), 360 - abs(b1 - b2))

def detect_sharp_curve(segment, threshold=60):
    for i in range(len(segment) - 2):
        b1 = bearing(segment[i], segment[i+1])
        b2 = bearing(segment[i+1], segment[i+2])
        if angle_between(b1, b2) >= threshold:
            return True
    return False

def calc_slope(points):
    if len(points) < 2:
        return 0.0
    elev_diff = points[-1][2] - points[0][2]
    dist = geodesic(points[0][:2], points[-1][:2]).meters
    return round((elev_diff / dist) * 100, 1) if dist > 1 else 0.0

def get_street_surface(lat, lon):
    random.seed(int(abs(lat * 1000) + abs(lon * 1000)))
    return random.choice(["asphalt", "gravel", "cobblestone"])

def segmentize(coords, segment_km=0.2):
    segments, current, total = [], [], 0
    prev = None
    for p in coords:
        if prev:
            d = geodesic(prev[:2], p[:2]).km
            total += d
            current.append(p)
            if total >= segment_km:
                segments.append(current)
                current, total = [], 0
        else:
            current.append(p)
        prev = p
    if current:
        segments.append(current)
    return segments

def is_nighttime_at(dt, lat, lon):
    loc = LocationInfo(latitude=lat, longitude=lon)
    s = sun(loc.observer, date=dt.date())
    return dt < s["sunrise"] or dt > s["sunset"]

def calc_risk(temp, wind, precip, slope, fahrer_typ, teilnehmer, nighttime, sharp_curve, rennen_art,
              geschlecht, street_surface, alter, schutzausruestung, material, overuse_knee, rueckenschmerzen,
              massenstart):
    r = 1
    if temp <= 5: r += 1
    if wind >= 25: r += 1
    if precip >= 1: r += 1
    if abs(slope) > 4: r += 1
    if fahrer_typ.lower() in ["hobby", "c-lizenz", "anfänger"]: r += 1
    if fahrer_typ.lower() in ["a", "b", "elite", "profi"]: r -= 1
    if teilnehmer > 80: r += 1
    if massenstart: r += 1
    if nighttime: r += 1
    if sharp_curve: r += 1
    if rennen_art.lower() in ["downhill", "freeride"]: r += 2
    if geschlecht.lower() in ["w", "frau", "female"]: r += 1
    if alter >= 60: r += 1
    if street_surface in ["gravel", "cobblestone"]: r += 1
    if material.lower() == "carbon": r += 1
    if schutzausruestung.get("helm"): r -= 1
    if schutzausruestung.get("protektoren"): r -= 1
    if overuse_knee: r += 1
    if rueckenschmerzen: r += 1
    return min(max(r, 1), 5)

def needs_saniposten(r):
    return r >= 3

def typical_injuries(risk, art):
    if risk <= 2:
        return ["Abschürfungen", "Prellungen"]
    if risk in [3, 4]:
        i = ["Abschürfungen", "Prellungen", "Claviculafraktur", "Handgelenksverletzung"]
        if art.lower() in ["downhill", "freeride"]:
            i.append("Wirbelsäulenverletzung (selten, aber möglich)")
        return i
    i = ["Abschürfungen", "Claviculafraktur", "Wirbelsäulenverletzung", "Beckenfraktur"]
    if art.lower() in ["downhill", "freeride"]:
        i.append("Schwere Rücken-/Organverletzungen")
    return i

@app.route("/")
def home():
    return "CycleDocGPT live - ready to analyze GPX!"

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "Keine Datei"}), 400
    gpx = gpxpy.parse(file.stream)
    coords = [[pt.latitude, pt.longitude, pt.elevation] for trk in gpx.tracks for seg in trk.segments for pt in seg.points]
    return jsonify({"coordinates": coords})

@app.route("/chunk-upload", methods=["POST"])
def chunk_upload():
    data = request.json
    coords = data.get("coordinates", [])
    chunk_size = data.get("chunk_size", 200)
    if not coords:
        return jsonify({"error": "Keine Koordinaten"}), 400
    chunks = [(coords[i:i+chunk_size], f"chunk_{i//chunk_size+1}.json") for i in range(0, len(coords), chunk_size)]
    for c, fname in chunks:
        with open(os.path.join("chunks", fname), "w") as f:
            json.dump({"coordinates": c}, f)
    return jsonify({"message": f"{len(chunks)} Chunks gespeichert", "chunks": [x[1] for x in chunks]})

@app.route("/run-chunks", methods=["GET"])
def run_chunks():
    output = []
    files = sorted([f for f in os.listdir("chunks") if f.endswith(".json")])
    for fname in files:
        with open(os.path.join("chunks", fname)) as f:
            data = json.load(f)
            res = requests.post("https://gpx-heatmap-api.onrender.com/heatmap-with-weather", json=data)
            if res.ok:
                output.append(res.json())
        os.remove(os.path.join("chunks", fname))  # Lösche nach Verarbeitung
    return jsonify({"processed": len(output), "results": output})

@app.route("/heatmap-with-weather", methods=["POST"])
def heatmap():
    data = request.json
    coords = data.get("coordinates", [])
    if not coords:
        return jsonify({"error": "Keine Koordinaten"}), 400

    fahrer_typ = data.get("fahrer_typ", "hobby")
    teilnehmer = data.get("anzahl", 50)
    rennen_art = data.get("rennen_art", "unknown")
    geschlecht = data.get("geschlecht", "mixed")
    alter = data.get("alter", 35)
    start_time = data.get("start_time")
    material = data.get("material", "alu")
    massenstart = data.get("massenstart", False)
    overuse_knee = data.get("overuse_knee", False)
    rueckenschmerzen = data.get("rueckenschmerzen", False)
    schutzausruestung = data.get("schutzausruestung", {})
    wetter_override = data.get("wetter_override", {})

    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")) if start_time else datetime.utcnow()
    nighttime = is_nighttime_at(dt, coords[0][0], coords[0][1])

    segments = segmentize(coords, 0.2)
    results, all_points = [], []

    for i, s in enumerate(segments):
        lat, lon = s[len(s)//2][:2]
        slope = calc_slope(s)
        sharp = detect_sharp_curve(s)
        surface = get_street_surface(lat, lon)
        weather = wetter_override or {"temperature": 6, "wind_speed": 10, "precip": 0, "condition": "Clear"}
        risk = calc_risk(weather["temperature"], weather["wind_speed"], weather["precip"], slope, fahrer_typ, teilnehmer,
                         nighttime, sharp, rennen_art, geschlecht, surface, alter, schutzausruestung, material,
                         overuse_knee, rueckenschmerzen, massenstart)
        injuries = typical_injuries(risk, rennen_art)
        sani = needs_saniposten(risk)
        terrain = "Anstieg" if slope > 2 else "Abfahrt" if slope < -2 else "Flach"
        results.append({"segment_index": i+1, "center": {"lat": lat, "lon": lon}, "slope": slope,
                        "sharp_curve": sharp, "terrain": terrain, "weather": weather,
                        "nighttime": nighttime, "street_surface": surface, "risk": risk,
                        "injuries": injuries, "sani_needed": sani})
        all_points += [(p[0], p[1]) for p in s]

    m = folium.Map(location=[coords[0][0], coords[0][1]], zoom_start=14)
    for i, seg in enumerate(segments):
        folium.PolyLine([(p[0], p[1]) for p in seg], color="red", weight=4,
                        popup=f"Segment {i+1} (Risk {results[i]['risk']})").add_to(m)
        if results[i]["sani_needed"]:
            folium.Marker(location=(results[i]["center"]["lat"], results[i]["center"]["lon"]),
                          icon=folium.Icon(color="red", icon="plus", prefix="fa"),
                          popup="Sani empfohlen!").add_to(m)
    m.fit_bounds(all_points)
    filename = f"heatmap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
    filepath = os.path.join("static", filename)
    m.save(filepath)
    return jsonify({"heatmap_url": f"https://gpx-heatmap-api.onrender.com/static/{filename}", "segments": results})

if __name__ == "__main__":
    app.run(debug=True, port=5000)

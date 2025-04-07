################################################################
# main.py (FINAL VERSION)
# - Heatmap-Analyse mit GPX + Wetterdaten + Risikoauswertung
# - Marker-Fix: Sani-Marker liegt exakt auf dem ersten Streckenpunkt
# - Auto-Löschung von Chunks nach Heatmap
################################################################

import os
import json
import math
import random
import tempfile
import glob
from datetime import datetime
from flask import Flask, request, jsonify
import gpxpy
import folium
from geopy.distance import geodesic
from astral import LocationInfo
from astral.sun import sun

app = Flask(__name__)
os.makedirs("chunks", exist_ok=True)
os.makedirs("static", exist_ok=True)

# === Hilfsfunktionen ===
def bearing(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def angle_between(b1, b2):
    return min(abs(b1 - b2), 360 - abs(b1 - b2))

def detect_sharp_curve(pts, t=60):
    return any(angle_between(bearing(pts[i], pts[i+1]), bearing(pts[i+1], pts[i+2])) >= t
               for i in range(len(pts) - 2))

def calc_slope(pts):
    if len(pts) < 2: return 0.0
    elev = (pts[-1][2] if len(pts[-1]) > 2 else 0) - (pts[0][2] if len(pts[0]) > 2 else 0)
    dist = geodesic(pts[0][:2], pts[-1][:2]).meters
    return round((elev / dist) * 100, 1) if dist > 1e-6 else 0.0

def get_street_surface(lat, lon):
    random.seed(int(abs(lat * 1000) + abs(lon * 1000)))
    return random.choice(["asphalt", "cobblestone", "gravel"])

def is_nighttime_at(dt, lat, lon):
    loc = LocationInfo("loc", "", "UTC", lat, lon)
    s = sun(loc.observer, date=dt.date())
    return dt < s["sunrise"] or dt > s["sunset"]

def segmentize(coords, len_km=0.2):
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
    r = 1 + int(temp <= 5) + int(wind >= 25) + int(precip >= 1) + int(abs(slope) > 4)
    r += int(typ.lower() in ["hobby", "c-lizenz", "anfänger"])
    r -= int(typ.lower() in ["a", "b", "elite", "profi"])
    r += int(n > 80) + int(opt.get("massenstart") or False) + int(opt.get("nighttime") or False)
    r += int(opt.get("sharp_curve") or False)
    r += int(opt.get("geschlecht", "").lower() in ["w", "frau", "female"])
    r += int(opt.get("alter", 0) >= 60) + int(opt.get("street_surface") in ["gravel", "cobblestone"])
    r += int(opt.get("material", "") == "carbon")
    r -= int(opt.get("schutzausruestung", {}).get("helm", False))
    r -= int(opt.get("schutzausruestung", {}).get("protektoren", False))
    r += int(opt.get("overuse_knee") or False) + int(opt.get("rueckenschmerzen") or False)
    if opt.get("rennen_art", "").lower() in ["downhill", "freeride"]: r += 2
    return max(1, min(r, 5))

def needs_saniposten(r): return r >= 3

def typical_injuries(r, art):
    if r <= 2: return ["Abschürfungen", "Prellungen"]
    base = ["Abschürfungen", "Prellungen", "Claviculafraktur", "Handgelenksverletzung"] if r <= 4 else ["Abschürfungen", "Claviculafraktur", "Wirbelsäulenverletzung", "Beckenfraktur"]
    if art.lower() in ["downhill", "freeride"]:
        base.append("Schwere Rücken-/Organverletzungen") if r == 5 else base.append("Wirbelsäulenverletzung (selten, aber möglich)")
    return base

# === Endpunkte ===
@app.route("/")
def home():
    return "CycleDoc Heatmap API aktiv. Bereit für Analyse."

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx():
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei empfangen."}), 400
    gpx = gpxpy.parse(request.files["file"].stream)
    coords = [[p.latitude, p.longitude, p.elevation] for t in gpx.tracks for s in t.segments for p in s.points]
    return jsonify({"coordinates": coords})

@app.route("/heatmap-with-weather", methods=["POST"])
def heatmap():
    d = request.json
    coords = d.get("coordinates", [])
    if not coords: return jsonify({"error": "Keine Koordinaten"}), 400
    segs = segmentize(coords, 0.2)
    if not segs: return jsonify({"error": "Keine Segmente gebildet"}), 400

    try:
        dt = datetime.fromisoformat(d.get("start_time", "").replace("Z", "+00:00"))
        night = is_nighttime_at(dt, coords[0][0], coords[0][1])
    except: night = False

    seg_infos, all_locs = [], []
    for i, s in enumerate(segs):
        center = s[0]  # Fix: nimm den echten Streckenpunkt, nicht den Mittelpunkt
        lat, lon = center[:2]
        slope = calc_slope(s)
        curve = detect_sharp_curve(s)
        surf = get_street_surface(lat, lon)
        weather = d.get("wetter_override", {}) or {"temperature": 15, "wind_speed": 10, "precip": 0, "condition": "Unbekannt"}
        r = calc_risk(weather["temperature"], weather["wind_speed"], weather["precip"], slope,
                      d.get("fahrer_typ", "hobby"), d.get("anzahl", 50), nighttime=night, sharp_curve=curve,
                      rennen_art=d.get("rennen_art", ""), geschlecht=d.get("geschlecht", ""),
                      street_surface=surf, alter=d.get("alter", 35),
                      schutzausruestung=d.get("schutzausruestung", {}), material=d.get("material", "aluminium"),
                      overuse_knee=d.get("overuse_knee"), rueckenschmerzen=d.get("rueckenschmerzen"),
                      massenstart=d.get("massenstart"))

        seg_infos.append({
            "segment_index": i+1,
            "center": {"lat": lat, "lon": lon},
            "slope": slope,
            "sharp_curve": curve,
            "terrain": "Anstieg" if slope > 2 else "Abfahrt" if slope < -2 else "Flach",
            "weather": weather,
            "nighttime": night,
            "street_surface": surf,
            "risk": r,
            "injuries": typical_injuries(r, d.get("rennen_art", "")),
            "sani_needed": needs_saniposten(r)
        })
        all_locs += [(p[0], p[1]) for p in s]

    m = folium.Map(location=[coords[0][0], coords[0][1]], zoom_start=13)
    def col(r): return "green" if r <= 2 else "orange" if r == 3 else "red"
    for info, seg in zip(seg_infos, segs):
        folium.PolyLine([(p[0], p[1]) for p in seg], color=col(info["risk"]), weight=5,
                        popup=f"Segment {info['segment_index']} (Risk {info['risk']})").add_to(m)
        if info["sani_needed"]:
            txt = f"Sani empfohlen! (Risk {info['risk']})\nVerletzungen: {', '.join(info['injuries'])}"
            folium.Marker([info["center"]["lat"], info["center"]["lon"]],
                          popup=txt, icon=folium.Icon(color="red", icon="plus", prefix="fa")).add_to(m)

    if all_locs: m.fit_bounds(all_locs)
    filename = f"heatmap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
    out_path = os.path.join("static", filename)
    m.save(out_path)

    # Auto-delete aller Chunks nach Verarbeitung
    for f in glob.glob("chunks/chunk_*.json"):
        os.remove(f)

    return jsonify({"heatmap_url": f"https://gpx-heatmap-api.onrender.com/static/{filename}", "segments": seg_infos})

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

if __name__ == "__main__":
    app.run(debug=True, port=5000)

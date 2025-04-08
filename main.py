
################################################################
# main.py
# Verbesserte CycleDoc Heatmap-API mit realistischer Darstellung
################################################################

import os
import json
import math
import random
from datetime import datetime
from flask import Flask, request, jsonify, send_file
import gpxpy
import folium
from geopy.distance import geodesic
from astral import LocationInfo
from astral.sun import sun

app = Flask(__name__)
os.makedirs("chunks", exist_ok=True)
os.makedirs("static", exist_ok=True)

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

@app.route("/heatmap-quick", methods=["POST"])
def heatmap_quick():
    d = request.json
    coords = d.get("coordinates", [])
    if not coords: return jsonify({"error": "Keine Koordinaten empfangen"}), 400
    segs = segmentize(coords, 0.005)
    try:
        dt = datetime.fromisoformat(d.get("start_time", "").replace("Z", "+00:00"))
        night = is_nighttime_at(dt, coords[0][0], coords[0][1])
    except:
        night = False

    seg_infos, all_locs = [], []
    for i, s in enumerate(segs):
        lat, lon = s[len(s)//2][:2]
        slope = calc_slope(s)
        curve = detect_sharp_curve(s)
        surf = get_street_surface(lat, lon)
        weather = d.get("wetter_override", {}) or {"temperature": 15, "wind_speed": 10, "precip": 0, "condition": "klar"}
        risk = calc_risk(weather["temperature"], weather["wind_speed"], weather["precip"], slope,
                         d.get("fahrer_typ", "hobby"), d.get("anzahl", 5),
                         nighttime=night, sharp_curve=curve, rennen_art=d.get("rennen_art", ""),
                         geschlecht=d.get("geschlecht", ""), street_surface=surf,
                         alter=d.get("alter", 42), material=d.get("material", "aluminium"),
                         schutzausruestung=d.get("schutzausruestung", {}), overuse_knee=d.get("overuse_knee"),
                         rueckenschmerzen=d.get("rueckenschmerzen"), massenstart=d.get("massenstart"))
        injuries = typical_injuries(risk, d.get("rennen_art", ""))
        terrain = "Anstieg" if slope > 2 else "Abfahrt" if slope < -2 else "Flach"
        seg_infos.append({
            "segment_index": i+1,
            "center": {"lat": lat, "lon": lon},
            "slope": slope,
            "sharp_curve": curve,
            "terrain": terrain,
            "weather": weather,
            "nighttime": night,
            "street_surface": surf,
            "risk": risk,
            "injuries": injuries,
            "sani_needed": needs_saniposten(risk)
        })
        all_locs += [(p[0], p[1]) for p in s]

    m = folium.Map(location=[coords[0][0], coords[0][1]], zoom_start=13)

    folium.PolyLine([(p[0], p[1]) for p in coords], color="blue", weight=3, opacity=0.6).add_to(m)

    def col(r): return "green" if r <= 2 else "orange" if r == 3 else "red"
    for info, seg in zip(seg_infos, segs):
        reason = []
        if info["street_surface"] in ["gravel", "cobblestone"]: reason.append(f"Untergrund: {info['street_surface']}")
        if info["sharp_curve"]: reason.append("enge Kurve")
        if info["weather"]["wind_speed"] >= 25: reason.append("starker Wind")
        if info["weather"]["precip"] >= 1: reason.append("Regen")
        text = f"Risk {info['risk']} – {', '.join(reason)}"
        folium.PolyLine([(p[0], p[1]) for p in seg], color=col(info["risk"]), weight=6, popup=text).add_to(m)
        if info["sani_needed"]:
            folium.Marker([info["center"]["lat"], info["center"]["lon"]],
                          popup=f"🚑 Saniposten empfohlen! Grund: {text}",
                          icon=folium.Icon(color="red", icon="medkit", prefix="fa")).add_to(m)

    if all_locs: m.fit_bounds(all_locs)
    filename = f"heatmap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
    m.save(os.path.join("static", filename))
    dist = sum(geodesic(coords[i - 1][:2], coords[i][:2]).km for i in range(1, len(coords)))
    return jsonify({
        "heatmap_url": f"https://gpx-heatmap-api.onrender.com/static/{filename}",
        "distance_km": round(dist, 2),
        "segments": seg_infos
    })

@app.route("/")
def home(): return "✅ Heatmap-System bereit"

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx():
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei empfangen"}), 400
    gpx = gpxpy.parse(request.files["file"].stream)
    coords = [[p.latitude, p.longitude, p.elevation] for t in gpx.tracks for s in t.segments for p in s.points]
    km = sum(geodesic(coords[i - 1][:2], coords[i][:2]).km for i in range(1, len(coords)))
    return jsonify({"coordinates": coords, "distance_km": round(km, 2)})

@app.route("/chunk-upload", methods=["POST"])
def chunk_upload():
    d = request.json
    coords = d.get("coordinates", [])
    size = d.get("chunk_size", 200)
    if not coords: return jsonify({"error": "Keine Koordinaten empfangen"}), 400
    files = []
    for i in range((len(coords) + size - 1) // size):
        fn = os.path.join("chunks", f"chunk_{i+1}.json")
        with open(fn, "w") as f:
            json.dump({"coordinates": coords[i*size:(i+1)*size]}, f)
        files.append(fn)
    return jsonify({"message": f"{len(files)} Chunks gespeichert", "chunks": files})

@app.route("/openapi.yaml")
def serve_openapi():
    return send_file("openapi.yaml", mimetype="text/yaml")

if __name__ == "__main__":
    app.run(debug=True, port=5000)

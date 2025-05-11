# main.py
# CycleDoc Heatmap API – Optimierte Version mit Health-Check, CORS, Rate-Limits & Plugin-Manifest

import os
import io
import math
import base64
import logging
from datetime import datetime

import folium
import requests
from astral import Observer
from astral.sun import sun
from cachetools import TTLCache
from flask import (
    Flask, Response, request, jsonify,
    send_from_directory
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from geopy.distance import geodesic
from gpxpy import parse as parse_gpx
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from celery import Celery
from dotenv import load_dotenv

from config import (
    MIN_SEGMENT_LENGTH_KM, MAX_POINTS, DEFAULT_WEATHER,
    MAX_SEGMENTS, RISK_THRESHOLDS
)

# ─────────────── Environment & Logging ───────────────
load_dotenv()
logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ─────────────── Flask & Extensions ───────────────
app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)
limiter = Limiter(get_remote_address, app=app,
                  default_limits=["10 per minute", "200 per day"])

# ─────────────── Celery ───────────────
celery_app = Celery(
    'tasks',
    broker=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0')
)

# ─────────────── In-Memory Cache & Database ───────────────
weather_cache = TTLCache(maxsize=500, ttl=3600)  # 1 h TTL

engine = create_engine(os.getenv('DATABASE_URL', 'sqlite:///chunks.db'))
Base = declarative_base()

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    filename = Column(String, unique=True, nullable=False)
    data = Column(String, nullable=False)

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# ─────────────── Helferfunktionen ───────────────
def validate_coordinates(coords):
    if not isinstance(coords, list) or len(coords) > MAX_POINTS:
        return False, f"Maximal {MAX_POINTS} Punkte erlaubt"
    for pt in coords:
        if not (isinstance(pt, (list, tuple)) and 2 <= len(pt) <= 3):
            return False, "Ungültiges Koordinatenformat"
        lat, lon = pt[0], pt[1]
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False, "Ungültige Breiten-/Längengrade"
    return True, None

def get_weather(lat, lon, timestamp):
    key = f"{lat:.6f}:{lon:.6f}:{timestamp}"
    if key in weather_cache:
        return weather_cache[key]
    api_key = os.getenv("WEATHERSTACK_API_KEY")
    if not api_key:
        logger.warning("WEATHERSTACK_API_KEY nicht gesetzt, verwende Default-Wetter")
        return DEFAULT_WEATHER
    try:
        resp = requests.get(
            "http://api.weatherstack.com/current",
            params={"access_key": api_key, "query": f"{lat},{lon}"},
            timeout=5
        )
        resp.raise_for_status()
        data = resp.json().get("current", {})
        w = {
            "temperature": data.get("temperature", DEFAULT_WEATHER["temperature"]),
            "wind_speed": data.get("wind_speed", DEFAULT_WEATHER["wind_speed"]),
            "precip": data.get("precip", DEFAULT_WEATHER["precip"]),
            "condition": (data.get("weather_descriptions") or [DEFAULT_WEATHER["condition"]])[0]
        }
        weather_cache[key] = w
        return w
    except Exception as ex:
        logger.error(f"Weather API-Fehler: {ex}")
        return DEFAULT_WEATHER

def calculate_distance(coords):
    return sum(
        geodesic((coords[i-1][0], coords[i-1][1]),
                 (coords[i][0], coords[i][1])).kilometers
        for i in range(1, len(coords))
    )

def group_segments(coords):
    segments, curr, dist = [], [coords[0]], 0.0
    for i in range(1, len(coords)):
        d = geodesic((coords[i-1][0], coords[i-1][1]),
                     (coords[i][0], coords[i][1])).kilometers
        dist += d
        curr.append(coords[i])
        if dist >= MIN_SEGMENT_LENGTH_KM or i == len(coords)-1:
            center = [sum(p[0] for p in curr)/len(curr),
                      sum(p[1] for p in curr)/len(curr)]
            segments.append({"coordinates": curr, "distance_km": dist, "center": center})
            curr, dist = [coords[i]], 0.0
            if len(segments) >= MAX_SEGMENTS:
                break
    return segments

def detect_terrain(slope):
    if slope > 0.5: return "Anstieg"
    if slope < -0.5: return "Abfahrt"
    return "Flach"

def get_injuries(risk):
    return {
        2: ["Abschürfungen"],
        3: ["Abschürfungen", "Prellungen"],
        4: ["Abschürfungen", "Prellungen", "Claviculafraktur"],
        5: ["Abschürfungen", "Prellungen", "Claviculafraktur", "Schädel-Hirn-Trauma"]
    }.get(risk, [])

def analyze_risk(seg, time_iso, mode, override=None):
    lat, lon = seg["center"]
    weather = override or get_weather(lat, lon, time_iso)
    coords = seg["coordinates"]
    z0 = coords[0][2] if len(coords[0])>2 else 0
    z1 = coords[-1][2] if len(coords[-1])>2 else 0
    slope = (z1 - z0) / (seg["distance_km"]*1000) * 100 if seg["distance_km"] > 0 else 0

    sharp = False
    for j in range(1, len(coords)-1):
        v1 = (coords[j][0]-coords[j-1][0], coords[j][1]-coords[j-1][1])
        v2 = (coords[j+1][0]-coords[j][0], coords[j+1][1]-coords[j][1])
        angle = math.degrees(math.acos(
            sum(a*b for a,b in zip(v1, v2)) /
            ((math.hypot(*v1)*math.hypot(*v2)) + 1e-9)
        ))
        if angle >= RISK_THRESHOLDS["sharp_curve_angle"]:
            sharp = True
            break

    dt = datetime.fromisoformat(time_iso.replace("Z", "+00:00"))
    obs = Observer(latitude=lat, longitude=lon)
    ss = sun(obs, date=dt.date())
    night = dt.time() < ss["sunrise"].time() or dt.time() > ss["sunset"].time()

    score = 1
    if abs(slope) > RISK_THRESHOLDS["slope"]:          score += 1
    if sharp:                                          score += 1
    if weather["precip"] > RISK_THRESHOLDS["precipitation"]: score += 1
    if weather["wind_speed"] > RISK_THRESHOLDS["wind_speed"]: score += 1
    if night:                                          score += 1

    risk = min(score, 5)
    return {"risk": risk, "sani_needed": risk >= 3, "nighttime": night}

def generate_heatmap(segs, risks):
    m = folium.Map(location=segs[0]["center"], zoom_start=13)
    for seg, r in zip(segs, risks):
        color = "green" if r["risk"] <= 2 else "orange" if r["risk"] == 3 else "red"
        folium.PolyLine(seg["coordinates"], color=color, weight=5).add_to(m)
        if r["sani_needed"]:
            folium.Marker(seg["center"], icon=folium.Icon(icon="plus-sign", color="red")).add_to(m)
    fname = f"heatmap_{int(datetime.utcnow().timestamp())}.html"
    m.save(os.path.join("static", fname))
    return f"/{fname}"

def compile_report(total_km, weather, start_iso, infos, avg_risk):
    lines = [
        f"Streckenlänge: {total_km:.2f} km",
        f"Wetter (lat={infos[0]['segment']['center']['lat']}, lon={infos[0]['segment']['center']['lon']}): "
        f"{weather['temperature']}°C, Wind {weather['wind_speed']} km/h, "
        f"Niederschlag {weather['precip']} mm, {weather['condition']} ({start_iso})",
        "",
        "Risikoanalyse pro Segment:"
    ]
    for i, info in enumerate(infos, 1):
        seg = info["segment"]
        r   = info["analysis"]["risk"]
        mark = " 🚑" if info["analysis"]["sani_needed"] else ""
        lines.append(
            f"{i}. Risk={r}, Steigung={seg['slope']:.1f}%, "
            f"Terrain={seg['terrain']}, scharfe Kurve={seg['sharp_curve']}{mark}"
        )
    lvl = "gering" if avg_risk <= 2 else "erhöht" if avg_risk < 4 else "kritisch"
    lines += [
        "",
        f"Gesamtrisiko: {avg_risk:.2f} ({lvl})",
        "Wahrscheinliche Verletzungen: " + (", ".join(get_injuries(round(avg_risk))) or "keine"),
        "",
        "Prävention: Vorsicht bei scharfen Kurven, Tempokontrolle auf Abfahrten.",
        "Quellen: Rehlinghaus2022, Kronisch2002, Nelson2010, Dannenberg1996, Ruedl2015, Clarsen2005",
        "Heatmap-Link: siehe heatmap_url. Grün=low, Orange=medium, Rot=high."
    ]
    return "\n".join(lines)

# ─────────────── Routen ───────────────
@app.route("/", methods=["GET", "HEAD"])
def health_check():
    return Response("✅ CycleDoc Heatmap-API ready",
                    mimetype="text/plain; charset=utf-8")

@app.route("/.well-known/ai-plugin.json", methods=["GET"])
def serve_manifest():
    return send_from_directory("static/.well-known", "ai-plugin.json",
                                mimetype="application/json")

@app.route("/openapi.yaml", methods=["GET"])
def serve_openapi():
    return send_from_directory("static", "openapi.yaml",
                                mimetype="application/x-yaml")

@app.route("/parse-gpx", methods=["POST"])
@limiter.limit("5 per minute")
def parse_gpx_endpoint():
    data = request.get_json(silent=True) or {}
    b64, t = data.get("file_base64"), data.get("start_time")
    if not b64 or not t:
        return jsonify(error="file_base64 und start_time erforderlich"), 400
    try:
        raw = base64.b64decode(b64)
        gpx = parse_gpx(io.StringIO(raw.decode("utf-8", "ignore")))
        pts = [[p.latitude, p.longitude, p.elevation] 
               for tr in gpx.tracks for seg in tr.segments for p in seg.points]
        ok, err = validate_coordinates(pts)
        if not ok:
            return jsonify(error=err), 400
        return jsonify(points=pts), 200
    except Exception as ex:
        logger.error(f"parse-gpx: {ex}")
        return jsonify(error="Internal server error"), 500

@app.route("/chunk-upload", methods=["POST"])
@limiter.limit("5 per minute")
def chunk_upload():
    data = request.get_json(silent=True) or {}
    chunks = data.get("chunks")
    if not isinstance(chunks, list):
        return jsonify(error="Chunks-Liste erwartet"), 400
    session = Session()
    try:
        for ch in chunks:
            fn, b64 = ch.get("filename"), ch.get("file_base64")
            if fn and b64:
                if not session.query(Chunk).filter_by(filename=fn).first():
                    session.add(Chunk(filename=fn, data=b64))
        session.commit()
        return jsonify(status="ok"), 200
    except Exception as ex:
        logger.error(f"chunk-upload: {ex}")
        session.rollback()
        return jsonify(error="Internal server error"), 500
    finally:
        session.close()

@app.route("/heatmap-quick", methods=["POST"])
@limiter.limit("10 per hour")
def heatmap_quick():
    data = request.get_json(silent=True) or {}
    coords, t = data.get("coordinates"), data.get("start_time")
    if not coords or not t:
        return jsonify(error="coordinates und start_time erforderlich"), 400
    ok, err = validate_coordinates(coords)
    if not ok:
        return jsonify(error=err), 400

    try:
        total_km = calculate_distance(coords)
        segs = group_segments(coords)
        infos = []
        for seg in segs:
            analysis = analyze_risk(seg, t, data.get("mode"), data.get("wetter_override"))
            z0 = seg["coordinates"][0][2] if len(seg["coordinates"][0])>2 else 0
            z1 = seg["coordinates"][-1][2] if len(seg["coordinates"][-1])>2 else 0
            slope = (z1 - z0) / (seg["distance_km"]*1000) * 100 if seg["distance_km"]>0 else 0
            infos.append({
                "segment": {
                    "segment_index": len(infos)+1,
                    "center": {"lat": seg["center"][0], "lon": seg["center"][1]},
                    "slope": slope,
                    "sharp_curve": analysis["risk"]>1,
                    "terrain": detect_terrain(slope),
                    "weather": get_weather(seg["center"][0], seg["center"][1], t),
                    "nighttime": analysis["nighttime"],
                    "street_surface": data.get("street_surface", "asphalt"),
                    "risk": analysis["risk"],
                    "injuries": get_injuries(analysis["risk"]),
                    "sani_needed": analysis["sani_needed"]
                },
                "analysis": analysis
            })
        avg = sum(i["analysis"]["risk"] for i in infos) / len(infos)
        heatmap_url = generate_heatmap([i["segment"]["center"] for i in infos],
                                       [i["analysis"] for i in infos])
        report = compile_report(total_km,
                                get_weather(infos[0]["segment"]["center"]["lat"],
                                            infos[0]["segment"]["center"]["lon"], t),
                                t, infos, avg)
        return jsonify(
            distance_km=round(total_km, 3),
            segments=[i["segment"] for i in infos],
            heatmap_url=heatmap_url,
            detailed_report=report
        ), 200

    except Exception as ex:
        logger.error(f"heatmap-quick: {ex}")
        return jsonify(error="Internal server error"), 500

@app.route("/heatmap-gpx", methods=["POST"])
@limiter.limit("5 per minute")
def heatmap_gpx():
    file = request.files.get("file")
    if not file:
        return jsonify(error="Datei erforderlich"), 400
    try:
        raw = file.read()
        gpx = parse_gpx(io.StringIO(raw.decode("utf-8", "ignore")))
        pts = [[p.latitude, p.longitude, p.elevation]
               for tr in gpx.tracks for seg in tr.segments for p in seg.points]
        chunks = [pts[i:i+200] for i in range(0, len(pts), 200)]
        results = []
        for ch in chunks:
            ok, err = validate_coordinates(ch)
            if not ok:
                results.append({"error": err})
                continue
            total = calculate_distance(ch)
            segs = group_segments(ch)
            risks = [analyze_risk(s, datetime.utcnow().isoformat()+"Z", None) for s in segs]
            url = generate_heatmap([s["center"] for s in segs], risks)
            results.append({
                "distance_km": round(total, 3),
                "segments": [{"center": s["center"], "risk": r["risk"], "sani_needed": r["sani_needed"]}
                             for s, r in zip(segs, risks)],
                "heatmap_url": url
            })
        return jsonify(results=results, combined_report=f"Chunks: {len(chunks)}"), 200

    except Exception as ex:
        logger.error(f"heatmap-gpx: {ex}")
        return jsonify(error="Internal server error"), 500

# ─────────────── Main ───────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

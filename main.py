# main.py
# CycleDoc Heatmap API mit vollständiger Implementierung, Static-Serving und Health-Check

import os
import base64
import io
import math
import folium
import requests
import json
import logging
from datetime import datetime
from astral.sun import sun
from astral import Observer
from cachetools import TTLCache
from flask import Flask, request, jsonify, send_from_directory
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
    MIN_SEGMENT_LENGTH_KM, MAX_POINTS, DEFAULT_WEATHER, MAX_SEGMENTS,
    RISK_THRESHOLDS
)

# Environment laden
load_dotenv()

# Logging konfigurieren
logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Flask-Setup: static_folder als Root
app = Flask(__name__, static_folder="static", static_url_path="")
limiter = Limiter(get_remote_address, app=app,
                  default_limits=["10 per minute", "200 per day"])

# Celery-Setup
celery_app = Celery(
    'tasks',
    broker=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0')
)

# Wetter-Cache (TTL: 1h)
weather_cache = TTLCache(maxsize=100, ttl=3600)

# Datenbank für Chunks
engine = create_engine(os.getenv('DATABASE_URL', 'sqlite:///chunks.db'))
Base = declarative_base()

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    filename = Column(String, unique=True)
    data = Column(String)

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# Health-Check Endpoint
@app.route('/', methods=['GET'])
def health_check():
    return '✅ CycleDoc Heatmap-API ready', 200

# Serve OpenAPI spec
@app.route("/openapi.yaml")
def serve_openapi():
    return send_from_directory("static", "openapi.yaml")

# Helferfunktionen
def validate_coordinates(coords):
    if not isinstance(coords, list) or len(coords) > MAX_POINTS:
        return False, f"Maximal {MAX_POINTS} Punkte erlaubt"
    for c in coords:
        if not (isinstance(c, list) and len(c) >= 2):
            return False, "Ungültiges Koordinatenformat"
        lat, lon = c[0], c[1]
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False, "Ungültige Breiten-/Längengrade"
    return True, None

def get_weather(lat, lon, timestamp):
    key = f"{lat}:{lon}:{timestamp}"
    if key in weather_cache:
        return weather_cache[key]
    api_key = os.getenv("WEATHERSTACK_API_KEY")
    if not api_key:
        logger.warning("WEATHERSTACK_API_KEY nicht gesetzt, Default-Wetter")
        return DEFAULT_WEATHER
    try:
        resp = requests.get(
            "http://api.weatherstack.com/current",
            params={"access_key": api_key, "query": f"{lat},{lon}"},
            timeout=5
        )
        resp.raise_for_status()
        d = resp.json()
        w = {
            "temperature": d["current"]["temperature"],
            "wind_speed": d["current"]["wind_speed"],
            "precip": d["current"]["precip"],
            "condition": d["current"]["weather_descriptions"][0]
        }
        weather_cache[key] = w
        return w
    except Exception as e:
        logger.error(f"Weather API Fehler: {e}")
        return DEFAULT_WEATHER

def calculate_distance(coords):
    dist = 0.0
    for i in range(1, len(coords)):
        dist += geodesic((coords[i-1][0], coords[i-1][1]),
                         (coords[i][0], coords[i][1])).kilometers
    return dist

def group_segments(coords):
    segments = []
    curr_seg = [coords[0]]
    curr_dist = 0.0
    for i in range(1, len(coords)):
        d = geodesic((coords[i-1][0], coords[i-1][1]),
                     (coords[i][0], coords[i][1])).kilometers
        curr_dist += d
        curr_seg.append(coords[i])
        if curr_dist >= MIN_SEGMENT_LENGTH_KM or i == len(coords)-1:
            center = [
                sum(p[0] for p in curr_seg)/len(curr_seg),
                sum(p[1] for p in curr_seg)/len(curr_seg)
            ]
            segments.append({
                "coordinates": curr_seg,
                "distance_km": curr_dist,
                "center": center
            })
            curr_seg = [coords[i]]
            curr_dist = 0.0
        if len(segments) >= MAX_SEGMENTS:
            break
    return segments

def detect_terrain(slope):
    if slope > 0.5:
        return "Anstieg"
    if slope < -0.5:
        return "Abfahrt"
    return "Flach"

def get_injuries(risk):
    mapping = {
        1: [],
        2: ["Abschürfungen"],
        3: ["Abschürfungen", "Prellungen"],
        4: ["Abschürfungen", "Prellungen", "Claviculafraktur"],
        5: ["Abschürfungen", "Prellungen", "Claviculafraktur", "Schädel-Hirn-Trauma"]
    }
    return mapping.get(risk, [])

def analyze_risk(segment, start_time, mode, wetter_override=None):
    center = segment["center"]
    weather = wetter_override or get_weather(center[0], center[1], start_time)
    coords = segment["coordinates"]
    elev_start = coords[0][2] if len(coords[0]) > 2 else 0
    elev_end   = coords[-1][2] if len(coords[-1]) > 2 else 0
    elev_diff  = elev_end - elev_start
    slope = (elev_diff / (segment["distance_km"]*1000) * 100) if segment["distance_km"] > 0 else 0

    # Sharp curve detection
    sharp = False
    for j in range(1, len(coords)-1):
        v1 = (coords[j][0]-coords[j-1][0], coords[j][1]-coords[j-1][1])
        v2 = (coords[j+1][0]-coords[j][0], coords[j+1][1]-coords[j][1])
        angle = math.degrees(math.acos(
            sum(a*b for a,b in zip(v1,v2)) /
            ((math.hypot(*v1)*math.hypot(*v2))+1e-10)
        ))
        if angle >= RISK_THRESHOLDS["sharp_curve_angle"]:
            sharp = True
            break

    dt = datetime.fromisoformat(start_time.replace("Z","+00:00"))
    obs = Observer(latitude=center[0], longitude=center[1])
    s   = sun(obs, date=dt.date())
    is_night = dt.time() < s['sunrise'].time() or dt.time() > s['sunset'].time()

    # Risk scoring
    risk = 1
    if abs(slope) > RISK_THRESHOLDS['slope']: risk += 1
    if sharp: risk += 1
    if weather['precip'] > RISK_THRESHOLDS['precipitation']: risk += 1
    if weather['wind_speed'] > RISK_THRESHOLDS['wind_speed']: risk += 1
    if is_night: risk += 1

    sani_needed = (risk >= 3)
    return {
        "risk": min(risk, 5),
        "sani_needed": sani_needed,
        "nighttime": is_night
    }

def generate_heatmap(segments, risks, mode):
    m = folium.Map(location=segments[0]['center'], zoom_start=13)
    markers = []
    for idx, seg in enumerate(segments):
        clr = 'green' if risks[idx]['risk'] <= 2 else 'orange' if risks[idx]['risk'] == 3 else 'red'
        folium.PolyLine(seg['coordinates'], color=clr, weight=5).add_to(m)
        if risks[idx]['sani_needed']:
            markers.append(seg['center'])
    for coord in markers:
        folium.Marker(coord, icon=folium.Icon(icon='plus-sign', color='red')).add_to(m)
    fname = f"heatmap_{int(datetime.utcnow().timestamp())}.html"
    m.save(os.path.join('static', fname))
    return f"/{fname}"

def compile_report(distance_km, weather, start_time, segments_info, overall_risk):
    report = f"Route Length: The route covers {distance_km:.2f} km.\n"
    rep = segments_info[0]["segment"]["center"]
    report += (f"Weather Conditions: Representative Point: (Lat: {rep['lat']}, Lon: {rep['lon']}) "
               f"Date and Time: {start_time}\n"
               f"Temperature: {weather['temperature']}°C, Wind: {weather['wind_speed']} km/h, "
               f"Precipitation: {weather['precip']} mm, Condition: {weather['condition']}\n"
               f"Source: WeatherStack ({datetime.utcnow().date()})\n")
    report += "Risk Assessment per Segment:\n"
    for idx, info in enumerate(segments_info, start=1):
        seg = info["segment"]
        r   = info["analysis"]["risk"]
        line = (f"Segment {idx}: Risk: {r} (Slope: {seg['slope']:.1f}%, Terrain: {seg['terrain']}, "
                f"sharp_curve: {seg['sharp_curve']})")
        if info["analysis"]["sani_needed"]:
            line += " – 🚑 Sanitäter empfohlen"
        report += line + "\n"
    report += (f"Overall Risk: Average Risk Score: {overall_risk:.2f} "
               f"({'gering' if overall_risk <= 2 else 'erhöht' if overall_risk < 4 else 'kritisch'})\n")
    inj = get_injuries(round(overall_risk))
    if inj:
        report += "Likely Injuries: " + ", ".join(inj) + "\n"
    else:
        report += "Dazu liegen keine Informationen vor.\n"
    report += "Prevention Recommendations: Vorsicht bei scharfen Kurven, langsam auf steilen Abfahrten fahren.\n"
    report += ("Sources: Scientific Sources: (Rehlinghaus 2022), (Kronisch 2002, S. 5), "
               "(Nelson 2010), (Dannenberg 1996), (Ruedl 2015), (Clarsen 2005). Weather Data: WeatherStack\n")
    report += ("Interactive Map Details: See `heatmap_url` in response. "
               "Color Scale: green = low, orange = medium, red = high. 🚑 markers indicate segments "
               "where paramedics are recommended.")
    return report

# GPX parsing
@app.route('/parse-gpx', methods=['POST'])
@limiter.limit("5 per minute")
def parse_gpx_endpoint():
    data = request.get_json() or {}
    b64 = data.get('file_base64')
    start_time = data.get('start_time')
    if not b64 or not start_time:
        return jsonify(error="file_base64 und start_time erforderlich."), 400
    try:
        raw = base64.b64decode(b64)
        gpx = parse_gpx(io.StringIO(raw.decode()))
        points = []
        for tr in gpx.tracks:
            for seg in tr.segments:
                for p in seg.points:
                    points.append([p.latitude, p.longitude, p.elevation])
        valid, err = validate_coordinates(points)
        if not valid:
            return jsonify(error=err), 400
        return jsonify(points=points), 200
    except Exception as e:
        logger.error(f"Parse-GPX Fehler: {e}")
        return jsonify(error="Internal server error"), 500

# Chunk upload
@app.route('/chunk-upload', methods=['POST'])
@limiter.limit("5 per minute")
def chunk_upload():
    data = request.get_json() or {}
    chunks = data.get('chunks')
    if not isinstance(chunks, list):
        return jsonify(error="Chunks-Liste erwartet."), 400
    session = Session()
    try:
        for ch in chunks:
            filename = ch.get('filename')
            b64 = ch.get('file_base64')
            if filename and b64:
                rec = session.query(Chunk).filter_by(filename=filename).first()
                if not rec:
                    session.add(Chunk(filename=filename, data=b64))
        session.commit()
        return jsonify(status="ok"), 200
    except Exception as e:
        logger.error(f"Chunk-Upload Fehler: {e}")
        session.rollback()
        return jsonify(error="Internal server error"), 500
    finally:
        session.close()

# Heatmap quick
@app.route('/heatmap-quick', methods=['POST'])
@limiter.limit("10 per hour")
def heatmap_quick():
    data = request.get_json() or {}
    coords = data.get('coordinates')
    start_time = data.get('start_time')
    mode = data.get('mode', 'privat')
    surface = data.get('street_surface', 'asphalt')
    if not coords or not start_time:
        return jsonify(error="coordinates und start_time erforderlich."), 400
    valid, err = validate_coordinates(coords)
    if not valid:
        return jsonify(error=err), 400
    try:
        total_km = calculate_distance(coords)
        segs = group_segments(coords)
        segments_info = []
        for seg in segs:
            analysis = analyze_risk(seg, start_time, mode, data.get('wetter_override'))
            center = seg['center']
            elev_diff = (seg['coordinates'][-1][2] - seg['coordinates'][0][2]) if len(seg['coordinates'][0]) > 2 else 0
            slope = (elev_diff / (seg['distance_km']*1000) * 100) if seg['distance_km'] > 0 else 0
            terrain = detect_terrain(slope)
            segments_info.append({
                "segment": {
                    "segment_index": len(segments_info) + 1,
                    "center": {"lat": center[0], "lon": center[1]},
                    "slope": slope,
                    "sharp_curve": analysis['risk'] > 1,
                    "terrain": terrain,
                    "weather": get_weather(center[0], center[1], start_time),
                    "nighttime": analysis['nighttime'],
                    "street_surface": surface,
                    "risk": analysis['risk'],
                    "injuries": get_injuries(analysis['risk']),
                    "sani_needed": analysis['sani_needed']
                },
                "analysis": analysis
            })
        risks = [i['analysis'] for i in segments_info]
        overall = sum(r['risk'] for r in risks) / len(risks)
        heatmap_url = generate_heatmap([i['segment']['center'] for i in segments_info], risks, mode)
        report = compile_report(total_km, get_weather(
            segments_info[0]['segment']['center']['lat'],
            segments_info[0]['segment']['center']['lon'],
            start_time
        ), start_time, segments_info, overall)
        return jsonify(
            distance_km=round(total_km, 3),
            segments=[i['segment'] for i in segments_info],
            heatmap_url=heatmap_url,
            detailed_report=report
        ), 200
    except Exception as e:
        logger.error(f"Heatmap-Quick Fehler: {e}")
        return jsonify(error="Internal server error"), 500

# Heatmap from GPX with chunking
@app.route('/heatmap-gpx', methods=['POST'])
@limiter.limit("5 per minute")
def heatmap_gpx():
    file = request.files.get('file')
    if not file:
        return jsonify(error="Datei erforderlich."), 400
    try:
        raw = file.read()
        gpx = parse_gpx(io.StringIO(raw.decode()))
        points = [
            [p.latitude, p.longitude, p.elevation]
            for tr in gpx.tracks for s in tr.segments for p in s.points
        ]
        chunks = [points[i:i+200] for i in range(0, len(points), 200)]
        results = []
        for ch in chunks:
            valid, err = validate_coordinates(ch)
            if not valid:
                results.append({"error": err})
                continue
            total_km = calculate_distance(ch)
            segs = group_segments(ch)
            risks = [analyze_risk(seg, datetime.utcnow().isoformat()+"Z", 'privat') for seg in segs]
            heatmap = generate_heatmap([seg['center'] for seg in segs], risks, 'privat')
            results.append({
                "distance_km": round(total_km, 3),
                "segments": [
                    {"center": seg['center'], "risk": r['risk'], "sani_needed": r['sani_needed']}
                    for seg, r in zip(segs, risks)
                ],
                "heatmap_url": heatmap
            })
        combined_report = f"Total Chunks: {len(chunks)}"
        return jsonify(results=results, combined_report=combined_report), 200
    except Exception as e:
        logger.error(f"Heatmap-GPX Fehler: {e}")
        return jsonify(error="Internal server error"), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

# main.py
# CycleDoc Heatmap API mit erweiterter Spec-Übereinstimmung

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
from cachetools import TTLCache
from flask import Flask, request, jsonify, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from geopy.distance import geodesic
from gpxpy import parse as parse_gpx
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from celery import Celery
from config import (
    MIN_SEGMENT_LENGTH_KM, MAX_POINTS, DEFAULT_WEATHER, MAX_SEGMENTS,
    RISK_THRESHOLDS, HEATMAP_SIZE
)

# Logging konfigurieren
logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Flask-Setup
app = Flask(__name__)
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

# SQLite für Chunks
engine = create_engine(os.getenv('DATABASE_URL', 'sqlite:///chunks.db'))
Base = declarative_base()

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    filename = Column(String, unique=True)
    data = Column(String)

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# Helfer­funktionen

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
            center = [sum(p[0] for p in curr_seg)/len(curr_seg),
                      sum(p[1] for p in curr_seg)/len(curr_seg)]
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


def compile_report(distance_km, weather, start_time, segments_info, overall_risk):
    # Abschnitt 0
    report = f"Route Length: The route covers {distance_km:.2f} km.\n"
    # Abschnitt 1
    rep = segments_info[0]["segment"]["center"]
    report += (f"Weather Conditions: Representative Point: (Lat: {rep[0]}, Lon: {rep[1]}) "
                 f"Date and Time: {start_time}\n"
               f"Temperature: {weather['temperature']}°C, Wind: {weather['wind_speed']} km/h, "
                 f"Precipitation: {weather['precip']} mm, Condition: {weather['condition']}\n"
               f"Source: WeatherStack ({datetime.utcnow().date()})\n")
    # Abschnitt 2
    report += "Risk Assessment per Segment:\n"
    for idx, info in enumerate(segments_info, start=1):
        seg = info["segment"]
        r = info["analysis"]["risk"]
        line = (f"Segment {idx}: Risk: {r} (Slope: {seg['slope']:.1f}%, Terrain: {seg['terrain']}, "
                f"sharp_curve: {seg['sharp_curve']})")
        if info["analysis"]["sani_needed"]:
            line += " – 🚑 Sanitäter empfohlen"
        report += line + "\n"
    # Abschnitt 3
    report += (f"Overall Risk: Average Risk Score: {overall_risk:.2f} "
               f"({'gering' if overall_risk<=2 else 'erhöht' if overall_risk<4 else 'kritisch'})\n")
    # Abschnitt 4
    report += "Likely Injuries: " + ", ".join(get_injuries(round(overall_risk)))
    report += "\n" if get_injuries(round(overall_risk)) else "Dazu liegen keine Informationen vor.\n"
    # Abschnitt 5
    report += "Prevention Recommendations: Vorsicht bei scharfen Kurven, langsam auf steilen Abfahrten fahren.\n"
    # Abschnitt 6
    report += ("Sources: Scientific Sources: (Rehlinghaus 2022), (Kronisch 2002, S. 5), "
               "(Nelson 2010), (Dannenberg 1996), (Ruedl 2015), (Clarsen 2005). Weather Data: WeatherStack\n")
    # Abschnitt 7
    report += "Interactive Map Details: See `heatmap_url` in response. Color Scale: green = low, orange = medium, red = high. "
               "🚑 markers indicate segments where paramedics are recommended."  
    return report

# API-Endpunkte

@app.route('/heatmap-quick', methods=['POST'])
@limiter.limit("10 per hour")
def heatmap_quick():
    data = request.get_json() or {}
    coords = data.get('coordinates')
    start_time = data.get('start_time')
    mode = data.get('mode', 'privat')
    if not coords or not start_time:
        return jsonify(error="coordinates und start_time sind erforderlich."), 400
    valid, err = validate_coordinates(coords)
    if not valid:
        return jsonify(error=err), 400
    try:
        total_km = calculate_distance(coords)
        segments = group_segments(coords)
        segments_info = []
        for seg in segments:
            analysis = analyze_risk(seg, start_time, mode, data.get('wetter_override'))
            center = seg['center']
            elev_diff = (seg['coordinates'][-1][2] - seg['coordinates'][0][2]) if len(seg['coordinates'][0])>2 else 0
            slope = (elev_diff / (seg['distance_km']*1000) * 100) if seg['distance_km']>0 else 0
            terrain = detect_terrain(slope)
            segments_info.append({
                "segment": {
                    "segment_index": len(segments_info)+1,
                    "center": {"lat": center[0], "lon": center[1]},
                    "slope": slope,
                    "sharp_curve": analysis['risk']>1,
                    "terrain": terrain,
                    "weather": get_weather(center[0], center[1], start_time),
                    "nighttime": analysis.get('nighttime', False),
                    "street_surface": data.get('street_surface', 'asphalt'),
                    "risk": analysis['risk'],
                    "injuries": get_injuries(analysis['risk']),
                    "sani_needed": analysis['sani_needed']
                },
                "analysis": analysis
            })
        risks = [info['analysis'] for info in segments_info]
        overall = sum(r['risk'] for r in risks)/len(risks)
        # Heatmap generieren
        heatmap_file = generate_heatmap([info['segment']['center'] for info in segments_info], risks, mode)
        report = compile_report(total_km, get_weather(
            segments_info[0]['segment']['center']['lat'],
            segments_info[0]['segment']['center']['lon'],
            start_time
        ), start_time, segments_info, overall)
        return jsonify(
            distance_km=round(total_km,3),
            segments=[info['segment'] for info in segments_info],
            heatmap_url=heatmap_file,
            detailed_report=report
        ), 200
    except Exception as e:
        logger.error(f"Heatmap-Quick Fehler: {e}")
        return jsonify(error="Internal server error"), 500

# weitere Endpunkte (/parse-gpx, /chunk-upload, /heatmap-gpx) bleiben unverändert…

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

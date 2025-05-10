# main.py
# CycleDoc Heatmap API with GPX chunking support

import os
import json
import folium
import gpxpy
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from celery import Celery
from config import (
    MIN_SEGMENT_LENGTH_KM, MAX_POINTS, MAX_SEGMENTS, DEFAULT_WEATHER,
    VALID_FAHRER_TYPES, VALID_RENNEN_ART, VALID_GESCHLECHT, VALID_MATERIAL, VALID_STREET_SURFACE
)

# Flask app setup
app = Flask(__name__)

# Flask-Limiter setup (using Redis)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=os.getenv("REDIS_URL", "redis://localhost:6379")
)

# Celery setup
celery_app = Celery(
    app.name,
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# WeatherStack API setup
WEATHERSTACK_API_KEY = os.getenv("WEATHERSTACK_API_KEY")

def fetch_weather(lat, lon, start_time):
    """Fetch weather data for a given location and time."""
    if not WEATHERSTACK_API_KEY:
        return DEFAULT_WEATHER
    try:
        params = {
            "access_key": WEATHERSTACK_API_KEY,
            "query": f"{lat},{lon}",
            "historical_date": start_time.split("T")[0],
            "hourly": 1
        }
        response = requests.get("http://api.weatherstack.com/historical", params=params)
        response.raise_for_status()
        data = response.json()
        historical = data["historical"][start_time.split("T")[0]]
        hour = int(start_time.split("T")[1].split(":")[0])
        weather = historical["hourly"][hour // 3]
        return {
            "temperature": weather["temperature"],
            "wind_speed": weather["wind_speed"],
            "precip": weather["precip"],
            "condition": weather["weather_descriptions"][0]
        }
    except Exception as e:
        print(f"Weather API error: {e}")
        return DEFAULT_WEATHER

@celery_app.task
def generate_heatmap_task(coordinates, weather, fahrer_typ, geschlecht, anzahl):
    """Generate heatmap and risk analysis for a chunk of coordinates."""
    # Placeholder for heatmap generation
    m = folium.Map(location=[coordinates[0][0], coordinates[0][1]], zoom_start=13)
    folium.PolyLine(
        locations=[[point[0], point[1]] for point in coordinates],
        color="red",
        weight=5
    ).add_to(m)
    
    # Placeholder for risk analysis
    risk_score = 50  # Simplified example
    if weather["wind_speed"] > 20:
        risk_score += 10
    if weather["precip"] > 0:
        risk_score += 15
    if fahrer_typ in ["anfänger"]:
        risk_score += 10
    
    # Save heatmap to a file (simplified for Render)
    heatmap_path = f"/tmp/heatmap_{generate_heatmap_task.request.id}.html"
    m.save(heatmap_path)
    return {
        "heatmap_url": heatmap_path,  # In production, upload to S3 or similar
        "risk_score": risk_score,
        "distance_km": len(coordinates) * 0.1  # Simplified distance calculation
    }

def process_gpx_in_chunks(gpx_data, chunk_size=200):
    """Split GPX data into chunks and process them separately."""
    try:
        gpx = gpxpy.parse(gpx_data)
        all_points = []
        for track in gpx.tracks:
            for segment in track.segments:
                all_points.extend(segment.points)

        if len(all_points) > MAX_POINTS:
            return {"error": f"Too many points ({len(all_points)}). Max allowed: {MAX_POINTS}"}, 400

        # Split points into chunks
        chunks = [all_points[i:i + chunk_size] for i in range(0, len(all_points), chunk_size)]
        results = []
        for chunk in chunks:
            # Convert chunk to coordinates format
            coordinates = [[point.latitude, point.longitude, point.elevation or 0] for point in chunk]
            if len(coordinates) < 2:
                continue

            # Fetch weather for the first point in the chunk
            weather = fetch_weather(coordinates[0][0], coordinates[0][1], "2025-05-11T10:00:00Z")
            # Simplified: Use default values for fahrer_typ, geschlecht, anzahl
            result = generate_heatmap_task.delay(coordinates, weather, "hobby", "m", 2)
            results.append(result.id)
        return results, 202
    except Exception as e:
        return {"error": f"Failed to process GPX: {str(e)}"}, 500

@app.route("/heatmap-quick", methods=["POST"])
@limiter.limit("10 per minute")
def heatmap_quick():
    """Generate heatmap from coordinates."""
    try:
        data = request.get_json()
        coordinates = data.get("coordinates", [])
        start_time = data.get("start_time", datetime.utcnow().isoformat() + "Z")
        anzahl = data.get("anzahl", 1)
        geschlecht = data.get("geschlecht", "m")
        fahrer_typ = data.get("fahrer_typ", "hobby")

        # Validate inputs
        if not coordinates or len(coordinates) < 2:
            return jsonify({"error": "At least 2 coordinates required"}), 400
        if fahrer_typ not in VALID_FAHRER_TYPES:
            return jsonify({"error": f"Invalid fahrer_typ. Must be one of {VALID_FAHRER_TYPES}"}), 400
        if geschlecht not in VALID_GESCHLECHT:
            return jsonify({"error": f"Invalid geschlecht. Must be one of {VALID_GESCHLECHT}"}), 400

        # Fetch weather
        weather = fetch_weather(coordinates[0][0], coordinates[0][1], start_time)

        # Split into segments if necessary
        if len(coordinates) > MAX_SEGMENTS:
            coordinates = coordinates[:MAX_SEGMENTS]

        # Generate heatmap asynchronously
        task = generate_heatmap_task.delay(coordinates, weather, fahrer_typ, geschlecht, anzahl)
        return jsonify({"task_id": task.id, "status": "Processing"}), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/heatmap-gpx", methods=["POST"])
@limiter.limit("5 per minute")
def heatmap_gpx():
    """Generate heatmap from GPX file with chunking."""
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if not file.filename.endswith(".gpx"):
            return jsonify({"error": "File must be a .gpx file"}), 400

        gpx_data = file.read().decode("utf-8")
        task_ids, status = process_gpx_in_chunks(gpx_data, chunk_size=200)
        if status != 202:
            return jsonify(task_ids), status

        return jsonify({"task_ids": task_ids, "status": "Processing"}), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/task/<task_id>", methods=["GET"])
def task_status(task_id):
    """Check the status of a Celery task."""
    task = celery_app.AsyncResult(task_id)
    if task.state == "PENDING":
        return jsonify({"task_id": task_id, "status": "Pending"}), 200
    elif task.state != "SUCCESS":
        return jsonify({"task_id": task_id, "status": task.state, "error": str(task.result)}), 500
    else:
        return jsonify({"task_id": task_id, "status": "Success", "result": task.result}), 200

@app.route("/", methods=["GET"])
def index():
    """Root endpoint for health check."""
    return jsonify({"status": "CycleDoc Heatmap API is running"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

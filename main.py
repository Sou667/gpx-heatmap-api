from flask import Flask, request, jsonify
import folium
from folium.plugins import HeatMap
import os
from datetime import datetime
from geopy.distance import geodesic
import requests

app = Flask(__name__)

@app.route('/')
def home():
    return 'GPX Heatmap API läuft!'

# 🔹 Route 1: klassische Heatmap
@app.route('/heatmap', methods=['POST'])
def generate_heatmap():
    data = request.json
    coordinates = data.get("coordinates", [])

    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    center = coordinates[0]  # Mittelpunkt setzen
    m = folium.Map(location=center, zoom_start=13)
    HeatMap(coordinates).add_to(m)

    # Sicher speichern
    static_path = os.path.join(os.path.dirname(__file__), "static")
    if not os.path.exists(static_path):
        os.makedirs(static_path)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"heatmap_{timestamp}.html"
    filepath = os.path.join(static_path, filename)
    m.save(filepath)

    base_url = "https://gpx-heatmap-api.onrender.com"
    return jsonify({"heatmap_url": f"{base_url}/static/{filename}"})


# 🔹 Route 2: Heatmap + Wetteranalyse pro Abschnitt
@app.route('/heatmap-with-weather', methods=['POST'])
def heatmap_with_weather():
    data = request.json
    coordinates = data.get("coordinates", [])

    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    # Segmentierung (~1 km)
    segments = []
    segment = []
    segment_distance = 0.0
    segment_length_target_km = 1.0
    prev_point = None

    for point in coordinates:
        if prev_point:
            d = geodesic(prev_point, point).kilometers
            segment_distance += d
            segment.append(point)
            if segment_distance >= segment_length_target_km:
                segments.append(segment)
                segment = []
                segment_distance = 0.0
        else:
            segment.append(point)
        prev_point = point

    if segment:
        segments.append(segment)

    # Wetterabfrage
    WEATHERSTACK_API_KEY = "c46f7d44c360dbd7bbe824a5a8438859"  # ⬅️ HIER DEIN WEATHERSTACK-KEY EINFÜGEN
    base_url = "http://api.weatherstack.com/current"
    result = []

    for i, seg in enumerate(segments):
        center = seg[len(seg)//2]
        lat, lon = center
        params = {
            "access_key": WEATHERSTACK_API_KEY,
            "query": f"{lat},{lon}"
        }
        weather = {}
        try:
            res = requests.get(base_url, params=params)
            if res.status_code == 200:
                data = res.json()
                weather = {
                    "temperature": data["current"].get("temperature"),
                    "wind_speed": data["current"].get("wind_speed"),
                    "precip": data["current"].get("precip"),
                    "condition": data["current"].get("weather_descriptions", ["–"])[0]
                }
            else:
                weather = {"error": f"HTTP {res.status_code}"}
        except Exception as e:
            weather = {"error": str(e)}

        result.append({
            "segment_index": i + 1,
            "segment_center": {"lat": lat, "lon": lon},
            "weather": weather
        })

    return jsonify({"segments": result})

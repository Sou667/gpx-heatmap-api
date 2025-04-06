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

# 🔹 Klassische Heatmap (einfach)
@app.route('/heatmap', methods=['POST'])
def generate_heatmap():
    data = request.json
    coordinates = data.get("coordinates", [])

    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    center = coordinates[0]
    m = folium.Map(location=center, zoom_start=13)
    HeatMap(coordinates).add_to(m)

    static_path = os.path.join(os.path.dirname(__file__), "static")
    if not os.path.exists(static_path):
        os.makedirs(static_path)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"heatmap_{timestamp}.html"
    filepath = os.path.join(static_path, filename)
    m.save(filepath)

    base_url = "https://gpx-heatmap-api.onrender.com"
    return jsonify({"heatmap_url": f"{base_url}/static/{filename}"})


# 🔹 Heatmap mit Wetterdaten und Sanitätermarkern
@app.route('/heatmap-with-weather', methods=['POST'])
def heatmap_with_weather():
    data = request.json
    coordinates = data.get("coordinates", [])

    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    # Feine Segmentierung (~0.2 km)
    segments = []
    segment = []
    segment_distance = 0.0
    segment_length_target_km = 0.2
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

    WEATHERSTACK_API_KEY = os.environ.get("WEATHERSTACK_API_KEY")
    base_url = "http://api.weatherstack.com/current"
    result = []
    marker_coords = []

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
                if "current" in data:
                    weather = {
                        "temperature": data["current"].get("temperature"),
                        "wind_speed": data["current"].get("wind_speed"),
                        "precip": data["current"].get("precip"),
                        "condition": data["current"].get("weather_descriptions", ["–"])[0]
                    }

                    # Marker setzen bei erhöhtem Risiko (z. B. Wind > 25 km/h oder Regen)
                    if weather["wind_speed"] and weather["wind_speed"] >= 25 or weather["precip"] > 0:
                        marker_coords.append({
                            "lat": lat,
                            "lon": lon,
                            "popup": f"🚑 Sanitäter-Empfehlung – Wind: {weather['wind_speed']} km/h, Regen: {weather['precip']} mm"
                        })
                else:
                    weather = {"error": data.get("error", "Keine 'current'-Daten enthalten")}
            else:
                weather = {"error": f"HTTP {res.status_code}"}
        except Exception as e:
            weather = {"error": str(e)}

        result.append({
            "segment_index": i + 1,
            "segment_center": {"lat": lat, "lon": lon},
            "weather": weather
        })

    # HTML-Heatmap erzeugen
    center = coordinates[0] if coordinates else [50.0, 8.0]
    m = folium.Map(location=center, zoom_start=13)

    for seg in segments:
        if seg:
            HeatMap(seg).add_to(m)

    for marker in marker_coords:
        folium.Marker(
            location=[marker["lat"], marker["lon"]],
            popup=marker["popup"],
            icon=folium.Icon(color="red", icon="plus", prefix="fa")
        ).add_to(m)

    static_path = os.path.join(os.path.dirname(__file__), "static")
    if not os.path.exists(static_path):
        os.makedirs(static_path)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"heatmap_{timestamp}.html"
    filepath = os.path.join(static_path, filename)
    m.save(filepath)

    base_url = "https://gpx-heatmap-api.onrender.com"
    heatmap_url = f"{base_url}/static/{filename}"

    return jsonify({
        "segments": result,
        "heatmap_url": heatmap_url
    })

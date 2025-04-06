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

@app.route('/heatmap-with-weather', methods=['POST'])
def heatmap_with_weather():
    data = request.json
    coordinates = data.get("coordinates", [])

    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    segments = []
    segment = []
    segment_distance = 0.0
    segment_length_km = 0.2
    prev_point = None

    for point in coordinates:
        if prev_point:
            dist = geodesic(prev_point, point).kilometers
            segment_distance += dist
            segment.append(point)
            if segment_distance >= segment_length_km:
                segments.append(segment)
                segment = []
                segment_distance = 0.0
        else:
            segment.append(point)
        prev_point = point
    if segment:
        segments.append(segment)

    WEATHERSTACK_API_KEY = os.environ.get("WEATHERSTACK_API_KEY")
    weather_url = "http://api.weatherstack.com/current"
    html_map = None
    result = []

    for i, seg in enumerate(segments):
        center = seg[len(seg)//2]
        lat, lon = center
        params = {"access_key": WEATHERSTACK_API_KEY, "query": f"{lat},{lon}"}
        weather = {}
        risk = 1
        verletzungen = []
        sani = None

        try:
            res = requests.get(weather_url, params=params)
            if res.status_code == 200:
                data = res.json()
                if "current" in data:
                    current = data["current"]
                    temp = current.get("temperature", 0)
                    wind = current.get("wind_speed", 0)
                    precip = current.get("precip", 0)

                    if temp <= 5:
                        risk += 1
                        verletzungen.append("❄️ Muskelverspannung durch Kälte")
                    if wind >= 16:
                        risk += 1
                        verletzungen.append("💨 Kontrollverlust durch Seitenwind")
                    if precip > 0:
                        risk += 1
                        verletzungen.append("☔ Claviculafraktur bei Nässe")

                    if risk >= 3:
                        sani = "🚑 Sanitäter-Posten empfohlen (Fixationsset, Wärmedecken)"

                    weather = {
                        "temperature": temp,
                        "wind_speed": wind,
                        "precip": precip,
                        "condition": current.get("weather_descriptions", ["–"])[0]
                    }
        except Exception as e:
            weather = {"error": str(e)}

        color = 'green' if risk == 1 else 'yellow' if risk == 2 else 'orange' if risk == 3 else 'red'

        if html_map is None:
            html_map = folium.Map(location=center, zoom_start=14)

        popup_text = f"""
        <b>Segment {i+1}</b><br>
        🌡 Temperatur: {weather.get('temperature', '?')}°C<br>
        💨 Wind: {weather.get('wind_speed', '?')} km/h<br>
        ☔ Niederschlag: {weather.get('precip', '?')} mm<br>
        ⚠️ Risikostufe: {risk}/5<br>
        <b>💥 Mögliche Verletzungen:</b><br>
        {'<br>'.join(verletzungen)}<br>
        """

        folium.PolyLine(
            seg, color=color, weight=5, popup=popup_text
        ).add_to(html_map)

        if sani:
            folium.Marker(
                location=center,
                popup=sani,
                icon=folium.Icon(color='red', icon='plus-sign')
            ).add_to(html_map)

        result.append({
            "segment_index": i+1,
            "segment_center": {"lat": lat, "lon": lon},
            "weather": weather,
            "risk": risk,
            "verletzungen": verletzungen,
            "sani": sani
        })

    static_path = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_path, exist_ok=True)
    filename = f"heatmap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
    filepath = os.path.join(static_path, filename)
    html_map.save(filepath)

    base_url = "https://gpx-heatmap-api.onrender.com"
    return jsonify({"heatmap_url": f"{base_url}/static/{filename}", "segments": result})

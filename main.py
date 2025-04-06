# KOMPLETTER CODE → hier klicken zum Aufklappen
from flask import Flask, request, jsonify
import folium
from folium.plugins import HeatMap
import os
from datetime import datetime
from geopy.distance import geodesic
import requests
import gpxpy
import gpxpy.gpx

app = Flask(__name__)

@app.route('/')
def home():
    return 'CycleDoc GPX Heatmap API läuft!'

@app.route('/parse-gpx', methods=['POST'])
def parse_gpx():
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei empfangen."}), 400

    file = request.files['file']
    gpx = gpxpy.parse(file.stream)
    coordinates = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                coordinates.append([point.latitude, point.longitude, point.elevation])
    return jsonify({"coordinates": coordinates})

@app.route('/heatmap-with-weather', methods=['POST'])
def heatmap_with_weather():
    data = request.json
    coordinates = data.get("coordinates", [])
    weather_override = data.get("wetter_override", {})
    fahrertyp = data.get("fahrer_typ", "Amateur")
    teilnehmer = data.get("anzahl", 100)

    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    # Segmentierung (~0.2 km)
    segments = []
    segment = []
    segment_distance = 0.0
    segment_length_target_km = 0.2
    prev_point = None

    for point in coordinates:
        if prev_point:
            d = geodesic(prev_point[:2], point[:2]).kilometers
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

    # Wetterdaten
    WEATHERSTACK_API_KEY = os.environ.get("WEATHERSTACK_API_KEY")
    base_url = "http://api.weatherstack.com/current"

    result = []

    def calc_risk(temp, wind, precip, slope, fahrer, teilnehmer):
        risiko = 1
        if temp <= 5: risiko += 1
        if wind >= 25: risiko += 1
        if precip >= 1: risiko += 1
        if abs(slope) > 4: risiko += 1
        if fahrer == "Amateur": risiko += 1
        if teilnehmer > 80: risiko += 1
        return min(risiko, 5)

    for i, seg in enumerate(segments):
        center = seg[len(seg)//2]
        lat, lon = center[:2]
        elevations = [p[2] for p in seg if len(p) > 2]
        slope = round((elevations[-1] - elevations[0]) / (geodesic(seg[0][:2], seg[-1][:2]).meters + 1e-6) * 100, 1) if elevations else 0.0

        # Wetterdaten abrufen
        if weather_override:
            weather = weather_override
        else:
            params = {"access_key": WEATHERSTACK_API_KEY, "query": f"{lat},{lon}"}
            try:
                res = requests.get(base_url, params=params)
                data = res.json()
                weather = {
                    "temperature": data["current"]["temperature"],
                    "wind_speed": data["current"]["wind_speed"],
                    "precip": data["current"]["precip"],
                    "condition": data["current"]["weather_descriptions"][0]
                }
            except:
                weather = {"temperature": 13, "wind_speed": 10, "precip": 0, "condition": "Sunny"}

        risiko = calc_risk(weather["temperature"], weather["wind_speed"], weather["precip"], slope, fahrertyp, teilnehmer)

        verletzungen = []
        if risiko >= 3:
            verletzungen.append("🚴‍♂️ Kontrollverlust möglich")
        if slope > 4 or slope < -4:
            verletzungen.append("📉 Sturzgefahr bei Abfahrt/Auffahrt")
        if weather["precip"] > 0.5:
            verletzungen.append("💦 Rutschgefahr bei Nässe")
        if weather["wind_speed"] > 25:
            verletzungen.append("💨 Seitenwind – Schulterverletzungen möglich")

        sani = "🚑 Saniposten empfohlen bei hoher Dichte" if risiko >= 3 and teilnehmer > 50 else None

        result.append({
            "segment_index": i + 1,
            "segment_center": {"lat": lat, "lon": lon},
            "steigung": slope,
            "terrain": "Flach" if abs(slope) < 2 else "Anstieg" if slope > 2 else "Abfahrt",
            "weather": weather,
            "risk": risiko,
            "verletzungen": verletzungen,
            "sani": sani
        })

    # Karte erstellen
    center = result[0]["segment_center"]
    m = folium.Map(location=[center["lat"], center["lon"]], zoom_start=13)
    for seg in result:
        color = {1: "green", 2: "yellow", 3: "orange", 4: "red", 5: "darkred"}[seg["risk"]]
        folium.CircleMarker(
            location=[seg["segment_center"]["lat"], seg["segment_center"]["lon"]],
            radius=6,
            popup=f"Risikostufe: {seg['risk']}, Sani: {seg['sani'] or '–'}",
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7
        ).add_to(m)

    # Datei speichern
    static_path = os.path.join(os.path.dirname(__file__), "static")
    if not os.path.exists(static_path):
        os.makedirs(static_path)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"heatmap_{timestamp}.html"
    filepath = os.path.join(static_path, filename)
    m.save(filepath)

    base_url = "https://gpx-heatmap-api.onrender.com"

    return jsonify({
        "heatmap_url": f"{base_url}/static/{filename}",
        "segments": result
    })


from flask import Flask, request, jsonify
import folium
from folium.plugins import HeatMap
import os
from datetime import datetime
from geopy.distance import geodesic
import requests
import gpxpy
import math

app = Flask(__name__)

@app.route("/")
def home():
    return "GPX Heatmap API läuft!"

def berechne_steigung(p1, p2):
    dist = geodesic((p1.latitude, p1.longitude), (p2.latitude, p2.longitude)).meters
    höhe = (p2.elevation or 0) - (p1.elevation or 0)
    if dist == 0:
        return 0.0
    return round((höhe / dist) * 100, 1)

def terrain_klassifikation(steigung):
    if steigung < -6:
        return "Gefährliche Abfahrt"
    elif steigung < -3:
        return "Leichte Abfahrt"
    elif steigung < 3:
        return "Flach"
    elif steigung < 6:
        return "Leichte Steigung"
    else:
        return "Starke Steigung"

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx():
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei empfangen."}), 400
    gpx_file = request.files["file"]
    gpx = gpxpy.parse(gpx_file.stream)
    coords = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                coords.append([point.latitude, point.longitude, point.elevation])
    return jsonify({"coordinates": coords})

@app.route("/heatmap-full-context", methods=["POST"])
def heatmap_full_context():
    data = request.get_json()
    coordinates = data.get("coordinates", [])
    fahrer = data.get("fahrer", "hobby")
    teilnehmer = data.get("teilnehmer", 50)
    geschlecht = data.get("geschlecht", "gemischt")
    alter = data.get("alter", "erwachsene")
    disziplin = data.get("disziplin", "strasse")

    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    segments = []
    segment = []
    segment_distance = 0.0
    segment_length_target_km = 0.2
    prev_point = None

    for pt in coordinates:
        lat, lon = pt[0], pt[1]
        ele = pt[2] if len(pt) > 2 else 0
        point = type("P", (), {"latitude": lat, "longitude": lon, "elevation": ele})
        if prev_point:
            d = geodesic((prev_point.latitude, prev_point.longitude), (lat, lon)).kilometers
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
    map_coords = []

    for i, seg in enumerate(segments):
        center = seg[len(seg) // 2]
        lat, lon = center.latitude, center.longitude
        map_coords.append([lat, lon])
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
                    current = data["current"]
                    weather = {
                        "temperature": current.get("temperature"),
                        "wind_speed": current.get("wind_speed"),
                        "precip": current.get("precip"),
                        "condition": current.get("weather_descriptions", ["–"])[0]
                    }
                else:
                    weather = {"error": data.get("error", "Keine 'current'-Daten enthalten")}
            else:
                weather = {"error": f"HTTP {res.status_code}"}
        except Exception as e:
            weather = {"error": str(e)}

        steigung = berechne_steigung(seg[0], seg[-1])
        terrain = terrain_klassifikation(steigung)

        risk = 1
        verletzungen = []
        sani = None

        if fahrer == "hobby":
            risk += 1
            verletzungen.append("🚴‍♂️ Geringere Kontrolle bei Amateuren")
        if alter == "senioren":
            risk += 1
            verletzungen.append("👵 Höheres Sturzrisiko laut Studienlage")
        if weather.get("wind_speed", 0) >= 16:
            risk += 1
            verletzungen.append("🌬 Kontrollverlust bei Seitenwind möglich")
        if weather.get("temperature", 99) < 6:
            risk += 1
            verletzungen.append("❄️ Risiko für Muskelverspannung")
        if terrain in ["Starke Steigung", "Gefährliche Abfahrt"]:
            risk += 1
            verletzungen.append("⛰ Gelände erhöht Sturzgefahr")

        if risk >= 3 and teilnehmer >= 100:
            sani = "🚑 Saniposten empfohlen bei hoher Dichte"

        result.append({
            "segment_index": i + 1,
            "segment_center": {"lat": lat, "lon": lon},
            "risk": min(risk, 5),
            "weather": weather,
            "terrain": terrain,
            "steigung": steigung,
            "verletzungen": verletzungen,
            "sani": sani
        })

    m = folium.Map(location=map_coords[0], zoom_start=14)
    colors = {1: "green", 2: "yellow", 3: "orange", 4: "red", 5: "black"}

    for seg in result:
        color = colors.get(seg["risk"], "gray")
        folium.CircleMarker(
            location=[seg["segment_center"]["lat"], seg["segment_center"]["lon"]],
            radius=6,
            color=color,
            fill=True,
            fill_opacity=0.8,
            popup=f"Risikostufe: {seg['risk']}<br>{seg['terrain']}<br>Temp: {seg['weather'].get('temperature')}°C<br>Wind: {seg['weather'].get('wind_speed')} km/h<br>{'<br>'.join(seg['verletzungen'])}"
        ).add_to(m)

        if seg["sani"]:
            folium.Marker(
                location=[seg["segment_center"]["lat"], seg["segment_center"]["lon"]],
                popup=seg["sani"],
                icon=folium.Icon(color="red", icon="plus-sign")
            ).add_to(m)

    static_path = os.path.join(os.path.dirname(__file__), "static")
    if not os.path.exists(static_path):
        os.makedirs(static_path)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"heatmap_{timestamp}.html"
    filepath = os.path.join(static_path, filename)
    m.save(filepath)

    base_url = "https://gpx-heatmap-api.onrender.com"
    return jsonify({"heatmap_url": f"{base_url}/static/{filename}", "segments": result})

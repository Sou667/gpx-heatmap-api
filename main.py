from flask import Flask, request, jsonify
import folium
from folium.plugins import HeatMap
import os
from datetime import datetime
from geopy.distance import geodesic
import requests

app = Flask(__name__)

@app.route("/")
def home():
    return "Multifaktorielle Heatmap API aktiv."

@app.route("/heatmap-full-context", methods=["POST"])
def full_context_heatmap():
    data = request.json
    coordinates = data.get("coordinates", [])
    fahrer = data.get("fahrer", "hobby")  # 'hobby' oder 'profi'
    teilnehmer = data.get("teilnehmer", 50)
    geschlecht = data.get("geschlecht", "gemischt")  # 'm', 'w', 'gemischt'
    alter = data.get("alter", "erwachsene")  # 'jugend', 'erwachsene', 'senioren'
    disziplin = data.get("disziplin", "straße")  # 'straße', 'gravel', 'mtb', ...

    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    WEATHERSTACK_API_KEY = os.environ.get("WEATHERSTACK_API_KEY")
    weather_url = "http://api.weatherstack.com/current"

    segments = []
    segment = []
    segment_distance = 0.0
    segment_length_km = 0.2
    total_distance = 0.0
    prev_point = None

    for point in coordinates:
        if prev_point:
            dist = geodesic(prev_point, point).kilometers
            total_distance += dist
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

    result = []
    html_map = None
    segment_counter = 0

    for seg in segments:
        segment_counter += 1
        center = seg[len(seg)//2]
        lat, lon = center
        params = {"access_key": WEATHERSTACK_API_KEY, "query": f"{lat},{lon}"}
        weather = {}
        try:
            res = requests.get(weather_url, params=params)
            if res.status_code == 200:
                data = res.json()
                current = data["current"]
                temp = current.get("temperature", 0)
                wind = current.get("wind_speed", 0)
                rain = current.get("precip", 0)
                condition = current.get("weather_descriptions", ["–"])[0]
            else:
                temp = 0
                wind = 0
                rain = 0
                condition = "Unbekannt"
        except Exception:
            temp = 0
            wind = 0
            rain = 0
            condition = "Fehler"

        # Risikobewertung
        risiko = 1
        verletzungen = []
        sani = None

        # Wetterbasiert
        if temp <= 5:
            risiko += 1
            verletzungen.append("❄️ Muskelverspannung bei Kälte")
        if wind >= 16:
            risiko += 1
            verletzungen.append("💨 Kontrollverlust bei Wind")
        if rain > 0:
            risiko += 1
            verletzungen.append("☔ Rutschgefahr bei Nässe")

        # Terrainunabhängig: Ermüdung basierend auf Renndistanz
        km_pos = segment_counter * 0.2
        if km_pos > 0.75 * total_distance:
            risiko += 1
            verletzungen.append("🧠 Ermüdungseffekt (Streckenende)")

        # Fahrerprofil
        if fahrer == "hobby":
            risiko += 1
            verletzungen.append("🚴‍♂️ Geringere Kontrolle bei Amateuren")
        if alter == "senioren":
            risiko += 1
            verletzungen.append("👵 Höheres Sturzrisiko laut Studienlage")

        # Teilnehmerdichte
        if teilnehmer >= 100 and risiko >= 3:
            sani = "🚑 Saniposten empfohlen bei hoher Dichte"

        # Farbzuweisung
        color = 'green' if risiko == 1 else 'yellow' if risiko == 2 else 'orange' if risiko == 3 else 'red'

        # Karte
        if html_map is None:
            html_map = folium.Map(location=center, zoom_start=14)

        popup = f"<b>Segment {segment_counter}</b><br>🌡 {temp}°C, 💨 {wind} km/h, ☔ {rain} mm<br>⚠️ Risiko: {risiko}/5<br>" + "<br>".join(verletzungen)
        folium.PolyLine(seg, color=color, weight=5, popup=popup).add_to(html_map)

        if sani:
            folium.Marker(location=center, popup=sani, icon=folium.Icon(color="red", icon="plus-sign")).add_to(html_map)

        result.append({
            "segment_index": segment_counter,
            "segment_center": {"lat": lat, "lon": lon},
            "weather": {
                "temperature": temp,
                "wind_speed": wind,
                "precip": rain,
                "condition": condition
            },
            "risk": risiko,
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

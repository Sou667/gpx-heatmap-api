from flask import Flask, request, jsonify
import folium
from folium.plugins import HeatMap
import os
from datetime import datetime

app = Flask(__name__)

@app.route('/')
def home():
    return 'GPX Heatmap API läuft!'

@app.route('/heatmap', methods=['POST'])
def generate_heatmap():
    data = request.json
    coordinates = data.get("coordinates", [])

    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    center = coordinates[0]  # Mittelpunkt auf ersten Punkt setzen

    # Heatmap erstellen
    m = folium.Map(location=center, zoom_start=13)
    HeatMap(coordinates).add_to(m)

    # Ordnerpfad für static sicher erstellen
    static_path = os.path.join(os.path.dirname(__file__), "static")
    if not os.path.exists(static_path):
        os.makedirs(static_path)

    # Dateiname
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"heatmap_{timestamp}.html"
    filepath = os.path.join(static_path, filename)
    m.save(filepath)

    # Feste Render-URL verwenden
    base_url = "https://gpx-heatmap-api.onrender.com"

    return jsonify({
        "heatmap_url": f"{base_url}/static/{filename}"
    })

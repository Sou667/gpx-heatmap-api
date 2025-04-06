################################################################
# main.py
# - Zeigt gesamten Track auf der Folium-Karte (fit_bounds).
# - Einfache Farbschema: 1-2 (grün), 3 (orange), 4-5 (rot).
# - Popup für Sani: Mehr Kontext (z. B. "Scharfe Kurve").
# - NEU: /chunk-upload + /heatmap-with-weather mit Auto-Delete.
################################################################

import os
import math
import random
import tempfile
import json
import shutil
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from geopy.distance import geodesic
import requests
import gpxpy
import gpxpy.gpx
import folium
from weasyprint import HTML
from astral import LocationInfo
from astral.sun import sun

os.makedirs("chunks", exist_ok=True)
app = Flask(__name__)

# ... [ALLE HILFSFUNKTIONEN BLEIBEN UNVERÄNDERT, ausgelassen zur Kürzung] ...

@app.route("/", methods=["GET"])
def home():
    return "CycleDoc Heatmap mit Server-Chunks aktiv."

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx_route():
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei empfangen."}), 400
    file = request.files["file"]
    gpx = gpxpy.parse(file.stream)
    coords = [[pt.latitude, pt.longitude, pt.elevation]
              for trk in gpx.tracks for seg in trk.segments for pt in seg.points]
    return jsonify({"coordinates": coords})

@app.route("/chunk-upload", methods=["POST"])
def chunk_upload():
    data = request.json
    coords = data.get("coordinates", [])
    chunk_size = data.get("chunk_size", 200)
    if not coords:
        return jsonify({"error": "Keine Koordinaten empfangen"}), 400
    total_chunks = (len(coords) + chunk_size - 1) // chunk_size
    files = []
    for i in range(total_chunks):
        path = os.path.join("chunks", f"chunk_{i+1}.json")
        with open(path, "w") as f:
            json.dump({"coordinates": coords[i*chunk_size:(i+1)*chunk_size]}, f)
        files.append(f"chunk_{i+1}.json")
    return jsonify({"message": f"{total_chunks} Chunks gespeichert", "chunks": files})

@app.route("/heatmap-with-weather", methods=["POST"])
def heatmap_with_weather():
    data = request.json
    coords = data.get("coordinates", [])
    if not coords:
        return jsonify({"error": "Keine Koordinaten empfangen"}), 400

    # ... [Analysecode ausgelassen zur Kürzung - Risiko, Segmentierung, Wetter etc.] ...

    # Heatmap & Segmentinfos generieren => m, segment_infos
    # Speicherpfad
    static_path = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_path, exist_ok=True)
    filename = f"heatmap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
    filepath = os.path.join(static_path, filename)
    m.save(filepath)

    # Chunks aufräumen
    shutil.rmtree("chunks", ignore_errors=True)
    os.makedirs("chunks", exist_ok=True)

    return jsonify({
        "heatmap_url": f"https://gpx-heatmap-api.onrender.com/static/{filename}",
        "segments": segment_infos
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)

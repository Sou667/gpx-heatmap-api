################################################################
# main.py
# - Zeigt gesamten Track auf der Folium-Karte (fit_bounds).
# - Einfache Farbschema: 1-2 (grün), 3 (orange), 4-5 (rot).
# - Popup für Sani: Mehr Kontext (z. B. "Scharfe Kurve").
# - NEU: /chunk-upload + /run-chunks + automatisches Löschen von Chunks
################################################################

import os
import math
import random
import tempfile
import json
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
os.makedirs("static", exist_ok=True)
app = Flask(__name__)

# Hilfsfunktionen (bearing, slopes, etc.) ausgelassen für Kürze - wie gehabt
# ... (Deine vorhandenen Funktionen bleiben vollständig erhalten)

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
        chunk_data = coords[i*chunk_size:(i+1)*chunk_size]
        filename = f"chunk_{i+1}.json"
        path = os.path.join("chunks", filename)
        with open(path, "w") as f:
            json.dump({"coordinates": chunk_data}, f)
        files.append(filename)

    return jsonify({"message": f"{len(files)} Chunks gespeichert", "chunks": files})

@app.route("/run-chunks", methods=["POST"])
def run_chunks():
    from glob import glob

    file_list = sorted(glob("chunks/chunk_*.json"))
    all_coords = []

    for path in file_list:
        with open(path) as f:
            chunk = json.load(f)
            all_coords.extend(chunk.get("coordinates", []))

    # Alle Chunk-Dateien nach erfolgreichem Laden löschen
    for path in file_list:
        try:
            os.remove(path)
        except:
            pass

    # Simuliere den heatmap-with-weather Endpoint (du kannst das gerne optimieren)
    payload = {
        "coordinates": all_coords,
        "fahrer_typ": "C-Lizenz",
        "anzahl": 100,
        "rennen_art": "Straße",
        "geschlecht": "mixed",
        "alter": 35,
        "start_time": datetime.utcnow().isoformat() + "Z",
        "material": "carbon",
        "massenstart": True,
        "schutzausruestung": {"helm": True, "protektoren": False}
    }

    with app.test_client() as client:
        resp = client.post("/heatmap-with-weather", json=payload)
        return resp

# Alle bisherigen Funktionen (parse_gpx, heatmap_with_weather, etc.) bleiben bestehen
# ...

if __name__ == "__main__":
    app.run(debug=True, port=5000)

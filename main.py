##############################################################
# main.py
# 
# Vollständiger Code, der die Dissertation-Punkte berücksichtigt.
# 
# Starten lokal: 
#   python main.py 
# Oder:
#   flask run --host=0.0.0.0 --port=5000
##############################################################
from flask import Flask, request, jsonify
import folium
import os
import math
from datetime import datetime
from geopy.distance import geodesic
import requests
import gpxpy
import gpxpy.gpx

# Für Tag/Nacht-Bestimmung
from astral import LocationInfo
from astral.sun import sun

import random

app = Flask(__name__)

# ---------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------

def bearing(pointA, pointB):
    """
    Berechnet die Kursrichtung (Bearing) von pointA nach pointB.
    pointA, pointB: (lat, lon)
    Rückgabe: Grad 0..360
    """
    lat1 = math.radians(pointA[0])
    lon1 = math.radians(pointA[1])
    lat2 = math.radians(pointB[0])
    lon2 = math.radians(pointB[1])
    d_lon = lon2 - lon1
    x = math.sin(d_lon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon))
    initial_bearing = math.degrees(math.atan2(x, y))
    compass_bearing = (initial_bearing + 360) % 360
    return compass_bearing

def angle_between(b1, b2):
    """
    Liefert die kleinste Winkel-Differenz zwischen zwei Bearing-Werten (0..360).
    """
    diff = abs(b1 - b2)
    return min(diff, 360 - diff)

def detect_sharp_curve(segment_points, threshold=60):
    """
    Prüft, ob es im Segment eine 'scharfe Kurve' (starke Richtungsänderung) gibt.
    threshold: Winkel in Grad, ab dem wir sagen: "scharfe Kurve".
    """
    if len(segment_points) < 3:
        return False
    for i in range(len(segment_points) - 2):
        latlonA = (segment_points[i][0], segment_points[i][1])
        latlonB = (segment_points[i+1][0], segment_points[i+1][1])
        latlonC = (segment_points[i+2][0], segment_points[i+2][1])

        bAB = bearing(latlonA, latlonB)
        bBC = bearing(latlonB, latlonC)
        angle = angle_between(bAB, bBC)
        if angle >= threshold:
            return True
    return False

def calc_slope(points):
    """
    Steigungsberechnung in % (Start- vs. Endpunkt).
    """
    if len(points) < 2:
        return 0.0
    start = points[0]
    end = points[-1]
    elev_diff = (end[2] if len(end) > 2 else 0) - (start[2] if len(start) > 2 else 0)
    dist_m = geodesic((start[0], start[1]), (end[0], end[1])).meters
    if dist_m < 1e-6:
        return 0.0
    slope = (elev_diff / dist_m) * 100
    return round(slope, 1)

def get_street_surface(lat, lon):
    """
    Beispiel-Funktion für Straßenbelag (Demo).
    In Wirklichkeit würdest du hier Overpass (OSM) oder eine Datenbank befragen.
    """
    surfaces = ["asphalt", "cobblestone", "gravel", "asphalt", "asphalt", "gravel"]
    random.seed(int(abs(lat*1000) + abs(lon*1000)))
    return random.choice(surfaces)

def is_nighttime_at(dt, lat, lon):
    """
    Tag/Nacht-Abfrage über astral.
    dt: datetime, lat/lon: Koordinaten
    """
    location = LocationInfo(
        name="RaceLocation",
        region="",
        timezone="UTC",  # ggf. anpassen
        latitude=lat,
        longitude=lon
    )
    s = sun(location.observer, date=dt.date())
    sunrise = s["sunrise"]
    sunset = s["sunset"]

    return dt < sunrise or dt > sunset

def segmentize(coordinates, segment_length_km=0.2):
    """
    Teilt Koordinaten (lat,lon,elev) in ~0,2-km-Segmente auf.
    """
    segments = []
    segment = []
    segment_distance = 0.0
    prev_point = None

    for point in coordinates:
        if prev_point:
            d = geodesic(prev_point[:2], point[:2]).kilometers
            segment_distance += d
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

    return segments

# ---------------------
# Risikoberechnung
# ---------------------
def calc_risk(
    temp, wind, precip, slope,
    fahrer_typ,
    teilnehmer,
    nighttime=False,
    sharp_curve=False,
    rennen_art="unknown",
    geschlecht="mixed",
    street_surface="asphalt",
    alter=35,
    schutzausruestung=None,  # dict: {"helm": True, "protektoren": True, ...}
    material="aluminium",
    overuse_knee=False,
    rueckenschmerzen=False,
    massenstart=False
):
    """
    Erweiterte Risikoformel, die möglichst viele Faktoren aus der Dissertation 
    (und weiteren Studien) berücksichtigt.
    
    Skala: 1..10 (Beispiel)
    """
    if schutzausruestung is None:
        schutzausruestung = {}

    risiko = 1

    # Wetter-Faktoren
    if temp <= 5:
        risiko += 1  # kalte Temp => steife Muskeln, Auskühlung
    if wind >= 25:
        risiko += 1
    if precip >= 1:  # starker Regen
        risiko += 1

    # Steigung/Gefälle
    if abs(slope) > 4:
        risiko += 1

    # Fahrertyp (Lizenzklasse, Hobby vs. Profi)
    typ_lower = fahrer_typ.lower()
    # Annahme: Hobby/C = +1, A/B = -1, Elite/Profi -> -1
    if typ_lower in ["hobby", "c-lizenz", "anfänger"]:
        risiko += 1
    elif typ_lower in ["a", "b", "elite", "profi"]:
        risiko -= 1

    # Teilnehmerzahl
    if teilnehmer > 80:
        risiko += 1

    # Massenstart => hohes Kollisionsrisiko
    if massenstart:
        risiko += 1

    # Nachtmodus
    if nighttime:
        risiko += 1

    # Scharfe Kurve
    if sharp_curve:
        risiko += 1

    # Disziplin
    # Downhill => +2, MTB => +1, Kriterien => +1, Straßenrennen => 0 ...
    r = rennen_art.lower()
    if r in ["downhill", "freeride"]:
        risiko += 2
    elif r in ["mtb", "mountainbike", "xc", "gelände"]:
        risiko += 1
    elif r in ["kriterienrennen", "criterium"]:
        risiko += 1

    # Geschlecht
    if geschlecht.lower() in ["w", "frau", "female"]:
        risiko += 1

    # Alter
    if alter >= 60:
        risiko += 1

    # Straßenbelag
    if street_surface in ["cobblestone", "gravel"]:
        risiko += 1

    # Material (carbon vs. alu vs. stahl)
    if material.lower() == "carbon":
        risiko += 1

    # Schutzkleidung
    # z. B. helm => -1, protektoren => -1
    if schutzausruestung.get("helm", False):
        risiko -= 1
    if schutzausruestung.get("protektoren", False):
        risiko -= 1

    # Overuse-Faktoren
    # z. B. wer Knie- oder Rückenprobleme hat => +1
    if overuse_knee:
        risiko += 1
    if rueckenschmerzen:
        risiko += 1

    # Deckeln (Skala 1..10)
    if risiko < 1:
        risiko = 1
    if risiko > 10:
        risiko = 10

    return risiko

def needs_saniposten(risk_value):
    """
    Beispiel: ab 7 => Sani empfohlen.
    """
    return risk_value >= 7


# ---------------------------------------------------
# FLASK-Routen
# ---------------------------------------------------
@app.route("/")
def home():
    return "CycleDoc Heatmap API – Dissertation-Faktoren (Erweiterte Version)!"

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx():
    """
    Lädt die GPX-Datei und gibt Koordinaten zurück, falls gewünscht.
    """
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei empfangen."}), 400

    file = request.files["file"]
    gpx = gpxpy.parse(file.stream)
    coordinates = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                coordinates.append([point.latitude, point.longitude, point.elevation])
    return jsonify({"coordinates": coordinates})

@app.route("/extended-heatmap", methods=["POST"])
def extended_heatmap():
    """
    Hier wird die Heatmap erstellt.
    
    Erwartetes JSON-Beispiel:
    {
      "coordinates": [[lat, lon, elev], ...],
      "fahrer_typ": "C-Lizenz",
      "anzahl": 120,
      "rennen_art": "Downhill",
      "geschlecht": "female",
      "alter": 65,
      "start_time": "2025-08-01T19:00:00Z",
      "wetter_override": {
        "temperature": 10,
        "wind_speed": 20,
        "precip": 0,
        "condition": "Cloudy"
      },
      "material": "carbon",
      "massenstart": true,
      "overuse_knee": true,
      "rueckenschmerzen": false,
      "schutzausruestung": {
        "helm": true,
        "protektoren": false
      }
    }
    """
    data = request.json
    coordinates = data.get("coordinates", [])
    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    # Parameter einsammeln
    fahrer_typ = data.get("fahrer_typ", "hobby")
    teilnehmer = data.get("anzahl", 50)
    rennen_art = data.get("rennen_art", "unknown")
    geschlecht = data.get("geschlecht", "mixed")
    alter = data.get("alter", 35)
    start_time_str = data.get("start_time", None)
    weather_override = data.get("wetter_override", {})
    material = data.get("material", "aluminium")
    massenstart = data.get("massenstart", False)
    overuse_knee = data.get("overuse_knee", False)
    rueckenschmerzen = data.get("rueckenschmerzen", False)
    schutzausruestung = data.get("schutzausruestung", {})

    # Segmentierung
    segments = segmentize(coordinates, 0.2)
    if not segments:
        return jsonify({"error": "Keine Segmente gebildet"}), 400

    # Tag/Nacht-Bestimmung
    first_seg_center = segments[0][len(segments[0]) // 2]
    lat_first, lon_first = first_seg_center[:2]

    nighttime = False
    if start_time_str:
        try:
            dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
            nighttime = is_nighttime_at(dt, lat_first, lon_first)
        except:
            # falls es scheitert, bleibt nighttime=False
            pass

    # Wetter-API
    WEATHERSTACK_API_KEY = os.environ.get("WEATHERSTACK_API_KEY", "")
    ws_base_url = "http://api.weatherstack.com/current"

    segment_infos = []
    for i, seg in enumerate(segments):
        center_idx = len(seg) // 2
        center = seg[center_idx]
        lat, lon = center[:2]

        slope = calc_slope(seg)
        sharp_curve = detect_sharp_curve(seg, threshold=60)
        street_surface = get_street_surface(lat, lon)

        if weather_override:
            weather = weather_override
        else:
            # Externe Wetter-API
            try:
                params = {"access_key": WEATHERSTACK_API_KEY, "query": f"{lat},{lon}"}
                res = requests.get(ws_base_url, params=params, timeout=5)
                data_ws = res.json().get("current", {})
                weather = {
                    "temperature": data_ws.get("temperature", 15),
                    "wind_speed": data_ws.get("wind_speed", 10),
                    "precip": data_ws.get("precip", 0),
                    "condition": data_ws.get("weather_descriptions", [""])[0]
                }
            except:
                # Fallback
                weather = {
                    "temperature": 15,
                    "wind_speed": 10,
                    "precip": 0,
                    "condition": "Sunny"
                }

        # Risiko
        risiko = calc_risk(
            temp=weather["temperature"],
            wind=weather["wind_speed"],
            precip=weather["precip"],
            slope=slope,
            fahrer_typ=fahrer_typ,
            teilnehmer=teilnehmer,
            nighttime=nighttime,
            sharp_curve=sharp_curve,
            rennen_art=rennen_art,
            geschlecht=geschlecht,
            street_surface=street_surface,
            alter=alter,
            schutzausruestung=schutzausruestung,
            material=material,
            overuse_knee=overuse_knee,
            rueckenschmerzen=rueckenschmerzen,
            massenstart=massenstart
        )

        sani_needed = needs_saniposten(risiko)

        # Terrain klassifizieren
        if slope > 2:
            terrain = "Anstieg"
        elif slope < -2:
            terrain = "Abfahrt"
        else:
            terrain = "Flach"

        segment_infos.append({
            "segment_index": i + 1,
            "center": {"lat": lat, "lon": lon},
            "slope": slope,
            "sharp_curve": sharp_curve,
            "terrain": terrain,
            "weather": weather,
            "nighttime": nighttime,
            "street_surface": street_surface,
            "risk": risiko,
            "sani_needed": sani_needed
        })

    # Karte erstellen
    map_center = segment_infos[0]["center"]
    m = folium.Map(location=[map_center["lat"], map_center["lon"]], zoom_start=13)

    # Farben 1..10
    risk_colors = {
        1:  "green",
        2:  "lime",
        3:  "yellow",
        4:  "orange",
        5:  "darkorange",
        6:  "red",
        7:  "darkred",
        8:  "darkred",
        9:  "darkred",
        10: "black"
    }

    for seg_info, seg_points in zip(segment_infos, segments):
        risk = seg_info["risk"]
        color = risk_colors.get(risk, "green")
        latlon_segment = [(p[0], p[1]) for p in seg_points]

        folium.PolyLine(
            locations=latlon_segment,
            color=color,
            weight=5,
            popup=f"Segment {seg_info['segment_index']}, Risk {risk}, Surface {seg_info['street_surface']}"
        ).add_to(m)

        if seg_info["sani_needed"]:
            folium.Marker(
                location=[seg_info["center"]["lat"], seg_info["center"]["lon"]],
                popup=f"Sani empfohlen! Risk: {risk}",
                icon=folium.Icon(icon="plus", prefix="fa", color="red")
            ).add_to(m)

    # Karte speichern
    static_path = os.path.join(os.path.dirname(__file__), "static")
    if not os.path.exists(static_path):
        os.makedirs(static_path)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"extended_heatmap_{timestamp}.html"
    filepath = os.path.join(static_path, filename)
    m.save(filepath)

    # Base-URL anpassen
    base_url = "http://localhost:5000"  # oder deine Domain/Render-URL

    return jsonify({
        "heatmap_url": f"{base_url}/static/{filename}",
        "segments": segment_infos
    })

if __name__ == "__main__":
    # Lokaler Start
    app.run(debug=True, port=5000)

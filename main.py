from flask import Flask, request, jsonify
import folium
import os
import math
from datetime import datetime
from geopy.distance import geodesic
import requests
import gpxpy
import gpxpy.gpx

# Für Tag/Nacht-Berechnung:
from astral import LocationInfo
from astral.sun import sun

# Für Demo-Straßenbelag (Zufall):
import random

app = Flask(__name__)

# ---------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------

def bearing(pointA, pointB):
    """
    Berechnet die Kursrichtung (Bearing) von pointA nach pointB.
    pointA, pointB: (lat, lon) in Grad
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
    Prüft, ob es in den Punkten eine 'scharfe Kurve' (starke Richtungsänderung) gibt.
    threshold: Winkel in Grad, ab dem wir sagen: "scharfe Kurve"
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
    Einfache Steigungsberechnung in Prozent fürs ganze Segment:
    (Höhediff) / (horizontale Distanz in Metern) * 100.
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
    Beispiel-Funktion für Straßenbelag. In echt würdest du hier z. B. Overpass-API
    oder eine Datenbank abfragen. Hier nur Zufall als Demo.
    """
    surfaces = ["asphalt", "cobblestone", "gravel", "asphalt", "asphalt", "gravel"]
    # Pseudo-Zufall basierend auf Koordinaten
    random.seed(int(abs(lat*1000) + abs(lon*1000)))
    return random.choice(surfaces)

def calc_risk(temp, wind, precip, slope, fahrer_typ, teilnehmer,
              nighttime=False, sharp_curve=False,
              rennen_art="unknown", geschlecht="mixed",
              street_surface="asphalt"):
    """
    Beispielhafte Risiko-Formel, die diverse Faktoren berücksichtigt.
    """
    risiko = 1

    # Wetter
    if temp <= 5:
        risiko += 1
    if wind >= 25:
        risiko += 1
    if precip >= 1:
        risiko += 1

    # Steigung/Gefälle
    if abs(slope) > 4:
        risiko += 1

    # Fahrertyp (z. B. 'Profi', 'Amateur')
    if fahrer_typ.lower() == "amateur":
        risiko += 1

    # Teilnehmerzahl
    if teilnehmer > 80:
        risiko += 1

    # Nachtmodus (schlechte Sicht)
    if nighttime:
        risiko += 1

    # Scharfe Kurve
    if sharp_curve:
        risiko += 1

    # Rennart (Beispiel)
    if rennen_art.lower() in ["kriterienrennen", "kriterium"]:
        risiko += 1

    # Straßenbelag (Kopfsteinpflaster, Schotter => höheres Risiko)
    if street_surface in ["cobblestone", "gravel"]:
        risiko += 1

    # Deckeln bei 5
    risiko = min(risiko, 5)
    return risiko

def needs_saniposten(risk_value, sharp_curve, street_surface):
    """
    Wann benötigen wir einen Sani-Posten?
    Beispiel: risk >= 4 oder risk=3 + scharfe Kurve + schlechter Belag
    """
    if risk_value >= 4:
        return True
    if (risk_value == 3) and sharp_curve and (street_surface in ["cobblestone", "gravel"]):
        return True
    return False

def segmentize(coordinates, segment_length_km=0.2):
    """
    Teilt eine Liste von Koordinaten in ~0,2-km-Segmente auf.
    Rückgabe: Liste von Segmenten (Liste von Punkten).
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

    # Reste
    if segment:
        segments.append(segment)

    return segments

def is_nighttime_at(dt, lat, lon):
    """
    Bestimmt per astral, ob es zur angegebenen datetime (dt) an (lat, lon) Nacht ist.
    """
    location = LocationInfo(
        name="RaceLocation",
        region="",
        timezone="UTC",  # oder "Europe/Berlin", wenn du die lokale Zeitzone weißt
        latitude=lat,
        longitude=lon
    )
    s = sun(location.observer, date=dt.date())
    sunrise = s["sunrise"]
    sunset = s["sunset"]

    # Wenn dt vor sunrise oder nach sunset -> Nacht
    if dt < sunrise or dt > sunset:
        return True
    return False


# ---------------------------------------------------
# Flask-Routen
# ---------------------------------------------------

@app.route("/")
def home():
    return "Erweiterte CycleDoc Heatmap mit Straßenbelag + Tag/Nacht!"

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx():
    """
    Liest eine GPX-Datei (Upload-Feld: 'file'), parse sie mit gpxpy,
    und gibt die Koordinatenliste (lat,lon,elev) als JSON zurück.
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

@app.route("/advanced-heatmap", methods=["POST"])
def advanced_heatmap():
    """
    Nimmt JSON-Input:
    {
      "coordinates": [...],
      "fahrer_typ": "Amateur",
      "anzahl": 100,
      "geschlecht": "mixed",
      "rennen_art": "Kriterienrennen",
      "start_time": "2025-04-06T18:00:00Z",
      "wetter_override": {...} (optional)
    }
    Segmentiert, berechnet Risiko, erstellt eine Folium-Karte, speichert sie
    als HTML und gibt den Link + Segment-Infos zurück.
    """
    data = request.json
    coordinates = data.get("coordinates", [])
    if not coordinates or not isinstance(coordinates, list):
        return jsonify({"error": "Keine gültigen Koordinaten empfangen"}), 400

    fahrer_typ = data.get("fahrer_typ", "Amateur")
    teilnehmer = data.get("anzahl", 100)
    geschlecht = data.get("geschlecht", "mixed")
    rennen_art = data.get("rennen_art", "unknown")
    start_time_str = data.get("start_time", None)

    weather_override = data.get("wetter_override", {})

    # GPX in ~0.2-km-Segmente aufteilen
    segments = segmentize(coordinates, 0.2)
    if not segments:
        return jsonify({"error": "Keine Segmente gebildet"}), 400

    # Tag/Nacht für Startpunkt bestimmen
    first_seg_center = segments[0][len(segments[0]) // 2]
    lat_first, lon_first = first_seg_center[:2]

    nighttime = False  # Default: Tag
    if start_time_str:
        try:
            dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
            nighttime = is_nighttime_at(dt, lat_first, lon_first)
        except:
            # Fallback -> nighttime bleibt False
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

        # Wetter
        if weather_override:
            weather = weather_override
        else:
            try:
                params = {"access_key": WEATHERSTACK_API_KEY, "query": f"{lat},{lon}"}
                res = requests.get(ws_base_url, params=params, timeout=5)
                w_current = res.json()["current"]
                weather = {
                    "temperature": w_current["temperature"],
                    "wind_speed": w_current["wind_speed"],
                    "precip": w_current["precip"],
                    "condition": w_current["weather_descriptions"][0] if w_current["weather_descriptions"] else ""
                }
            except:
                weather = {
                    "temperature": 15,
                    "wind_speed": 10,
                    "precip": 0,
                    "condition": "Sunny"
                }

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
            street_surface=street_surface
        )

        sani_needed = needs_saniposten(risiko, sharp_curve, street_surface)

        # Terrain grob kategorisieren
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

    # Karte erzeugen
    map_center = segment_infos[0]["center"]
    m = folium.Map(location=[map_center["lat"], map_center["lon"]], zoom_start=13)

    risk_colors = {
        1: "green",
        2: "yellow",
        3: "orange",
        4: "red",
        5: "darkred"
    }

    for seg_info, seg_points in zip(segment_infos, segments):
        risk = seg_info["risk"]
        color = risk_colors.get(risk, "green")
        latlon_segment = [(p[0], p[1]) for p in seg_points]

        folium.PolyLine(
            locations=latlon_segment,
            color=color,
            weight=5,
            popup=(
                f"Seg {seg_info['segment_index']}, "
                f"Risk {risk}, "
                f"Belag {seg_info['street_surface']}"
            )
        ).add_to(m)

        if seg_info["sani_needed"]:
            folium.Marker(
                location=[seg_info["center"]["lat"], seg_info["center"]["lon"]],
                popup=(
                    f"Sani empfohlen!\n"
                    f"Risk: {seg_info['risk']}, "
                    f"Belag: {seg_info['street_surface']}"
                ),
                icon=folium.Icon(icon="plus", prefix="fa", color="red")
            ).add_to(m)

    # HTML speichern
    static_path = os.path.join(os.path.dirname(__file__), "static")
    if not os.path.exists(static_path):
        os.makedirs(static_path)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"advanced_heatmap_{timestamp}.html"
    filepath = os.path.join(static_path, filename)
    m.save(filepath)

    # Base-URL anpassen, falls nötig (z. B. http://localhost:5000)
    base_url = "https://gpx-heatmap-api.onrender.com"

    return jsonify({
        "heatmap_url": f"{base_url}/static/{filename}",
        "segments": segment_infos
    })

if __name__ == "__main__":
    # Startet den Server lokal auf Port 5000
    app.run(debug=True, port=5000)

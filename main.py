##############################################################
# main.py (mit Debug-Ausgaben für WeatherStack)
#
# 1) fetch_weather() -> print() der URL, Lat/Lon, Statuscode, Res.text
# 2) Sonst alles unverändert
##############################################################

from flask import Flask, request, jsonify, send_file
import folium
import os
import math
from datetime import datetime
from geopy.distance import geodesic
import requests
import gpxpy
import gpxpy.gpx

from astral import LocationInfo
from astral.sun import sun

from weasyprint import HTML
import random
import tempfile

app = Flask(__name__)

def bearing(pointA, pointB):
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
    diff = abs(b1 - b2)
    return min(diff, 360 - diff)

def detect_sharp_curve(segment_points, threshold=60):
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
    surfaces = ["asphalt", "cobblestone", "gravel", "asphalt", "asphalt", "gravel"]
    random.seed(int(abs(lat*1000) + abs(lon*1000)))
    return random.choice(surfaces)

def is_nighttime_at(dt, lat, lon):
    location = LocationInfo(
        name="RaceLocation",
        region="",
        timezone="UTC",
        latitude=lat,
        longitude=lon
    )
    s = sun(location.observer, date=dt.date())
    sunrise = s["sunrise"]
    sunset = s["sunset"]
    return dt < sunrise or dt > sunset

def segmentize(coordinates, segment_length_km=0.2):
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
    schutzausruestung=None,
    material="aluminium",
    overuse_knee=False,
    rueckenschmerzen=False,
    massenstart=False
):
    if schutzausruestung is None:
        schutzausruestung = {}

    risiko = 1

    # Wetter
    if temp <= 5:
        risiko += 1
    if wind >= 25:
        risiko += 1
    if precip >= 1:
        risiko += 1

    if abs(slope) > 4:
        risiko += 1

    typ_lower = fahrer_typ.lower()
    if typ_lower in ["hobby", "c-lizenz", "anfänger"]:
        risiko += 1
    elif typ_lower in ["a", "b", "elite", "profi"]:
        risiko -= 1

    if teilnehmer > 80:
        risiko += 1

    if massenstart:
        risiko += 1

    if nighttime:
        risiko += 1

    if sharp_curve:
        risiko += 1

    r = rennen_art.lower()
    if r in ["downhill", "freeride"]:
        risiko += 2
    elif r in ["mtb", "mountainbike", "xc", "gelände"]:
        risiko += 1
    elif r in ["kriterienrennen", "criterium"]:
        risiko += 1

    if geschlecht.lower() in ["w", "frau", "female"]:
        risiko += 1

    if alter >= 60:
        risiko += 1

    if street_surface in ["cobblestone", "gravel"]:
        risiko += 1

    if material.lower() == "carbon":
        risiko += 1

    if schutzausruestung.get("helm", False):
        risiko -= 1
    if schutzausruestung.get("protektoren", False):
        risiko -= 1

    if overuse_knee:
        risiko += 1
    if rueckenschmerzen:
        risiko += 1

    if risiko < 1:
        risiko = 1
    if risiko > 5:
        risiko = 5

    return risiko

def needs_saniposten(risk_value):
    return risk_value >= 3

def typical_injuries(risk, rennen_art):
    r = rennen_art.lower()
    if risk <= 2:
        return ["Abschürfungen", "Prellungen"]
    elif risk in [3, 4]:
        inj = ["Abschürfungen", "Prellungen", "Claviculafraktur", "Handgelenksverletzung"]
        if r in ["downhill", "freeride"]:
            inj.append("Wirbelsäulenverletzung (selten, aber möglich)")
        return inj
    else:  # risk == 5
        inj = ["Abschürfungen", "Claviculafraktur", "Wirbelsäulenverletzung", "Beckenfraktur"]
        if r in ["downhill", "freeride"]:
            inj.append("Schwere Rücken-/Organverletzungen")
        return inj

app = Flask(__name__)

@app.route("/")
def home():
    return "Erweiterte CycleDoc Heatmap (Skala 1..5) - DEBUG WeatherStack!"

@app.route("/parse-gpx", methods=["POST"])
def parse_gpx_route():
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
    data = request.json
    coords = data.get("coordinates", [])
    if not coords:
        return jsonify({"error": "Keine Koordinaten empfangen"}), 400

    fahrer_typ = data.get("fahrer_typ", "hobby")
    teilnehmer = data.get("anzahl", 50)
    rennen_art = data.get("rennen_art", "unknown")
    geschlecht = data.get("geschlecht", "mixed")
    alter = data.get("alter", 35)
    start_time_str = data.get("start_time", None)
    material = data.get("material", "aluminium")
    massenstart = data.get("massenstart", False)
    overuse_knee = data.get("overuse_knee", False)
    rueckenschmerzen = data.get("rueckenschmerzen", False)
    schutzausruestung = data.get("schutzausruestung", {})
    weather_override = data.get("wetter_override", {})

    segments = segmentize(coords, 0.2)
    if not segments:
        return jsonify({"error": "Keine Segmente gebildet"}), 400

    nighttime = False
    if start_time_str:
        try:
            dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
            nighttime = is_nighttime_at(dt, coords[0][0], coords[0][1])
        except:
            pass

    WEATHERSTACK_API_KEY = os.environ.get("WEATHERSTACK_API_KEY", "")
    ws_base_url = "http://api.weatherstack.com/current"  # oder https:// - je nach Plan

    # DEBUG: print statements to see if we have a KEY and URL
    print("DEBUG: Using WeatherStack endpoint:", ws_base_url)
    # (Beachte: KEY nicht ausgeben wenn du ihn nicht öffentlich machen willst)

    def fetch_weather(lat, lon):
        """
        Fetch weather from WeatherStack, with debug prints for status code + response text.
        """
        try:
            # Debug
            print(f"fetch_weather() called with lat={lat}, lon={lon}")
            if not WEATHERSTACK_API_KEY:
                print("DEBUG: No WEATHERSTACK_API_KEY found in environment!")
            query_str = f"{lat},{lon}"
            params = {"access_key": WEATHERSTACK_API_KEY, "query": query_str}
            
            print("DEBUG: Making request to WeatherStack with params:", params)
            res = requests.get(ws_base_url, params=params, timeout=5)

            print("DEBUG: WeatherStack response status:", res.status_code)
            print("DEBUG: WeatherStack response text:", res.text)

            data_ws = res.json()
            if "current" in data_ws:
                c = data_ws["current"]
                return {
                    "temperature": c.get("temperature", 15),
                    "wind_speed": c.get("wind_speed", 10),
                    "precip": c.get("precip", 0),
                    "condition": c.get("weather_descriptions", [""])[0] if c.get("weather_descriptions") else ""
                }
            else:
                print("DEBUG: 'current' not in data_ws. Possibly an error from WeatherStack.")
                return None
        except Exception as e:
            print("DEBUG: Exception in fetch_weather:", e)
            return None

    segment_infos = []
    for i, seg in enumerate(segments):
        center_idx = len(seg)//2
        center_pt = seg[center_idx]
        lat, lon = center_pt[:2]

        slope = calc_slope(seg)
        sharp_curve = detect_sharp_curve(seg, threshold=60)
        surface = get_street_surface(lat, lon)

        if weather_override:
            weather = weather_override
        else:
            w = fetch_weather(lat, lon)
            if w is None:
                weather = {
                    "temperature": 15,
                    "wind_speed": 10,
                    "precip": 0,
                    "condition": "MANUELL BITTE EINGEBEN"
                }
            else:
                weather = w

        r_value = calc_risk(
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
            street_surface=surface,
            alter=alter,
            schutzausruestung=schutzausruestung,
            material=material,
            overuse_knee=overuse_knee,
            rueckenschmerzen=rueckenschmerzen,
            massenstart=massenstart
        )

        injuries = typical_injuries(r_value, rennen_art)
        sani_needed = needs_saniposten(r_value)

        if slope > 2:
            terrain = "Anstieg"
        elif slope < -2:
            terrain = "Abfahrt"
        else:
            terrain = "Flach"

        segment_infos.append({
            "segment_index": i+1,
            "center": {"lat": lat, "lon": lon},
            "slope": slope,
            "sharp_curve": sharp_curve,
            "terrain": terrain,
            "weather": weather,
            "nighttime": nighttime,
            "street_surface": surface,
            "risk": r_value,
            "injuries": injuries,
            "sani_needed": sani_needed
        })

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
        c = risk_colors.get(seg_info["risk"], "green")
        latlons = [(p[0], p[1]) for p in seg_points]

        folium.PolyLine(
            locations=latlons,
            color=c,
            weight=5,
            popup=(f"Seg {seg_info['segment_index']}, "
                   f"R {seg_info['risk']}, "
                   f"{seg_info['injuries']}")
        ).add_to(m)

        if seg_info["sani_needed"]:
            folium.Marker(
                location=[seg_info["center"]["lat"], seg_info["center"]["lon"]],
                popup=f"Sani empfohlen (Risk {seg_info['risk']})",
                icon=folium.Icon(icon="plus", prefix="fa", color="red")
            ).add_to(m)

    static_path = os.path.join(os.path.dirname(__file__), "static")
    if not os.path.exists(static_path):
        os.makedirs(static_path)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"heatmap_{timestamp}.html"
    filepath = os.path.join(static_path, filename)
    m.save(filepath)

    # URL anpassen
    base_url = "http://localhost:5000"
    # If you are on Render => base_url = "https://gpx-heatmap-api.onrender.com"

    return jsonify({
        "heatmap_url": f"{base_url}/static/{filename}",
        "segments": segment_infos
    })

@app.route("/pdf-report", methods=["POST"])
def pdf_report():
    data = request.json
    title = data.get("title", "Radsport Report")
    summary = data.get("summary", "")
    segments = data.get("segments", [])
    heatmap_url = data.get("heatmap_url", "#")

    html_content = f"""
    <html>
    <head>
      <meta charset='utf-8' />
      <style>
        body {{ font-family: sans-serif; }}
        h1 {{ color: #333; }}
        .risk {{ color: red; font-weight: bold; }}
        .seg-box {{ margin-bottom: 15px; border-bottom: 1px solid #ccc; padding: 5px; }}
      </style>
    </head>
    <body>
      <h1>{title}</h1>
      <p>{summary}</p>
      <p>Heatmap: <a href='{heatmap_url}' target='_blank'>{heatmap_url}</a></p>
      <hr />
      <h2>Segmente</h2>
    """

    for seg in segments:
        injuries_str = seg.get("injuries", [])
        if isinstance(injuries_str, list):
            injuries_str = ", ".join(injuries_str)
        else:
            injuries_str = str(injuries_str)
        
        html_content += f"""
        <div class='seg-box'>
          <h3>Segment {seg.get('segment_index')}</h3>
          <p>Risk: <span class='risk'>{seg.get('risk')}</span></p>
          <p>Injuries: {injuries_str}</p>
          <p>Weather: {seg.get('weather')}</p>
        </div>
        """

    html_content += """
    </body>
    </html>
    """

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmpfile:
        pdf_path = tmpfile.name

    HTML(string=html_content).write_pdf(pdf_path)
    return send_file(pdf_path, as_attachment=True, download_name="radsport_report.pdf")

if __name__ == "__main__":
    app.run(debug=True, port=5000)

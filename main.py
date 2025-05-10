# main.py
# CycleDoc Heatmap API with GPX chunking support

import os
import base64
import io
import math
import folium
import requests
import json
from datetime import datetime
from astral.sun import sun
from cachetools import TTLCache
from flask import Flask, request, jsonify, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from geopy.distance import geodesic
from gpxpy import parse as parse_gpx
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from celery import Celery
from config import (
    MIN_SEGMENT_LENGTH_KM, MAX_POINTS, DEFAULT_WEATHER, VALID_FAHRER_TYPES,
    VALID_RENNEN_ART, VALID_GESCHLECHT, VALID_MATERIAL, VALID_STREET_SURFACE, MAX_SEGMENTS
)

# Logging configuration
logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Flask app setup
app = Flask(__name__)

# Celery setup
celery_app = Celery(
    'tasks',
    broker=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0')
)

# Rate limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["10 per minute", "200 per day", "50 per hour"]
)

# Weather cache (TTL: 1 hour)
weather_cache = TTLCache(maxsize=100, ttl=3600)

# SQLite database setup
engine = create_engine("sqlite:///chunks.db")
Base = declarative_base()

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    filename = Column(String, unique=True)
    data = Column(String)

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# Helper functions
def validate_coordinates(coordinates):
    """Validate list of coordinates."""
    if not isinstance(coordinates, list) or len(coordinates) > MAX_POINTS:
        return False, f"Invalid coordinates or exceeds {MAX_POINTS} points"
    for coord in coordinates:
        if not (isinstance(coord, list) and 2 <= len(coord) <= 3):
            return False, "Invalid coordinate format"
        lat, lon = coord[0], coord[1]
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False, "Invalid latitude or longitude"
    return True, None

def get_weather(lat, lon, timestamp):
    """Fetch or return cached weather data."""
    cache_key = f"{lat}:{lon}:{timestamp}"
    if cache_key in weather_cache:
        return weather_cache[cache_key]
    
    api_key = os.getenv("WEATHERSTACK_API_KEY")
    if not api_key:
        logger.warning("WEATHERSTACK_API_KEY not set, using default weather")
        return DEFAULT_WEATHER
    
    try:
        response = requests.get(
            f"http://api.weatherstack.com/current",
            params={"access_key": api_key, "query": f"{lat},{lon}"},
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        weather = {
            "temperature": data["current"]["temperature"],
            "wind_speed": data["current"]["wind_speed"],
            "precip": data["current"]["precip"],
            "condition": data["current"]["weather_descriptions"][0]
        }
        weather_cache[cache_key] = weather
        return weather
    except requests.Timeout:
        logger.error("Weather API timed out")
        return DEFAULT_WEATHER
    except Exception as e:
        logger.error(f"Weather API error: {e}")
        return DEFAULT_WEATHER

def calculate_distance(coordinates):
    """Calculate total distance in kilometers."""
    total_distance = 0.0
    for i in range(1, len(coordinates)):
        total_distance += geodesic(
            (coordinates[i-1][0], coordinates[i-1][1]),
            (coordinates[i][0], coordinates[i][1])
        ).kilometers
    return total_distance

def group_segments(coordinates, distance_km):
    """Group coordinates into segments with a limit on max segments."""
    segments = []
    current_segment = [coordinates[0]]
    current_distance = 0.0
    for i in range(1, len(coordinates)):
        dist = geodesic(
            (coordinates[i-1][0], coordinates[i-1][1]),
            (coordinates[i][0], coordinates[i][1])
        ).kilometers
        current_distance += dist
        current_segment.append(coordinates[i])
        if current_distance >= MIN_SEGMENT_LENGTH_KM:
            segments.append({
                "coordinates": current_segment,
                "distance_km": current_distance,
                "center": [
                    sum(c[0] for c in current_segment) / len(current_segment),
                    sum(c[1] for c in current_segment) / len(current_segment)
                ]
            })
            if len(segments) >= MAX_SEGMENTS:
                logger.warning(f"Reached max segments ({MAX_SEGMENTS}), stopping segmentation")
                break
            current_segment = [coordinates[i]]
            current_distance = 0.0
    if current_segment and len(segments) < MAX_SEGMENTS:
        segments.append({
            "coordinates": current_segment,
            "distance_km": current_distance,
            "center": [
                sum(c[0] for c in current_segment) / len(current_segment),
                sum(c[1] for c in current_segment) / len(current_segment)
                ]
            })
    return segments

def analyze_risk(segment, params, timestamp):
    """Analyze risk for a segment."""
    center = segment["center"]
    weather = params.get("wetter_override") or get_weather(center[0], center[1], timestamp)
    
    # Calculate slope
    coords = segment["coordinates"]
    elevation_diff = coords[-1][2] - coords[0][2] if len(coords[0]) > 2 and len(coords[-1]) > 2 else 0
    slope = (elevation_diff / (segment["distance_km"] * 1000)) * 100 if segment["distance_km"] > 0 else 0
    
    # Check for sharp curves
    sharp_curve = False
    for i in range(1, len(coords)-1):
        v1 = [coords[i][0] - coords[i-1][0], coords[i][1] - coords[i-1][1]]
        v2 = [coords[i+1][0] - coords[i][0], coords[i+1][1] - coords[i][1]]
        angle = math.degrees(math.acos(
            sum(a*b for a, b in zip(v1, v2)) /
            (math.sqrt(sum(a*a for a in v1)) * math.sqrt(sum(b*b for b in v2)) + 1e-10)
        ))
        if angle >= 60:
            sharp_curve = True
            break
    
    # Nighttime check
    s = sun(center[0], center[1], date=datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date())
    is_night = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).time() < s["sunrise"].time() or \
               datetime.fromisoformat(timestamp.replace("Z", "+00:00")).time() > s["sunset"].time()
    
    # Risk scoring
    risk = 1
    if abs(slope) > 5:
        risk += 1
    if sharp_curve:
        risk += 1
    if weather["precip"] > 2 or weather["wind_speed"] > 20:
        risk += 1
    if is_night:
        risk += 1
    if params.get("fahrer_typ") in ["anfänger", "hobby"]:
        risk += 1
    risk = min(risk, 5)
    
    terrain = "Anstieg" if slope > 2 else "Abfahrt" if slope < -2 else "Flach"
    street_surface = params.get("street_surface", VALID_STREET_SURFACE[0])
    
    injuries = ["Abschürfungen", "Prellungen"] if risk <= 3 else ["Abschürfungen", "Prellungen", "Claviculafraktur"]
    sani_needed = risk >= 3
    
    return {
        "segment_index": len(segment),
        "center": {"lat": center[0], "lon": center[1]},
        "slope": slope,
        "sharp_curve": sharp_curve,
        "terrain": terrain,
        "weather": weather,
        "nighttime": is_night,
        "street_surface": street_surface,
        "risk": risk,
        "injuries": injuries,
        "sani_needed": sani_needed
    }

# Celery task for heatmap rendering
@celery_app.task
def render_heatmap(segments, segment_details):
    """Render heatmap asynchronously."""
    try:
        # Use the center of the first segment as the map starting point
        center_lat = segments[0]["center"][0]
        center_lon = segments[0]["center"][1]
        m = folium.Map(location=[center_lat, center_lon], zoom_start=13)
        for segment, details in zip(segments, segment_details):
            color = "green" if details["risk"] <= 2 else "orange" if details["risk"] <= 3 else "red"
            folium.PolyLine(
                locations=[[c[0], c[1]] for c in segment["coordinates"]],
                color=color,
                weight=5
            ).add_to(m)
            if details["sani_needed"]:
                folium.Marker(
                    location=[details["center"]["lat"], details["center"]["lon"]],
                    popup="🚑 Sanitäter recommended",
                    icon=folium.Icon(color="red")
                ).add_to(m)
        heatmap_file = f"static/heatmap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
        os.makedirs("static", exist_ok=True)
        m.save(heatmap_file)
        return heatmap_file
    except Exception as e:
        logger.error(f"Celery heatmap rendering failed: {str(e)}")
        raise

def process_gpx_in_chunks(gpx_data, chunk_size=200):
    """Split GPX data into chunks and process them separately."""
    try:
        gpx = parse_gpx(io.StringIO(gpx_data))
        all_points = []
        for track in gpx.tracks:
            for segment in track.segments:
                all_points.extend(segment.points)

        if len(all_points) > MAX_POINTS:
            return {"error": f"Too many points ({len(all_points)}). Max allowed: {MAX_POINTS}"}, 400

        # Split points into chunks
        chunks = [all_points[i:i + chunk_size] for i in range(0, len(all_points), chunk_size)]
        results = []
        for chunk in chunks:
            # Convert chunk to coordinates format
            coordinates = [[point.latitude, point.longitude, point.elevation or 0] for point in chunk]
            if len(coordinates) < 2:
                continue

            # Calculate distance and segments for the chunk
            distance_km = calculate_distance(coordinates)
            segments = group_segments(coordinates, distance_km)
            segment_details = [analyze_risk(segment, {"fahrer_typ": "hobby", "geschlecht": "m", "anzahl": 2}, "2025-05-11T10:00:00Z") for segment in segments]

            # Offload heatmap rendering to Celery
            task = render_heatmap.delay(segments, segment_details)
            try:
                heatmap_file = task.get(timeout=60)
                results.append({
                    "heatmap_url": f"https://gpx-heatmap-api.onrender.com/{heatmap_file}",
                    "distance_km": distance_km,
                    "segments": segment_details
                })
            except Exception as e:
                logger.error(f"Heatmap rendering task failed for chunk: {str(e)}")
                results.append({"error": "Failed to render heatmap for this chunk"})
        return results, 200 if all("error" not in r for r in results) else 500
    except Exception as e:
        logger.error(f"GPX chunk processing error: {str(e)}")
        return {"error": f"Failed to process GPX: {str(e)}"}, 500

# API Endpoints
@app.route("/", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return "✅ CycleDoc Heatmap-API ready", 200

@app.route("/heatmap-quick", methods=["POST"])
@limiter.limit("10 per minute")
def heatmap_quick():
    """Generate heatmap and risk analysis."""
    try:
        data = request.get_json()
        if not data or "coordinates" not in data or "start_time" not in data:
            return jsonify({"error": "Missing coordinates or start_time"}), 400
        
        coordinates = data["coordinates"]
        valid, error = validate_coordinates(coordinates)
        if not valid:
            return jsonify({"error": error}), 400
        
        start_time = data["start_time"]
        try:
            datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            return jsonify({"error": "Invalid start_time format"}), 400
        
        params = {
            "fahrer_typ": data.get("fahrer_typ", VALID_FAHRER_TYPES[0]),
            "anzahl": data.get("anzahl", 5),
            "rennen_art": data.get("rennen_art", ""),
            "geschlecht": data.get("geschlecht", ""),
            "alter": data.get("alter", 42),
            "material": data.get("material", VALID_MATERIAL[1]),
            "schutzausruestung": data.get("schutzausruestung", {"helm": False, "protektoren": False}),
            "overuse_knee": data.get("overuse_knee", False),
            "rueckenschmerzen": data.get("rueckenschmerzen", False),
            "massenstart": data.get("massenstart", False),
            "wetter_override": data.get("wetter_override"),
            "street_surface": data.get("street_surface", VALID_STREET_SURFACE[0])
        }
        
        distance_km = calculate_distance(coordinates)
        segments = group_segments(coordinates, distance_km)
        segment_details = [analyze_risk(segment, params, start_time) for segment in segments]
        
        # Offload heatmap rendering to Celery
        task = render_heatmap.delay(segments, segment_details)
        try:
            heatmap_file = task.get(timeout=60)
        except Exception as e:
            logger.error(f"Heatmap rendering task failed: {str(e)}")
            return jsonify({"error": "Failed to render heatmap, please try again later"}), 500
        
        # Generate report
        report = "\n".join([
            f"Route Length: The route covers {distance_km:.1f} km.",
            f"Weather Conditions: Representative Point: (Lat: {segments[0]['center'][0]:.3f}, Lon: {segments[0]['center'][1]:.3f})\n"
            f"Date and Time: {start_time}\n"
            f"Temperature: {segment_details[0]['weather']['temperature']}°C, "
            f"Wind: {segment_details[0]['weather']['wind_speed']} km/h, "
            f"Precipitation: {segment_details[0]['weather']['precip']} mm, "
            f"Condition: {segment_details[0]['weather']['condition']}\n"
            f"Source: WeatherStack",
            "Risk Assessment per Segment: " + "\n".join(
                f"Segment {d['segment_index']}: Risk: {d['risk']} "
                f"(Slope: {d['slope']:.1f}%, Terrain: {d['terrain']}, Surface: {d['street_surface']})"
                f"{' – 🚑 Sanitäter recommended' if d['sani_needed'] else ''}"
                for d in segment_details
            ),
            f"Overall Risk: Average Risk Score: {sum(d['risk'] for d in segment_details) / len(segment_details):.1f}",
            f"Likely Injuries: Typical Injuries: {', '.join(set(sum([d['injuries'] for d in segment_details], [])))}\n"
            f"Recommended Studies: (Rehlinghaus 2022), (Nelson 2010)",
            "Prevention Recommendations: Watch for sharp curves, ride cautiously on steep slopes",
            "Sources: Scientific Sources: (Rehlinghaus 2022), (Kronisch 2002, p. 5), (Nelson 2010), "
            "(Dannenberg 1996), (Ruedl 2015), (Clarsen 2005)\nWeather Data: WeatherStack",
            f"Interactive Map Details: Heatmap URL: https://gpx-heatmap-api.onrender.com/{heatmap_file}\n"
            f"Color Scale: green = low risk, orange = medium risk, red = high risk.\n"
            f"🚑 markers indicate segments where a paramedic is recommended."
        ])
        
        logger.info(f"Generated heatmap for {len(coordinates)} points, {len(segments)} segments")
        return jsonify({
            "heatmap_url": f"https://gpx-heatmap-api.onrender.com/{heatmap_file}",
            "distance_km": distance_km,
            "segments": segment_details,
            "detailed_report": report
        })
    except Exception as e:
        logger.error(f"Unexpected error in /heatmap-quick: {str(e)}")
        return jsonify({"error": "Internal server error, please try again later"}), 500

@app.route("/parse-gpx", methods=["POST"])
@limiter.limit("10 per minute")
def parse_gpx_endpoint():
    """Parse GPX file and extract coordinates."""
    try:
        data = request.get_json()
        if not data or "file_base64" not in data:
            return jsonify({"error": "Missing file_base64 in JSON request"}), 400
        
        file_base64 = data["file_base64"]
        content = base64.b64decode(file_base64, validate=True)
        gpx_content = content.decode("utf-8", errors="replace")
        gpx = parse_gpx(io.StringIO(gpx_content))
        coordinates = []
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    coordinates.append([point.latitude, point.longitude, point.elevation or None])
        if not coordinates:
            return jsonify({"error": "No track points found in GPX file"}), 400
        valid, error = validate_coordinates(coordinates)
        if not valid:
            return jsonify({"error": error}), 400
        distance_km = calculate_distance(coordinates)
        logger.info(f"Successfully parsed GPX with {len(coordinates)} points")
        return jsonify({"coordinates": coordinates, "distance_km": round(distance_km, 2)})
    except base64.binascii.Error as e:
        logger.error(f"Invalid Base64 data: {e}")
        return jsonify({"error": "Invalid Base64 encoding"}), 400
    except UnicodeDecodeError as e:
        logger.error(f"Decoding error: {e}")
        return jsonify({"error": "Unable to decode GPX content, ensure UTF-8 encoding"}), 400
    except Exception as e:
        logger.error(f"GPX parsing error: {e}")
        return jsonify({"error": f"Invalid GPX file: {str(e)}"}), 400

@app.route("/chunk-upload", methods=["POST"])
@limiter.limit("10 per minute")
def chunk_upload():
    """Split coordinates into chunks and store."""
    try:
        data = request.get_json()
        if not data or "coordinates" not in data:
            return jsonify({"error": "Missing coordinates"}), 400
        
        coordinates = data["coordinates"]
        chunk_size = data.get("chunk_size", 200)
        valid, error = validate_coordinates(coordinates)
        if not valid:
            return jsonify({"error": error}), 400
        
        chunks = [coordinates[i:i + chunk_size] for i in range(0, len(coordinates), chunk_size)]
        session = Session()
        chunk_filenames = []
        try:
            for i, chunk in enumerate(chunks):
                filename = f"chunk_{i+1}.json"
                session.add(Chunk(filename=filename, data=json.dumps(chunk)))
                chunk_filenames.append(filename)
            session.commit()
            return jsonify({"message": f"{len(chunks)} chunks stored", "chunks": chunk_filenames})
        except Exception as e:
            session.rollback()
            logger.error(f"Chunk storage error: {e}")
            return jsonify({"error": "Error saving chunks"}), 500
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Unexpected error in /chunk-upload: {str(e)}")
        return jsonify({"error": "Internal server error, please try again later"}), 500

@app.route("/heatmap-gpx", methods=["POST"])
@limiter.limit("5 per minute")
def heatmap_gpx():
    """Generate heatmap from GPX file with chunking."""
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if not file.filename.endswith(".gpx"):
            return jsonify({"error": "File must be a .gpx file"}), 400

        gpx_data = file.read().decode("utf-8")
        results, status = process_gpx_in_chunks(gpx_data, chunk_size=200)
        if status != 200:
            return jsonify(results), status

        # Generate combined report for all chunks
        combined_report = "\n".join([
            f"Total Chunks Processed: {len(results)}",
            "Individual Chunk Results:",
            "\n".join([f"Chunk {i+1}: Distance: {r.get('distance_km', 0):.1f} km, Heatmap URL: {r.get('heatmap_url', 'N/A')}" 
                      for i, r in enumerate(results) if "error" not in r])
        ])
        if any("error" in r for r in results):
            combined_report += "\nErrors occurred in some chunks. Check individual results."

        return jsonify({
            "results": results,
            "combined_report": combined_report
        })
    except Exception as e:
        logger.error(f"Unexpected error in /heatmap-gpx: {str(e)}")
        return jsonify({"error": "Internal server error, please try again later"}), 500

@app.route("/openapi.yaml", methods=["GET"])
def openapi_spec():
    """Serve OpenAPI specification."""
    try:
        return send_file("openapi.yaml", mimetype="text/yaml")
    except FileNotFoundError:
        return jsonify({"error": "OpenAPI file not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

CycleDoc Heatmap-API
Eine API zur Verarbeitung von GPX-Daten, Segmentierung von Routen, Risikoanalyse und Erstellung einer interaktiven Heatmap. Die API berechnet Streckenlänge, führt eine Risikoanalyse basierend auf Wetter, Steigung, Kurven, Fahrerprofil und weiteren Parametern durch, erstellt einen detaillierten Bericht und visualisiert die Ergebnisse in einer interaktiven Karte mit intelligenter Sanitäterlogik.
Funktionalität

GPX-Verarbeitung: Lädt und parst GPX-Dateien, extrahiert Koordinaten und berechnet die Gesamtdistanz. Unterstützt sowohl multipart/form-data (Datei-Upload) als auch application/json (Base64-codierte Datei). Häufige XML-Probleme (z. B. BOM, falsches Encoding, fehlender Header) werden automatisch korrigiert.
Segmentierung: Teilt die Strecke in Segmente auf (Standard: 0,005 km pro Segment).
Risikoanalyse: Bewertet das Risiko basierend auf Wetter, Steigung, Kurven, Fahrerprofil (z. B. Typ, Alter, Geschlecht), Straßenoberfläche, Schutzausrüstung, Massenstart, Nachtzeit und weiteren Parametern.
Wetterabfrage: Ruft Wetterdaten von WeatherStack für mehrere Punkte entlang der Strecke ab (ca. alle 50 km), um regionale Unterschiede zu berücksichtigen. Unterstützt auch manuelle Überschreibung der Wetterdaten.
Heatmap: Erstellt eine interaktive Karte mit Folium, die die gesamte Route (blau) sowie riskante Segmente (grün/orange/rot) anzeigt. Sanitäterempfehlungen werden als Marker (🚑) hinzugefügt.
Detaillierter Bericht: Generiert einen umfassenden Bericht mit Streckenlänge, Wetterlage, Risikoeinschätzung, wahrscheinlichen Verletzungen, Präventionsempfehlungen, Quellen und einem Link zur Heatmap.
Chunking: Teilt große Strecken in kleinere JSON-Chunks auf, um die Verarbeitung zu erleichtern.
Logging: Detaillierte Logs werden in app.log geschrieben und enthalten Informationen zur Segmentierung, Risikoanalyse, Wetterabfrage und Fehlerbehandlung.

Einschränkungen

Es gibt ein Limit von 100.000 Trackpunkten pro GPX-Datei, um Speicherprobleme zu vermeiden.
Für große Dateien wird ein Task-Queue-System wie Celery empfohlen (nicht implementiert).

Installation

Abhängigkeiten installieren:
pip install flask gpxpy folium geopy astral requests chardet


flask: Web-Framework für die API.
gpxpy: Zum Parsen von GPX-Dateien.
folium: Zur Erstellung interaktiver Karten.
geopy: Zur Berechnung geodätischer Entfernungen.
astral: Zur Bestimmung von Sonnenaufgang und -untergang (Nachtzeit-Erkennung).
requests: Für die Wetterabfrage via WeatherStack.
chardet: Für die Erkennung und Korrektur des Encodings von GPX-Dateien.


Umgebungsvariable für Wetter-API setzen:
export WEATHERSTACK_API_KEY=dein_api_key

Ersetze dein_api_key durch deinen WeatherStack API-Schlüssel. Ohne Schlüssel werden Standardwetterdaten verwendet.

API starten:
python main.py

Die API läuft auf http://localhost:5000. Im Produktionsmodus sollte ein WSGI-Server wie gunicorn verwendet werden.


Endpunkte

GET /: Einfacher Health-Check. Antwort: "✅ CycleDoc Heatmap-API bereit".
POST /heatmap-quick: Erstellt eine Heatmap und einen detaillierten Bericht basierend auf Koordinaten und Parametern.
POST /parse-gpx: Parst eine GPX-Datei und gibt Koordinaten sowie die Streckenlänge zurück.
POST /chunk-upload: Teilt Koordinaten in kleinere JSON-Chunks auf und speichert diese.
GET /openapi.yaml: Liefert die OpenAPI-Spezifikation.

Details zu den Endpunkten findest du in der OpenAPI-Spezifikation.
Beispiel: /heatmap-quick
Anfrage
{
  "coordinates": [
    [48.137154, 11.576124, 520],
    [48.138, 11.577, 521],
    [48.139, 11.578, 522]
  ],
  "start_time": "2025-04-09T07:00:00Z",
  "fahrer_typ": "hobby",
  "anzahl": 5,
  "rennen_art": "road",
  "geschlecht": "w",
  "alter": 42,
  "material": "aluminium",
  "schutzausruestung": {
    "helm": true,
    "protektoren": false
  },
  "overuse_knee": false,
  "rueckenschmerzen": false,
  "massenstart": false
}

Antwort
{
  "heatmap_url": "https://gpx-heatmap-api.onrender.com/static/heatmap_20250409120000.html",
  "distance_km": 0.23,
  "segments": [
    {
      "segment_index": 1,
      "center": {"lat": 48.138, "lon": 11.577},
      "slope": 0.1,
      "sharp_curve": false,
      "terrain": "Flach",
      "weather": {
        "temperature": 15,
        "wind_speed": 10,
        "precip": 0,
        "condition": "klar"
      },
      "nighttime": false,
      "street_surface": "asphalt",
      "risk": 1,
      "injuries": ["Abschürfungen", "Prellungen"],
      "sani_needed": false
    }
  ],
  "detailed_report": "Abschnitt 0: Streckenlänge\nDie Strecke umfasst 0.23 km.\n\n..."
}

Fehlerbehandlung

400 (Bad Request): Ungültige Eingabedaten, z. B. ungültige Koordinaten, ungültige GPX-Datei, zu wenige Koordinaten, oder zu viele Trackpunkte (max. 100.000).
500 (Server Error): Fehler bei der Verarbeitung, z. B. beim Speichern der Heatmap oder Parsen der GPX-Datei. Überprüfe app.log für Details.

Lizenz
MIT License

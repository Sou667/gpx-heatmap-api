# 🚴‍♂️ CycleDoc Heatmap API

[![API Status](https://img.shields.io/badge/API-Live-green)](https://gpx-heatmap-api.onrender.com)  
[![Version](https://img.shields.io/badge/version-1.0-blue)](#)  
[![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1.0-yellow)](https://gpx-heatmap-api.onrender.com/openapi.yaml)  
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

CycleDoc Heatmap API ist ein KI-gestütztes Analyse-Tool, das Radsportverletzungen und Sicherheitsrisiken untersucht.  
Die API verarbeitet reale GPX‑Streckendaten, segmentiert die Strecke in kurze Abschnitte (etwa 0.005 km pro Segment) und berechnet risikoabhängige Kennzahlen – basierend auf Wetter, Streckenprofil, Straßenoberfläche und wissenschaftlichen Studien. Mithilfe eines intelligenten, clusterbasierten Algorithmus für die Sanitäter‑Logik werden interaktive Risiko‑Heatmaps generiert. Zusätzlich wird ein detaillierter Textbericht erstellt.

## Neuerungen in dieser Version

- **Echte Wetterabfrage:**  
  Die API ruft aktuelle Wetterdaten von WeatherStack ab (sofern die Umgebungsvariable `WEATHERSTACK_API_KEY` gesetzt ist). Ohne API‑Schlüssel werden Standardwerte verwendet.
  
- **Verbesserte Standortbestimmung:**  
  Es wird ein repräsentativer Mittelpunkt der Strecke zur Abfrage von Wetterdaten und zur Bestimmung der Nachtzeit verwendet.

- **Detaillierter Bericht:**  
  Zusätzlich zur JSON-Antwort liefert die API einen strukturierten Textbericht in folgenden Abschnitten:
  1. Streckenlänge  
  2. Wetterlage  
  3. Segmentweise Risikoeinschätzung  
  4. Gesamtrisiko  
  5. Wahrscheinliche Verletzungen  
  6. Präventionsempfehlung  
  7. Interaktive Karte (inkl. Erklärung der Farbskala und 🚑‑Markern)

## Live-Demo

👉 [Jetzt testen](https://gpx-heatmap-api.onrender.com/static/heatmap_YYYYMMDDHHMMSS.html)  
*Hinweis: Der Dateiname der generierten Heatmap enthält einen Zeitstempel (YYYYMMDDHHMMSS).*

## Endpunkte

- **GET /**  
  Health‑Check der API.

- **POST /heatmap-quick**  
  Führt eine segmentierte Risikoanalyse aus, erstellt eine interaktive Heatmap und generiert einen detaillierten Bericht.

- **POST /parse-gpx**  
  Parst eine hochgeladene GPX‑Datei und extrahiert Koordinaten sowie die Gesamtstrecke.

- **POST /chunk-upload**  
  Teilt GPX‑Koordinaten in kleinere Chunks und speichert diese als JSON‑Dateien.

- **GET /openapi.yaml**  
  Liefert die vollständige OpenAPI‑Spezifikation im YAML‑Format.

## Beispielaufruf

Hier ein Beispielaufruf mit cURL für den Endpunkt `/heatmap-quick`:

```bash
curl -X POST https://gpx-heatmap-api.onrender.com/heatmap-quick \
  -H "Content-Type: application/json" \
  -d '{
        "coordinates": [[51.242, 6.830, 42.0], [51.243, 6.831, 42.1], [51.244, 6.832, 42.2]],
        "start_time": "2025-04-09T07:00:00Z",
        "fahrer_typ": "hobby",
        "anzahl": 1,
        "alter": 42,
        "geschlecht": "m",
        "massenstart": false,
        "overuse_knee": false,
        "rueckenschmerzen": false,
        "material": "aluminium",
        "rennen_art": "downhill",
        "wetter_override": {
           "temperature": 10,
           "wind_speed": 12,
           "precip": 0,
           "condition": "klar"
        },
        "schutzausruestung": {
           "helm": true,
           "protektoren": false
        }
      }'

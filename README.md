# 🚴‍♂️ CycleDoc Heatmap API

[![API Status](https://img.shields.io/badge/API-Live-green)](https://gpx-heatmap-api.onrender.com)
[![Version](https://img.shields.io/badge/version-1.0-blue)](#)
[![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1.0-yellow)](https://gpx-heatmap-api.onrender.com/openapi.yaml)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

CycleDoc Heatmap API ist ein KI-gestütztes Analyse-Tool, das Radsportverletzungen und Sicherheitsrisiken untersucht.  
Die API verarbeitet reale GPX-Streckendaten, segmentiert die Strecke in kurze Abschnitte (etwa 0.005 km pro Segment) und berechnet risikoabhängige Kennzahlen – basierend auf Wetter, Streckenprofil, Straßenoberfläche und wissenschaftlichen Studien. Mithilfe eines intelligenten, clusterbasierten Algorithmus für die Sanitäter‑Logik werden interaktive Risiko‑Heatmaps generiert.

## Neuerungen in dieser Version

- **Echte Wetterabfrage:**  
  Die API ruft aktuelle Wetterdaten von WeatherStack ab (sofern die Umgebungsvariable `WEATHERSTACK_API_KEY` gesetzt ist). Ohne API-Schlüssel werden Standardwerte verwendet.
  
- **Verbesserte Standortbestimmung:**  
  Es wird ein repräsentativer Mittelpunkt der Strecke zur Abfrage von Wetterdaten und zur Bestimmung, ob es Nacht ist, verwendet.

- **Detaillierter Bericht:**  
  Zusätzlich zu den JSON-Daten liefert die API einen strukturierten Textbericht in folgenden Abschnitten:
  1. Streckenlänge  
  2. Wetterlage  
  3. Segmentweise Risikoeinschätzung  
  4. Gesamtrisiko  
  5. Wahrscheinliche Verletzungen  
  6. Präventionsempfehlung  
  7. Interaktive Karte (inkl. Erklärung der Farbskala und 🚑‑Markern)

## Live-Demo

👉 [Jetzt testen](https://gpx-heatmap-api.onrender.com/static/heatmap_YYYYMMDDHHMMSS.html)  
Sende eine GPX-Datei oder JSON-Daten an den Endpunkt **`/heatmap-quick`**, um deine Heatmap zu generieren und den detaillierten Bericht zu erhalten.

## Endpunkte

- **GET /**  
  Health‑Check der API.

- **POST /heatmap-quick**  
  Führt eine segmentierte Risikoanalyse aus, erstellt eine interaktive Heatmap und generiert einen detaillierten Bericht.

- **POST /parse-gpx**  
  Parst eine hochgeladene GPX‑Datei und extrahiert Koordinaten sowie die Gesamtstrecke.

- **POST /chunk-upload**  
  Teilt GPX‑Koordinaten in kleinere Chunks und speichert diese als JSON-Dateien.

- **GET /openapi.yaml**  
  Liefert die vollständige OpenAPI‑Spezifikation im YAML‑Format.

## Installation

1. **Repository klonen:**

   ```bash
   git clone https://github.com/Sou667/gpx-heatmap-api.git
   cd gpx-heatmap-api

# 🚴‍♂️ CycleDoc Heatmap API

![API Status](https://img.shields.io/badge/API-Live-green)
![Version](https://img.shields.io/badge/version-1.0-blue)
![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1.0-yellow)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

CycleDoc Heatmap API ist ein KI-gestütztes Analyse-Tool für Radsportverletzungen.  
Die API verarbeitet GPX-Streckendaten, segmentiert die Strecke und berechnet Risiko‑Werte basierend auf:

- Aktueller Wetterlage (via WeatherStack oder manuelle Overrides)
- Streckenprofil und Straßenoberfläche
- Wissenschaftlichen Studien (z. B. Rehlinghaus, Kronisch, Nelson, Clarsen etc.)

Mit Hilfe einer intelligenten, clusterbasierten Sanitäter‑Logik werden interaktive Risiko‑Heatmaps generiert, die als strukturierte JSON‑Objekte zurückgegeben werden.

---

## 🌐 Live-Demo

👉 [Jetzt testen](https://gpx-heatmap-api.onrender.com/static/heatmap_YYYYMMDDHHMMSS.html)  
Sende eine GPX-Datei und JSON an `/heatmap-quick`, um eine interaktive Karte mit Risikobewertung und Saniposten zu erhalten.

---

## 🔧 Funktionen

- **GPX-Analyse:**  
  Extraktion realer Streckendaten über den Endpunkt `/parse-gpx` oder per direktem JSON-Input.

- **Segmentweise Risikoanalyse:**  
  Auflösung von 0.005 km, um kurze Streckenabschnitte zu analysieren.

- **Wetter- und Streckenbewertung:**  
  Berücksichtigt Parameter wie Temperatur, Wind, Niederschlag, Steigung sowie Straßenoberfläche.

- **Intelligente Sanitäter‑Logik:**  
  - **Rennmodus:** In riskanten Clustern wird – unter Einhaltung eines Mindestabstands – nur ein repräsentativer Marker gesetzt.
  - **Privattouren:** Alle riskanten Segmente werden markiert.
  
- **Interaktive Heatmaps:**  
  Visualisierung der Route (grün = geringes Risiko, rot = hohes Risiko) mit integrierten Risiko- und Verletzungseinschätzungen.

- **Volle OpenAPI-Integration:**  
  Umfangreiche API-Dokumentation (OpenAPI 3.1) ist über `/openapi.yaml` abrufbar.

---

## 📦 Abhängigkeiten

Die API verwendet folgende Python-Pakete:

- **flask**
- **requests**
- **folium**
- **geopy**
- **gpxpy**
- **astral**
- **weasyprint**
- **gunicorn**

### Installation über `requirements.txt`

Erstelle eine Datei `requirements.txt` mit folgendem Inhalt:


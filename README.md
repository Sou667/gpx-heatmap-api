# 🚴‍♂️ CycleDoc Heatmap API

![API Status](https://img.shields.io/badge/API-Live-green)
![Version](https://img.shields.io/badge/version-1.0-blue)
![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1.0-yellow)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

CycleDoc Heatmap API ist ein KI-gestütztes Analyse-Tool, das Radsportverletzungen und Sicherheitsrisiken untersucht.  
Die API verarbeitet reale GPX-Streckendaten, segmentiert die Strecke in kurze Abschnitte (0.005 km Auflösung) und berechnet risikoabhängige Kennzahlen – basierend auf Wetterbedingungen, Streckenprofil, Oberflächenbeschaffenheit und wissenschaftlichen Studien. Mithilfe eines intelligenten, clusterbasierten Algorithmus für die Sanitäter‑Logik werden interaktive Risiko‑Heatmaps generiert, die als strukturierte JSON‑Objekte zurückgegeben werden.

---

## 🌐 Live-Demo

👉 [Jetzt testen](https://gpx-heatmap-api.onrender.com/static/heatmap_YYYYMMDDHHMMSS.html)  
Sende eine GPX-Datei und die zugehörigen JSON-Daten an den Endpunkt **`/heatmap-quick`**, um eine interaktive Karte mit Risikobewertung und Saniposten zu erhalten.

---

## 🔧 Funktionen

- **GPX-Analyse:**  
  - Extrahiert reale Streckendaten über den Endpunkt **`/parse-gpx`** oder direkt via JSON.
- **Segmentweise Risikoanalyse:**  
  - Die Strecke wird in Abschnitte von ca. 0.005 km unterteilt.
  - Für jedes Segment werden Parameter wie Steigung, Kurven (sharp_curve), Wetter, Straßenoberfläche und Fahrerinformationen berücksichtigt.
- **Erweiterte Sanitäter‑Logik:**  
  - **Rennmodus:** In riskanten Clustern wird – unter Einhaltung eines Mindestabstands von 5 Segmenten – nur ein repräsentativer Marker gesetzt.
  - **Privattouren:** Alle Segmente mit Risiko ≥ 3 werden markiert.
- **Interaktive Heatmaps:**  
  - Visualisierung der gesamten Strecke mit Farbkodierung (grün = geringes Risiko, orange = mittleres Risiko, rot = hohes Risiko) und integrierten Risiko- sowie Verletzungseinschätzungen.
- **OpenAPI-Integration:**  
  - Die API-Dokumentation (OpenAPI 3.1) ist unter **`/openapi.yaml`** abrufbar.

---

## 📦 Abhängigkeiten

Die API verwendet folgende Python-Pakete:

- `flask`
- `requests`
- `folium`
- `geopy`
- `gpxpy`
- `astral`
- `weasyprint`
- `gunicorn`

### Installation über `requirements.txt`

Erstelle eine Datei `requirements.txt` mit folgendem Inhalt:

```txt
flask>=2.2.2
requests>=2.28.0
folium>=0.12.1
geopy>=2.2.0
gpxpy>=1.4.2
astral>=3.2
weasyprint>=53.3
gunicorn>=20.1.0

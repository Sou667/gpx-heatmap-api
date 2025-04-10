# 🚴‍♂️ CycleDoc Heatmap API

![API Status](https://img.shields.io/badge/API-Live-green)
![Version](https://img.shields.io/badge/version-1.0-blue)
![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1.0-yellow)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

CycleDoc Heatmap API ist ein KI-gestütztes Analyse-Tool, das Radsportverletzungen und Sicherheitsrisiken untersucht.  
Die API verarbeitet reale GPX-Streckendaten, segmentiert die Strecke in kurze Abschnitte (ca. 0.005 km Auflösung) und berechnet risikoabhängige Kennzahlen – basierend auf Wetterbedingungen, Streckenprofil, Straßenoberfläche und wissenschaftlichen Studien. Mithilfe eines intelligenten, clusterbasierten Algorithmus für die Sanitäter‑Logik werden interaktive Risiko‑Heatmaps generiert, die als strukturierte JSON‑Objekte zurückgegeben werden.

> **Wichtig:**  
> Der Parameter `start_time` (im ISO‑8601-Format) ist jetzt verpflichtend und wird bei ungültiger Angabe mit einem 400-Error abgelehnt.

---

## 🌐 Live-Demo

👉 [Jetzt testen](https://gpx-heatmap-api.onrender.com/static/heatmap_YYYYMMDDHHMMSS.html)  
Sende eine GPX-Datei und die zugehörigen JSON-Daten an den Endpunkt **`/heatmap-quick`**, um eine interaktive Karte mit Risikobewertung und Saniposten zu erhalten.

---

## 🔧 Funktionen

- **GPX-Analyse:**  
  - Extrahiert reale Streckendaten über den Endpunkt **`/parse-gpx`** oder direkt via JSON.
  
- **Segmentweise Risikoanalyse:**  
  - Die Strecke wird automatisch in ca. 0.005 km lange Segmente unterteilt.
  - Für jedes Segment werden Parameter wie Steigung, Kurven (sharp_curve), Wetter, Straßenoberfläche sowie Fahrer- und Renninformationen berücksichtigt.
  - Jeder Abschnitt erhält einen Risikowert (1 bis 5) und es werden typische Verletzungsprofile (z. B. "Abschürfungen", "Claviculafraktur") ermittelt.

- **Erweiterte Sanitäter‑Logik:**  
  - **Rennmodus:** In riskanten Clustern wird – basierend auf dem Median des Clusters – ein repräsentativer Marker gesetzt, sofern der Abstand zu zuvor markierten Segmenten mindestens 5 Segmente beträgt.
  - **Privattouren:** Alle Segmente mit Risiko ≥ 3 werden markiert.

- **Interaktive Heatmaps:**  
  - Die generierte Karte visualisiert die gesamte Strecke farbkodiert (grün = geringes Risiko, orange = mittleres Risiko, rot = hohes Risiko).
  - Ein Link (`heatmap_url`) verweist auf die erzeugte Karte, und 🚑‑Marker heben potenziell gefährliche Abschnitte hervor.

- **OpenAPI‑Integration:**  
  - Die vollständige API-Dokumentation ist unter **`/openapi.yaml`** abrufbar.

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

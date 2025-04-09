# 🚴‍♂️ CycleDoc Heatmap API

![API Status](https://img.shields.io/badge/API-Live-green)
![Version](https://img.shields.io/badge/version-1.0-blue)
![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1.0-yellow)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

CycleDoc ist ein KI-gestütztes Analyse-Tool für Radsportverletzungen.  
Es verarbeitet GPX-Streckendaten und erstellt interaktive Risiko-Heatmaps basierend auf:

- Wetterlage (via WeatherStack oder Override)
- Streckenprofil & Oberfläche
- wissenschaftlichen Studien (z. B. Rehlinghaus, Kronisch, Nelson, Clarsen etc.)

## 🌐 Live-Demo

👉 [Jetzt testen](https://gpx-heatmap-api.onrender.com/static/heatmap_YYYYMMDDHHMMSS.html)  
GPX-Datei + JSON an `/heatmap-quick` senden → interaktive Karte mit Risikobewertung & Saniposten

---

## 🔧 Funktionen

- Analyse realer GPX-Strecken (über `/parse-gpx` oder JSON-Body)
- Segmentweise Risikoanalyse (0.005 km Auflösung)
- Wetterbasierte Risikoeinstufung
- Visualisierung mit Heatmap (grün = geringes Risiko, rot = hohes Risiko)
- 🚑 Saniposten-Empfehlung bei `risk ≥ 3`
- Durchschnitts-Risiko & Verletzungsprognose
- Volle OpenAPI-Integration & GPT-Kompatibilität

---

## 📦 Installation (lokal)

```bash
git clone https://github.com/dein-username/gpx-heatmap-api.git
cd gpx-heatmap-api
pip install -r requirements.txt
python main.py
```

API ist dann erreichbar unter `http://localhost:5000`

---

## 🚀 Deployment (Render.com)

1. Repository verbinden
2. `main.py` als Startpunkt setzen
3. Python 3.11 oder höher wählen
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `python main.py`

---

## 📘 API-Dokumentation (OpenAPI 3.1)

**POST /heatmap-quick**

Analysiert eine Strecke und erstellt eine Heatmap:

- `coordinates`: Liste von GPS-Koordinaten
- `fahrer_typ`, `alter`, `geschlecht`, `rennen_art`
- `start_time`: UTC im ISO-Format
- `wetter_override`: optional manuelle Wetterdaten
- `schutzausruestung`, `overuse_knee`, `rueckenschmerzen`, `massenstart`

Antwort enthält:

- `heatmap_url`: Link zur Karte
- `distance_km`: Gesamtlänge
- `segments[]`: je Segment mit Risiko, Terrain, Wetter, Oberfläche, Verletzungsrisiko

→ Vollständige Spezifikation: [openapi.yaml](https://gpx-heatmap-api.onrender.com/openapi.yaml)

---

## 📊 Beispiel-Workflow

```json
POST /heatmap-quick
{
  "coordinates": [[51.242, 6.830, 42.0], [51.243, 6.831, 42.1]],
  "fahrer_typ": "hobby",
  "anzahl": 1,
  "alter": 42,
  "geschlecht": "m",
  "material": "aluminium",
  "start_time": "2025-04-09T10:00:00Z",
  "wetter_override": {
    "temperature": 5,
    "wind_speed": 20,
    "precip": 1.2,
    "condition": "snow"
  },
  "schutzausruestung": {
    "helm": true,
    "protektoren": false
  }
}
```

---

## 📚 Studienquellen

- Rehlinghaus, M. (2022). *Verletzungen im Radsport*
- Kronisch, R. (2002)
- Nelson, N. (2010)
- Dannenberg, A. (1996)
- Ruedl, G. (2015)
- Clarsen, B. (2005)

Verwendet für evidenzbasierte Risiko- & Verletzungsmodelle

---

## 📎 Lizenz

MIT License – freie Nutzung, Modifikation & Weiterverwendung erlaubt.

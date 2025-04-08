# 🚴‍♂️ CycleDoc – GPX Heatmap & Risikoanalyse API

Diese API verarbeitet GPX-Streckendaten und generiert eine **visuelle Heatmap** sowie eine **segmentierte Risikoanalyse** auf Basis von:

- echten GPS-Daten (`.gpx`)
- Wetterparametern (optional via WeatherStack oder manuell)
- wissenschaftlichen Studien (Rehlinghaus 2022 u.a.)

## 🔧 Endpunkte

| Methode | Pfad                    | Beschreibung |
|--------|-------------------------|--------------|
| POST   | `/parse-gpx`            | GPX-Datei hochladen, extrahiert Koordinaten |
| POST   | `/chunk-upload`         | Große Koordinatenmengen in Chunks speichern |
| POST   | `/heatmap-with-weather` | Segmentierte Risikoanalyse & interaktive Karte |
| GET    | `/openapi.yaml`         | OpenAPI-Spezifikation für Swagger oder GPT |

## 🧠 GPT-Nutzung (optional)

Wenn du diese API in einem GPT (z. B. Data Action) nutzen willst:

- Verwende: `https://gpx-heatmap-api.onrender.com/openapi.yaml`
- Upload `.gpx` → `/chunk-upload` → `/heatmap-with-weather`
- Ergebnis: `heatmap_url`, `segments`, `injuries`, `risk`, `sani_needed`

## 🔁 Chunks (große Dateien)

- Chunk-Upload: max. 200 Koordinaten/Chunk
- Alle Chunks werden nach Analyse automatisch gelöscht ✅

## 🌍 Beispielkarte

👉 [Beispiel ansehen](https://gpx-heatmap-api.onrender.com/static/heatmap_20250407122528.html)

---

## 📦 Lokale Installation

```bash
pip install -r requirements.txt
python main.py

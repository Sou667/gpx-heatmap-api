# 🚴‍♂️ CycleDoc – GPX Heatmap & Risikoanalyse API

Diese API verarbeitet GPX-Streckendaten und generiert eine **visuelle Heatmap** sowie eine **segmentierte Risikoanalyse** auf Basis von:
- echten GPS-Daten (`.gpx`)
- Wetterparametern (optional via WeatherStack oder manuell)
- wissenschaftlichen Studien (Rehlinghaus 2022 u.a.)

---

## 🔧 Endpunkte

| Methode | Pfad                     | Beschreibung |
|--------|--------------------------|--------------|
| `POST` | `/parse-gpx`             | GPX-Datei hochladen, extrahiert Koordinaten |
| `POST` | `/heatmap-with-weather`  | Segmentierte Risikoanalyse & interaktive Heatmap |
| `POST` | `/chunk-upload`          | Große Koordinatenmengen in serverseitige Chunks speichern (max. 200/Chunk) ✅

---

## 🔁 Workflow für große Dateien (Chunking)
1. GPX-Datei hochladen → `/parse-gpx`
2. JSON mit allen `coordinates` an `/chunk-upload` senden
3. Für jeden Chunk einzeln: `/heatmap-with-weather`
4. ✅ Die Chunks werden nach der Analyse **automatisch gelöscht**

---

## 🌍 Beispiel: Interaktive Karte

👉 [Zur Beispiel-Heatmap](https://gpx-heatmap-api.onrender.com/static/heatmap_20250407122528.html)  
(Farben: **Grün** = geringes Risiko, **Orange** = mittel, **Rot** = hoch, ➕/🚑 = Sanitätspunkt)

---

## 🧠 GPT-Integration (optional)

Wenn du CycleDoc z. B. über **ChatGPT** oder eine GPT-Aktion nutzt, beachte:

- Verwende nur echte `.gpx`-Daten – keine Demodaten
- Nutze `/chunk-upload` → `/heatmap-with-weather`
- Interaktive Karte (`heatmap_url`) wird automatisch eingebunden
- Risikostufen, Verletzungsarten & Sanitäterpunkte werden je Segment analysiert

Fehlermeldung `500`? 👉 Dann bitte Wetterdaten manuell angeben.

---

## 📘 OpenAPI (Swagger)

API-Dokumentation via `openapi.yaml`:
- [openapi.yaml ansehen](https://github.com/Sou667/gpx-heatmap-api/blob/main/openapi.yaml)
- Kompatibel mit Swagger, ReDoc oder GPT-Actions

---

## 📦 Installation (lokal)

```bash
pip install -r requirements.txt
python main.py

# GPX Heatmap API

Ein Python-Flask-Webdienst zur Analyse von Radsport-GPX-Strecken auf Basis von:

- Wetterbedingungen
- GPX-Koordinaten
- Risikofaktoren aus der Dissertation von Marc Rehlinghaus
- Ergänzender wissenschaftlicher Literatur

## Funktionen

- **/parse-gpx** – Extrahiert GPS-Koordinaten aus GPX-Dateien
- **/chunk-upload** – Teilt große GPX-Dateien in kleinere Chunks (Standard: 200 Punkte)
- **/heatmap-with-weather** – Berechnet Risiko-Segmente, erstellt interaktive Heatmap & JSON-Ausgabe
- **Automatisches Löschen** der Chunk-Dateien nach Analyse

## Beispielablauf

1. **GPX-Datei vorbereiten**
   - Datei z. B. mit Komoot, Strava oder Garmin exportieren

2. **GPX-Daten als Koordinaten extrahieren**
   ```bash
   POST /parse-gpx
   Content-Type: multipart/form-data
   file: your-tour.gpx
   ```
   → Rückgabe: `{ "coordinates": [...] }`

3. **Optional: /chunk-upload nutzen** (für große GPX-Daten)
   ```bash
   POST /chunk-upload
   Content-Type: application/json
   {
     "coordinates": [...],
     "chunk_size": 200
   }
   ```

4. **Analyse durchführen**
   ```bash
   POST /heatmap-with-weather
   Content-Type: application/json
   {
     "coordinates": [...],
     "fahrer_typ": "c-lizenz",
     "anzahl": 50,
     "rennen_art": "Straße",
     "geschlecht": "mixed",
     "alter": 35,
     "start_time": "2025-04-07T08:58:00Z",
     "material": "carbon",
     "massenstart": false,
     "overuse_knee": false,
     "rueckenschmerzen": false,
     "schutzausruestung": {
       "helm": true,
       "protektoren": false
     }
   }
   ```

5. **Rückgabe:**
   ```json
   {
     "heatmap_url": "https://gpx-heatmap-api.onrender.com/static/heatmap_20250407103500.html",
     "segments": [ ... ]
   }
   ```

## Heatmap

- Segmente werden nach Risikostufe eingefärbt:
  - Grün: 1–2
  - Orange: 3
  - Rot: 4–5
- Marker mit 🚑 bei Sanitäterempfehlung (ab Risikostufe 3)

## Anforderungen

- Python 3.11+
- Installiere Pakete mit:
  ```bash
  pip install -r requirements.txt
  ```

## Live-Demo

➡ï¸ [Beispiel-Heatmap ansehen](https://gpx-heatmap-api.onrender.com/static/heatmap_20250407103500.html)

## Lizenz
MIT

---

Made with ❤️ for CycleDoc.ai


## Autoren

- Sou667 (Projektleitung, Promptentwicklung)
- GPT-4 (Codegenerierung, Risikologik, PDF-Report)


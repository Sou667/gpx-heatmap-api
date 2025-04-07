# CycleDoc Heatmap API

Dies ist die offizielle Radsport-Risikoanalyse-API mit Heatmap-Rendering, Wetteranalyse und Chunk-Support.

## Endpunkte

### `/parse-gpx` (POST)
Liest eine GPX-Datei und gibt die Koordinaten als JSON zurück.

**Body:** `multipart/form-data` mit Key: `file`

---

### `/chunk-upload` (POST)
Segmentiert eine große Koordinatenliste in serverseitige JSON-Chunks (Standard: 200 Punkte).

**Body:**
```json
{
  "coordinates": [[lat, lon, elev], ...],
  "chunk_size": 200
}

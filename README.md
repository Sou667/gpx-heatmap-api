# CycleDoc Heatmap-API

Eine API zur Verarbeitung von GPX-Daten, Segmentierung von Routen, Risikoanalyse und Erstellung einer interaktiven Heatmap.  
Die API berechnet Streckenlänge, führt eine Risikoanalyse basierend auf Wetter, Steigung, Kurven, Fahrerprofil und weiteren Parametern durch, erstellt einen detaillierten Bericht und visualisiert die Ergebnisse in einer interaktiven Karte mit intelligenter Sanitäterlogik.

---

## Funktionalität

- **GPX-Verarbeitung**  
  Lädt und parst GPX-Dateien, extrahiert Koordinaten und berechnet die Gesamtdistanz.  
  Unterstützt sowohl `multipart/form-data` (Datei-Upload) als auch `application/json` (Base64-codierte Datei).  
  Häufige XML-Probleme (z. B. BOM, falsches Encoding, fehlender Header) werden automatisch korrigiert.

- **Segmentierung**  
  Teilt die Strecke in Segmente auf (Standard: 0,005 km pro Segment).

- **Risikoanalyse**  
  Bewertet das Risiko basierend auf  
  - Wetter (Temperatur, Wind, Niederschlag)  
  - Steigung und Geländeform  
  - Scharfe Kurven  
  - Fahrerprofil (Typ, Alter, Geschlecht)  
  - Straßenoberfläche, Schutzausrüstung, Massenstart, Nachtzeit

- **Wetterabfrage**  
  Ruft Wetterdaten von WeatherStack für mehrere Punkte entlang der Strecke ab (ca. alle 50 km), um regionale Unterschiede zu berücksichtigen.  
  Unterstützt manuelle Überschreibung (`wetter_override`).

- **Heatmap**  
  Erstellt eine interaktive Karte mit Folium, die  
  - die gesamte Route (blau)  
  - riskante Segmente (grün/orange/rot)  
  anzeigt.  
  Sanitäterempfehlungen werden als Marker (🚑) hinzugefügt.

- **Detaillierter Bericht**  
  Generiert einen umfassenden Textbericht mit  
  1. Streckenlänge  
  2. Wetterlage  
  3. Risikoeinschätzung pro Segment  
  4. Wahrscheinliche Verletzungen  
  5. Präventionsempfehlungen  
  6. Quellen  
  7. Link zur Heatmap

- **Chunking**  
  Teilt große Strecken in kleinere JSON-Chunks (Standard: 200 Punkte), um die Verarbeitung zu erleichtern.

- **Logging**  
  Detaillierte Logs in `app.log` enthalten Infos zur Segmentierung, Risikoanalyse, Wetterabfrage und Fehlerbehandlung.

---

## Einschränkungen

- Maximal **100 000** Trackpunkte pro GPX-Datei (Speicher- und Performance-Limit).  
- Für sehr große Dateien empfiehlt sich eine Task-Queue (z. B. Celery), um asynchron zu verarbeiten (derzeit nicht implementiert).

---

## Installation

1. Repository klonen  
   ```bash
   git clone https://github.com/Sou667/gpx-heatmap-api.git
   cd gpx-heatmap-api

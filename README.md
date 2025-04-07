# 🧭 GPX Heatmap API – CycleDoc Risk Analyzer

Diese Flask-API nimmt GPX-Daten entgegen, analysiert sie segmentweise auf Radsport-Risiken und erzeugt eine interaktive Heatmap mit Farbcodierung (grün–orange–rot) sowie Sanitäter-Warnpunkten.

## 🔧 Setup

### Voraussetzungen
- Python 3.11+
- `pip install -r requirements.txt`
- Folgende Pakete müssen installiert sein:
  - flask, requests, folium, geopy, gpxpy, astral, weasyprint, gunicorn

### Starten des Servers
```bash
python main.py
# oder über gunicorn
gunicorn main:app

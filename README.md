# Hazard API

A FastAPI service to extract seismic and wind hazard values, as well as inspection area names, based on geographic coordinates (latitude, longitude).  
The service parses multiple **KML** files and returns all relevant values for a given point in a single JSON response.

---

## ✨ Features
- Full support for **Shapely 2.x** (handles STRtree indices instead of geometries).
- Values are read directly from the `<name>` tag inside each Placemark.
- Aggregates **all hazard values** (PGA, Ss, S1, TL, Cr1, Crs, Wind, Inspection Area) for a given lat/lon across all KML files in one response.
- Returns, for each field:
  - **value**: numeric or string value from the Placemark.
  - **unit**: unit of measurement (g, m/s, s, string).
  - **source**: source KML file.
  - **distance_km**: `0` if the point is inside the polygon, or haversine distance (km) to the nearest polygon otherwise.
- Optional **debug mode** to show:
  - Selection method (`covers`, `nearest_of_candidates`, `nearest_of_layer`).
  - Whether the point is inside or on boundary.
  - Polygon centroid and sample coordinates.
  - Source KML file and Placemark value.

---

## 📂 Project Structure
```
project/
├── app.py          # Main FastAPI application
├── data/           # Folder containing KML files
│   ├── pga-earthquake-...kml
│   ├── SS-earthquake-...kml
│   ├── S1-earthquake-...kml
│   ├── tl-earthquake-...kml
│   ├── cr1-earthquake-...kml
│   ├── crs-earthquake-...kml
│   ├── i-wind-sbc-...kml
│   ├── ii-wind-sbc-...kml
│   ├── iiiiv-wind-sbc-...kml
│   └── Inspection Areas.kml
```

---

## 🚀 Run the API

### Requirements
- Python 3.10+  
- Install dependencies:
  ```bash
  pip install fastapi uvicorn shapely
  ```

### Start the server
From the project root:
```bash
uvicorn app:app --host 127.0.0.1 --port 8000
```

---

## 📡 API Usage

### Health check
```
GET /health
```
Response:
```json
{"ok": true}
```

### Query hazard values
```
GET /api/query?lat=<LAT>&lon=<LON>&nearest=true&debug=true
```

#### Parameters
- `lat`: latitude (float).
- `lon`: longitude (float).
- `nearest` (default = `true`):  
  - `true`: return the nearest polygon if the point is not inside any polygon.  
  - `false`: return values only if the point is strictly inside a polygon.  
- `debug` (default = `false`):  
  - `true`: include extended debug details for the chosen polygon(s).  

#### Example
```
GET http://127.0.0.1:8000/api/query?lat=24.7136&lon=46.6753&nearest=true&debug=true
```

#### Example response
```json
{
  "input": {
    "lat": 24.7136,
    "lon": 46.6753,
    "nearest": true
  },
  "values": {
    "pga": {
      "value": 0.08,
      "unit": "g",
      "source": "pga-earthquake-sbc-3012018-l875-v129.kml",
      "distance_km": 0.0
    },
    "ss": {
      "value": 20.0,
      "unit": "g",
      "source": "SS-earthquake-sbc-3012018-l873-v129.kml",
      "distance_km": 0.0
    },
    "v": {
      "value": 46.0,
      "unit": "m/s",
      "source": "ii-wind-sbc-3012018-l871-v129.kml",
      "distance_km": 0.0
    },
    "inspection_area": {
      "value": "Riyadh Region",
      "unit": "string",
      "source": "Inspection Areas.kml",
      "distance_km": 0.0
    }
  },
  "debug": [
    {
      "field": "pga",
      "picked_from": "pga-earthquake-sbc-3012018-l875-v129.kml",
      "value": 0.08,
      "selection": "covers",
      "inside_or_on_boundary": true,
      "distance_km": 0.0,
      "polygon_centroid_latlon": {"lat": 24.7, "lon": 46.6},
      "polygon_sample_latlon": [[24.6, 46.5], [24.7, 46.6], [24.8, 46.7]]
    }
  ]
}
```

---

## 📝 Notes
- Fully compatible with **Shapely 2.x**.
- You can update or add new KML files in the `data/` folder without changing the code.
- Works with Postman, curl, or any HTTP client.
- Ready for deployment with Docker or a production server.

---

## 📌 Latest Commit Message
```
Add Shapely 2.x safe querying with distance + debug output

- Fixed STRtree handling for Shapely 2.x (indices vs geometries)
- Added distance_km field (0 if inside polygon, else haversine distance)
- Extended debug info: source file, selection method, centroid, polygon sample
- Values now consistently taken from <name> in KML placemarks
- API now aggregates and returns all hazard values (PGA, Ss, S1, TL, Cr1, Crs, Wind, Inspection Area) 
  for a given lat/lon across all KML files in one response
```

# app.py
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pathlib import Path
import xml.etree.ElementTree as ET
import glob, re, math, traceback

from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree
from shapely.validation import make_valid
from shapely.ops import nearest_points

app = FastAPI(title="Hazard API (Shapely 2.x safe + units/source/distance/debug)", version="2.8.0")

DATA_DIR = Path("data")

FILE_FIELD_MAP = {
    "pga-earthquake": "pga",
    "SS-earthquake":  "ss",
    "S1-earthquake":  "s1",
    "tl-earthquake":  "tl",
    "cr1-earthquake": "cr1",
    "crs-earthquake": "crs",
    "wind-sbc":       "v",
    "Inspection Areas": "inspection_area",
}

COMBINE_RULES = {
    "pga": "max", "ss": "max", "s1": "max",
    "cr1": "max", "crs": "max",
    "tl": "first",
    "v": "max",
    "inspection_area": "first",
}

UNITS = {
    "pga": "g", "ss": "g", "s1": "g",
    "cr1": "g", "crs": "g",
    "tl": "s",
    "v": "m/s",
    "inspection_area": "string",
}

# ---------- helpers ----------
def safe_number(val):
    try:
        m = re.findall(r"[-+]?\d*\.?\d+", str(val))
        return float(m[0]) if m else val
    except Exception:
        return val

def detect_field(filename: str):
    for key, field in FILE_FIELD_MAP.items():
        if key.lower() in filename.lower():
            return field
    return None

def parse_kml_file(path: Path, field: str):
    results = []
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        placemarks = [el for el in root.iter() if el.tag.endswith("Placemark")]
        for pm in placemarks:
            name, desc, coords = None, None, None
            for child in pm.iter():
                t = child.tag
                if t.endswith("name"): name = child
                elif t.endswith("description"): desc = child
                elif t.endswith("coordinates"): coords = child

            attrs = {}
            if name is not None and name.text:
                attrs[field] = name.text.strip()

            if desc is not None and desc.text:
                for line in desc.text.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        if k.strip().lower() == field.lower():
                            attrs[field] = v.strip()

            if coords is None or not coords.text:
                continue
            try:
                pts = []
                for token in coords.text.strip().split():
                    lon, lat, *_ = token.split(",")
                    pts.append((float(lon), float(lat)))  # KML = lon,lat
                if len(pts) >= 3:
                    geom = Polygon(pts)
                    results.append((geom, attrs, path.name))
            except Exception as e:
                print(f"[WARN] coords parse error in {path.name}: {e}")

        print(f"[DEBUG] {path.name}: {len(results)} placemarks loaded, sample {results[0][1] if results else None}")
    except Exception as e:
        print(f"[ERROR] parse_kml_file {path}: {e}")
    return results

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    return 2 * R * math.asin(math.sqrt(a))

def point_geom_distance_km(pt: Point, geom: Polygon):
    try:
        if geom.covers(pt):   # covers: inside or on boundary
            return 0.0
    except Exception:
        pass
    try:
        p1, p2 = nearest_points(pt, geom)
        return round(haversine_km(p1.y, p1.x, p2.y, p2.x), 3)
    except Exception:
        return None

# ---------- layer ----------
class Layer:
    def __init__(self, field):
        self.field   = field
        self.geoms   = []
        self.attrs   = []
        self.sources = []
        self.strtree: STRtree | None = None

    def build_index(self):
        fixed = []
        for g in self.geoms:
            try:
                if not g.is_valid:
                    g = make_valid(g)
            except Exception:
                pass
            fixed.append(g)
        self.geoms = fixed
        if self.geoms:
            self.strtree = STRtree(self.geoms)

def load_layers():
    layers = {}
    for f in glob.glob(str(DATA_DIR / "*.kml")):
        fname = Path(f).name
        field = detect_field(fname)
        if not field:
            print(f"[WARN] Unknown file {fname}, skipped")
            continue
        feats = parse_kml_file(Path(f), field)
        if field not in layers:
            layers[field] = Layer(field)
        L = layers[field]
        for geom, attrs, src in feats:
            val = attrs.get(field)
            if val is not None:
                attrs[field] = safe_number(val)
            L.geoms.append(geom)
            L.attrs.append(attrs)
            L.sources.append(src)
    for fld, L in layers.items():
        L.build_index()
        print(f"[INFO] Field '{fld}' → {len(L.geoms)} polygons loaded")
    return layers

LAYERS = load_layers()

# ---------- Shapely 2.x normalizers ----------
def _to_index_array(L: Layer, cands):
    """
    Normalize STRtree.query/nearest outputs to a list of indices.
    - Shapely 2.x: returns numpy array of indices
    - Shapely 1.8: returns list of geometries
    """
    idxs = []
    if cands is None:
        return idxs
    # if it's iterable of integers
    try:
        for item in cands:
            if isinstance(item, (int,)) or getattr(item, "__class__", None).__name__.startswith("int"):
                idxs.append(int(item))
            else:
                # it's a geometry -> map to index by equality check
                try:
                    cwkb = item.wkb
                    # brute-force (rare path)
                    found = next((i for i, g in enumerate(L.geoms) if g.wkb == cwkb), None)
                    if found is not None:
                        idxs.append(found)
                except Exception:
                    # last resort: linear search by equals()
                    found = next((i for i, g in enumerate(L.geoms) if g.equals(item)), None)
                    if found is not None:
                        idxs.append(found)
    except TypeError:
        # single scalar int
        if isinstance(cands, (int,)) or getattr(cands, "__class__", None).__name__.startswith("int"):
            idxs = [int(cands)]
    return idxs

def _nearest_index(L: Layer, pt: Point):
    """Return index of nearest geometry in the layer, for Shapely 1.8/2.x."""
    if not L.strtree or len(L.geoms) == 0:
        return None
    try:
        res = L.strtree.nearest(pt)
    except TypeError:
        # some versions require (geom, return_all=False)
        res = L.strtree.nearest(pt)
    idxs = _to_index_array(L, res)
    if len(idxs) >= 1:
        return idxs[0]
    # fallback manual
    try:
        return min(range(len(L.geoms)), key=lambda i: L.geoms[i].distance(pt))
    except Exception:
        return None

# ---------- query ----------
def query_point(lat: float, lon: float, force_nearest: bool = True, want_debug: bool = False):
    pt = Point(lon, lat)
    results = {}
    debug_rows = []

    for field, L in LAYERS.items():
        if not L.strtree:
            continue

        # 1) candidates by point bbox
        try:
            raw = L.strtree.query(pt)
        except Exception:
            raw = []
        cand_idxs = _to_index_array(L, raw)

        chosen_idx = None
        selection = "none"
        inside = False

        # prefer covers (includes boundary)
        for i in cand_idxs:
            try:
                if L.geoms[i].covers(pt):
                    chosen_idx = i
                    selection = "covers"
                    inside = True
                    break
            except Exception:
                continue

        # 2) if no bbox matches, expand ~50km radius
        if (chosen_idx is None) and (len(cand_idxs) == 0):
            try:
                env = pt.buffer(0.45)  # ~50 km
                raw2 = L.strtree.query(env)
            except Exception:
                raw2 = []
            cand_idxs = _to_index_array(L, raw2)

        # 3) if still none, pick nearest among candidates
        if (chosen_idx is None) and (len(cand_idxs) > 0):
            try:
                chosen_idx = min(cand_idxs, key=lambda i: L.geoms[i].distance(pt))
            except Exception:
                chosen_idx = cand_idxs[0]
            selection = "nearest_of_candidates"

        # 4) if still none and force_nearest → nearest in whole layer
        if (chosen_idx is None) and force_nearest:
            chosen_idx = _nearest_index(L, pt)
            if chosen_idx is not None:
                selection = "nearest_of_layer"

        if chosen_idx is None:
            continue

        value = L.attrs[chosen_idx].get(field)
        if value is None:
            continue

        geom = L.geoms[chosen_idx]
        dist_km = point_geom_distance_km(pt, geom)
        record = {
            "value": value,
            "unit": UNITS.get(field, ""),
            "source": L.sources[chosen_idx],
            "distance_km": dist_km if dist_km is not None else None,
        }

        rule = COMBINE_RULES.get(field, "first")
        if field not in results:
            results[field] = record
        else:
            if rule == "max":
                try:
                    if float(value) > float(results[field]["value"]):
                        results[field] = record
                except Exception:
                    pass
            elif rule == "min":
                try:
                    if float(value) < float(results[field]["value"]):
                        results[field] = record
                except Exception:
                    pass
            elif rule == "last":
                results[field] = record

        if want_debug:
            try:
                cent = geom.representative_point()
                centroid_latlon = {"lat": round(cent.y, 6), "lon": round(cent.x, 6)}
            except Exception:
                centroid_latlon = None
            try:
                ext = list(geom.exterior.coords)
                sample = ext[:3] if len(ext) >= 3 else ext
                sample_ll = [[round(y, 6), round(x, 6)] for (x, y) in sample]
            except Exception:
                sample_ll = None

            debug_rows.append({
                "field": field,
                "picked_from": L.sources[chosen_idx],
                "value": value,
                "selection": selection,
                "inside_or_on_boundary": inside,
                "distance_km": record["distance_km"],
                "polygon_centroid_latlon": centroid_latlon,
                "polygon_sample_latlon": sample_ll
            })

    return (results, debug_rows if want_debug else None)

# ---------- routes ----------
@app.get("/")
def root():
    return {"message": "Hazard API is running. Use /api/query?lat=..&lon=..&nearest=true|false&debug=true|false"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/api/query")
def api_query(
    lat: float = Query(...),
    lon: float = Query(...),
    nearest: bool = Query(True, description="Return nearest value if point not inside any polygon"),
    debug: bool = Query(False, description="Include debug details about selected polygon(s)")
):
    try:
        values, dbg = query_point(lat, lon, force_nearest=nearest, want_debug=debug)
        payload = {"input": {"lat": lat, "lon": lon, "nearest": nearest}, "values": values}
        if debug:
            payload["debug"] = dbg
        return JSONResponse(payload)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": str(e), "trace": traceback.format_exc().splitlines()[-3:]},
        )

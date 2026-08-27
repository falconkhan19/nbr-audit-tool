"""
sector_utils.py

Builds antenna "sector" (pie-slice) polygons from Latitude / Longitude / Azimuth /
Beamwidth / Radius, and helper routines to turn a pandas DataFrame of EP records
into a QGIS memory vector layer of sector polygons.

All geometry math is done on a local metric approximation (equirectangular /
small-circle) which is accurate enough for sector plotting at cellsite scale
(radii of a few hundred meters to a few kilometers). Layers are created in
EPSG:4326 (WGS84) to match typical EP exports (lat/lon in decimal degrees).
"""

import math

from qgis.core import (
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsFeature,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

EARTH_RADIUS_M = 6378137.0


def _destination_point(lat, lon, bearing_deg, distance_m):
    """Return (lat, lon) of the point `distance_m` meters from (lat, lon) along `bearing_deg`."""
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    brng = math.radians(bearing_deg)
    d_r = distance_m / EARTH_RADIUS_M

    lat2 = math.asin(
        math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(brng)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(d_r) * math.cos(lat1),
        math.cos(d_r) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def _to_float(v):
    """Safely coerce a cell value (which may be a string with stray spaces,
    thousands separators, NaN, or None) to float. Returns None if not possible."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        try:
            f = float(str(v).strip().replace(",", ""))
        except (TypeError, ValueError):
            return None
    if f != f:  # NaN check without importing math for this alone
        return None
    return f


def create_sector_polygon(lat, lon, azimuth, beamwidth, radius_m, arc_points=24):
    """
    Build a pie-slice QgsGeometry (Polygon) representing an antenna sector.
    Returns None (never raises) if any input is missing/invalid so callers
    can skip the row and keep going instead of aborting the whole import.

    lat, lon      : site position (decimal degrees)
    azimuth       : main lobe direction, degrees clockwise from North (0-360)
    beamwidth     : total horizontal beamwidth in degrees (e.g. 65, 90, 120).
                    If beamwidth >= 359, a full circle is drawn instead of a wedge.
    radius_m      : sector radius in meters
    arc_points    : number of points used to approximate the arc
    """
    lat = _to_float(lat)
    lon = _to_float(lon)
    azimuth = _to_float(azimuth)
    beamwidth = _to_float(beamwidth)
    radius_m = _to_float(radius_m)

    if None in (lat, lon, azimuth, beamwidth, radius_m):
        return None
    if radius_m <= 0 or beamwidth <= 0:
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None

    azimuth = azimuth % 360.0

    try:
        if beamwidth >= 359.0:
            pts = []
            for i in range(arc_points + 1):
                brng = (360.0 / arc_points) * i
                plat, plon = _destination_point(lat, lon, brng, radius_m)
                pts.append(QgsPointXY(plon, plat))
            geom = QgsGeometry.fromPolygonXY([pts])
        else:
            half_bw = beamwidth / 2.0
            start_bearing = azimuth - half_bw
            end_bearing = azimuth + half_bw

            ring = [QgsPointXY(lon, lat)]  # apex at the site
            steps = max(2, arc_points)
            for i in range(steps + 1):
                brng = start_bearing + (end_bearing - start_bearing) * (i / steps)
                plat, plon = _destination_point(lat, lon, brng, radius_m)
                ring.append(QgsPointXY(plon, plat))
            ring.append(QgsPointXY(lon, lat))  # close back to apex

            geom = QgsGeometry.fromPolygonXY([ring])
    except Exception:
        return None

    if geom is None or geom.isEmpty():
        return None

    # If self-intersecting (can happen for beamwidth close to 360 or odd
    # arc/radius combos), try to repair it but only keep the result if it's
    # still a polygon-type geometry - a repaired GeometryCollection would
    # break a Polygon-typed layer, so in that case just drop the feature
    # rather than corrupt the layer.
    try:
        if not geom.isGeosValid():
            fixed = geom.makeValid()
            if fixed and not fixed.isEmpty() and fixed.type() == geom.type():
                geom = fixed
            else:
                return None
    except Exception:
        pass  # isGeosValid()/makeValid() unavailable on very old QGIS - use geom as-is

    return geom


def build_sector_layer(df, layer_name, lat_col, lon_col, azimuth_col, beamwidth_val,
                        radius_val, beamwidth_is_column, radius_is_column,
                        extra_fields=None, crs="EPSG:4326"):
    """
    Build an in-memory QGIS polygon layer of sectors from a pandas DataFrame.

    beamwidth_val / radius_val: either a column name (if the *_is_column flag is True)
        or a fixed numeric value (manual entry) applied to every row.
    extra_fields: list of column names from df to carry through as attributes
        (e.g. CellName, EnodeB/gNodeB ID, Cell ID, the generated Key, etc.)
        Duplicate names (including "CellName", which is always added) are
        automatically dropped.

    Returns (layer, skipped_row_count). `layer` is a QgsVectorLayer (not yet
    added to the project) or None if nothing could be built at all.
    """
    extra_fields = extra_fields or []
    # de-duplicate while preserving order, and never collide with the
    # always-present core fields below
    core_names = {"CellName", "Latitude", "Longitude", "Azimuth", "Beamwidth", "Radius_m"}
    seen = set()
    clean_extra_fields = []
    for col in extra_fields:
        col = str(col)
        if col in core_names or col in seen:
            continue
        seen.add(col)
        clean_extra_fields.append(col)

    if beamwidth_is_column and beamwidth_val not in df.columns:
        raise ValueError(f"Beamwidth column '{beamwidth_val}' not found in the file.")
    if radius_is_column and radius_val not in df.columns:
        raise ValueError(f"Radius column '{radius_val}' not found in the file.")
    for required in (lat_col, lon_col, azimuth_col):
        if required not in df.columns:
            raise ValueError(f"Required column '{required}' not found in the file.")

    # manual values must be numeric up-front
    if not beamwidth_is_column:
        bw_fixed = _to_float(beamwidth_val)
        if bw_fixed is None:
            raise ValueError(f"Manual beamwidth value '{beamwidth_val}' is not a valid number.")
    if not radius_is_column:
        rad_fixed = _to_float(radius_val)
        if rad_fixed is None:
            raise ValueError(f"Manual radius value '{radius_val}' is not a valid number.")

    layer = QgsVectorLayer(f"Polygon?crs={crs}", layer_name, "memory")
    provider = layer.dataProvider()

    fields = QgsFields()
    fields.append(QgsField("CellName", QVariant.String))
    fields.append(QgsField("Latitude", QVariant.Double))
    fields.append(QgsField("Longitude", QVariant.Double))
    fields.append(QgsField("Azimuth", QVariant.Double))
    fields.append(QgsField("Beamwidth", QVariant.Double))
    fields.append(QgsField("Radius_m", QVariant.Double))
    for col in clean_extra_fields:
        fields.append(QgsField(col, QVariant.String))
    provider.addAttributes(fields)
    layer.updateFields()

    feats = []
    skipped = 0
    for _, row in df.iterrows():
        lat = row.get(lat_col)
        lon = row.get(lon_col)
        az = row.get(azimuth_col)
        bw = row.get(beamwidth_val) if beamwidth_is_column else beamwidth_val
        rad = row.get(radius_val) if radius_is_column else radius_val

        geom = create_sector_polygon(lat, lon, az, bw, rad)
        if geom is None:
            skipped += 1
            continue

        f = QgsFeature(fields)
        f.setGeometry(geom)
        cell_name_val = row.get("CellName", "")
        f.setAttribute("CellName", "" if cell_name_val is None else str(cell_name_val))
        f.setAttribute("Latitude", _to_float(lat))
        f.setAttribute("Longitude", _to_float(lon))
        f.setAttribute("Azimuth", _to_float(az))
        f.setAttribute("Beamwidth", _to_float(bw))
        f.setAttribute("Radius_m", _to_float(rad))
        for col in clean_extra_fields:
            val = row.get(col, "")
            f.setAttribute(col, "" if val is None else str(val))
        feats.append(f)

    if feats:
        ok, _ = provider.addFeatures(feats)
        if not ok:
            raise RuntimeError("QGIS memory provider rejected the generated sector features.")
    layer.updateExtents()
    return layer, skipped

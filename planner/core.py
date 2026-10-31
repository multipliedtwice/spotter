import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from planner.models import CacheEntry, STATION_DATASET_CACHE_KEY, Station

TANK = 50.0
MPG = 10.0
EPS = 1e-8
SIMPLIFY_TOLERANCE = 1e-3

def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()

def station_dataset_digest():
    with transaction.atomic():
        entry = CacheEntry.objects.filter(pk=STATION_DATASET_CACHE_KEY, expires__gt=timezone.now()).first()
        if entry:
            return entry.value
        fields = ('id', 'source_id', 'name', 'address', 'city', 'state', 'price', 'price_min', 'price_max', 'latitude', 'longitude', 'evidence', 'rows')
        digest = key(list(Station.objects.order_by('pk').values(*fields)))
        CacheEntry.objects.update_or_create(pk=STATION_DATASET_CACHE_KEY, defaults={'value': digest, 'expires': timezone.now() + timedelta(days=3650)})
        return digest


def cached(kind, value, producer, hours=24):
    cache_key = key([kind, value])
    entry = CacheEntry.objects.filter(pk=cache_key, expires__gt=timezone.now()).first()
    if entry:
        return entry.value
    result = producer()
    CacheEntry.objects.update_or_create(pk=cache_key, defaults={'value': result, 'expires': timezone.now() + timedelta(hours=hours)})
    return result

def distance(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    x = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 3958.7613 * 2 * math.asin(min(1, math.sqrt(x)))

def simplify(points, tolerance=SIMPLIFY_TOLERANCE):
    if len(points) < 3:
        return [list(point) for point in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        ax, ay = points[lo][:2]
        dx, dy = points[hi][0] - ax, points[hi][1] - ay
        span = dx * dx + dy * dy
        best, index = -1.0, None
        for i in range(lo + 1, hi):
            px, py = points[i][:2]
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / span)) if span else 0.0
            offset = math.hypot(px - ax - t * dx, py - ay - t * dy)
            if offset > best:
                best, index = offset, i
        if index is not None and best > tolerance:
            keep[index] = True
            stack.extend([(lo, index), (index, hi)])
    return [list(point) for point, kept in zip(points, keep) if kept]

def optimize(legs, prices, start_fuel):
    if len(legs) != len(prices) + 1 or not math.isfinite(start_fuel) or not 0 <= start_fuel <= TANK or any(x < 0 or not math.isfinite(x) for x in legs) or any(x <= 0 or not math.isfinite(x) for x in prices):
        raise ValueError('Invalid fuel sequence')
    fuel = start_fuel
    purchases = []
    lowest = [{'point': 'start', 'fuel_gallons': fuel}]
    for i, leg in enumerate(legs):
        fuel -= leg / MPG
        if fuel < -EPS:
            return None
        fuel = max(0, fuel)
        lowest.append({'point': 'arrival' if i == len(prices) else f'stop_{i+1}', 'fuel_gallons': fuel})
        if i == len(prices):
            break
        cumulative = 0.0
        target = None
        for j in range(i + 1, len(prices)):
            cumulative += legs[j] / MPG
            if cumulative > TANK + EPS:
                break
            if prices[j] < prices[i]:
                target = cumulative
                break
        if target is None:
            remaining = sum(legs[i+1:]) / MPG
            target = min(TANK, remaining)
        amount = max(0, target - fuel)
        purchases.append({'fuel_before_gallons': fuel, 'gallons': amount, 'fuel_after_gallons': fuel + amount, 'cost_usd': amount * prices[i]})
        fuel += amount
    minimum = min(p['fuel_gallons'] for p in lowest)
    return {'purchases': purchases, 'purchased_gallons': sum(p['gallons'] for p in purchases), 'purchase_cost_usd': sum(p['cost_usd'] for p in purchases), 'consumed_gallons': sum(legs)/MPG, 'remaining_gallons': fuel, 'lowest_fuel_points': [p for p in lowest if abs(p['fuel_gallons'] - minimum) < EPS]}

def point_in_ring(point, ring):
    x, y = point[1], point[0]
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1]) + a[0]:
            inside = not inside
    return inside

def validate_boundary(geo):
    if not isinstance(geo, dict):
        raise ValueError('Invalid US boundary geometry')
    kind = geo.get('type')
    if kind == 'FeatureCollection':
        features = geo.get('features')
        if not isinstance(features, list) or not features:
            raise ValueError('Invalid US boundary feature collection')
        for feature in features:
            validate_boundary(feature)
        return
    if kind == 'Feature':
        validate_boundary(geo.get('geometry'))
        return
    if kind not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Invalid US boundary geometry')
    coordinates = geo.get('coordinates')
    polygons = [coordinates] if kind == 'Polygon' else coordinates
    if not isinstance(polygons, list) or not polygons:
        raise ValueError('Invalid US boundary coordinates')
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError('Invalid US boundary polygon')
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError('Invalid US boundary ring')
            for vertex in ring:
                if not isinstance(vertex, list) or len(vertex) < 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vertex[:2]) or not -180 <= vertex[0] <= 180 or not -90 <= vertex[1] <= 90:
                    raise ValueError('Invalid US boundary point')


def in_us(point, geo):
    if not isinstance(geo, dict):
        raise ValueError('Invalid US boundary geometry')
    kind = geo.get('type')
    if kind == 'FeatureCollection':
        features = geo.get('features')
        if not isinstance(features, list) or not features:
            raise ValueError('Invalid US boundary feature collection')
        return any(in_us(point, feature) for feature in features)
    if kind == 'Feature':
        return in_us(point, geo.get('geometry'))
    if kind not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Invalid US boundary geometry')
    try:
        polygons = [geo['coordinates']] if kind == 'Polygon' else geo['coordinates']
        return any(point_in_ring(point, poly[0]) and not any(point_in_ring(point, hole) for hole in poly[1:]) for poly in polygons if poly)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('Invalid US boundary coordinates') from exc


@lru_cache(maxsize=1)
def _read_boundary(path, mtime_ns, size):
    with Path(path).open(encoding='utf-8') as stream:
        boundary = json.load(stream)
    validate_boundary(boundary)
    return boundary


def load_boundary(path):
    path = Path(path).resolve()
    stat = path.stat()
    return _read_boundary(str(path), stat.st_mtime_ns, stat.st_size)

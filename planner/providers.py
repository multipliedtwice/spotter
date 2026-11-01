import csv
import io
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from django.conf import settings
from planner.core import cached
from planner.locations import STATE_NAMES, strip_country

_routing_lock = threading.Lock()
_last_route_request = 0.0

class ProviderError(Exception):
    pass

class RouteCoverageError(ProviderError):
    pass

class AddressError(Exception):
    pass

def request(url, data=None, timeout=20):
    try:
        req = urllib.request.Request(url, data=data, headers={'User-Agent': 'FuelRouteAssessment/1.0', 'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode('utf-8-sig')
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode('utf-8-sig'))
        except (OSError, UnicodeError, ValueError):
            payload = None
        if exc.code == 400 and isinstance(payload, dict) and payload.get('code') in ('NoRoute', 'NoSegment'):
            raise RouteCoverageError('No drivable route found in loaded road data') from exc
        raise ProviderError('External provider unavailable') from exc
    except (OSError, urllib.error.URLError, UnicodeError) as exc:
        raise ProviderError('External provider unavailable') from exc

def address_fields(address):
    parts = strip_country([part.strip() for part in address.split(',')])
    if len(parts) == 4:
        street, city, state, postal = parts
    elif len(parts) == 3:
        street, city, state_zip = parts
        words = state_zip.split()
        if not words:
            raise AddressError('Provide street, city, and state.')
        if words[-1].isdigit() and len(words[-1]) == 5:
            postal, state = words[-1], ' '.join(words[:-1])
        else:
            postal, state = '', state_zip
    else:
        raise AddressError('Provide street, city, and state separated by commas.')
    if not street or not city or not state or (postal and (len(postal) != 5 or not postal.isdigit())):
        raise AddressError('Provide street, city, state, and an optional five-digit ZIP.')
    state = STATE_NAMES.get(state.upper(), state.upper())
    if state not in STATE_NAMES.values():
        raise AddressError('Use a valid US state.')
    return [street, city, state, postal]

def census(addresses):
    fields = [address_fields(address) for address in addresses]
    def fetch():
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        for index, values in enumerate(fields):
            writer.writerow([index, *values])
        boundary = 'FuelRouteBoundary'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="addressFile"; filename="addresses.csv"\r\nContent-Type: text/csv\r\n\r\n{output.getvalue()}\r\n--{boundary}\r\nContent-Disposition: form-data; name="benchmark"\r\n\r\nPublic_AR_Current\r\n--{boundary}--\r\n').encode()
        req = urllib.request.Request('https://geocoding.geo.census.gov/geocoder/locations/addressbatch', data=body, headers={'User-Agent': 'FuelRouteAssessment/1.0', 'Content-Type': f'multipart/form-data; boundary={boundary}'})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                rows = list(csv.reader(io.StringIO(response.read().decode('utf-8-sig'))))
        except (OSError, urllib.error.URLError, UnicodeError, csv.Error) as exc:
            raise ProviderError('Census geocoder unavailable') from exc
        results = [None] * len(addresses)
        seen = set()
        try:
            for row in rows:
                index = int(row[0])
                if index < 0 or index >= len(addresses) or index in seen or row[2] not in ('Match', 'No_Match', 'Tie'):
                    raise ValueError()
                seen.add(index)
                if row[2] == 'Match':
                    lon, lat = map(float, row[5].split(','))
                    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                        raise ValueError()
                    results[index] = [lat, lon]
            if len(seen) != len(addresses):
                raise ValueError()
        except (IndexError, ValueError, TypeError) as exc:
            raise ProviderError('Invalid Census response') from exc
        return results
    return cached('census-batch-v2', fields, fetch, 24 * 30)

def route_settings():
    endpoint_radius = settings.OSRM_ENDPOINT_RADIUS_METERS
    stop_radius = settings.OSRM_STOP_RADIUS_METERS
    if any(not math.isfinite(value) or value <= 0 for value in (endpoint_radius, stop_radius)):
        raise ProviderError('OSRM snapping radiuses must be positive and finite')
    return {'snap_policy': 'coincident-group-min-v2', 'endpoint_radius_meters': endpoint_radius, 'stop_radius_meters': stop_radius, 'base_url': settings.OSRM_BASE_URL, 'profile': settings.OSRM_PROFILE, 'dataset_version': settings.OSRM_DATASET_VERSION, 'timeout': settings.OSRM_TIMEOUT, 'geometry': 'geojson', 'overview': 'full', 'steps': False}

def parse_routes(response, point_count):
    try:
        if response.get('code') in ('NoRoute', 'NoSegment'):
            raise RouteCoverageError('No drivable route found in loaded road data')
        if response.get('code') != 'Ok' or not isinstance(response['routes'], list) or not response['routes']:
            raise ValueError()
        routes = []
        for item in response['routes']:
            geometry = item['geometry']
            coords = geometry['coordinates']
            if geometry['type'] != 'LineString' or not isinstance(coords, list) or len(coords) < 2:
                raise ValueError()
            for point in coords:
                if not isinstance(point, list) or len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point) or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90:
                    raise ValueError()
            meters, duration = item['distance'], item['duration']
            legs = [leg['distance'] for leg in item['legs']]
            if len(legs) != point_count - 1 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in [meters, duration, *legs]):
                raise ValueError()
            if not math.isclose(sum(legs), meters, rel_tol=0.002, abs_tol=2):
                raise ValueError()
            routes.append({'geometry': geometry, 'distance_miles': meters/1609.344, 'duration_seconds': duration, 'legs_miles': [leg/1609.344 for leg in legs]})
        return sorted(routes, key=lambda r: (r['duration_seconds'], r['distance_miles']))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ProviderError('Invalid routing response') from exc

def route(points, alternatives=False):
    options = route_settings()
    def fetch():
        coords = ';'.join(f'{lon},{lat}' for lat, lon in points)
        endpoint_radius = options['endpoint_radius_meters']
        stop_radius = options['stop_radius_meters']
        radiuses = [endpoint_radius, *([stop_radius] * (len(points) - 2)), endpoint_radius]
        minimums = {}
        for point, radius in zip(points, radiuses):
            coordinate = tuple(point)
            minimums[coordinate] = min(minimums.get(coordinate, radius), radius)
        radiuses = [minimums[tuple(point)] for point in points]
        params = urllib.parse.urlencode({'overview': options['overview'], 'geometries': options['geometry'], 'alternatives': 'true' if alternatives else 'false', 'steps': 'false', 'radiuses': ';'.join(str(radius) for radius in radiuses)})
        try:
            global _last_route_request
            url = f"{options['base_url']}/route/v1/{urllib.parse.quote(options['profile'], safe='')}/{coords}?{params}"
            if urllib.parse.urlsplit(options['base_url']).hostname == 'router.project-osrm.org':
                with _routing_lock:
                    delay = 1.0 - (time.monotonic() - _last_route_request)
                    if delay > 0:
                        time.sleep(delay)
                    _last_route_request = time.monotonic()
                    response = json.loads(request(url, timeout=options['timeout']))
            else:
                response = json.loads(request(url, timeout=options['timeout']))
            return parse_routes(response, len(points))
        except (ValueError, TypeError) as exc:
            raise ProviderError('Invalid routing response') from exc
    return cached('osrm-v2', {'points': points, 'alternatives': alternatives, **options}, fetch, 24)

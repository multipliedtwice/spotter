import math
import re
from urllib.parse import urlparse

from planner.core import distance as distance_miles, in_us, point_in_ring
from planner.road import road_marker_keys
from planner.locations import STATE_NAMES


def normalized(value):
    return re.sub(r'\s+', ' ', value.strip()).upper()


def street_key(value):
    text = re.sub(r'[^A-Z0-9]+', ' ', normalized(value))
    aliases = {'STREET': 'ST', 'ROAD': 'RD', 'AVENUE': 'AVE', 'BOULEVARD': 'BLVD',
               'DRIVE': 'DR', 'LANE': 'LN', 'HIGHWAY': 'HWY', 'NORTH': 'N',
               'SOUTH': 'S', 'EAST': 'E', 'WEST': 'W', 'NORTHEAST': 'NE',
               'NORTHWEST': 'NW', 'SOUTHEAST': 'SE', 'SOUTHWEST': 'SW'}
    return ' '.join(aliases.get(word, word) for word in text.split())


def supported_street_address(value):
    key = street_key(value)
    return bool(re.match(r'^\d+[A-Z]?\s+[A-Z0-9]', key)) and not re.search(r'&|@|\b(?:EXIT|MILE|MM)\b', normalized(value))


def normalize_ref(value):
    match = re.fullmatch(r'(\d+)([A-Z]?)', value)
    return str(int(match.group(1))) + match.group(2) if match else ''


def refs(value):
    return {normalize_ref(ref) for ref in re.findall(r'#\s*(\d+[A-Z]?)(?![A-Z0-9])', normalized(value))}


def identities(tags):
    names = [tags.get(key, '') for key in ('name', 'brand', 'operator')]
    numbers = set()
    for name in names:
        numbers |= refs(name)
    ref = normalized(tags.get('ref', ''))
    if re.fullmatch(r'\d+[A-Z]?', ref):
        numbers.add(normalize_ref(ref))
    url = urlparse(tags.get('website', ''))
    if url.hostname and url.hostname.lower() in ('loves.com', 'www.loves.com'):
        match = re.fullmatch(r'/locations/(\d+)/?', url.path, re.I)
        if match:
            numbers.add(normalize_ref(match.group(1)))
    return names, numbers


def canonical_name(value):
    value = re.sub(r'#\s*\d+[A-Z]?(?![A-Z0-9])', ' ', normalized(value))
    value = value.replace("'", '').replace('’', '')
    value = ' '.join(re.findall(r'[A-Z0-9]+', value))
    value = re.sub(r'\s+(?:TRAVEL CENT(?:ER|RE)|TRAVEL STOP|TRUCK STOP|FUEL STATION|GAS STATION|FUEL|STATION)$', '', value)
    return {'LOVE': 'LOVES', 'TA': 'TRAVELCENTERS OF AMERICA', 'TRAVEL CENTERS OF AMERICA': 'TRAVELCENTERS OF AMERICA', 'CASEYS GENERAL STORE': 'CASEYS'}.get(value, value)


def canonical_source_name(value):
    clean = re.sub(r'#\s*\d+[A-Z]?(?![A-Z0-9])', ' ', normalized(value))
    clean = ' '.join(re.findall(r'[A-Z0-9]+', clean))
    if re.fullmatch(r'TA (?:[A-Z0-9]+ )+TRAVEL ?CENT(?:ER|RE)', clean):
        return 'TRAVELCENTERS OF AMERICA'
    return canonical_name(value)


def identity_matches(source_names, tags):
    names, numbers = identities(tags)
    source_refs = set().union(*(refs(name) for name in source_names))
    if numbers and source_refs and not numbers <= source_refs:
        return False
    source_keys = {canonical_source_name(name) for name in source_names} - {''}
    return any(canonical_name(name) in source_keys for name in names if name)


def is_business(tags):
    return tags.get('shop') == 'convenience' or tags.get('highway') == 'services' or tags.get('landuse') == 'retail'


def source_refs(station):
    return set().union(*(refs(row['Truckstop Name']) for row in station.rows))


def exact_ref(station, tags):
    numbers = identities(tags)[1]
    return bool(numbers and source_refs(station) and numbers <= source_refs(station))


def identity_tags(context):
    return context.get('site', context)['tags']


def supported_exit_keys(value):
    clauses = re.split(r'\s*(?:&|\bOR\b|,(?=\s*(?:INTERSTATE|HIGHWAY|HWY|US|SR|I)[ -]*\d))\s*', normalized(value))
    keys = set()
    pending_road = False
    for clause in clauses:
        markers = {key for key in (road_marker_keys(clause) or ()) if key[2] == 'exit'}
        if markers:
            roads = {(key[0], key[1]) for key in markers}
            if not pending_road and len(roads) == 1:
                keys.update(markers)
            pending_road = False
        else:
            pending_road = pending_road or bool(road_marker_keys(clause + ' EXIT 0'))
    return keys


def osm_way_exit_keys(road_ref, junction_ref):
    marker = normalized(junction_ref)
    if not re.fullmatch(r'\d+[A-Z]?', marker) or re.search(r'\b(?:EXIT|MILE|MM)\b', normalized(road_ref)):
        return set()
    return {key for key in (road_marker_keys(f'{road_ref} EXIT {marker}') or ()) if key[2:] == ('exit', marker)}


def junction_markers(junction):
    return {marker for marker in (normalized(junction['ref']), normalized(junction.get('old_ref', ''))) if marker}


def junction_exit_keys(road_ref, junction):
    return {key for marker in junction_markers(junction) for key in osm_way_exit_keys(road_ref, marker)}


ROAD_REF = re.compile(r'\b(INTERSTATE|HIGHWAY|HWY|US|SR|I)[ -]*(\d+[A-Z]?)(?![A-Z0-9])')
STATE_REF = re.compile(r'\b([A-Z]{2})[ -]*(\d+[A-Z]?)(?![A-Z0-9])')


def typed_roads(value, state=None):
    text = normalized(value)
    aliases = {'INTERSTATE': 'I', 'HIGHWAY': 'HWY'}
    roads = {(aliases.get(m.group(1), m.group(1)), m.group(2)) for m in ROAD_REF.finditer(text)}
    states = set(STATE_NAMES.values())
    for match in STATE_REF.finditer(text):
        prefix, number = match.groups()
        if prefix in states:
            if state is None:
                roads.add((f'STATE:{prefix}', number))
            elif prefix == state:
                roads.add(('SR', number))
    return roads


def intersection_constraint(value):
    text = normalized(value)
    if re.search(r'\b(?:OR|MM|MILE|MARKER)\b', text):
        return None
    exits = re.findall(r'\bEXIT\s*#?\s*(\d+[A-Z]?)(?![A-Z0-9])', text)
    if len(exits) > 1:
        return None
    remaining = re.sub(r'\bEXIT\s*#?\s*\d+[A-Z]?(?![A-Z0-9])', ' ', text)
    roads = typed_roads(remaining, state='')
    remaining = ROAD_REF.sub(' ', remaining)
    remaining = re.sub(r'\bAND\b', ' ', remaining)
    if len(roads) < 2 or re.sub(r'[\s,&]', '', remaining):
        return None
    return roads, exits[0] if exits else ''


def matched_values(tags):
    name = tags.get('name') or tags.get('brand') or tags.get('operator') or ''
    address = tags.get('addr:full', '').strip() or ' '.join(tags.get(k, '').strip() for k in ('addr:housenumber', 'addr:street')).strip()
    return name, address


def valid_point(point):
    return (isinstance(point, (list, tuple)) and len(point) == 2
            and all(type(value) in (int, float) and math.isfinite(value) for value in point)
            and -90 <= point[0] <= 90 and -180 <= point[1] <= 180)


def valid_context(station, context, point, state_boundary, city_points):
    try:
        if not isinstance(context, dict) or not valid_point(point):
            return False
        tags = context['tags']
        kind, identifier = context['type'], context['id']
        geometry = context['geometry']
        if not isinstance(tags, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items()) or not isinstance(geometry, dict):
            return False
        if kind not in ('node', 'way', 'relation') or type(identifier) is not int or identifier <= 0:
            return False
        site = context.get('site')
        if site is not None:
            if tags.get('amenity') != 'fuel' or not isinstance(site, dict) or not isinstance(site.get('tags'), dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in site['tags'].items()):
                return False
            site_kind, site_id = site.get('type'), site.get('id')
            if site_kind not in ('way', 'relation') or type(site_id) is not int or site_id <= 0 or site.get('url') != f'https://www.openstreetmap.org/{site_kind}/{site_id}':
                return False
            if not (site['tags'].get('highway') == 'services' or site['tags'].get('landuse') == 'retail'):
                return False
            fuel_numbers = identities(tags)[1]
            site_numbers = identities(site['tags'])[1]
            if fuel_numbers and site_numbers and fuel_numbers != site_numbers:
                return False
            if fuel_numbers and source_refs(station) and not fuel_numbers <= source_refs(station):
                return False
            tags = site['tags']
        elif tags.get('amenity') != 'fuel':
            if not is_business(tags) or not exact_ref(station, tags):
                return False
        if not identity_matches([r['Truckstop Name'] for r in station.rows], tags):
            return False
        if tags.get('addr:state'):
            state = normalized(tags['addr:state'])
            if STATE_NAMES.get(state, state) != station.state:
                return False
        if tags.get('addr:city') and normalized(tags['addr:city']) != station.city:
            return False
        if not tags.get('addr:city') and not any(valid_point(city) and distance_miles(point, city) <= 30 for city in city_points):
            return False
        _, address = matched_values(tags)
        source_key, target_key = street_key(station.address), street_key(address)
        street_match = supported_street_address(station.address) and source_key == target_key
        exit_match = False
        junction = context.get('junction')
        if 'junction' in context:
            if not isinstance(junction, dict) or not isinstance(junction.get('road'), dict):
                return False
            junction_point = junction['point']
            road = junction['road']
            if not valid_point(junction_point) or not isinstance(junction.get('ref'), str) or not isinstance(junction.get('old_ref', ''), str) or not isinstance(road.get('ref'), str) or not isinstance(road.get('nodes'), list) or not all(type(n) is int and n > 0 for n in road['nodes']):
                return False
            if not (type(junction['id']) is int and junction['id'] > 0 and type(road['id']) is int and road['id'] > 0 and junction['highway'] == 'motorway_junction' and junction['url'] == f"https://www.openstreetmap.org/node/{junction['id']}" and road['url'] == f"https://www.openstreetmap.org/way/{road['id']}" and junction['id'] in road['nodes'] and road['highway'] == 'motorway' and distance_miles(point, junction_point) <= 1):
                return False
            markers = junction_markers(junction)
            keys = supported_exit_keys(station.address)
            road_keys = junction_exit_keys(road['ref'], junction)
            exit_match = bool(keys & road_keys)
            constraint = intersection_constraint(station.address)
            if constraint:
                required, marker = constraint
                main_roads = typed_roads(road['ref'], station.state)
                interchange_roads = set(main_roads)
                ramps = junction.get('ramps', [])
                if not isinstance(ramps, list):
                    return False
                for ramp in ramps:
                    if not isinstance(ramp, dict) or type(ramp.get('id')) is not int or ramp['id'] <= 0 or ramp.get('highway') != 'motorway_link' or ramp.get('url') != f"https://www.openstreetmap.org/way/{ramp['id']}" or not isinstance(ramp.get('destination:ref'), str) or not isinstance(ramp.get('nodes'), list) or not all(type(n) is int and n > 0 for n in ramp['nodes']) or junction['id'] not in ramp['nodes']:
                        return False
                    interchange_roads.update(typed_roads(ramp['destination:ref'], station.state))
                exit_match = exit_match or bool(required & main_roads and required <= interchange_roads and (not marker or marker in markers))
        if not (street_match or exit_match):
            return False
        if not in_us(point, state_boundary) or ('junction' in context and not in_us(junction_point, state_boundary)):
            return False
        if geometry.get('type') == 'Point':
            coords = geometry['coordinates']
            if kind != 'node' or not isinstance(coords, list) or len(coords) != 2 or not valid_point([coords[1], coords[0]]) or coords != [point[1], point[0]]:
                return False
        elif kind == 'node' or not valid_area(geometry, point):
            return False
        if site is not None and not valid_area(site.get('geometry'), point):
            return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError, IndexError):
        return False


def segments_intersect(a, b, c, d):
    def cross(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return (cross(a, b, c) * cross(a, b, d) <= 0 and cross(c, d, a) * cross(c, d, b) <= 0
            and max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0]))
            and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1])))


def rings_intersect(first, second):
    return any(segments_intersect(a, b, c, d) for a, b in zip(first, first[1:]) for c, d in zip(second, second[1:]))


def simple_ring(ring):
    edges = list(zip(ring, ring[1:]))
    if sum(a[0] * b[1] - b[0] * a[1] for a, b in edges) == 0 or any(a == b for a, b in edges):
        return False
    return not any(segments_intersect(a, b, c, d)
                   for i, (a, b) in enumerate(edges)
                   for j, (c, d) in enumerate(edges)
                   if j > i + 1 and not (i == 0 and j == len(edges) - 1))


def ring_contains(ring, vertex):
    return point_in_ring([vertex[1], vertex[0]], ring)


def valid_area(geometry, point):
    if not isinstance(geometry, dict) or geometry.get('type') not in ('Polygon', 'MultiPolygon'):
        return False
    try:
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        if not isinstance(polygons, list) or not polygons:
            return False
        for poly in polygons:
            if not isinstance(poly, list) or not poly:
                return False
            for ring in poly:
                if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                    return False
                if not all(isinstance(p, list) and len(p) == 2 and valid_point([p[1], p[0]]) for p in ring):
                    return False
                if len({tuple(p) for p in ring}) < 3 or not simple_ring(ring):
                    return False
            outer, *holes = poly
            for index, hole in enumerate(holes):
                if rings_intersect(outer, hole) or not ring_contains(outer, hole[0]):
                    return False
                for other in holes[:index]:
                    if rings_intersect(hole, other) or ring_contains(hole, other[0]) or ring_contains(other, hole[0]):
                        return False
        for index, poly in enumerate(polygons):
            for other in polygons[:index]:
                if any(rings_intersect(ring, other_ring) for ring in poly for other_ring in other):
                    return False
                if in_us([poly[0][0][1], poly[0][0][0]], {'type': 'Polygon', 'coordinates': other}) or in_us([other[0][0][1], other[0][0][0]], {'type': 'Polygon', 'coordinates': poly}):
                    return False
        return in_us(point, geometry)
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return False


def area_point(geometry):
    polygons = [geometry['coordinates']] if geometry.get('type') == 'Polygon' else geometry.get('coordinates', [])
    for polygon in polygons:
        if not polygon or len(polygon[0]) < 4:
            continue
        ys = sorted({p[1] for ring in polygon for p in ring})
        for low, high in zip(ys, ys[1:]):
            y = (low + high) / 2
            xs = []
            for ring in polygon:
                for a, b in zip(ring, ring[1:]):
                    if (a[1] > y) != (b[1] > y):
                        xs.append(a[0] + (y-a[1]) * (b[0]-a[0]) / (b[1]-a[1]))
            xs.sort()
            for left, right in zip(xs[::2], xs[1::2]):
                point = [y, (left + right) / 2]
                if valid_area(geometry, point):
                    return point
    return None

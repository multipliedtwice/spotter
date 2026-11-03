import re

from planner.core import distance, in_us
from planner.operator_roads import ROAD_KINDS, whole_source_routes
from planner.osm_evidence import evidence_city_key, exact_road_address_match, normalized, refs, supported_street_address, street_key, typed_roads, valid_point
from planner.road import marker_keys_match, road_marker_keys

SOURCE = 'https://am-best.com/ambest_new/public/api/get-user-locations-and-fuel-price'
FIELDS = {'id', 'internal_id', 'name', 'directory_address', 'city', 'state_in_sort', 'state', 'zip', 'lat', 'long'}


def observed_point(record):
    try:
        if not isinstance(record, dict) or not isinstance(record.get('lat'), str) or not isinstance(record.get('long'), str):
            return None
        point = [float(record['lat']), float(record['long'])]
        return point if valid_point(point) else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def name_key(value):
    text = re.sub(r'\bTRUCKSTOP\b', 'TRUCK STOP', normalized(value).replace("'", '').replace('’', ''))
    return ' '.join(re.findall(r'[A-Z0-9]+', text))


def native_point(record):
    try:
        if not isinstance(record, dict) or set(record) != FIELDS or type(record['id']) is not int or record['id'] <= 0 or record['internal_id'] is not None or record['state_in_sort'] is not None:
            return None
        if any(not isinstance(record[k], str) or not record[k].strip() for k in ('name', 'directory_address', 'city', 'state', 'lat', 'long')) or not re.fullmatch(r'[A-Z]{2}', record['state']):
            return None
        if record['zip'] is not None and not isinstance(record['zip'], str):
            return None
        point = [float(record['lat']), float(record['long'])]
        return point if valid_point(point) else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def connected_intersection(station, point, proof, state_boundary):
    try:
        required = whole_source_routes(station.address)
        if len(required) < 2 or any(kind not in {'I', 'US', 'SR', 'CR', 'FM'} for kind, _ in required) or not isinstance(proof, dict) or set(proof) != {'node_id', 'canonical_url', 'latitude', 'longitude', 'node_tags', 'route_ways'}:
            return False
        node = proof['node_id']
        if not isinstance(node, str) or not re.fullmatch(r'[1-9]\d*', node) or proof['canonical_url'] != f'https://www.openstreetmap.org/node/{node}' or not isinstance(proof['node_tags'], dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in proof['node_tags'].items()) or not isinstance(proof['latitude'], str) or not isinstance(proof['longitude'], str):
            return False
        shared = [float(proof['latitude']), float(proof['longitude'])]
        if not valid_point(shared) or not in_us(shared, state_boundary) or distance(point, shared) > 1:
            return False
        ways = proof['route_ways']
        if not isinstance(ways, list) or len(ways) < 2:
            return False
        found, ids, way_routes = set(), set(), []
        for way in ways:
            if not isinstance(way, dict) or set(way) != {'id', 'canonical_url', 'tags', 'node_ids', 'geometry'}:
                return False
            wid, tags, nodes, geometry = way['id'], way['tags'], way['node_ids'], way['geometry']
            if not isinstance(wid, str) or not re.fullmatch(r'[1-9]\d*', wid) or wid in ids or way['canonical_url'] != f'https://www.openstreetmap.org/way/{wid}':
                return False
            ids.add(wid)
            if not isinstance(tags, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items()) or tags.get('highway') not in ROAD_KINDS or not tags.get('ref'):
                return False
            if not isinstance(nodes, list) or len(nodes) < 2 or not all(isinstance(n, str) and re.fullmatch(r'[1-9]\d*', n) for n in nodes) or not isinstance(geometry, list) or len(geometry) != len(nodes) or nodes.count(node) != 1:
                return False
            for identifier, vertex in zip(nodes, geometry):
                if not isinstance(vertex, dict) or set(vertex) != {'id', 'lat', 'lon', 'tags'} or vertex['id'] != identifier or not isinstance(vertex['lat'], str) or not isinstance(vertex['lon'], str) or not isinstance(vertex['tags'], dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in vertex['tags'].items()):
                    return False
                coords = [float(vertex['lat']), float(vertex['lon'])]
                if not valid_point(coords) or (identifier == node and coords != shared):
                    return False
            routes = typed_roads(tags['ref'], station.state) & required
            if not routes:
                return False
            found.update(routes)
            way_routes.append(routes)
        separate = any(left != right for i, routes in enumerate(way_routes) for left in routes for other in way_routes[i + 1:] for right in other)
        return required <= found and separate
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def valid_ambest_record(station, context, point, state_boundary):
    try:
        if not isinstance(context, dict) or set(context) not in ({'source', 'record'}, {'source', 'record', 'intersection'}, {'source', 'record', 'junction'}) or context['source'] != SOURCE:
            return False
        record = context['record']
        native = native_point(record)
        if native is None or native != list(point) or not state_boundary or not in_us(native, state_boundary):
            return False
        if normalized(record['state']) != normalized(station.state) or evidence_city_key(record['city']) != evidence_city_key(station.city):
            return False
        names = [row['Truckstop Name'] for row in station.rows]
        if not names or any(name_key(name) != name_key(record['name']) or refs(name) != refs(record['name']) for name in names):
            return False
        from planner.osm_evidence import compound_routes_match, junction_match
        source, target = normalized(station.address), normalized(record['directory_address'])
        markers = marker_keys_match(road_marker_keys(source), road_marker_keys(target), source) and compound_routes_match(source, target, station.state)
        street = (supported_street_address(source) and supported_street_address(target) and street_key(source) == street_key(target)) or exact_road_address_match(source, target)
        if 'junction' in context:
            return junction_match(station, native, context['junction'], state_boundary, max_distance=1) is True
        if 'intersection' in context:
            return connected_intersection(station, native, context['intersection'], state_boundary)
        return bool(markers or street)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False

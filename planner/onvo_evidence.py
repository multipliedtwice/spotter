import re

from planner.core import in_us
from planner.osm_evidence import compound_routes_match, evidence_city_key, normalized, refs, street_key, supported_street_address, valid_point
from planner.road import marker_keys_match, road_marker_keys

SOURCE_URL = re.compile(r'https://tryonvo\.com/location/onvo-[a-z0-9]+(?:-[a-z0-9]+)*/')
COMMON_FIELDS = {'source_url', 'page_title', 'schema_type', 'name', 'street_address_literal', 'address_locality_literal', 'address_region_literal', 'address_postal_code_literal', 'address_country_literal', 'latitude', 'longitude', 'map_marker_latitude', 'map_marker_longitude', 'map_link'}
FIELDS = COMMON_FIELDS | {'literal_route_labels', 'literal_road_mentions'}


def onvo_observed_point(record):
    if not isinstance(record, dict):
        return None
    point = [record.get('latitude'), record.get('longitude')]
    return point if valid_point(point) else None


def branch_key(value, native=False):
    text = normalized(value).replace('–', '-').replace('—', '-')
    pattern = r"ONVO\s*-\s*([A-Z][A-Z .']+)" if native else r"ONVO\s+TRAVEL\s+PLAZA\s*-\s*([A-Z][A-Z .']+)"
    match = re.fullmatch(pattern, text)
    return ' '.join(re.findall(r'[A-Z]+', match.group(1))) if match else ''


def onvo_view(record):
    try:
        if not isinstance(record, dict) or set(record) != FIELDS:
            return None
        string_fields = COMMON_FIELDS - {'latitude', 'longitude'}
        if any(not isinstance(record[k], str) for k in string_fields) or record['schema_type'] != 'GasStation' or record['address_country_literal'] != 'US' or not SOURCE_URL.fullmatch(record['source_url']):
            return None
        if any(not isinstance(record[k], list) or not all(isinstance(value, str) for value in record[k]) for k in ('literal_route_labels', 'literal_road_mentions')):
            return None
        if not branch_key(record['name'], native=True):
            return None
        match = re.fullmatch(r'([^,]+),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?),\s*USA', record['street_address_literal'].strip(), re.I)
        if not match or not supported_street_address(match.group(1)):
            return None
        street, city, state, postal = (x.strip() for x in match.groups())
        state = state.upper()
        if record['address_locality_literal'] and evidence_city_key(record['address_locality_literal'], state) != evidence_city_key(city, state):
            return None
        if record['address_region_literal'] and normalized(record['address_region_literal']) != state:
            return None
        if record['address_postal_code_literal'] and record['address_postal_code_literal'] != postal:
            return None
        point = [record['latitude'], record['longitude']]
        if not valid_point(point) or not record['map_marker_latitude'] or not record['map_marker_longitude'] or [float(record['map_marker_latitude']), float(record['map_marker_longitude'])] != point:
            return None
        return {'source': record['source_url'], 'name': record['name'], 'address': street, 'city': city, 'state': state, 'latitude': point[0], 'longitude': point[1]}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def onvo_key(context):
    if not isinstance(context, dict) or set(context) != {'source', 'record'}:
        return None
    view = onvo_view(context['record'])
    return ('ONVO', view['source']) if view and context['source'] == view['source'] else None


def valid_onvo_record(station, context, point, state_boundary):
    try:
        if not onvo_key(context):
            return False
        record, view = context['record'], onvo_view(context['record'])
        if [view['latitude'], view['longitude']] != list(point) or not state_boundary or not in_us(point, state_boundary):
            return False
        if normalized(station.state) != view['state'] or evidence_city_key(station.city, station.state) != evidence_city_key(view['city'], view['state']):
            return False
        branch = branch_key(view['name'], native=True)
        if not station.rows or any(refs(row['Truckstop Name']) or branch_key(row['Truckstop Name']) != branch for row in station.rows):
            return False
        if supported_street_address(station.address) and street_key(station.address) == street_key(view['address']):
            return True
        labels = record['literal_route_labels']
        street = re.sub(r'\bSTATE\s+ROUTE\b', 'SR', normalized(view['address']))
        for label in labels:
            route = re.fullmatch(r'\s*EXIT\s+(\d+[A-D]?)\s+(I-?\d+)\s*', normalized(label))
            if route:
                published = f'{route.group(2)} EXIT {route.group(1)} & {street}'
                if marker_keys_match(road_marker_keys(station.address), road_marker_keys(published), station.address) and compound_routes_match(station.address, published, station.state):
                    return True
        return False
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return False

import re

from planner.core import in_us
from planner.osm_evidence import canonical_source_name, compound_routes_match, evidence_city_key, exact_road_address_match, junction_match, normalized, refs, street_key, supported_street_address, valid_point
from planner.road import marker_keys_match, road_marker_keys

SOURCE = 'https://www.wexinc.com/products/fuel-cards-fleet/wex-fleet-fuel-card-locations/'
ENDPOINT = 'https://www.wexinc.com/wp-content/plugins/wex-wp-plugin-fuel-map/includes/fuel-location-get.php'
FIELDS = {'siteId', 'name', 'brand', 'address', 'city', 'state', 'zip', 'location'}


def observed_point(record):
    try:
        location = record['location']
        point = [location['latitude'], location['longitude']]
        return point if valid_point(point) else None
    except (KeyError, TypeError):
        return None


def native_point(record):
    if not isinstance(record, dict) or set(record) != FIELDS or any(not isinstance(record[k], str) or not record[k].strip() for k in FIELDS - {'location'}) or not isinstance(record['location'], dict) or set(record['location']) != {'latitude', 'longitude'}:
        return None
    if not re.fullmatch(r'(?=.*[A-Za-z0-9])[A-Za-z0-9-]+', record['siteId']) or not re.fullmatch(r'[A-Z]{2}', record['state']) or not re.fullmatch(r'\d{5}(?:-\d{4})?', record['zip']):
        return None
    return observed_point(record)


def business_name_key(value):
    return ''.join(character for character in normalized(value) if character.isalnum())


def valid_wex_record(station, context, point, state_boundary):
    try:
        if not isinstance(context, dict) or set(context) not in ({'source', 'record'}, {'source', 'record', 'junction'}, {'source', 'record', 'intersection'}) or context['source'] != SOURCE:
            return False
        record = context['record']
        native = native_point(record)
        if native is None or native != list(point) or not state_boundary or not in_us(native, state_boundary):
            return False
        if evidence_city_key(record['city']) != evidence_city_key(station.city) or normalized(record['state']) != normalized(station.state):
            return False
        names = [row['Truckstop Name'] for row in station.rows]
        if not names:
            return False
        if any(canonical_source_name(name) == 'CASEYS' for name in names):
            if normalized(record['brand']).replace('’', "'") != "CASEY'S GENERAL STORE":
                return False
            label = re.fullmatch(r'CASEYS\s*#\s*(\d+)', normalized(record['name']))
            if not label or int(label.group(1)) <= 0:
                return False
            number = str(int(label.group(1)))
            if any(not re.fullmatch(r"CASEY(?:'|’)?S\s*#\s*\d+", normalized(name)) or canonical_source_name(name) != 'CASEYS' or refs(name) != {number} for name in names):
                return False
        elif not business_name_key(record['name']) or any(business_name_key(name) != business_name_key(record['name']) for name in names):
            return False
        source, target = normalized(station.address), normalized(record['address'])
        street = (supported_street_address(source) and supported_street_address(target) and street_key(source) == street_key(target)) or exact_road_address_match(source, target)
        markers = marker_keys_match(road_marker_keys(source), road_marker_keys(target), source) and compound_routes_match(source, target, station.state)
        if 'junction' in context:
            return junction_match(station, native, context['junction'], state_boundary, max_distance=1) is True
        if 'intersection' in context:
            from planner.ambest_evidence import connected_intersection
            return connected_intersection(station, native, context['intersection'], state_boundary)
        return bool(street or markers)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return False

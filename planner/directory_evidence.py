import math
import re

from planner.core import in_us
from planner.osm_evidence import canonical_name, canonical_source_name, compound_routes_match, evidence_city_key, exact_road_address_match, identity_matches, junction_match, normalized, refs, street_key, supported_street_address
from planner.road import marker_keys_match, road_marker_keys
from planner.ambest_evidence import SOURCE as AMBEST_SOURCE, valid_ambest_record
from planner.wex_evidence import SOURCE as WEX_SOURCE, valid_wex_record
from planner.onvo_evidence import onvo_key, valid_onvo_record


SOURCE_URL = re.compile(r'https://www\.findfuelstops\.com/truck-stop-\d{6}')
OPIS_SOURCE = 'https://info.opisnet.com/hubfs/Product%20Campaigns/Truckstop%20Spread%20Report/OPIS%20Truckstop%20Spread%20Report%20Sample.pdf'
FIELDS = ('source', 'name', 'address', 'city', 'state', 'country', 'latitude', 'longitude')
OPIS_FIELDS = ('id', 'name', 'address', 'address2', 'city', 'state', 'country', 'latitude', 'longitude', 'source')


def directory_key(record):
    record = directory_record(record)
    if not isinstance(record, dict):
        return None
    source = record.get('source')
    if isinstance(record.get('record'), dict) and (key := onvo_key(record)):
        return key
    if source == WEX_SOURCE and isinstance(record.get('record'), dict):
        identifier = record['record'].get('siteId')
        return (source, identifier) if isinstance(identifier, str) and re.fullmatch(r'(?=.*[A-Za-z0-9])[A-Za-z0-9-]+', identifier) else None
    if source == AMBEST_SOURCE and isinstance(record.get('record'), dict):
        identifier = record['record'].get('id')
        return (source, identifier) if type(identifier) is int and identifier > 0 else None
    if isinstance(source, str) and SOURCE_URL.fullmatch(source):
        return (source,)
    identifier = record.get('id')
    if source == OPIS_SOURCE and isinstance(identifier, str) and re.fullmatch(r'\d+', identifier):
        return (source, str(int(identifier)))
    return None


def directory_record(context):
    if isinstance(context, dict) and set(context) == {'record', 'junction'}:
        return context['record']
    return context


def valid_opis_record(station, record, point, state_boundary):
    try:
        if set(record) != set(OPIS_FIELDS) or not directory_key(record) or record['source'] != OPIS_SOURCE:
            return False
        if any(not isinstance(record[k], str) or not record[k].strip() for k in ('id', 'name', 'address', 'address2', 'city', 'state', 'country', 'source')):
            return False
        if not re.fullmatch(r'\d+', station.source_id) or int(station.source_id) != int(record['id']) or record['country'] != 'USA':
            return False
        if normalized(record['address2']) != normalized(station.address) or evidence_city_key(record['city']) != evidence_city_key(station.city) or normalized(record['state']) != normalized(station.state):
            return False
        names = [row['Truckstop Name'] for row in station.rows]
        target = canonical_source_name(record['name'])
        source_refs = set().union(*(refs(name) for name in names))
        target_refs = refs(record['name'])
        if not target or not any(canonical_source_name(name) == target for name in names) or len(source_refs) > 1 or len(target_refs) > 1 or (source_refs and target_refs and source_refs != target_refs):
            return False
        coords = [record['latitude'], record['longitude']]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in coords):
            return False
        return coords == list(point) and -90 <= coords[0] <= 90 and -180 <= coords[1] <= 180 and bool(state_boundary) and in_us(coords, state_boundary)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def comparison_address(value):
    return re.sub(r'\bEX\.?\s*(?=\d)', 'EXIT ', normalized(value))


def street_addresses(value):
    return {street_key(part) for part in value.split(',') if supported_street_address(part)}


def city_appended_identity(station, record):
    names = [row['Truckstop Name'] for row in station.rows]
    source_refs = set().union(*(refs(name) for name in names))
    target_refs = refs(record['name'])
    if len(source_refs) != 1 or source_refs != target_refs or len(re.findall(r'#\s*\d+[A-Z]?(?![A-Z0-9])', normalized(record['name']))) != 1:
        return False
    name = re.sub(r'#\s*\d+[A-Z]?(?![A-Z0-9])', ' ', normalized(record['name']))
    name_tokens = re.findall(r'[A-Z0-9]+', name)
    city_tokens = re.findall(r'[A-Z0-9]+', normalized(record['city']))
    if not city_tokens or len(name_tokens) <= len(city_tokens) or name_tokens[-len(city_tokens):] != city_tokens:
        return False
    prefix = name_tokens[:-len(city_tokens)]
    if ''.join(prefix) == 'QUICKFUEL':
        return any(''.join(re.findall(r'[A-Z0-9]+', re.sub(r'#\s*\d+[A-Z]?(?![A-Z0-9])', ' ', normalized(name)))) == 'QUICKFUEL' and refs(name) == source_refs and len(re.findall(r'#\s*\d+[A-Z]?(?![A-Z0-9])', normalized(name))) == 1 for name in names)
    brand = canonical_name(' '.join(prefix))
    permitted = {'TRAVELCENTERS OF AMERICA', 'PETRO', 'TA EXPRESS', 'TOOTN TOTUM'}
    return brand in permitted and any(canonical_source_name(name) == brand and refs(name) == source_refs and len(re.findall(r'#\s*\d+[A-Z]?(?![A-Z0-9])', normalized(name))) == 1 for name in names)


def valid_directory_record(station, record, point, state_boundary):
    if isinstance(record, dict) and isinstance(record.get('source'), str) and record['source'].startswith('https://tryonvo.com/'):
        return valid_onvo_record(station, record, point, state_boundary)
    if isinstance(record, dict) and record.get('source') == AMBEST_SOURCE:
        return valid_ambest_record(station, record, point, state_boundary)
    if isinstance(record, dict) and record.get('source') == WEX_SOURCE:
        return valid_wex_record(station, record, point, state_boundary)
    junction = None
    if isinstance(record, dict) and set(record) == {'record', 'junction'}:
        junction = record['junction']
        record = record['record']
        if junction is None or not isinstance(record, dict) or record.get('source') == OPIS_SOURCE:
            return False
    if isinstance(record, dict) and record.get('source') == OPIS_SOURCE:
        return valid_opis_record(station, record, point, state_boundary)
    if not isinstance(record, dict) or set(record) not in (set(FIELDS), set(FIELDS) - {'country'}):
        return False
    if not all(isinstance(record[k], str) and record[k].strip() for k in ('source', 'name', 'address', 'city', 'state')):
        return False
    if 'country' in record and (not isinstance(record['country'], str) or normalized(record['country']) != 'US'):
        return False
    if not SOURCE_URL.fullmatch(record['source']):
        return False
    if normalized(record['state']) != normalized(station.state) or evidence_city_key(record['city']) != evidence_city_key(station.city):
        return False
    coords = [record['latitude'], record['longitude']]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in coords):
        return False
    if not (-90 <= coords[0] <= 90 and -180 <= coords[1] <= 180) or coords != list(point):
        return False
    if not state_boundary or not in_us(coords, state_boundary):
        return False
    if not identity_matches([row['Truckstop Name'] for row in station.rows], {'name': record['name']}) and not city_appended_identity(station, record):
        return False
    if junction is not None:
        source_refs = set().union(*(refs(row['Truckstop Name']) for row in station.rows))
        if source_refs and (len(source_refs) != 1 or refs(record['name']) != source_refs):
            return False
    source_address = comparison_address(station.address)
    target_address = comparison_address(record['address'])
    source_roads, target_roads = road_marker_keys(source_address), road_marker_keys(target_address)
    highway_match = marker_keys_match(source_roads, target_roads, source_address) and compound_routes_match(source_address, target_address, station.state)
    street_match = bool(street_addresses(source_address) & street_addresses(target_address)) or exact_road_address_match(source_address, target_address)
    if junction is not None:
        try:
            if junction_match(station, coords, junction, state_boundary, max_distance=1) is not True:
                return False
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
    return bool(highway_match or street_match or junction is not None)

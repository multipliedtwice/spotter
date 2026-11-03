import re

from planner.core import in_us
from planner.osm_evidence import canonical_name, canonical_source_name, compound_routes_match, evidence_city_key, exact_road_address_match, junction_match, normalized, refs, street_key, supported_street_address, typed_roads, valid_point
from planner.road import marker_keys_match, road_marker_keys
from planner.operator_roads import roads_match, whole_source_routes
from planner.roadranger_evidence import roadranger_display, roadranger_key, valid_roadranger_record
from planner.raw_operator_evidence import KENTKWIK_SOURCE, kentkwik_source_brand, kentkwik_source_numbers, PARKERS_SOURCE, parkers_source_brand, parkers_source_numbers, DANDY_SOURCE, DUCKTHRU_SOURCE, GOOD2GO_SOURCE, HUCKS_SOURCE, JETFOOD_SOURCE, PETES_SOURCE, SPINX_SOURCE, dandy_source_brand, duckthru_source_brand, good2go_source_brand, hucks_source_brand, jetfood_source_brand, petes_source_brand, petes_source_numbers, raw_operator_key, raw_operator_view, spinx_source_brand, spinx_source_numbers

RAW_SOURCE_BRANDS = {KENTKWIK_SOURCE: kentkwik_source_brand, PARKERS_SOURCE: parkers_source_brand, DANDY_SOURCE: dandy_source_brand, DUCKTHRU_SOURCE: duckthru_source_brand, GOOD2GO_SOURCE: good2go_source_brand, HUCKS_SOURCE: hucks_source_brand, JETFOOD_SOURCE: jetfood_source_brand, PETES_SOURCE: petes_source_brand, SPINX_SOURCE: spinx_source_brand}
RAW_SOURCE_NUMBERS = {KENTKWIK_SOURCE: kentkwik_source_numbers, PARKERS_SOURCE: parkers_source_numbers, PETES_SOURCE: petes_source_numbers, SPINX_SOURCE: spinx_source_numbers}

KWIK_SOURCE = 'https://www.kwiktrip.com/Maps-Downloads/Store-List'
YESWAY_SOURCE = 'https://yesway.com/wp-content/themes/yesway/locations/locations.json'
LOVES_SOURCE = 'https://www.loves.com/api/fetch_stores'
CIRCLEK_SOURCE = 'https://api.circlek.com/us/ngrp-store-locator/v1/stations'
PILOT_SOURCE = re.compile(r'https://locations\.pilotflyingj\.com/us/[a-z]{2}/[a-z0-9-]+/[a-z0-9][a-z0-9.-]*')
LOCAL_SOURCE = re.compile(r'https://locations\.(maverik|quiktrip)\.com/([a-z]{2})/[a-z0-9-]+/[a-z0-9][a-z0-9.-]*')
TA_SOURCE = re.compile(r'https://www\.ta-petro\.com/location/([a-z]{2})/[a-z0-9-]+/')
COMMON = {'number', 'name', 'address', 'city', 'state', 'latitude', 'longitude', 'source'}


def pilot_source_brand(name):
    clean = re.sub(r'#\s*\d+[A-Z]?(?![A-Z0-9])', ' ', normalized(name))
    clean = ' '.join(re.findall(r'[A-Z0-9]+', clean))
    if clean in ('FLYING J TRAVEL PLAZA', 'FLYING J TRAVELPLAZA', 'FLYING J FUEL STOP'):
        return 'FLYING J'
    return canonical_source_name(name)


def valid_identity_flag(context):
    return 'identity_only' not in context or (context['identity_only'] is True and not any(key in context for key in ('junction', 'roads', 'approved_primary_exit', 'approved_named_plaza')))


def ta_branch_key(name):
    text = re.sub(r'#\s*\d+[A-Z]?(?![A-Z0-9])', ' ', normalized(name))
    text = ' '.join(re.findall(r'[A-Z0-9]+', text))
    text = re.sub(r'\s+TRAVEL ?CENT(?:ER|RE)$', '', text)
    if re.match(r'^PETRO SERVE USA(?: |$)', text):
        return None
    match = re.fullmatch(r'(TA EXPRESS|TA|PETRO)(?: (.+))?', text)
    if not match:
        return None
    return match.group(1), match.group(2) or ''


def operator_store_key(store, source_override=None):
    if raw_operator_key(store):
        return raw_operator_key(store)
    if roadranger_key(store):
        return roadranger_key(store)
    source, number, name = store.get('source'), store.get('number'), store.get('name')
    if isinstance(store.get('id'), str) and re.fullmatch(r'\d+', store['id']) and source == f"{CIRCLEK_SOURCE}/{store['id']}":
        return ('CIRCLE K', str(int(store['id'])))
    if source_override == LOVES_SOURCE and not isinstance(number, bool) and isinstance(number, (int, str)) and re.fullmatch(r'\d+', str(number)):
        return ('LOVES', str(int(number)))
    if not isinstance(number, str) or not re.fullmatch(r'\d+', number) or not isinstance(name, str):
        return None
    brand = canonical_name(name)
    if isinstance(source, str) and TA_SOURCE.fullmatch(source) and ta_branch_key(name):
        return ('TA', str(int(number)))
    if source == YESWAY_SOURCE and brand in ('YESWAY', 'ALLSUPS'):
        return (brand, str(int(number)))
    if source == KWIK_SOURCE and brand in ('KWIK TRIP', 'KWIK STAR'):
        return ('KWIK', str(int(number)))
    if isinstance(source, str) and PILOT_SOURCE.fullmatch(source) and brand in ('PILOT', 'PILOT DEALER', 'PILOT EXPRESS', 'FLYING J', 'FLYING J DEALER'):
        return ('PILOT', str(int(number)))
    local = LOCAL_SOURCE.fullmatch(source) if isinstance(source, str) else None
    if local and brand == local.group(1).upper():
        return (brand, str(int(number)))
    return None


def operator_display(store):
    view = raw_operator_view(store)
    if view:
        return view
    if roadranger_key(store):
        return roadranger_display(store)
    if operator_store_key(store) and operator_store_key(store)[0] == 'CIRCLE K':
        return {'number': store['id'], 'name': 'Circle K', 'address': store['address']['street'], 'city': store['address']['city'], 'state': store['address']['state'], 'latitude': store['latitude'], 'longitude': store['longitude'], 'source': store['source'], 'highway': ''}
    return store


def valid_circlek_record(station, context, point, state_boundary):
    try:
        if not isinstance(context, dict) or set(context) - {'store', 'junction', 'roads', 'identity_only'} or ('junction' in context and 'roads' in context) or not valid_identity_flag(context) or not isinstance(context.get('store'), dict):
            return False
        store = context['store']
        if set(store) != {'id', 'brand', 'publicBrand', 'latitude', 'longitude', 'address', 'source'} or not operator_store_key(store) or operator_store_key(store)[0] != 'CIRCLE K':
            return False
        if store['brand'] != 'CIRCLEK' or store['publicBrand'] != 'CIRCLEK' or not isinstance(store['address'], dict) or set(store['address']) != {'street', 'city', 'state', 'postalCode', 'country'}:
            return False
        if any(not isinstance(value, str) or not value.strip() for value in store['address'].values()) or store['address']['country'] != 'US':
            return False
        view = operator_display(store)
        coords = [view['latitude'], view['longitude']]
        if not valid_point(coords) or coords != list(point) or not state_boundary or not in_us(coords, state_boundary):
            return False
        if evidence_city_key(view['city'], view['state']) != evidence_city_key(station.city, station.state) or normalized(view['state']) != normalized(station.state):
            return False
        names = [row['Truckstop Name'] for row in station.rows]
        number = str(int(store['id']))
        source_refs = set().union(*(refs(name) for name in names))
        if source_refs != {number} or not any(canonical_source_name(name) in ('CIRCLE K', 'CIRCLEK') and re.findall(r'#\s*(\d+[A-Z]?)(?![A-Z0-9])', normalized(name)) == [store['id']] for name in names):
            return False
        if context.get('identity_only') is True:
            return all(canonical_source_name(name) in ('CIRCLE K', 'CIRCLEK') for name in names)
        if 'junction' in context and context['junction'] is None:
            return False
        if 'roads' in context and context['roads'] is None:
            return False
        return operator_address_match(station, view, context.get('junction'), state_boundary, context.get('roads'))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def valid_ta_record(station, context, point, state_boundary):
    try:
        if not isinstance(context, dict) or set(context) - {'store', 'junction', 'roads', 'identity_only'} or ('junction' in context and 'roads' in context) or not valid_identity_flag(context) or not isinstance(context.get('store'), dict):
            return False
        store = context['store']
        if set(store) != COMMON | {'highway'} or any(not isinstance(store[k], str) or not store[k].strip() for k in ('number', 'name', 'address', 'city', 'state', 'source', 'highway')):
            return False
        source = TA_SOURCE.fullmatch(store['source'])
        if not source or source.group(1).upper() != normalized(store['state']) or not re.fullmatch(r'\d+', store['number']):
            return False
        target = ta_branch_key(store['name'])
        number = str(int(store['number']))
        if not target or refs(store['name']) != {number}:
            return False
        coords = [store['latitude'], store['longitude']]
        if not valid_point(coords) or coords != list(point) or not state_boundary or not in_us(coords, state_boundary):
            return False
        if evidence_city_key(store['city'], store['state']) != evidence_city_key(station.city, station.state) or normalized(store['state']) != normalized(station.state):
            return False
        names = [row['Truckstop Name'] for row in station.rows]
        source_refs = set().union(*(refs(name) for name in names))
        numbered = bool(source_refs)
        if numbered:
            if source_refs != {number} or not any(ta_branch_key(name) and ta_branch_key(name)[0] == target[0] and refs(name) == {number} for name in names):
                return False
        elif not target[1] or not any(ta_branch_key(name) == target for name in names):
            return False
        if context.get('identity_only') is True:
            return numbered and all(ta_branch_key(name) and ta_branch_key(name)[0] == target[0] for name in names)
        if ('junction' in context and context['junction'] is None) or ('roads' in context and context['roads'] is None):
            return False
        if not numbered and 'roads' in context:
            return False
        street = supported_street_address(station.address) and supported_street_address(store['address']) and street_key(station.address) == street_key(store['address'])
        junction = False
        if 'junction' in context:
            junction = junction_match(station, coords, context['junction'], state_boundary, max_distance=5)
            if junction is None:
                return False
        source_markers = road_marker_keys(station.address)
        marker = bool(source_markers and all(key[2] == 'exit' for key in source_markers) and published_marker_match(station.address, ' & '.join((store['highway'], store['address'])), station.state))
        if not numbered:
            return bool(street or (junction and source_markers and any(key[2] == 'exit' for key in source_markers)) or marker)
        if 'roads' in context and not roads_match(station, context['roads'], coords, state_boundary):
            return False
        return bool(street or junction or marker or ('roads' in context) or operator_route_match(station, store))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def operator_route_match(station, store):
    routes = whole_source_routes(station.address)
    published = typed_roads(' '.join((store['address'], store.get('highway', ''))), station.state)
    return bool(routes and routes <= published)


def published_marker_match(address, published, state):
    source_markers = road_marker_keys(address)
    published_markers = road_marker_keys(published)
    if not marker_keys_match(source_markers, published_markers, address):
        return False
    return compound_routes_match(address, published, state)


def operator_address_match(station, store, junction, state_boundary, roads=None):
    point = [store['latitude'], store['longitude']]
    street = (supported_street_address(station.address) and supported_street_address(store['address']) and street_key(station.address) == street_key(store['address'])) or any(exact_road_address_match(station.address, value) for value in (store['address'], store.get('highway', '')))
    if junction is not None:
        road = junction_match(station, point, junction, state_boundary, max_distance=5)
        if road is None:
            return False
    else:
        road = False
    if roads is not None:
        if not roads_match(station, roads, point, state_boundary):
            return False
        road = True
    markers_match = published_marker_match(station.address, ' & '.join((store.get('highway', ''), store['address'])), station.state)
    return bool(street or road or markers_match or operator_route_match(station, store))


def valid_loves_route_record(station, context, point, state_boundary, approvals=()):
    try:
        if not isinstance(context, dict) or not {'source', 'store'} <= set(context) or set(context) - {'source', 'store', 'junction', 'approved_primary_exit', 'approved_named_plaza', 'identity_only'} or not valid_identity_flag(context) or context['source'] != LOVES_SOURCE or not isinstance(context['store'], dict):
            return False
        if 'approved_named_plaza' in context and (context['approved_named_plaza'] is not True or any(k in context for k in ('junction', 'approved_primary_exit', 'identity_only'))):
            return False
        if 'approved_primary_exit' in context and (context['approved_primary_exit'] is not True or 'junction' in context):
            return False
        store = context['store']
        key = operator_store_key(store, LOVES_SOURCE)
        if not key or store.get('isLoveStore') is not True:
            return False
        if not all(isinstance(store.get(k), str) for k in ('city', 'state', 'highway')):
            return False
        coords = [store['latitude'], store['longitude']]
        if not valid_point(coords) or coords != list(point) or not state_boundary or not in_us(coords, state_boundary):
            return False
        if normalized(store['state']) != normalized(station.state) or (context.get('approved_named_plaza') is not True and evidence_city_key(store['city'], store['state']) != evidence_city_key(station.city, station.state)):
            return False
        names = [row['Truckstop Name'] for row in station.rows]
        source_refs = set().union(*(refs(name) for name in names))
        if source_refs != {key[1]} or not any(canonical_source_name(name) == 'LOVES' and refs(name) == {key[1]} for name in names):
            return False
        address = store.get('address1', '')
        if not isinstance(address, str) or (context.get('identity_only') is True and not address.strip()):
            return False
        if context.get('identity_only') is True:
            return all(canonical_source_name(name) == 'LOVES' for name in names)
        if context.get('approved_named_plaza') is True:
            from planner.operator_approval import approved_named_plaza
            return all(canonical_source_name(name) == 'LOVES' and refs(name) == {key[1]} for name in names) and approved_named_plaza(station, store, approvals)
        if context.get('approved_primary_exit') is True:
            from planner.operator_approval import approved_primary_exit
            return approved_primary_exit(station, store, approvals)
        if 'junction' in context:
            road = junction_match(station, coords, context['junction'], state_boundary, max_distance=5)
            if road is None:
                return False
        else:
            road = False
        return bool(road or any(exact_road_address_match(station.address, value) for value in (address, store['highway'])) or operator_route_match(station, {'address': address, 'highway': store['highway']}))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def valid_operator_record(station, context, point, state_boundary):
    try:
        if not isinstance(context, dict) or set(context) - {'store', 'junction', 'roads', 'identity_only'} or ('junction' in context and 'roads' in context) or not valid_identity_flag(context) or not isinstance(context.get('store'), dict):
            return False
        store = context['store']
        if 'record' in store:
            view = raw_operator_view(store)
            if not view:
                return False
            coords = [view['latitude'], view['longitude']]
            if coords != list(point) or not state_boundary or not in_us(coords, state_boundary):
                return False
            if evidence_city_key(view['city'], view['state']) != evidence_city_key(station.city, station.state) or normalized(view['state']) != normalized(station.state):
                return False
            names = [row['Truckstop Name'] for row in station.rows]
            number, brand = str(int(view['number'])), canonical_name(view['name'])
            source_numbers = RAW_SOURCE_NUMBERS.get(view['source'], refs)
            source_refs = set().union(*(source_numbers(name) for name in names))
            source_brands = [RAW_SOURCE_BRANDS.get(view['source'], canonical_source_name)(name) for name in names]
            if source_refs != {number} or not any(source_numbers(name) == {number} for name in names) or not all(value == brand for value in source_brands):
                return False
            if view['source'] in (DUCKTHRU_SOURCE, DANDY_SOURCE, PETES_SOURCE, SPINX_SOURCE, PARKERS_SOURCE, KENTKWIK_SOURCE) and any(source_numbers(name) != {number} for name in names):
                return False
            if view['source'] in RAW_SOURCE_BRANDS and any(len(re.findall(r'#\s*\d+[A-Z]?(?![A-Z0-9])', normalized(name))) > 1 for name in names):
                return False
            if view['source'] in (PARKERS_SOURCE, KENTKWIK_SOURCE) and context.get('identity_only') is not True:
                return False
            if context.get('identity_only') is True:
                return True
            if ('junction' in context and context['junction'] is None) or ('roads' in context and context['roads'] is None):
                return False
            return operator_address_match(station, view, context.get('junction'), state_boundary, context.get('roads'))
        if 'billing' in store or 'locator' in store:
            return valid_roadranger_record(station, context, point, state_boundary)
        if 'id' in store:
            return valid_circlek_record(station, context, point, state_boundary)
        if isinstance(store.get('source'), str) and TA_SOURCE.fullmatch(store['source']):
            return valid_ta_record(station, context, point, state_boundary)
        source = store.get('source')
        if source == KWIK_SOURCE:
            if set(store) != COMMON | {'sells_gas', 'sells_diesel'}:
                return False
            if type(store['sells_gas']) is not bool or type(store['sells_diesel']) is not bool or not (store['sells_gas'] or store['sells_diesel']):
                return False
            brands = {'KWIK TRIP', 'KWIK STAR'}
        elif isinstance(source, str) and PILOT_SOURCE.fullmatch(source):
            if set(store) != COMMON | {'highway'} or not isinstance(store['highway'], str):
                return False
            brands = {'PILOT', 'PILOT DEALER', 'PILOT EXPRESS', 'FLYING J', 'FLYING J DEALER'}
        elif source == YESWAY_SOURCE:
            if context.get('identity_only') is True:
                return False
            if set(store) != COMMON | {'country', 'coming_soon', 'amenities', 'fuel_cards'} or store['coming_soon'] not in (False, None) or type(store['coming_soon']) not in (bool, type(None)) or store['country'] != 'US':
                return False
            if not isinstance(store['amenities'], list) or not all(isinstance(item, str) for item in store['amenities']):
                return False
            if store['fuel_cards'] is not None and (not isinstance(store['fuel_cards'], list) or not all(isinstance(item, str) for item in store['fuel_cards'])):
                return False
            brands = {'YESWAY', 'ALLSUPS'}
        elif isinstance(source, str) and LOCAL_SOURCE.fullmatch(source):
            if set(store) != COMMON | {'highway'} or not isinstance(store['highway'], str):
                return False
            brands = {LOCAL_SOURCE.fullmatch(source).group(1).upper()}
        else:
            return False
        if any(not isinstance(store[k], str) or not store[k].strip() for k in ('number', 'name', 'address', 'city', 'state', 'source')) or not re.fullmatch(r'\d+', store['number']):
            return False
        coords = [store['latitude'], store['longitude']]
        if not valid_point(coords) or coords != list(point) or not state_boundary or not in_us(coords, state_boundary):
            return False
        if evidence_city_key(store['city'], store['state']) != evidence_city_key(station.city, station.state) or normalized(store['state']) != normalized(station.state):
            return False
        if isinstance(source, str) and PILOT_SOURCE.fullmatch(source) and source.split('/')[4].upper() != normalized(store['state']):
            return False
        local = LOCAL_SOURCE.fullmatch(source) if isinstance(source, str) else None
        if local and local.group(2).upper() != normalized(store['state']):
            return False
        brand = canonical_name(store['name'])
        number = str(int(store['number']))
        if brand not in brands or refs(store['name']) != {number}:
            return False
        names = [row['Truckstop Name'] for row in station.rows]
        def same_brand(name):
            source_brand = pilot_source_brand(name) if isinstance(source, str) and PILOT_SOURCE.fullmatch(source) else canonical_source_name(name)
            if isinstance(source, str) and PILOT_SOURCE.fullmatch(source):
                source_brand = {'PILOT DEALER': 'PILOT', 'FLYING J DEALER': 'FLYING J'}.get(source_brand, source_brand)
                return source_brand == {'PILOT DEALER': 'PILOT', 'FLYING J DEALER': 'FLYING J'}.get(brand, brand)
            return source_brand == brand
        matching = [name for name in names if same_brand(name)]
        source_refs = set().union(*(refs(name) for name in names))
        if not matching or source_refs != {number} or not any(refs(name) == {number} for name in matching):
            return False
        if isinstance(source, str) and PILOT_SOURCE.fullmatch(source) and any(not same_brand(name) or refs(name) != {number} for name in names):
            return False
        if context.get('identity_only') is True:
            return all(same_brand(name) and refs(name) == {number} for name in names)
        if 'junction' in context and context['junction'] is None:
            return False
        if 'roads' in context and context['roads'] is None:
            return False
        return operator_address_match(station, store, context.get('junction'), state_boundary, context.get('roads'))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False

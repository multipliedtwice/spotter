import html
import re
from urllib.parse import parse_qsl, urlsplit

from planner.locations import STATE_NAMES
from planner.osm_evidence import canonical_name, normalized, refs, supported_street_address, valid_point

RACETRAC_SOURCE = 'https://www.racetrac.com/locations'
RUTTERS_SOURCE = 'https://www.rutters.com/stores/'
THORNTONS_SOURCE = 'https://www.mythorntons.com/locations/'
PUMP_PANTRY_SOURCE = 'https://pumpandpantry.com/wp-json/pump-pantry/v1/locations'
SUNSTOP_SOURCE = 'https://sunstopstores.com/wp-admin/admin-ajax.php?action=store_search'
TOOT_SOURCE = 'https://www.tootntotum.com/locations'
ROYAL_SOURCE = 'https://storelocator.royalfarms.com/api/stores'
SEVENFLEET_SOURCE = 'https://7fleetmcdiscountnetwork.com/'
TEXBEST_SOURCE = 'https://www.texbeststores.com/locations/'
YESWAY_NATIVE_SOURCE = 'https://yesway.com/wp-content/themes/yesway/locations/locations.json'
ASAP_SOURCE = 'https://asapenergyinc.com/locations/'
HUCKS_SOURCE = 'https://hucks.com/locations/'
JETFOOD_SOURCE = 'https://www.jetfoodstores.com/locations/'
GOOD2GO_SOURCE = 'https://good2gostores.com/locations/'
SPINX_SOURCE = 'https://www.myspinx.com/locations/'
PETES_SOURCE = 'https://petescorp.com/locations/'
DUCKTHRU_SOURCE = 'https://duckthru.com/'
KENTKWIK_SOURCE = 'https://kentkwik.com/locations-2/'
KENTKWIK_MAP = 'https://fortress.maptive.com/ver4/408701b11ce6c0adbf9cd6908c4613f5/156428'
PARKERS_SOURCE = 'https://parkerskitchen.com/locations/'
DANDY_SOURCE = 'https://www.godandy.com/store-locator/'
RACE_FIELDS = {'StoreNumber', 'StoreName', 'StoreAddress1', 'StoreAddress2', 'StoreCity', 'StoreState', 'StoreLatitude', 'StoreLongitude', 'Brand', 'StoreUrl'}
RUTTERS_FIELDS = {'post_title', 'store_meta'}
RUTTERS_META = {'store_number', 'address', 'city', 'state', 'latitude', 'longitude'}
THORNTONS_FIELDS = {'data-latitude', 'data-longitude', 'name', 'address', 'city', 'state'}
PUMP_FIELDS = {'id', 'store_name', 'post_title', 'store_title', 'title', 'address', 'post_code', 'location', 'permalink'}
PUMP_LOCATION_FIELDS = {'address', 'lat', 'lng', 'zoom', 'place_id', 'name', 'street_number', 'street_name', 'street_name_short', 'city', 'state', 'state_short', 'post_code', 'country', 'country_short'}
SUNSTOP_FIELDS = {'id', 'store', 'address', 'address2', 'city', 'state', 'zip', 'country', 'lat', 'lng', 'url', 'permalink'}
TOOT_FIELDS = {'title', 'address', 'data-latitude', 'data-longitude', 'source_url'}
ROYAL_FIELDS = {'storeNumber', 'address', 'coordinates'}
SEVENFLEET_FIELDS = {'network', 'brand', 'site_name', 'address', 'city', 'state', 'zip', 'marker_title', 'latitude', 'longitude', 'locator_url'}
TEXBEST_FIELDS = {'name', 'address', 'lat', 'lng', 'coming_soon'}
YESWAY_ACF_REQUIRED = {'business_name', 'internal_store_code', 'address_line_1', 'address_line_2', 'city', 'state', 'country', 'postal_code', 'latitude', 'longitude', 'amenities'}
YESWAY_ACF_OPTIONAL = {'coming_soon', 'fuel_card'}
ASAP_PIN_FIELDS = {'data-title', 'data-lat', 'data-lng', 'address'}
HUCKS_FIELDS = {'location_title', 'address_lines', 'map_record'}


def hucks_source_brand(name):
    text = re.sub(r'#\s*\d+[A-Z]?(?![A-Z0-9])', ' ', normalized(name)).replace("'", '').replace('’', '')
    text = ' '.join(re.findall(r'[A-Z0-9]+', text))
    return 'HUCKS' if text in ('HUCKS', 'HUCKS FOOD FUEL', 'HUCKS FOOD AND FUEL', 'HUCKS MARKET', 'HUCKS TRAVEL CENTER') else ''


def jetfood_source_brand(name):
    text = re.sub(r'#\s*\d+[A-Z]?(?![A-Z0-9])', ' ', normalized(name))
    return 'JET FOOD' if ''.join(re.findall(r'[A-Z0-9]+', text)) in ('JETFOODSTORE', 'JETFOODSTORES') else ''


def good2go_source_brand(name):
    text = re.sub(r'#\s*\d+[A-Z]?(?![A-Z0-9])', ' ', normalized(name))
    return 'GOOD 2 GO' if ''.join(re.findall(r'[A-Z0-9]+', text)) == 'GOOD2GO' else ''


def spinx_source_brand(name):
    return 'SPINX' if spinx_source_numbers(name) else ''


def spinx_source_numbers(name):
    text = re.sub(r'\s*\(DISCOUNT AVAILABLE\)\s*$', '', normalized(name))
    match = re.fullmatch(r'SPINX(?:\s*#\s*|\s+)(\d+)', text)
    return {str(int(match.group(1)))} if match and int(match.group(1)) > 0 else set()


def petes_source_brand(name):
    return 'PETES' if petes_source_numbers(name) else ''


def petes_source_numbers(name):
    text = normalized(name).replace("'", '').replace('’', '')
    match = re.fullmatch(r'PETES(?:\s*#\s*|\s+)(\d+)', text)
    return {str(int(match.group(1)))} if match and int(match.group(1)) > 0 else set()


def duckthru_source_brand(name):
    return 'DUCK THRU' if re.fullmatch(r'DUCK\s+THRU(?:\s+FOOD\s+STORE)?\s*#\s*\d+', normalized(name)) else ''


def dandy_source_brand(name):
    return 'DANDY' if re.fullmatch(r'DANDY(?:\s+MINI\s+MART)?\s*#\s*\d+', normalized(name)) else ''



def parkers_source_numbers(name):
    text = re.sub(r'\s*\(DISCOUNT AVAILABLE\)\s*$', '', normalized(name))
    match = re.fullmatch(r"PARKER(?:'|’)?S\s*#\s*(\d+)", text)
    return {str(int(match.group(1)))} if match and int(match.group(1)) > 0 else set()


def parkers_source_brand(name):
    return 'PARKERS' if parkers_source_numbers(name) else ''


def kentkwik_source_numbers(name):
    match = re.fullmatch(r'KENT\s+KWIK\s*#\s*(\d+)', normalized(name))
    return {str(int(match.group(1)))} if match and int(match.group(1)) > 0 else set()


def kentkwik_source_brand(name):
    return 'KENT KWIK' if kentkwik_source_numbers(name) else ''


def kentkwik_marker_number(label):
    match = re.fullmatch(r'Kent Kwik(?: Location)?(?:\s*#|\s+)(\d+)', label)
    return str(int(match.group(1))) if match and int(match.group(1)) > 0 else None


def kentkwik_marker_point(marker):
    if not isinstance(marker, list) or len(marker) != 5:
        return None
    coords = marker[1:3]
    if any(type(value) not in (int, float, str) or (isinstance(value, str) and not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value)) for value in coords):
        return None
    try:
        point = [float(value) for value in coords]
    except (ValueError, OverflowError):
        return None
    return point if valid_point(point) else None

def published_postal_address(value, require_country=False):
    if not isinstance(value, str):
        return None
    text = value.strip()
    country = re.search(r'(?:,\s*|\s+)(USA|United States(?: of America)?)$', text, re.I)
    if country:
        text = text[:country.start()].strip()
    elif require_country:
        return None
    if require_country and not re.search(r'\b\d{5}(?:-\d{4})?$', text):
        return None
    state = r'(GA|Georgia|TX|Texas)'
    city = r"([A-Za-z][A-Za-z .'-]*)"
    ending = state + r'(?:\s+\d{5}(?:-\d{4})?)?'
    patterns = [r'^([^,]+),\s*' + city + r',\s*' + ending + r'$',
                r'^(\d+\s+(?:U\.?S\.?\s*(?:Hwy|Highway)?|Interstate)\s*\d+\s*(?:[NSEW]\b)?)\s+' + city + r',?\s+' + ending + r'$']
    matches = []
    for suffix in re.finditer(r'\b(?:Street|St)\b', text, re.I):
        street = text[:suffix.end()].strip()
        rest = re.fullmatch(r'\s+' + city + r',\s*' + ending, text[suffix.end():], re.I)
        if rest and re.fullmatch(r"\d+\s+[A-Za-z0-9 .'-]+", street) and supported_street_address(street) and not re.search(r'\b(?:OR|AND|EXIT|MILE|MM)\b|[&@]', street, re.I):
            locality, region = (part.strip() for part in rest.groups())
            region = {'GEORGIA': 'GA', 'TEXAS': 'TX'}.get(region.upper(), region.upper())
            matches.append((street, locality, region))
    for pattern in patterns:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            street, locality, region = (part.strip() for part in match.groups())
            region = {'GEORGIA': 'GA', 'TEXAS': 'TX'}.get(region.upper(), region.upper())
            if supported_street_address(street) and not re.search(r'\b(?:OR|AND|EXIT|MILE|MM)\b|[&@]', street, re.I):
                matches.append((street, locality, region))
    return matches[0] if len(set(matches)) == 1 else None


def raw_operator_view(store):
    try:
        if not isinstance(store, dict) or set(store) != {'source', 'record'} or not isinstance(store['record'], dict):
            return None
        source, raw = store['source'], store['record']
        if source == RACETRAC_SOURCE:
            if set(raw) != RACE_FIELDS or type(raw['StoreNumber']) is not int or raw['StoreNumber'] <= 0 or raw['Brand'] not in ('RaceTrac', 'RaceWay'):
                return None
            if any(not isinstance(raw[k], str) or not raw[k].strip() for k in ('StoreName', 'StoreAddress1', 'StoreCity', 'StoreState', 'StoreUrl')) or (raw['StoreAddress2'] is not None and not isinstance(raw['StoreAddress2'], str)):
                return None
            state = STATE_NAMES.get(normalized(raw['StoreState']))
            url = re.fullmatch(r'/locations/([a-z0-9_-]+)/([a-z0-9_~=@()\-]+)/([a-z0-9_~=@()\-]+)/?', raw['StoreUrl'])
            if not state or not url or url.group(1) != raw['StoreState'].strip().lower().replace(' ', '-'):
                return None
            point = [raw['StoreLatitude'], raw['StoreLongitude']]
            view = {'number': str(raw['StoreNumber']), 'name': raw['Brand'], 'address': raw['StoreAddress1'], 'city': raw['StoreCity'], 'state': state, 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == RUTTERS_SOURCE:
            if set(raw) != RUTTERS_FIELDS or not isinstance(raw['post_title'], str) or not isinstance(raw['store_meta'], dict) or set(raw['store_meta']) != RUTTERS_META:
                return None
            meta = raw['store_meta']
            if any(not isinstance(meta[k], str) or not meta[k].strip() for k in RUTTERS_META) or not re.fullmatch(r'\d+', meta['store_number']) or int(meta['store_number']) <= 0:
                return None
            if canonical_name(raw['post_title']) != 'RUTTERS' or refs(raw['post_title']) != {str(int(meta['store_number']))}:
                return None
            if not re.fullmatch(r'[A-Z]{2}', meta['state']) or meta['state'] not in STATE_NAMES.values():
                return None
            point = [float(meta['latitude']), float(meta['longitude'])]
            view = {'number': meta['store_number'], 'name': raw['post_title'], 'address': meta['address'], 'city': meta['city'], 'state': meta['state'], 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == THORNTONS_SOURCE:
            if set(raw) != THORNTONS_FIELDS or any(not isinstance(raw[k], str) or not raw[k].strip() for k in THORNTONS_FIELDS):
                return None
            numbers = refs(raw['name'])
            if canonical_name(raw['name']) != 'THORNTONS' or len(numbers) != 1 or not re.fullmatch(r'[A-Z]{2}', raw['state']) or raw['state'] not in STATE_NAMES.values():
                return None
            point = [float(raw['data-latitude']), float(raw['data-longitude'])]
            view = {'number': next(iter(numbers)), 'name': raw['name'], 'address': raw['address'], 'city': raw['city'], 'state': raw['state'], 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == PUMP_PANTRY_SOURCE:
            if set(raw) != PUMP_FIELDS or type(raw['id']) is not int or raw['id'] <= 0 or not isinstance(raw['location'], dict):
                return None
            loc = raw['location']
            if set(loc) not in (PUMP_LOCATION_FIELDS, PUMP_LOCATION_FIELDS | {'city_short'}):
                return None
            if not isinstance(raw['store_title'], str) or any(not isinstance(raw[k], str) or not raw[k].strip() for k in PUMP_FIELDS - {'id', 'location', 'store_title'}):
                return None
            if any(not isinstance(loc[k], str) or not loc[k].strip() for k in set(loc) - {'lat', 'lng', 'zoom'}) or type(loc['zoom']) is not int:
                return None
            names = [html.unescape(raw[k]) for k in ('store_name', 'post_title', 'title')]
            numbers = [refs(name) for name in names]
            if any(canonical_name(name) != 'PUMP PANTRY' for name in names) or len(numbers[0]) != 1 or any(value != numbers[0] for value in numbers):
                return None
            number = next(iter(numbers[0]))
            if not re.fullmatch(r'\d+', number) or int(number) <= 0 or raw['permalink'] != f'https://pumpandpantry.com/store/pump-pantry-{number}/':
                return None
            if loc['country_short'] != 'US' or STATE_NAMES.get(normalized(loc['state'])) != loc['state_short'] or raw['address'] != loc['address'] or raw['post_code'] != loc['post_code']:
                return None
            point = [loc['lat'], loc['lng']]
            view = {'number': number, 'name': names[0], 'address': loc['name'], 'city': loc['city'], 'state': loc['state_short'], 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == SUNSTOP_SOURCE:
            if set(raw) != SUNSTOP_FIELDS or type(raw['id']) is not int or raw['id'] <= 0 or any(not isinstance(raw[k], str) for k in SUNSTOP_FIELDS - {'id'}):
                return None
            if any(not raw[k].strip() for k in ('store', 'address', 'city', 'state', 'zip', 'country', 'lat', 'lng', 'permalink')) or raw['country'] != 'United States':
                return None
            numbers = refs(raw['store'])
            if canonical_name(raw['store']) != 'SUNSTOP' or len(numbers) != 1 or not re.fullmatch(r'https://sunstopstores\.com/stores/sunstop-' + re.escape(next(iter(numbers))) + r'(?:-\d+)?/', raw['permalink']):
                return None
            if raw['state'] not in STATE_NAMES.values():
                return None
            point = [float(raw['lat']), float(raw['lng'])]
            view = {'number': next(iter(numbers)), 'name': raw['store'], 'address': raw['address'], 'city': raw['city'], 'state': raw['state'], 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == TOOT_SOURCE:
            if set(raw) != TOOT_FIELDS or any(not isinstance(raw[k], str) or not raw[k].strip() for k in TOOT_FIELDS - {'address'}) or not isinstance(raw['address'], list) or len(raw['address']) != 2 or any(not isinstance(line, str) or not line.strip() for line in raw['address']):
                return None
            match = re.fullmatch(r'(.+?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)', raw['address'][1].strip())
            numbers = refs(raw['title'])
            raw_numbers = re.findall(r'#\s*(\d+)(?![A-Z0-9])', normalized(raw['title']))
            if not match or match.group(2) not in STATE_NAMES.values() or canonical_name(raw['title']) != 'TOOTN TOTUM' or len(numbers) != 1 or len(raw_numbers) != 1:
                return None
            number = next(iter(numbers))
            if raw['source_url'] != f'https://www.tootntotum.com/locations/tootntotum-{raw_numbers[0]}':
                return None
            point = [float(raw['data-latitude']), float(raw['data-longitude'])]
            view = {'number': number, 'name': raw['title'], 'address': raw['address'][0], 'city': match.group(1), 'state': match.group(2), 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == ROYAL_SOURCE:
            if set(raw) != ROYAL_FIELDS or not isinstance(raw['storeNumber'], str) or not re.fullmatch(r'\d+', raw['storeNumber']) or int(raw['storeNumber']) <= 0:
                return None
            address, coordinates = raw['address'], raw['coordinates']
            if not isinstance(address, dict) or set(address) != {'line1', 'line2', 'city', 'state', 'zip', 'full'} or any(not isinstance(value, str) for value in address.values()) or any(not address[k].strip() for k in ('line1', 'city', 'state', 'zip', 'full')):
                return None
            if address['state'] not in STATE_NAMES.values() or not isinstance(coordinates, dict) or set(coordinates) != {'lat', 'lng'}:
                return None
            point = [coordinates['lat'], coordinates['lng']]
            view = {'number': raw['storeNumber'], 'name': 'Royal Farms', 'address': address['line1'], 'city': address['city'], 'state': address['state'], 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == SEVENFLEET_SOURCE:
            if set(raw) != SEVENFLEET_FIELDS or any(not isinstance(raw[k], str) for k in SEVENFLEET_FIELDS):
                return None
            if any(not raw[k].strip() for k in SEVENFLEET_FIELDS - {'brand'}) or raw['network'] != '7FLEET' or raw['locator_url'] != SEVENFLEET_SOURCE:
                return None
            match = re.fullmatch(r'(7-Eleven|Stripes|Speedway)-(\d+)', raw['site_name'])
            if not match or raw['marker_title'] != raw['site_name'] or int(match.group(2)) <= 0 or raw['state'] not in STATE_NAMES.values() or not re.fullmatch(r'\d{5}(?:-\d{4})?', raw['zip']):
                return None
            point = [float(raw['latitude']), float(raw['longitude'])]
            view = {'number': match.group(2), 'name': match.group(1), 'address': raw['address'], 'city': raw['city'], 'state': raw['state'], 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == TEXBEST_SOURCE:
            if set(raw) != TEXBEST_FIELDS or raw['coming_soon'] is not False or not isinstance(raw['name'], str) or not isinstance(raw['address'], str):
                return None
            address = re.sub(r'^Tex Best Travel Center,\s*', '', raw['address'].strip())
            match = published_postal_address(address, require_country=True)
            number = re.fullmatch(r'Tex-Best\s*#\s*(\d+)', raw['name'], re.I)
            if not match or match[2] != 'TX' or not number or int(number.group(1)) <= 0:
                return None
            point = [raw['lat'], raw['lng']]
            view = {'number': number.group(1), 'name': raw['name'], 'address': match[0], 'city': match[1], 'state': 'TX', 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == JETFOOD_SOURCE:
            if set(raw) != {'location_list_record', 'map_marker'} or not isinstance(raw['location_list_record'], dict) or not isinstance(raw['map_marker'], dict):
                return None
            listing, marker = raw['location_list_record'], raw['map_marker']
            if set(listing) != {'data-loc-id', 'published_address'} or set(marker) != {'data-loc-id', 'data-lat', 'data-lng'} or any(not isinstance(v, str) or not v.strip() for v in (*listing.values(), *marker.values())) or not re.fullmatch(r'\d+', listing['data-loc-id']) or listing['data-loc-id'] != marker['data-loc-id']:
                return None
            label = re.fullmatch(r'Store\s*#\s*(\d+):\s*(.+)', listing['published_address'], re.I)
            address = published_postal_address(label.group(2)) if label else None
            if not label or int(label.group(1)) <= 0 or not address or address[2] != 'GA':
                return None
            point = [float(marker['data-lat']), float(marker['data-lng'])]
            view = {'number': label.group(1), 'name': 'Jet Food', 'address': address[0], 'city': address[1], 'state': address[2], 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == YESWAY_NATIVE_SOURCE:
            if set(raw) != {'id', 'store', 'acf'} or type(raw['id']) is not int or raw['id'] <= 0 or not isinstance(raw['store'], str) or not isinstance(raw['acf'], dict):
                return None
            acf = raw['acf']
            if not YESWAY_ACF_REQUIRED <= set(acf) or set(acf) - YESWAY_ACF_REQUIRED - YESWAY_ACF_OPTIONAL:
                return None
            string_fields = YESWAY_ACF_REQUIRED - {'amenities'}
            if any(not isinstance(acf[k], str) for k in string_fields) or any(not acf[k].strip() for k in ('business_name', 'address_line_1', 'city', 'state', 'country', 'latitude', 'longitude')):
                return None
            status, cards = acf.get('coming_soon'), acf.get('fuel_card')
            if type(status) not in (bool, type(None)) or status is True or (cards is not None and (not isinstance(cards, list) or not all(isinstance(item, str) for item in cards))):
                return None
            if not isinstance(acf['amenities'], list) or not all(isinstance(item, str) for item in acf['amenities']):
                return None
            label = html.unescape(raw['store'])
            match = re.fullmatch(r"(Allsup['’]s|Yesway)\s+Store\s*#\s*(\d+)", label, re.I)
            if not match or int(match.group(2)) <= 0 or canonical_name(match.group(1)) != canonical_name(acf['business_name']):
                return None
            if acf['country'] != 'US' or acf['state'] not in STATE_NAMES.values():
                return None
            point = [float(acf['latitude']), float(acf['longitude'])]
            view = {'number': match.group(2), 'name': acf['business_name'], 'address': acf['address_line_1'], 'city': acf['city'], 'state': acf['state'], 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == ASAP_SOURCE:
            if set(raw) not in ({'locator_pin'}, {'locator_pin', 'detail_card'}) or not isinstance(raw['locator_pin'], dict) or set(raw['locator_pin']) not in (ASAP_PIN_FIELDS, ASAP_PIN_FIELDS | {'address_lines'}, ASAP_PIN_FIELDS | {'address_fragments'}):
                return None
            pin = raw['locator_pin']
            if any(not isinstance(pin[k], str) for k in ASAP_PIN_FIELDS):
                return None
            title = re.fullmatch(r'(ASAP General Store)\s+(\d+)', pin['data-title'], re.I)
            if not title or int(title.group(2)) <= 0:
                return None
            card = raw.get('detail_card')
            lines = pin.get('address_lines')
            if 'address_fragments' in pin:
                fragments = pin['address_fragments']
                if not isinstance(fragments, list) or len(fragments) != 4 or any(not isinstance(item, dict) or set(item) != {'tag', 'text'} or not isinstance(item['text'], str) for item in fragments) or [item['tag'] for item in fragments] != ['span', 'text', 'span', 'text']:
                    return None
                state_zip = re.fullmatch(r',\s*(OK)\s+\d{5}(?:-\d{4})?', fragments[2]['text'].strip(), re.I)
                if not state_zip or not re.fullmatch(r',\s*USA', fragments[3]['text'].strip(), re.I):
                    return None
                street, city, state = fragments[0]['text'].strip(), fragments[1]['text'].strip(), state_zip.group(1).upper()
                flattened = ''.join(item['text'] for item in fragments)
                if re.sub(r'[^A-Z0-9]', '', normalized(flattened)) != re.sub(r'[^A-Z0-9]', '', normalized(pin['address'])) or card is not None:
                    return None
            elif lines is not None or not pin['address'].strip():
                if lines is None:
                    if not isinstance(card, dict):
                        return None
                    lines = card.get('address_lines')
                if not isinstance(lines, list) or len(lines) != 2 or any(not isinstance(line, str) or not line.strip() for line in lines):
                    return None
                if pin['address'].strip() and re.sub(r'[^A-Z0-9]', '', normalized(' '.join(lines))) != re.sub(r'[^A-Z0-9]', '', normalized(pin['address'])):
                    return None
                if card is not None:
                    if not isinstance(card, dict) or set(card) != {'href', 'title', 'address_lines'} or card['href'] != '/store' + title.group(2) or card['title'] != pin['data-title'] or card['address_lines'] != lines:
                        return None
                elif not pin['address'].strip():
                    return None
                match = re.fullmatch(r'([^,]+),\s*(OK)\s+\d{5}(?:-\d{4})?', lines[1].strip(), re.I)
                if not match:
                    return None
                street, city, state = lines[0].strip(), match.group(1).strip(), match.group(2).upper()
            else:
                if card is not None:
                    return None
                match = re.fullmatch(r'([^,]+),\s*([^,]+),\s*(OK)\s+\d{5}(?:-\d{4})?(?:,\s*USA)?', pin['address'].strip(), re.I)
                if not match:
                    return None
                street, city, state = match.group(1).strip(), match.group(2).strip(), match.group(3).upper()
            if not supported_street_address(street) or not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", city):
                return None
            point = [float(pin['data-lat']), float(pin['data-lng'])]
            view = {'number': title.group(2), 'name': title.group(1), 'address': street, 'city': city, 'state': state, 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == KENTKWIK_SOURCE:
            if set(raw) != {'marker', 'popup'} or not isinstance(raw['marker'], list) or len(raw['marker']) != 5 or not isinstance(raw['popup'], dict) or set(raw['popup']) != {'request', 'response_fields'}:
                return None
            marker, popup = raw['marker'], raw['popup']
            number = kentkwik_marker_number(marker[3]) if isinstance(marker[3], str) else None
            point = kentkwik_marker_point(marker)
            if type(marker[0]) is not int or marker[0] < 0 or type(marker[4]) is not int or point is None or not number or '#' not in marker[3]:
                return None
            request, response = popup['request'], popup['response_fields']
            if not isinstance(request, dict) or set(request) != {'is_grouped', 'map_id', 'data_id', 'id', 'lt', 'ln'} or any(not isinstance(v, str) for v in request.values()):
                return None
            if (request['is_grouped'], request['map_id'], request['data_id'], request['id']) != ('0', '182317', '182459', str(marker[0])):
                return None
            if any(not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', request[k]) for k in ('lt', 'ln')) or [float(request['lt']), float(request['ln'])] != point:
                return None
            if not isinstance(response, dict) or set(response) != {'response', 'description.html.heading', 'description.html.address_block'} or response['response'] is not True or any(not isinstance(response[k], str) for k in ('description.html.heading', 'description.html.address_block')):
                return None
            heading = re.fullmatch(r"<h1 class='(?:small )?title_header'>([^<>]+)</h1>", response['description.html.heading'])
            if not heading or html.unescape(heading.group(1)) != marker[3]:
                return None
            block = re.fullmatch(r'<p class="p_description" style="z-index:1;">([^<>]+)<br />\s*([^<>]+)<br />\s*(?:(USA|US|United States)\s*<br />\s*)?</p>', response['description.html.address_block'])
            if not block:
                return None
            street, locality = html.unescape(block.group(1)).strip(), html.unescape(block.group(2)).strip()
            place = re.fullmatch(r"([A-Za-z][A-Za-z .'-]*),\s*([A-Z]{2})\s+\d{5}(?:-\d{4})?", locality)
            if not place or place.group(2) not in STATE_NAMES.values() or not supported_street_address(street):
                return None
            view = {'number': number, 'name': 'Kent Kwik', 'address': street, 'city': place.group(1), 'state': place.group(2), 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == PARKERS_SOURCE:
            fields = {'publisher_label', 'detail_page_excerpt', 'page_url', 'directions_href', 'point'}
            if set(raw) != fields or any(not isinstance(raw[k], str) or not raw[k].strip() for k in fields - {'point'}):
                return None
            heading = re.fullmatch(r"(.+ Parker's) \^\{#(\d+)\}", raw['publisher_label'])
            parts = [part.strip() for part in raw['detail_page_excerpt'].split('|')]
            if not heading or len(parts) != 4 or not re.fullmatch(r'#\d+', parts[0]) or parts[0][1:] != heading.group(2) or parts[1] != heading.group(1) or int(heading.group(2)) <= 0:
                return None
            if raw['page_url'] != f"https://parkerskitchen.com/locations/parkers-{heading.group(2)}/":
                return None
            address = re.fullmatch(r"([A-Za-z][A-Za-z .'-]*),\s*(Georgia|South Carolina)\s+(\d{5})", parts[3])
            if not address or not supported_street_address(parts[2]):
                return None
            url = urlsplit(raw['directions_href'])
            if (url.scheme, url.netloc, url.path, url.fragment) != ('https', 'maps.google.com', '/', ''):
                return None
            query = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
            if len(query) not in (1, 2) or len(dict(query)) != len(query) or set(dict(query)) not in ({'daddr'}, {'daddr', 'saddr'}) or ('saddr' in dict(query) and dict(query)['saddr'] != 'Current Location'):
                return None
            coords = re.fullmatch(r'([+-]?\d+(?:\.\d+)?) ([+-]?\d+(?:\.\d+)?)', dict(query)['daddr'])
            location = raw['point']
            if not coords or not isinstance(location, dict) or set(location) != {'latitude', 'longitude'} or any(type(location[k]) not in (int, float) for k in location):
                return None
            point = [location['latitude'], location['longitude']]
            if point != [float(coords.group(1)), float(coords.group(2))]:
                return None
            view = {'number': heading.group(2), 'name': "Parker's", 'address': parts[2], 'city': address.group(1), 'state': {'Georgia': 'GA', 'South Carolina': 'SC'}[address.group(2)], 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source in (DUCKTHRU_SOURCE, DANDY_SOURCE):
            duck = source == DUCKTHRU_SOURCE
            if duck and set(raw) != {'source_page_uri', 'published_page_title', 'location'}:
                return None
            loc = raw['location'] if duck else raw
            fields = {'id', 'store', 'address', 'address2', 'city', 'state', 'zip', 'country', 'lat', 'lng'} | ({'mapShortcode'} if duck else {'url'})
            if not isinstance(loc, dict) or set(loc) != fields or type(loc['id']) is not int or loc['id'] <= 0 or any(not isinstance(loc[k], str) for k in fields - {'id', 'mapShortcode'}):
                return None
            if any(not loc[k].strip() for k in ('store', 'address', 'city', 'state', 'zip', 'country', 'lat', 'lng')) or loc['country'] not in ('United States', 'US', 'USA') or loc['state'] not in (('NC', 'VA') if duck else ('NY', 'PA')) or not re.fullmatch(r'\d{5}(?:-\d{4})?', loc['zip']) or not supported_street_address(loc['address']):
                return None
            label = html.unescape(loc['store'])
            title = re.fullmatch(r'Duck Thru\s*#\s*(\d+)', label, re.I) if duck else re.fullmatch(r'.+\s+[–—-]\s+Dandy\s+(\d+)', label, re.I)
            if not title or int(title.group(1)) <= 0:
                return None
            number = title.group(1)
            if duck:
                if loc['mapShortcode'] is not True or not isinstance(raw['published_page_title'], str) or raw['source_page_uri'] != f'https://duckthru.com/stores/duck-thru-{int(number)}/' or not re.match(r'^Duck Thru\s*#\s*' + re.escape(number) + r'\b', raw['published_page_title'], re.I):
                    return None
            elif not re.fullmatch(r'https://www\.godandy\.com/[a-z0-9-]+/?', loc['url']):
                return None
            point = [float(loc['lat']), float(loc['lng'])]
            view = {'number': number, 'name': 'Duck Thru' if duck else 'Dandy', 'address': loc['address'], 'city': loc['city'], 'state': loc['state'], 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == PETES_SOURCE:
            fields = {'marker_id', 'marker_title', 'latitude', 'longitude', 'popup_url', 'popup_title', 'postal_address', 'source_listing', 'popup_endpoint', 'popup_map'}
            if set(raw) != fields or any(not isinstance(raw[k], str) or not raw[k].strip() for k in fields - {'postal_address'}) or not isinstance(raw['postal_address'], dict):
                return None
            address = raw['postal_address']
            if set(address) != {'streetAddress', 'addressLocality', 'addressRegion', 'postalCode', 'addressCountry'} or any(not isinstance(v, str) or not v.strip() for v in address.values()):
                return None
            title = html.unescape(raw['marker_title']).replace('’', "'")
            popup = html.unescape(raw['popup_title']).replace('’', "'")
            match = re.fullmatch(r"PETES (\d+)( SIMPLE SIMON'S & BROASTER CHICKEN)?", title)
            if not match or title != popup or int(match.group(1)) <= 0 or not re.fullmatch(r'\d+', raw['marker_id']) or int(raw['marker_id']) <= 0:
                return None
            slug = f"petes-{match.group(1)}" + ('-simple-simons-broaster-chicken' if match.group(2) else '')
            if raw['popup_url'] != f'https://petescorp.com/places/{slug}/' or raw['popup_endpoint'] != f"https://petescorp.com/wp-json/geodir/v2/markers/{raw['marker_id']}" or raw['popup_map'] != 'osm' or raw['source_listing'] != PETES_SOURCE:
                return None
            if address['addressRegion'] != 'Kansas' or address['addressCountry'] != 'United States' or not re.fullmatch(r'\d{5}(?:-\d{4})?', address['postalCode']) or not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", address['addressLocality']) or not supported_street_address(address['streetAddress']):
                return None
            point = [float(raw['latitude']), float(raw['longitude'])]
            view = {'number': match.group(1), 'name': 'Petes', 'address': address['streetAddress'], 'city': address['addressLocality'], 'state': 'KS', 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == SPINX_SOURCE:
            if set(raw) != {'data-post-id', 'title', 'address', 'map_record'} or any(not isinstance(raw[k], str) or not raw[k].strip() for k in ('data-post-id', 'title', 'address')):
                return None
            title = re.fullmatch(r'Spinx\s*#\s*(\d+)\s*›', raw['title'], re.I)
            address = re.fullmatch(r"([^,]+),\s*([A-Za-z][A-Za-z .'-]*),\s*(SC)\s+\d{5}(?:-\d{4})?", raw['address'].strip(), re.I)
            marker = raw['map_record']
            if not title or int(title.group(1)) <= 0 or not address or not supported_street_address(address.group(1)) or not re.fullmatch(r'\d+', raw['data-post-id']):
                return None
            if not isinstance(marker, dict) or set(marker) != {'id', 'latLang'} or type(marker['id']) is not int or marker['id'] <= 0 or str(marker['id']) != raw['data-post-id'] or not isinstance(marker['latLang'], dict) or set(marker['latLang']) != {'lat', 'lng'}:
                return None
            point = [marker['latLang']['lat'], marker['latLang']['lng']]
            view = {'number': title.group(1), 'name': 'Spinx', 'address': address.group(1).strip(), 'city': address.group(2).strip(), 'state': 'SC', 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == GOOD2GO_SOURCE:
            if set(raw) != {'infoTitle', 'position', 'infoAddress', 'coordinates'} or any(not isinstance(v, str) or not v.strip() for v in raw.values()):
                return None
            title = re.fullmatch(r'Good\s*2\s*Go\s*#\s*(\d+)', raw['infoTitle'], re.I)
            address = re.fullmatch(r"([^,]+),\s*([A-Za-z][A-Za-z .'-]*),\s*(ID|WY|UT|CO)\s+\d{5}(?:-\d{4})?", raw['position'].strip(), re.I)
            coordinates = re.fullmatch(r'\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*', raw['coordinates'])
            if not title or int(title.group(1)) <= 0 or not address or not coordinates or normalized(raw['position']) != normalized(raw['infoAddress']) or not supported_street_address(address.group(1)):
                return None
            point = [float(coordinates.group(1)), float(coordinates.group(2))]
            view = {'number': title.group(1), 'name': 'Good 2 Go', 'address': address.group(1).strip(), 'city': address.group(2).strip(), 'state': address.group(3).upper(), 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        elif source == HUCKS_SOURCE:
            if set(raw) != HUCKS_FIELDS or not isinstance(raw['location_title'], str) or not isinstance(raw['address_lines'], list) or len(raw['address_lines']) != 2 or any(not isinstance(line, str) or not line.strip() for line in raw['address_lines']):
                return None
            title = re.fullmatch(r'Location\s*#\s*(\d+)', raw['location_title'], re.I)
            place = re.fullmatch(r'([^,]+),\s*([A-Z]{2})\s+\d{5}(?:-\d{4})?', raw['address_lines'][1].strip())
            marker = raw['map_record']
            if not title or int(title.group(1)) <= 0 or not place or place.group(2) not in STATE_NAMES.values() or not supported_street_address(raw['address_lines'][0]):
                return None
            if not isinstance(marker, dict) or set(marker) != {'data-id', 'data-latitude', 'data-longitude'} or any(not isinstance(value, str) or not value.strip() for value in marker.values()):
                return None
            point = [float(marker['data-latitude']), float(marker['data-longitude'])]
            view = {'number': title.group(1), 'name': "Huck's", 'address': raw['address_lines'][0], 'city': place.group(1).strip(), 'state': place.group(2), 'latitude': point[0], 'longitude': point[1], 'source': source, 'highway': ''}
        else:
            return None
        return view if valid_point(point) else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None




def validated_kentkwik_records(asset):
    if not isinstance(asset, dict) or not {'source', 'map', 'marker_request', 'markers', 'stores'} <= set(asset) or set(asset) - {'source', 'map', 'marker_request', 'popup_request', 'markers', 'stores'} or asset['source'] != KENTKWIK_SOURCE or asset['map'] != KENTKWIK_MAP or not isinstance(asset['marker_request'], dict) or not isinstance(asset['markers'], list) or not isinstance(asset['stores'], list):
        raise ValueError('Invalid Kent Kwik catalog')
    markers = asset['markers']
    if any(not isinstance(m, list) or len(m) != 5 or type(m[0]) is not int or m[0] < 0 or kentkwik_marker_point(m) is None or not isinstance(m[3], str) or not m[3].strip() or type(m[4]) is not int for m in markers) or len({m[0] for m in markers}) != len(markers):
        raise ValueError('Invalid Kent Kwik markers')
    kent = [m for m in markers if re.match(r'^Kent Kwik(?:\b|$)', m[3])]
    numbers = [kentkwik_marker_number(m[3]) for m in kent]
    points = [tuple(kentkwik_marker_point(m)) for m in kent]
    records = asset['stores']
    if any(not isinstance(record, dict) or record.get('marker') not in kent for record in records):
        raise ValueError('Unbound Kent Kwik record')
    record_markers = [record['marker'][0] for record in records]
    views = [raw_operator_view({'source': KENTKWIK_SOURCE, 'record': record}) for record in records]
    return [record for record, view in zip(records, views) if view is not None and record_markers.count(record['marker'][0]) == 1 and numbers.count(view['number']) == 1 and points.count((view['latitude'], view['longitude'])) == 1]

def validated_parkers_records(asset):
    if not isinstance(asset, dict) or set(asset) - {'source', 'stores', 'field_notes'} or asset.get('source') != PARKERS_SOURCE or not isinstance(asset.get('stores'), list):
        raise ValueError('Invalid Parker catalog')
    records = asset['stores']
    views = [raw_operator_view({'source': PARKERS_SOURCE, 'record': record}) for record in records]
    if any(view is None for view in views):
        raise ValueError('Invalid Parker record')
    numbers = [int(view['number']) for view in views]
    points = [(view['latitude'], view['longitude']) for view in views]
    if len(set(numbers)) != len(numbers) or len(set(points)) != len(points):
        raise ValueError('Duplicate Parker record')
    return records

def raw_operator_key(store):
    view = raw_operator_view(store)
    if view and store['source'] == SEVENFLEET_SOURCE:
        return ('7FLEET', str(int(view['number'])))
    return (canonical_name(view['name']), str(int(view['number']))) if view else None

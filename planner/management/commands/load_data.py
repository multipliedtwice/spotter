import csv
import json
import re
from collections import defaultdict
from statistics import median
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from planner.models import City, Station
from planner.core import in_us, load_boundary
from planner.road import road_marker_keys
from django.conf import settings

STATES = set('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split())

def norm(value):
    return re.sub(r'\s+', ' ', value.strip()).upper()

def station_match(source_names, source_address, matched_name, matched_address):
    name = norm(matched_name).replace("'", '').replace('’', '')
    address = norm(matched_address)
    if not name or not address:
        return False
    def numbers(value):
        return set(re.findall(r'(?<![A-Z0-9])\d+[A-Z]?(?![A-Z0-9])', value))
    matched_numbers = numbers(name)
    generic = {'TRAVEL', 'CENTER', 'CENTRE', 'TRUCK', 'STOP', 'FUEL', 'GAS', 'STATION', 'THE', 'AND', 'INC'}
    def words(value):
        return {word for word in re.findall(r'[A-Z]+', value) if len(word) >= 3 and word not in generic}
    brands = {'PILOT', 'LOVE', 'LOVES', 'KWIK', 'TRIP', 'TRAVELCENTERS', 'SPEEDWAY', 'FLYING', 'SHELL', 'MOBIL', 'EXXON', 'CHEVRON', 'MARATHON'}
    names_match = any((normalized == name and len(words(name) - brands) >= 2) or bool(numbers(normalized) & matched_numbers and words(normalized) & words(name)) for normalized in (norm(source).replace("'", "").replace("’", "") for source in source_names))
    source_keys, matched_keys = road_marker_keys(source_address), road_marker_keys(address)
    marker_match = bool((source_keys or set()) & (matched_keys or set()))
    address_match = source_keys is not None and matched_keys is not None and len(source_address) >= 6 and source_address == address
    return names_match and (marker_match or address_match)

GOVERNMENT_SUFFIX = re.compile(r'\s+(?:metropolitan government|metro government|unified government|consolidated government|urban county)$')
PLAIN_SUFFIX = re.compile(r'\s+(?:city and|city|corporation)$')

def alias_name(name):
    name = name.strip()
    if GOVERNMENT_SUFFIX.search(name):
        return re.split(r'[-/,]', GOVERNMENT_SUFFIX.sub('', name))[0].strip()
    return PLAIN_SUFFIX.sub('', name).strip()

def gazetteer_aliases(rows):
    taken = {(norm(row['name']), norm(row['state'])) for row in rows}
    aliases = []
    for row in rows:
        alias = alias_name(row['name'])
        key = (norm(alias), norm(row['state']))
        if alias and key not in taken:
            taken.add(key)
            aliases.append({**row, 'name': alias})
    return aliases

class Command(BaseCommand):
    help = 'Import source stations or verified evidence or local gazetteer.'

    def add_arguments(self, parser):
        parser.add_argument('kind', choices=['stations', 'evidence', 'gazetteer'])
        parser.add_argument('path')

    @transaction.atomic
    def handle(self, kind, path, **options):
        with open(path, newline='', encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream))
        if kind == 'stations':
            groups = defaultdict(list)
            ids = defaultdict(set)
            for row in rows:
                state = norm(row['State'])
                if state not in STATES:
                    continue
                key = (row['OPIS Truckstop ID'].strip(), norm(row['Address']), norm(row['City']), state)
                groups[key].append(row)
                ids[key[0]].add(key[1:])
            Station.objects.all().delete()
            objects = []
            for (source_id, address, city, state), source in groups.items():
                unique = {json.dumps(row, sort_keys=True): row for row in source}
                prices = [float(row['Retail Price']) for row in unique.values()]
                objects.append(Station(source_id=source_id, name=source[0]['Truckstop Name'].strip(), address=address, city=city, state=state, rows=source, price=median(prices), price_min=min(prices), price_max=max(prices)))
            Station.objects.bulk_create(objects)
            self.stdout.write(f'Imported {len(objects)} station groups; {sum(len(v) > 1 for v in ids.values())} IDs have conflicting locations.')
        elif kind == 'gazetteer':
            rows = rows + gazetteer_aliases(rows)
            City.objects.all().delete()
            City.objects.bulk_create([City(name=r['name'].strip(), state=norm(r['state']), latitude=float(r['latitude']), longitude=float(r['longitude'])) for r in rows])
            self.stdout.write(f'Imported {len(rows)} cities.')
        else:
            try:
                boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
                if boundary.get('type') != 'FeatureCollection':
                    raise ValueError('State features required')
                states = {}
                for feature in boundary['features']:
                    properties = feature.get('properties') if isinstance(feature, dict) and feature.get('type') == 'Feature' else None
                    state = properties.get('STUSPS') if isinstance(properties, dict) else None
                    if not isinstance(state, str) or state not in STATES or state in states:
                        raise ValueError('Invalid state feature')
                    states[state] = feature
                required = set(Station.objects.values_list('state', flat=True).distinct())
                if not required <= states.keys():
                    raise ValueError('Missing state feature')
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                raise CommandError('Valid state boundary features required for evidence import.') from exc
            from planner.osm_evidence import identity_tags, matched_values, valid_context
            city_points = defaultdict(list)
            for city in City.objects.all():
                city_points[(norm(city.name), norm(city.state))].append([city.latitude, city.longitude])
            coordinates = defaultdict(set)
            for row in rows:
                try:
                    point = (float(row['latitude']), float(row['longitude']))
                except (ValueError, TypeError, KeyError):
                    point = (str(row.get('latitude', '')).strip(), str(row.get('longitude', '')).strip())
                coordinates[(row['station_id'].strip(), norm(row['address']), norm(row['city']), norm(row['state']))].add(point)
            conflicts = sorted(key for key, points in coordinates.items() if len(points) > 1)
            if conflicts:
                raise CommandError('Conflicting evidence coordinates for station groups: ' + '; '.join('|'.join(key) for key in conflicts))
            Station.objects.update(latitude=None, longitude=None, evidence={})
            accepted = 0
            for row in rows:
                matches = Station.objects.filter(source_id=row['station_id'].strip(), address=norm(row['address']), city=norm(row['city']), state=norm(row['state']))
                station = matches.first() if matches.count() == 1 else None
                names = {norm(r['Truckstop Name']) for r in station.rows} if station else set()
                if not station or not row['source'].strip():
                    continue
                try:
                    lat, lon = float(row['latitude']), float(row['longitude'])
                except (ValueError, TypeError, KeyError):
                    continue
                osm_text = row.get('osm_evidence', '').strip()
                if osm_text:
                    try:
                        context = json.loads(osm_text)
                        source = f"https://www.openstreetmap.org/{context['type']}/{context['id']}"
                        if row['source'] != source or not valid_context(station, context, [lat, lon], states[station.state], city_points[(norm(station.city), norm(station.state))]):
                            continue
                    except (ValueError, KeyError, TypeError):
                        continue
                elif not station_match(names, station.address, row['matched_name'], row['matched_address']):
                    continue
                if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not in_us([lat, lon], states[station.state]):
                    continue
                station.latitude, station.longitude = lat, lon
                station.evidence = {'matched_name': row['matched_name'], 'matched_address': row['matched_address'], 'source': row['source'], **{field: row[field] for field in ('source_row_ids', 'place_id', 'datasource_name', 'datasource_license', 'datasource_attribution', 'datasource_url') if row.get(field)}}
                if osm_text:
                    station.evidence['matched_name'], station.evidence['matched_address'] = matched_values(identity_tags(context))
                    station.evidence.update({'place_id': str(context['id']), 'datasource_name': 'OpenStreetMap', 'datasource_license': 'ODbL', 'datasource_attribution': 'OpenStreetMap contributors', 'datasource_url': 'https://www.openstreetmap.org/copyright', 'osm_evidence': context})
                station.save(update_fields=['latitude', 'longitude', 'evidence'])
                accepted += 1
            self.stdout.write(f'Accepted {accepted} evidence records of {len(rows)}.')

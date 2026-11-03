import csv
import hashlib
import json
import math
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from planner.core import in_us, load_boundary
from planner.management.commands.load_data import norm, station_match
from planner.models import Station
from planner.evidence import COLUMNS

ENDPOINT = 'https://api.geoapify.com/v1/geocode/search'
FIELDS = ('name', 'address_line1', 'street', 'housenumber', 'formatted', 'city', 'state_code', 'country_code', 'lat', 'lon', 'place_id', 'result_type', 'ref')


def safe_results(response, secret):
    if not isinstance(response, dict) or not isinstance(response.get('results'), list):
        raise CommandError('Geoapify returned an invalid response.')
    results = []
    for item in response['results']:
        if not isinstance(item, dict):
            continue
        entry = {field: item[field] for field in FIELDS if isinstance(item.get(field), (str, int, float)) and not isinstance(item.get(field), bool)}
        other = item.get('other_names')
        if isinstance(other, dict) and isinstance(other.get('ref'), (str, int)) and not isinstance(other.get('ref'), bool):
            entry['other_names'] = {'ref': str(other['ref'])}
        datasource = item.get('datasource')
        if isinstance(datasource, dict):
            allowed = ('sourcename', 'sourceName', 'license', 'attribution')
            entry['datasource'] = {k: datasource[k] for k in allowed if isinstance(datasource.get(k), str)}
            for field in ('url', 'sourceURL'):
                if isinstance(datasource.get(field), str):
                    parsed = urllib.parse.urlsplit(datasource[field])
                    if parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.username and not parsed.password:
                        entry['datasource'][field] = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
        if secret and secret in json.dumps(entry):
            raise CommandError('Geoapify response could not be stored safely.')
        results.append(entry)
    return results

def source_query(station, with_address=True):
    parts = (station.name, station.address, station.city, station.state, 'USA') if with_address else (station.name, station.city, station.state, 'USA')
    text = ', '.join(parts)
    return ENDPOINT + '?' + urllib.parse.urlencode({'text': text, 'filter': 'countrycode:us', 'limit': 5, 'format': 'json'})

def save_asset(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)

def evidence(station, results, boundary, source):
    names = {norm(row['Truckstop Name']) for row in station.rows}
    for item in results:
        name = item.get('name', '')
        if not isinstance(name, str) or not name or item.get('result_type') not in ('amenity', 'building'):
            continue
        reference = item.get('ref') or item.get('other_names', {}).get('ref', '')
        if reference and re.fullmatch(r'\d+[A-Za-z]?', str(reference).strip()):
            name = f'{name} #{str(reference).strip()}'
        state = str(item.get('state_code', '')).upper().split('-')[-1]
        if state != station.state or str(item.get('country_code', '')).upper() != 'US':
            continue
        if not item.get('city') or norm(str(item['city'])) != norm(station.city):
            continue
        try:
            latitude, longitude = float(item['lat']), float(item['lon'])
            if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or not in_us([latitude, longitude], boundary):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        street = ' '.join(str(item.get(k, '')).strip() for k in ('housenumber', 'street')).strip()
        addresses = (street, item.get('address_line1', ''), item.get('formatted', ''))
        matched = next((address for address in addresses if isinstance(address, str) and station_match(names, station.address, name, address, station.state)), None)
        if matched:
            datasource = item.get('datasource', {})
            return {'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'latitude': latitude, 'longitude': longitude, 'matched_name': name, 'matched_address': matched, 'source': source, 'source_row_ids': '|'.join(f'{station.source_id}:{i+1}' for i in range(len(station.rows))), 'place_id': item.get('place_id', ''), 'datasource_name': datasource.get('sourcename', datasource.get('sourceName', '')), 'datasource_license': datasource.get('license', ''), 'datasource_attribution': datasource.get('attribution', ''), 'datasource_url': datasource.get('url', datasource.get('sourceURL', ''))} 
    return None

class Command(BaseCommand):
    help = 'Resolve station evidence with an explicit Geoapify request and credit budget.'

    def add_arguments(self, parser):
        parser.add_argument('--sample', help='CSV from sample_stations; omit for all station groups')
        parser.add_argument('--cache', required=True, help='Geoapify response asset path')
        parser.add_argument('--output', required=True, help='Evidence CSV output path')
        parser.add_argument('--max-requests', type=int, required=True)
        parser.add_argument('--credit-budget', type=int, required=True)
        parser.add_argument('--replace-output', action='store_true')
        parser.add_argument('--unresolved-only', action='store_true', help='Exclude stations with both coordinates')

    def handle(self, sample, cache, output, max_requests, credit_budget, replace_output, unresolved_only, **options):
        if max_requests < 0 or credit_budget < 0:
            raise CommandError('Request and credit budgets must be nonnegative.')
        secret = os.environ.get('GEOAPIFY_API_KEY', '').strip()
        cache_path, output_path = Path(cache), Path(output)
        if cache_path.resolve() == output_path.resolve():
            raise CommandError('Cache and evidence output must be different files.')
        if output_path.exists() and not replace_output:
            raise CommandError('Evidence output exists; choose another path or use --replace-output.')
        try:
            boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
            asset = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
            if not isinstance(asset, dict):
                raise ValueError()
        except (OSError, UnicodeError, ValueError) as exc:
            raise CommandError('US boundary or Geoapify asset is unavailable or invalid.') from exc
        stations = list(Station.objects.order_by('pk'))
        if sample:
            with open(sample, encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream)
                columns = set(reader.fieldnames or [])
                compact = ('station_id', 'address', 'city', 'state')
                original = ('OPIS Truckstop ID', 'Address', 'City', 'State')
                fields = compact if set(compact) <= columns else original if set(original) <= columns else None
                if fields is None:
                    raise CommandError('Sample columns must match sample_stations or source CSV.')
                sample_keys = {(row[fields[0]].strip(), norm(row[fields[1]]), norm(row[fields[2]]), norm(row[fields[3]])) for row in reader}
            stations = [s for s in stations if (s.source_id, norm(s.address), norm(s.city), norm(s.state)) in sample_keys]
            found_keys = {(s.source_id, norm(s.address), norm(s.city), norm(s.state)) for s in stations}
            if found_keys != sample_keys:
                raise CommandError('Sample contains station groups absent from the current import.')
        if unresolved_only:
            stations = [s for s in stations if s.latitude is None or s.longitude is None]
        rows, used, remaining, last_request = [], 0, 0, None
        for station in stations:
            found = None
            for with_address in (True, False):
                source = source_query(station, with_address=with_address)
                if secret and secret in source:
                    raise CommandError('Source query could not be stored safely.')
                identity = hashlib.sha256(source.encode()).hexdigest()
                if identity not in asset:
                    if used >= min(max_requests, credit_budget):
                        remaining += 1
                        break
                    if not secret:
                        raise CommandError('Set GEOAPIFY_API_KEY in the environment for uncached requests.')
                    if last_request is not None:
                        delay = 0.5 - (time.monotonic() - last_request)
                        if delay > 0:
                            time.sleep(delay)
                    url = source + '&' + urllib.parse.urlencode({'apiKey': secret})
                    try:
                        last_request = time.monotonic()
                        req = urllib.request.Request(url, headers={'User-Agent': 'FuelRouteAssessment/1.0'})
                        with urllib.request.urlopen(req, timeout=30) as response:
                            payload = json.load(response)
                    except (OSError, urllib.error.URLError, UnicodeError, ValueError):
                        raise CommandError('Geoapify request failed; cached source data retained.') from None
                    used += 1
                    asset[identity] = safe_results(payload, secret)
                    save_asset(cache_path, asset)
                found = evidence(station, safe_results({'results': asset[identity]}, secret), boundary, source)
                if found:
                    rows.append(found)
                    break
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        self.stdout.write(f'Evidence rows: {len(rows)}. Requests used: {used}. Groups awaiting request: {remaining}.')
        if remaining:
            self.stdout.write('Budget exhausted; coverage incomplete. Resume with the same cache and a new budget.')

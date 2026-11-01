import json
import uuid
from datetime import timedelta
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from planner.core import TANK, distance, key, station_dataset_digest
from planner.models import RoutePlan, Station
from planner.planning import InputError, normalize_legacy, planning_settings, plan, resolve_locations
from planner.providers import ProviderError, RouteCoverageError

def cacheable_plan(result):
    if result.get('status') == 'PROVIDER_FAILURE':
        return False
    candidates = [result.get('baseline'), *result.get('alternatives', [])]
    return not any(isinstance(candidate, dict) and candidate.get('reason') == 'VERIFICATION_PROVIDER_FAILURE' for candidate in candidates)


@csrf_exempt
@require_POST
def create_route(request):
    try:
        try:
            body = json.loads(request.body)
        except ValueError as exc:
            raise InputError('INVALID_REQUEST', 'Request body must be JSON.') from exc
        if not isinstance(body, dict) or 'start' not in body or 'finish' not in body:
            raise InputError('INVALID_REQUEST', 'Provide start and finish.')
        value = body.get('start_fuel_gallons', TANK)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= TANK:
            raise InputError('INVALID_FUEL', 'Starting fuel must be between 0 and 50 gallons.')
        value = float(value)
        start, finish = resolve_locations([body['start'], body['finish']])
        with transaction.atomic():
            dataset = station_dataset_digest()
            stations = list(Station.objects.filter(latitude__isnull=False, longitude__isnull=False).order_by('pk'))
            resolved = [start, finish]
            for index, location in enumerate((body['start'], body['finish'])):
                if isinstance(location, dict) and 'station_id' in location:
                    matches = [station for station in stations if station.source_id == str(location['station_id'])]
                    if len(matches) != 1:
                        raise InputError('UNRESOLVABLE_LOCATION', 'Station ID must identify one verified station.')
                    point = [matches[0].latitude, matches[0].longitude]
                    if point != resolved[index]:
                        resolved[index] = resolve_locations([location, location])[0]
            start, finish = resolved
        if value == 0:
            matches = [(distance(start, [station.latitude, station.longitude]), station) for station in stations]
            matches = [(miles, station) for miles, station in matches if miles < 1e-6]
            if not matches:
                raise InputError('ZERO_FUEL_ORIGIN_NOT_STATION', 'Zero starting fuel requires a verified station at the origin.')
            nearest = min(miles for miles, _ in matches)
            closest = [station for miles, station in matches if miles == nearest]
            locations = {(station.latitude, station.longitude) for station in closest}
            if len(locations) > 1:
                raise InputError('AMBIGUOUS_ZERO_FUEL_ORIGIN', 'Choose a station at the origin.', candidates=[{'station_id': station.source_id, 'location': {'latitude': station.latitude, 'longitude': station.longitude}} for station in closest])
            start = list(next(iter(locations)))
        cache_key = key([start, finish, value, dataset, planning_settings()])
        previous = RoutePlan.objects.filter(cache_key=cache_key, created__gt=timezone.now()-timedelta(hours=24)).order_by('-created').first()
        if previous and cacheable_plan(previous.result):
            return JsonResponse(previous.result, status=200 if previous.result['recommended'] else 422)
        result = plan(start, finish, value, stations)
        plan_id = uuid.uuid4()
        result['plan_id'] = str(plan_id)
        result['map_url'] = f'/map/{plan_id}'
        RoutePlan.objects.create(pk=plan_id, result=result, cache_key=cache_key if cacheable_plan(result) else '')
        return JsonResponse(result, status=200 if result['recommended'] else 503 if result['status'] == 'PROVIDER_FAILURE' else 422)
    except InputError as exc:
        return JsonResponse({'code': exc.code, 'message': exc.message, **exc.details}, status=400)
    except RouteCoverageError as exc:
        return JsonResponse({'code': 'ROUTING_COVERAGE_UNAVAILABLE', 'message': str(exc)}, status=422)
    except ProviderError as exc:
        return JsonResponse({'code': 'PROVIDER_FAILURE', 'message': str(exc)}, status=503)

@require_GET
def map_view(request, plan_id):
    try:
        stored = RoutePlan.objects.get(pk=plan_id)
    except RoutePlan.DoesNotExist as exc:
        raise Http404 from exc
    response = render(request, 'planner/map.html', {'result': normalize_legacy(stored.result)})
    response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

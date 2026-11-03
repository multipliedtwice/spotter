from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import SEVENFLEET_SOURCE


class Command(OperatorCommand):
    help = 'Resolve 7FLEET retailer locations from local locator records.'
    source_url = SEVENFLEET_SOURCE
    namespaces = {'7 ELEVEN': '7FLEET', 'STRIPES': '7FLEET', 'SPEEDWAY': '7FLEET'}
    datasource_name = '7FLEET'
    unique_operator_points = True
    wrap_raw_records = True

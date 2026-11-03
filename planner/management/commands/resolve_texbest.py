from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import TEXBEST_SOURCE


class Command(OperatorCommand):
    help = 'Resolve Tex-Best stations from local published locator records.'
    source_url = TEXBEST_SOURCE
    namespaces = {'TEX BEST': 'TEX BEST'}
    datasource_name = 'Tex-Best'
    unique_operator_points = True
    wrap_raw_records = True

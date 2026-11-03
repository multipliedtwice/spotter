from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.operator_evidence import pilot_source_brand


class Command(OperatorCommand):
    help = 'Resolve Pilot and Flying J stations from local operator records.'
    source_url = None
    namespaces = {'PILOT': 'PILOT', 'PILOT DEALER': 'PILOT', 'PILOT EXPRESS': 'PILOT', 'FLYING J': 'PILOT', 'FLYING J DEALER': 'PILOT'}
    datasource_name = 'Pilot Flying J'

    def source_brand(self, name):
        return pilot_source_brand(name)

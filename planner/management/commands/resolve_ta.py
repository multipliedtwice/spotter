from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand


class Command(OperatorCommand):
    help = 'Resolve TA, TA Express and Petro stations from local operator records.'
    source_url = None
    namespaces = {}
    datasource_name = 'TravelCenters of America'
    ta_branches = True

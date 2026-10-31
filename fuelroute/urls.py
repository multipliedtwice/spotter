from django.urls import path
from planner import views

urlpatterns = [path('api/routes', views.create_route), path('map/<uuid:plan_id>', views.map_view)]

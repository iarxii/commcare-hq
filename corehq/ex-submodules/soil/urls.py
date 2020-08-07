from django.conf.urls import url

from soil.views import (
    ajax_job_poll,
    heartbeat_status,
    retrieve_download,
)

urlpatterns = [
    url(r'^(?P<download_id>(?:dl-)?[0-9a-fA-Z]{25,32})$', retrieve_download, name='retrieve_download'),
    url(r'^ajax/(?P<download_id>(?:dl-)?[0-9a-fA-Z]{25,32})$', ajax_job_poll, name='ajax_job_poll'),
    url(r'^heartbeat/$', heartbeat_status, name='soil_heartbeat'),
]

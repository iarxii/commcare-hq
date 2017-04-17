from django.conf.urls import url
from corehq.apps.motech.openmrs import views

urlpatterns = [
    # concepts
    url(r'^rest/concept/$',
        views.all_openmrs_concepts,
        name='all_openmrs_concepts'),
    url(r'^rest/concept/search/$',
        views.concept_search,
        name='openmrs_concept_search'),
    url(r'^rest/concept/sync/$',
        views.sync_concepts,
        name='openmrs_sync_concepts'),
    url(r'^concept/search/$',
        views.concept_search_page,
        name='openmrs_concept_search_page'),

    # patients
    url(r'^rest/patientidentifiertype/$',
        views.all_patient_identifier_types,
        name='openmrs_all_patient_identifier_types'),
    url(r'^rest/patient/$',
        views.search_patients,
        name='openmrs_search_patients'),
]

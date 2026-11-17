from django.urls import path

from horilla_api.api_views.ohs import views

urlpatterns = [
    path("dashboard/summary/", views.DashboardSummaryAPIView.as_view()),
    path("general-register/", views.GeneralRegisterAPIView.as_view()),
    path("workplaces/", views.WorkplaceListCreate.as_view()),
    path("workplaces/<int:pk>/", views.WorkplaceDetail.as_view()),
    path("events/", views.EventListCreate.as_view()),
    path("events/<int:pk>/", views.EventDetail.as_view()),
    path("notifications/", views.NotificationListCreate.as_view()),
    path("notifications/<int:pk>/", views.NotificationDetail.as_view()),
    path("investigations/", views.InvestigationListCreate.as_view()),
    path("investigations/<int:pk>/", views.InvestigationDetail.as_view()),
    path("corrective-actions/", views.CorrectiveActionListCreate.as_view()),
    path("corrective-actions/<int:pk>/", views.CorrectiveActionDetail.as_view()),
    path("policies/", views.PolicyListCreate.as_view()),
    path("policies/<int:pk>/", views.PolicyDetail.as_view()),
    path("policy-acknowledgements/", views.PolicyAckListCreate.as_view()),
    path("policy-acknowledgements/<int:pk>/", views.PolicyAckDetail.as_view()),
    path("committees/", views.CommitteeListCreate.as_view()),
    path("committees/<int:pk>/", views.CommitteeDetail.as_view()),
    path("committee-meetings/", views.MeetingListCreate.as_view()),
    path("committee-meetings/<int:pk>/", views.MeetingDetail.as_view()),
    path("medical-records/", views.MedicalListCreate.as_view()),
    path("medical-records/<int:pk>/", views.MedicalDetail.as_view()),
    path("ppe-assignments/", views.PpeListCreate.as_view()),
    path("ppe-assignments/<int:pk>/", views.PpeDetail.as_view()),
    path("training-records/", views.TrainingListCreate.as_view()),
    path("training-records/<int:pk>/", views.TrainingDetail.as_view()),
]

"""OHS JSON API — Imara v1."""

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from horilla_api.api_decorators.base.decorators import permission_required
from horilla_api.api_methods.base.pagination import HorillaPageNumberPagination
from horilla_api.api_serializers.ohs.serializers import (
    OshCommitteeMeetingSerializer,
    OshCorrectiveActionSerializer,
    OshEventSerializer,
    OshInvestigationSerializer,
    OshMedicalRecordSerializer,
    OshNotificationSerializer,
    OshPolicyAcknowledgementSerializer,
    OshPolicySerializer,
    OshPpeAssignmentSerializer,
    OshSafetyCommitteeSerializer,
    OshTrainingRecordSerializer,
    OshWorkplaceSerializer,
)
from ohs.models import (
    OshCommitteeMeeting,
    OshCorrectiveAction,
    OshEvent,
    OshInvestigation,
    OshMedicalRecord,
    OshNotification,
    OshPolicy,
    OshPolicyAcknowledgement,
    OshPpeAssignment,
    OshSafetyCommittee,
    OshTrainingRecord,
    OshWorkplace,
)


def object_check(cls, pk):
    try:
        return cls.objects.get(id=pk)
    except cls.DoesNotExist:
        return None


def _paginated(request, queryset, serializer_class):
    paginator = HorillaPageNumberPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page, many=True)
    return paginator.get_paginated_response(serializer.data)


def _list_create(model, serializer_class, view_perm, add_perm, filter_fields=()):
    class View(APIView):
        permission_classes = [IsAuthenticated]
        queryset = model.objects.none()

        def get_queryset(self):
            if getattr(self, "swagger_fake_view", False):
                return model.objects.none()
            qs = model.objects.all()
            for field in filter_fields:
                value = self.request.GET.get(field)
                if value not in (None, ""):
                    qs = qs.filter(**{field: value})
            search = self.request.GET.get("search")
            if search and hasattr(model, "title"):
                qs = qs.filter(title__icontains=search)
            elif search and hasattr(model, "name"):
                qs = qs.filter(name__icontains=search)
            elif search and hasattr(model, "course_name"):
                qs = qs.filter(course_name__icontains=search)
            elif search and hasattr(model, "item_type"):
                qs = qs.filter(item_type__icontains=search)
            return qs

        @permission_required(view_perm)
        def get(self, request):
            return _paginated(request, self.get_queryset(), serializer_class)

        @permission_required(add_perm)
        def post(self, request):
            serializer = serializer_class(data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    View.__name__ = f"{model.__name__}ListCreate"
    return View


def _retrieve_update_delete(model, serializer_class, view_perm, change_perm, delete_perm):
    class View(APIView):
        permission_classes = [IsAuthenticated]

        @permission_required(view_perm)
        def get(self, request, pk):
            obj = object_check(model, pk)
            if obj is None:
                return Response(
                    {"error": _("%(model)s not found") % {"model": model.__name__}},
                    status=404,
                )
            return Response(serializer_class(obj).data, status=200)

        @permission_required(change_perm)
        def put(self, request, pk):
            obj = object_check(model, pk)
            if obj is None:
                return Response(
                    {"error": _("%(model)s not found") % {"model": model.__name__}},
                    status=404,
                )
            serializer = serializer_class(obj, data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=200)
            return Response(serializer.errors, status=400)

        @permission_required(change_perm)
        def patch(self, request, pk):
            obj = object_check(model, pk)
            if obj is None:
                return Response(
                    {"error": _("%(model)s not found") % {"model": model.__name__}},
                    status=404,
                )
            serializer = serializer_class(obj, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=200)
            return Response(serializer.errors, status=400)

        @permission_required(delete_perm)
        def delete(self, request, pk):
            obj = object_check(model, pk)
            if obj is None:
                return Response(
                    {"error": _("%(model)s not found") % {"model": model.__name__}},
                    status=404,
                )
            try:
                obj.delete()
                return Response(status=status.HTTP_204_NO_CONTENT)
            except Exception as exc:
                return Response({"error": str(exc)}, status=400)

    View.__name__ = f"{model.__name__}Detail"
    return View


WorkplaceListCreate = _list_create(
    OshWorkplace,
    OshWorkplaceSerializer,
    "ohs.view_oshworkplace",
    "ohs.add_oshworkplace",
    filter_fields=("company_id", "jurisdiction"),
)
WorkplaceDetail = _retrieve_update_delete(
    OshWorkplace,
    OshWorkplaceSerializer,
    "ohs.view_oshworkplace",
    "ohs.change_oshworkplace",
    "ohs.delete_oshworkplace",
)

EventListCreate = _list_create(
    OshEvent,
    OshEventSerializer,
    "ohs.view_oshevent",
    "ohs.add_oshevent",
    filter_fields=("workplace", "event_type", "status", "employee", "compensable"),
)
EventDetail = _retrieve_update_delete(
    OshEvent,
    OshEventSerializer,
    "ohs.view_oshevent",
    "ohs.change_oshevent",
    "ohs.delete_oshevent",
)

NotificationListCreate = _list_create(
    OshNotification,
    OshNotificationSerializer,
    "ohs.view_oshnotification",
    "ohs.add_oshnotification",
    filter_fields=("event",),
)
NotificationDetail = _retrieve_update_delete(
    OshNotification,
    OshNotificationSerializer,
    "ohs.view_oshnotification",
    "ohs.change_oshnotification",
    "ohs.delete_oshnotification",
)

InvestigationListCreate = _list_create(
    OshInvestigation,
    OshInvestigationSerializer,
    "ohs.view_oshinvestigation",
    "ohs.add_oshinvestigation",
    filter_fields=("event",),
)
InvestigationDetail = _retrieve_update_delete(
    OshInvestigation,
    OshInvestigationSerializer,
    "ohs.view_oshinvestigation",
    "ohs.change_oshinvestigation",
    "ohs.delete_oshinvestigation",
)

CorrectiveActionListCreate = _list_create(
    OshCorrectiveAction,
    OshCorrectiveActionSerializer,
    "ohs.view_oshcorrectiveaction",
    "ohs.add_oshcorrectiveaction",
    filter_fields=("event", "status", "owner"),
)
CorrectiveActionDetail = _retrieve_update_delete(
    OshCorrectiveAction,
    OshCorrectiveActionSerializer,
    "ohs.view_oshcorrectiveaction",
    "ohs.change_oshcorrectiveaction",
    "ohs.delete_oshcorrectiveaction",
)

PolicyListCreate = _list_create(
    OshPolicy,
    OshPolicySerializer,
    "ohs.view_oshpolicy",
    "ohs.add_oshpolicy",
    filter_fields=("workplace",),
)
PolicyDetail = _retrieve_update_delete(
    OshPolicy,
    OshPolicySerializer,
    "ohs.view_oshpolicy",
    "ohs.change_oshpolicy",
    "ohs.delete_oshpolicy",
)

PolicyAckListCreate = _list_create(
    OshPolicyAcknowledgement,
    OshPolicyAcknowledgementSerializer,
    "ohs.view_oshpolicyacknowledgement",
    "ohs.add_oshpolicyacknowledgement",
    filter_fields=("policy", "employee"),
)
PolicyAckDetail = _retrieve_update_delete(
    OshPolicyAcknowledgement,
    OshPolicyAcknowledgementSerializer,
    "ohs.view_oshpolicyacknowledgement",
    "ohs.change_oshpolicyacknowledgement",
    "ohs.delete_oshpolicyacknowledgement",
)

CommitteeListCreate = _list_create(
    OshSafetyCommittee,
    OshSafetyCommitteeSerializer,
    "ohs.view_oshsafetycommittee",
    "ohs.add_oshsafetycommittee",
    filter_fields=("workplace",),
)
CommitteeDetail = _retrieve_update_delete(
    OshSafetyCommittee,
    OshSafetyCommitteeSerializer,
    "ohs.view_oshsafetycommittee",
    "ohs.change_oshsafetycommittee",
    "ohs.delete_oshsafetycommittee",
)

MeetingListCreate = _list_create(
    OshCommitteeMeeting,
    OshCommitteeMeetingSerializer,
    "ohs.view_oshcommitteemeeting",
    "ohs.add_oshcommitteemeeting",
    filter_fields=("committee",),
)
MeetingDetail = _retrieve_update_delete(
    OshCommitteeMeeting,
    OshCommitteeMeetingSerializer,
    "ohs.view_oshcommitteemeeting",
    "ohs.change_oshcommitteemeeting",
    "ohs.delete_oshcommitteemeeting",
)

MedicalListCreate = _list_create(
    OshMedicalRecord,
    OshMedicalRecordSerializer,
    "ohs.view_oshmedicalrecord",
    "ohs.add_oshmedicalrecord",
    filter_fields=("employee", "workplace", "exam_type", "fitness"),
)
MedicalDetail = _retrieve_update_delete(
    OshMedicalRecord,
    OshMedicalRecordSerializer,
    "ohs.view_oshmedicalrecord",
    "ohs.change_oshmedicalrecord",
    "ohs.delete_oshmedicalrecord",
)

PpeListCreate = _list_create(
    OshPpeAssignment,
    OshPpeAssignmentSerializer,
    "ohs.view_oshppeassignment",
    "ohs.add_oshppeassignment",
    filter_fields=("employee", "workplace"),
)
PpeDetail = _retrieve_update_delete(
    OshPpeAssignment,
    OshPpeAssignmentSerializer,
    "ohs.view_oshppeassignment",
    "ohs.change_oshppeassignment",
    "ohs.delete_oshppeassignment",
)

TrainingListCreate = _list_create(
    OshTrainingRecord,
    OshTrainingRecordSerializer,
    "ohs.view_oshtrainingrecord",
    "ohs.add_oshtrainingrecord",
    filter_fields=("employee", "workplace"),
)
TrainingDetail = _retrieve_update_delete(
    OshTrainingRecord,
    OshTrainingRecordSerializer,
    "ohs.view_oshtrainingrecord",
    "ohs.change_oshtrainingrecord",
    "ohs.delete_oshtrainingrecord",
)


class GeneralRegisterAPIView(APIView):
    """Uganda General Register extract: accidents + occupational diseases."""

    permission_classes = [IsAuthenticated]

    @permission_required("ohs.view_oshevent")
    def get(self, request):
        qs = OshEvent.objects.filter(
            event_type__in=["accident", "occupational_disease"]
        ).select_related("workplace", "employee", "reported_by")
        workplace_id = request.GET.get("workplace")
        if workplace_id:
            qs = qs.filter(workplace_id=workplace_id)
        since = request.GET.get("since")
        if since:
            qs = qs.filter(occurred_at__date__gte=since)
        return _paginated(request, qs, OshEventSerializer)


class DashboardSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @permission_required("ohs.view_oshevent")
    def get(self, request):
        today = timezone.localdate()
        soon = today + timedelta(days=90)
        open_events = OshEvent.objects.exclude(status="closed").count()
        overdue_capa = OshCorrectiveAction.objects.filter(
            status__in=["open", "in_progress"], due_on__lt=today
        ).count()
        expiring_registrations = OshWorkplace.objects.filter(
            expires_on__isnull=False, expires_on__lte=soon, expires_on__gte=today
        ).count()
        expired_registrations = OshWorkplace.objects.filter(
            expires_on__isnull=False, expires_on__lt=today
        ).count()
        training_due = OshTrainingRecord.objects.filter(
            valid_until__isnull=False, valid_until__lte=soon
        ).count()
        medical_due = OshMedicalRecord.objects.filter(
            next_due_on__isnull=False, next_due_on__lte=soon
        ).count()
        compensable_without_notification = (
            OshEvent.objects.filter(compensable=True)
            .annotate(n=Count("notifications"))
            .filter(n=0)
            .exclude(status="closed")
            .count()
        )
        by_type = dict(
            OshEvent.objects.values_list("event_type")
            .annotate(c=Count("id"))
            .values_list("event_type", "c")
        )
        return Response(
            {
                "open_events": open_events,
                "overdue_corrective_actions": overdue_capa,
                "expiring_registrations": expiring_registrations,
                "expired_registrations": expired_registrations,
                "training_due_soon": training_due,
                "medical_due_soon": medical_due,
                "compensable_missing_notification": compensable_without_notification,
                "events_by_type": by_type,
                "as_of": today.isoformat(),
            }
        )

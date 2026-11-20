"""Biometric devices for the Imara API.

A parallel JSON surface for the classic ``biometric`` app. The HTMX views in
``biometric/views.py`` are left as they are; this module reuses the app's
models and its log-fetching functions (which hold no request or template
code), and talks to ZKTeco / eSSL machines directly for the device-side user
operations, because the classic versions of those are view functions that
return HTML.

Imara's first customers run ZKTeco / eSSL machines on their own network with
Imara hosted on premises, so the server reaches each machine by IP. Device
records of every type can be listed, added and edited; test connection and
the "People on device" operations are ZKTeco / eSSL only for now, and
"fetch now" works for every type the classic app can fetch from.

Scheduling needs no live job here: the scheduler process runs
``biometric.poll_devices`` every minute and polls each device whose
``is_scheduler`` is on once its ``scheduler_duration`` has elapsed, so turning
the schedule on is just a field change.
"""

import logging
from contextlib import contextmanager

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from zk import ZK
from zk import exception as zk_exception

from biometric.models import BiometricDevices, BiometricEmployees
from employee.models import Employee, EmployeeWorkInformation
from horilla_api.api_decorators.base.decorators import permission_required
from horilla_api.api_methods.base.pagination import HorillaPageNumberPagination
from horilla_api.api_serializers.biometric.serializers import (
    BiometricDeviceSerializer,
    BiometricMappingSerializer,
    employee_brief,
)

logger = logging.getLogger(__name__)

# Seconds to wait for a machine. The classic views wait 60, which leaves a
# browser request hanging for a minute when a machine is switched off.
ZK_TIMEOUT = 15

# First device user id handed out when enrolling, as the classic app does.
FIRST_ZK_USER_ID = 1000


class DeviceError(Exception):
    """A machine could not be reached or refused the request."""


def _not_found():
    return Response(
        {"error": _("Biometric device not found.")}, status=status.HTTP_404_NOT_FOUND
    )


def _get_device(pk):
    # HorillaCompanyManager scopes this to the caller's company.
    return BiometricDevices.objects.filter(pk=pk).first()


def _require_zk(device):
    if device.machine_type != "zk":
        return Response(
            {
                "error": _(
                    "This is only available for ZKTeco / eSSL machines at the moment."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


def _device_error(error):
    return Response({"error": str(error)}, status=status.HTTP_502_BAD_GATEWAY)


@contextmanager
def zk_connection(device):
    """Open a connection to a ZKTeco / eSSL machine and always close it."""
    try:
        password = int(device.zk_password or 0)
    except (TypeError, ValueError) as error:
        raise DeviceError(_("The machine password must be a number.")) from error
    machine = ZK(
        device.machine_ip,
        port=device.port,
        timeout=ZK_TIMEOUT,
        password=password,
        force_udp=False,
        ommit_ping=False,
    )
    conn = None
    try:
        conn = machine.connect()
    except zk_exception.ZKErrorResponse as error:
        raise DeviceError(
            _("The machine refused the connection. Check the password.")
        ) from error
    except Exception as error:
        logger.warning("Could not reach biometric device %s", device.pk, exc_info=True)
        raise DeviceError(
            _("Could not reach the machine at %(ip)s:%(port)s. Check the IP address, port and network.")
            % {"ip": device.machine_ip, "port": device.port}
        ) from error
    try:
        yield conn
    finally:
        try:
            conn.enable_device()
        except Exception:
            pass
        try:
            conn.disconnect()
        except Exception:
            pass


def _device_info(conn):
    info = {}
    for key, getter in (
        ("device_name", "get_device_name"),
        ("serial_number", "get_serialnumber"),
        ("firmware", "get_firmware_version"),
        ("platform", "get_platform"),
    ):
        try:
            info[key] = getattr(conn, getter)()
        except Exception:
            info[key] = None
    try:
        conn.read_sizes()
        info["users"] = conn.users
        info["fingerprints"] = conn.fingers
        info["records"] = conn.records
    except Exception:
        info["users"] = info["fingerprints"] = info["records"] = None
    return info


def _fetch_logs(device):
    """Run the classic fetch for one device. Returns (count, error)."""
    # Imported here: biometric.views registers the polling job on import.
    from biometric import views as classic

    if device.machine_type == "zk":
        return classic.zk_biometric_attendance_logs(device)
    fetchers = {
        "anviz": classic.anviz_biometric_attendance_logs,
        "cosec": classic.cosec_biometric_attendance_logs,
        "dahua": classic.dahua_biometric_attendance_logs,
        "etimeoffice": classic.etimeoffice_biometric_attendance_logs,
    }
    fetcher = fetchers.get(device.machine_type)
    if fetcher is None:
        return None, _("This device type cannot fetch punches.")
    try:
        count = fetcher(device)
    except Exception as error:
        logger.exception("Biometric fetch failed for %s", device.pk)
        return None, str(error)
    if isinstance(count, int):
        return count, None
    return None, _("The machine did not return any punches. Check its settings.")


def _default_company(request):
    """The caller's own company, for a device added without one."""
    work_info = (
        EmployeeWorkInformation.objects.filter(employee_id__employee_user_id=request.user)
        .select_related("company_id")
        .first()
    )
    return work_info.company_id if work_info else None


class DeviceListCreateAPIView(APIView):
    """GET lists devices; POST adds one."""

    permission_classes = [IsAuthenticated]

    @permission_required("biometric.view_biometricdevices")
    def get(self, request):
        devices = BiometricDevices.objects.select_related("company_id").annotate(
            people_total=Count("biometricemployees")
        )
        is_active = request.GET.get("is_active", "true").lower()
        if is_active in ("true", "false"):
            devices = devices.filter(is_active=is_active == "true")
        machine_type = request.GET.get("machine_type")
        if machine_type:
            devices = devices.filter(machine_type=machine_type)
        search = (request.GET.get("search") or "").strip()
        if search:
            devices = devices.filter(
                Q(name__icontains=search) | Q(machine_ip__icontains=search)
            )
        devices = devices.order_by("name")
        paginator = HorillaPageNumberPagination()
        page = paginator.paginate_queryset(devices, request)
        return paginator.get_paginated_response(
            BiometricDeviceSerializer(page, many=True).data
        )

    @permission_required("biometric.add_biometricdevices")
    def post(self, request):
        serializer = BiometricDeviceSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        extra = {}
        if not serializer.validated_data.get("company_id"):
            extra["company_id"] = _default_company(request)
        device = serializer.save(**extra)
        return Response(
            BiometricDeviceSerializer(device).data, status=status.HTTP_201_CREATED
        )


class DeviceDetailAPIView(APIView):
    """GET, PATCH (also archive and schedule) or DELETE one device."""

    permission_classes = [IsAuthenticated]

    @permission_required("biometric.view_biometricdevices")
    def get(self, request, pk):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        return Response(BiometricDeviceSerializer(device).data)

    @permission_required("biometric.change_biometricdevices")
    def patch(self, request, pk):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        serializer = BiometricDeviceSerializer(device, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        extra = {}
        # A scheduled machine is polled; the classic live-capture thread is
        # switched off the same way the classic schedule view does it.
        if serializer.validated_data.get("is_scheduler"):
            extra["is_live"] = False
        device = serializer.save(**extra)
        return Response(BiometricDeviceSerializer(device).data)

    put = patch

    @permission_required("biometric.delete_biometricdevices")
    def delete(self, request, pk):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        device.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceTestAPIView(APIView):
    """POST: connect to the machine, report what it says about itself."""

    permission_classes = [IsAuthenticated]

    @permission_required("biometric.view_biometricdevices")
    def post(self, request, pk):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        not_zk = _require_zk(device)
        if not_zk:
            return not_zk
        try:
            with zk_connection(device) as conn:
                try:
                    conn.test_voice(index=0)
                except Exception:
                    pass
                info = _device_info(conn)
        except DeviceError as error:
            return _device_error(error)
        return Response({"ok": True, "message": _("Connected to the machine."), **info})


class DeviceFetchAPIView(APIView):
    """POST: pull new punches from the machine into attendance now."""

    permission_classes = [IsAuthenticated]

    @permission_required("biometric.view_biometricdevices")
    def post(self, request, pk):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        count, error = _fetch_logs(device)
        device.refresh_from_db()
        body = {
            "punches": count,
            "last_fetch_date": device.last_fetch_date,
            "last_fetch_time": device.last_fetch_time,
        }
        if error:
            logger.warning("Biometric fetch for %s failed: %s", device.pk, error)
            if device.machine_type == "zk":
                message = _(
                    "Could not read punches from the machine at %(ip)s:%(port)s. "
                    "Check that it is switched on and reachable, and that the password is right."
                ) % {"ip": device.machine_ip, "port": device.port}
            else:
                message = _(
                    "Could not read punches from this device. Check its connection settings."
                )
            return Response(
                {**body, "ok": False, "error": message, "detail_log": error},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({**body, "ok": True})


class DeviceMappingsAPIView(APIView):
    """
    GET: who is linked to this device, from Imara's records only (no call to
    the machine). POST {user_id, employee_id, uid?}: link a user already on
    the machine to an employee.
    """

    permission_classes = [IsAuthenticated]

    @permission_required("biometric.view_biometricemployees")
    def get(self, request, pk):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        mappings = (
            BiometricEmployees.objects.filter(device_id=device)
            .select_related("employee_id")
            .order_by("user_id")
        )
        return Response(BiometricMappingSerializer(mappings, many=True).data)

    @permission_required("biometric.add_biometricemployees")
    def post(self, request, pk):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        user_id = str(request.data.get("user_id") or "").strip()
        employee = Employee.objects.filter(pk=request.data.get("employee_id")).first()
        if not user_id or employee is None:
            return Response(
                {"error": _("Choose an employee and the user ID on the machine.")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        existing = BiometricEmployees.objects.filter(device_id=device)
        if existing.filter(user_id=user_id).exists():
            return Response(
                {"user_id": [_("This machine user is already linked to someone.")]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if existing.filter(employee_id=employee).exists():
            return Response(
                {"employee_id": [_("This employee is already linked on this machine.")]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        uid = request.data.get("uid")
        try:
            uid = int(uid) if uid not in (None, "") else None
        except (TypeError, ValueError):
            uid = None
        mapping = BiometricEmployees.objects.create(
            uid=uid, user_id=user_id, employee_id=employee, device_id=device
        )
        return Response(
            BiometricMappingSerializer(mapping).data, status=status.HTTP_201_CREATED
        )


class DeviceMappingDetailAPIView(APIView):
    """DELETE: unlink an employee from a device user. The machine is not touched."""

    permission_classes = [IsAuthenticated]

    @permission_required("biometric.delete_biometricemployees")
    def delete(self, request, pk, mapping_id):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        deleted, _rows = BiometricEmployees.objects.filter(
            pk=mapping_id, device_id=device
        ).delete()
        if not deleted:
            return Response(
                {"error": _("Link not found.")}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceUsersAPIView(APIView):
    """GET: the users stored on the machine, each with the employee it is linked to."""

    permission_classes = [IsAuthenticated]

    @permission_required("biometric.view_biometricemployees")
    def get(self, request, pk):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        not_zk = _require_zk(device)
        if not_zk:
            return not_zk
        try:
            with zk_connection(device) as conn:
                users = conn.get_users()
                try:
                    templates = conn.get_templates()
                except Exception:
                    templates = []
        except DeviceError as error:
            return _device_error(error)

        fingers = {}
        for template in templates:
            fingers[template.uid] = fingers.get(template.uid, 0) + 1
        mappings = {
            str(m.user_id): m
            for m in BiometricEmployees.objects.filter(device_id=device).select_related(
                "employee_id"
            )
        }
        rows = []
        for user in users:
            mapping = mappings.get(str(user.user_id))
            rows.append(
                {
                    "uid": user.uid,
                    "user_id": str(user.user_id),
                    "name": user.name,
                    "is_admin": user.privilege == 14,
                    "has_card": bool(user.card),
                    "has_password": bool(user.password),
                    "fingerprints": fingers.get(user.uid, 0),
                    "mapping_id": mapping.pk if mapping else None,
                    "employee": employee_brief(mapping.employee_id) if mapping else None,
                }
            )
        rows.sort(key=lambda row: (row["employee"] is None, row["name"] or ""))
        return Response({"count": len(rows), "results": rows})


class DeviceUserDetailAPIView(APIView):
    """DELETE: remove a user from the machine and unlink it in Imara."""

    permission_classes = [IsAuthenticated]

    @permission_required("biometric.delete_biometricemployees")
    def delete(self, request, pk, uid):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        not_zk = _require_zk(device)
        if not_zk:
            return not_zk
        try:
            with zk_connection(device) as conn:
                users = {user.uid: user for user in conn.get_users()}
                user = users.get(uid)
                if user is None:
                    return Response(
                        {"error": _("That user is not on the machine.")},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                conn.delete_user(uid=uid)
        except DeviceError as error:
            return _device_error(error)
        # Scope to this device: the classic view matched on uid alone and
        # could drop another machine's link that shared the number.
        BiometricEmployees.objects.filter(device_id=device).filter(
            Q(uid=uid) | Q(user_id=str(user.user_id))
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceEnrolAPIView(APIView):
    """
    POST {employee_ids: [...]}: create each employee as a user on the machine
    and link them. Fingerprints are then captured at the machine itself.
    """

    permission_classes = [IsAuthenticated]

    @permission_required("biometric.add_biometricemployees")
    def post(self, request, pk):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        not_zk = _require_zk(device)
        if not_zk:
            return not_zk
        ids = request.data.get("employee_ids") or []
        if not isinstance(ids, list) or not ids:
            return Response(
                {"error": _("Choose at least one employee.")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        employees = list(Employee.objects.filter(pk__in=ids))
        linked = set(
            BiometricEmployees.objects.filter(
                device_id=device, employee_id__in=employees
            ).values_list("employee_id", flat=True)
        )
        added, skipped = [], []
        try:
            with zk_connection(device) as conn:
                device_users = conn.get_users()
                taken_uids = {user.uid for user in device_users}
                # The machine reports user_id as text; compare like with like.
                taken_user_ids = {str(user.user_id) for user in device_users}
                taken_user_ids.update(
                    BiometricEmployees.objects.filter(device_id=device).values_list(
                        "user_id", flat=True
                    )
                )
                uid, user_id = 1, FIRST_ZK_USER_ID
                for employee in employees:
                    if employee.pk in linked:
                        skipped.append(
                            {
                                **employee_brief(employee),
                                "reason": _("Already on this machine"),
                            }
                        )
                        continue
                    while uid in taken_uids:
                        uid += 1
                    while str(user_id) in taken_user_ids:
                        user_id += 1
                    conn.set_user(
                        uid=uid,
                        # ZKTeco names are limited to 24 characters.
                        name=employee.get_full_name()[:24],
                        password="",
                        group_id="",
                        user_id=str(user_id),
                        card=0,
                    )
                    taken_uids.add(uid)
                    taken_user_ids.add(str(user_id))
                    try:
                        with transaction.atomic():
                            BiometricEmployees.objects.create(
                                uid=uid,
                                user_id=str(user_id),
                                employee_id=employee,
                                device_id=device,
                            )
                    except IntegrityError:
                        logger.exception("Could not save biometric link")
                    added.append(
                        {**employee_brief(employee), "uid": uid, "user_id": str(user_id)}
                    )
        except DeviceError as error:
            if not added:
                return _device_error(error)
            return Response(
                {"added": added, "skipped": skipped, "error": str(error)},
                status=status.HTTP_207_MULTI_STATUS,
            )
        return Response({"added": added, "skipped": skipped})


class DeviceMatchBadgesAPIView(APIView):
    """
    POST: link machine users whose user ID equals an active employee's badge
    ID. Useful when the machine was set up before Imara.
    """

    permission_classes = [IsAuthenticated]

    @permission_required("biometric.add_biometricemployees")
    def post(self, request, pk):
        device = _get_device(pk)
        if device is None:
            return _not_found()
        not_zk = _require_zk(device)
        if not_zk:
            return not_zk
        try:
            with zk_connection(device) as conn:
                zk_users = {str(user.user_id): user.uid for user in conn.get_users()}
        except DeviceError as error:
            return _device_error(error)
        existing = BiometricEmployees.objects.filter(device_id=device)
        taken_user_ids = set(existing.values_list("user_id", flat=True))
        linked_employees = set(existing.values_list("employee_id", flat=True))
        created = []
        for employee in Employee.objects.filter(is_active=True).exclude(
            badge_id__isnull=True
        ):
            badge = str(employee.badge_id or "").strip()
            if (
                badge
                and badge in zk_users
                and badge not in taken_user_ids
                and employee.pk not in linked_employees
            ):
                created.append(
                    BiometricEmployees(
                        uid=zk_users[badge],
                        user_id=badge,
                        employee_id=employee,
                        device_id=device,
                    )
                )
                taken_user_ids.add(badge)
        BiometricEmployees.objects.bulk_create(created)
        return Response({"linked": len(created)})

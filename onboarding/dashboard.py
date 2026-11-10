"""
Modern onboarding dashboard views — KPI summary + ApexCharts.

Accessible at /onboarding/dashboard/modern/ alongside the existing dashboard.
"""

from datetime import date

from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from horilla.decorators import login_required
from horilla.methods import handle_no_permission


def _has_onboarding_permission(request):
    """Return True if the user may access the onboarding dashboard."""
    user = request.user
    if user.is_superuser or user.has_perm("onboarding.view_onboardingstage"):
        return True
    try:
        employee = user.employee_get
        return (
            employee.onboardingstage_set.all().exists()
            or employee.onboarding_task.all().exists()
        )
    except Exception:
        return False


def _parse_period(request):
    """Parse from_date and to_date from GET params. Defaults to current month."""
    today = date.today()
    from_str = request.GET.get("from_date")
    to_str = request.GET.get("to_date")
    try:
        from_date = date.fromisoformat(from_str) if from_str else today.replace(day=1)
    except (ValueError, TypeError):
        from_date = today.replace(day=1)
    try:
        to_date = date.fromisoformat(to_str) if to_str else today
    except (ValueError, TypeError):
        to_date = today
    return from_date, to_date


def _onboarding_candidates_in_period(request):
    """Return Candidate queryset (start_onboard=True) filtered to the requested period."""
    from recruitment.models import Candidate

    from_date, to_date = _parse_period(request)
    return Candidate.objects.filter(
        is_active=True,
        start_onboard=True,
        created_at__date__gte=from_date,
        created_at__date__lte=to_date,
    )


@login_required
def onboarding_dashboard_view(request):
    """Render the modern onboarding dashboard page."""
    if not _has_onboarding_permission(request):
        return handle_no_permission(request)
    return render(request, "onboarding/dashboard.html")


@login_required
def onboarding_kpi_data(request):
    """Return onboarding KPI summary data as JSON."""
    if not _has_onboarding_permission(request):
        return JsonResponse({"no_permission": True})
    from onboarding.models import CandidateStage, CandidateTask, OnboardingPortal

    # "Onboarding" tile: every candidate actually sitting in a pipeline
    # stage (a CandidateStage row), not scoped to the selected period --
    # that's a standing state, not a one-time event tied to when the
    # candidate record was created, and the vast majority of them predate
    # this month. start_onboard=True is NOT a reliable proxy for this: a
    # candidate can be added to the pipeline (fixture data, or the "safe
    # onboarding stage insert" fallback in email_send) without that flag
    # ever getting set, which left this tile undercounting against what
    # the Pipeline board itself shows. Already-converted-to-employee
    # candidates are excluded -- they've left the candidate pipeline for
    # good, same exclusion email_send itself applies before sending a
    # portal link.
    onboard_stages = CandidateStage.objects.filter(
        candidate_id__is_active=True
    ).exclude(candidate_id__converted_employee_id__isnull=False)
    total_candidates = onboard_stages.count()
    completed_all_time = onboard_stages.filter(
        onboarding_stage_id__is_final_stage=True
    ).count()
    completion_rate = (
        round((completed_all_time / total_candidates * 100), 1)
        if total_candidates > 0
        else 0
    )

    # Portal link sent, but the candidate hasn't finished the onboarding
    # portal flow yet (used flips to True only once they reach the very
    # end -- see employee_bank_details_save in onboarding/views.py).
    portals = OnboardingPortal.objects.filter(candidate_id__is_active=True)
    portal_sent = portals.count()
    portal_incomplete = portals.filter(used=False).count()

    # Task stats — every pipeline candidate's checklist, all-time (same
    # population as the "Onboarding Candidates"/"Candidate Rate In Final
    # Stage" tiles above), not just whoever was created this month.
    pipeline_tasks = CandidateTask.objects.filter(
        candidate_id__in=onboard_stages.values("candidate_id")
    )
    total_tasks = pipeline_tasks.count()
    stuck_tasks = pipeline_tasks.filter(status="stuck").count()

    return JsonResponse(
        {
            "total_candidates": total_candidates,
            "portal_sent": portal_sent,
            "portal_incomplete": portal_incomplete,
            "completed_all_time": completed_all_time,
            "completion_rate": completion_rate,
            "total_tasks": total_tasks,
            "stuck_tasks": stuck_tasks,
        }
    )


@login_required
def onboarding_by_job_position(request):
    """Candidates onboarding per job position.

    Every candidate currently in the pipeline (a CandidateStage row),
    all-time -- same population as the "Onboarding Candidates"/"Task
    Completion"/"Final Stage By Position" cards on this same dashboard,
    not just whoever happened to be added this calendar month.
    """
    if not _has_onboarding_permission(request):
        return JsonResponse({"no_permission": True})
    from onboarding.models import CandidateStage

    positions = []

    try:
        data = (
            CandidateStage.objects.filter(candidate_id__is_active=True)
            .exclude(candidate_id__converted_employee_id__isnull=False)
            .values(
                "candidate_id__job_position_id",
                "candidate_id__job_position_id__job_position",
            )
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        for item in data:
            pos = item["candidate_id__job_position_id__job_position"]
            pos_id = item["candidate_id__job_position_id"]
            if pos:
                positions.append(
                    {"position": pos, "position_id": pos_id, "count": item["count"]}
                )
    except Exception:
        pass

    return JsonResponse({"positions": positions})


@login_required
def onboarding_task_managers(request):
    """Task assignment by manager (logged-in user's tasks), scoped to the selected period."""
    if not _has_onboarding_permission(request):
        return JsonResponse({"no_permission": True})
    from onboarding.models import CandidateStage, CandidateTask, OnboardingTask

    tasks = []

    try:
        user_emp = getattr(request.user, "employee_get", None)
        if user_emp:
            pipeline_candidates = (
                CandidateStage.objects.filter(candidate_id__is_active=True)
                .exclude(candidate_id__converted_employee_id__isnull=False)
                .values("candidate_id")
            )
            task_qs = OnboardingTask.objects.filter(
                employee_id=user_emp,
            ).order_by("stage_id__sequence")

            for task in task_qs:
                ct_base = CandidateTask.objects.filter(
                    onboarding_task_id=task,
                    candidate_id__in=pipeline_candidates,
                )
                total = ct_base.count()
                if total == 0:
                    continue
                done = ct_base.filter(status="done").count()
                if done == total:
                    continue
                stuck = ct_base.filter(status="stuck").count()
                progress = round((done / total * 100))
                # Fully done has nothing left to manage, so it shouldn't take
                # up one of this panel's slots -- keep slicing to 10 after
                # this filter, not before, or a finished task would crowd out
                # one still in progress.
                if progress == 100:
                    continue

                tasks.append(
                    {
                        "id": task.pk,
                        "title": task.task_title,
                        "stage": task.stage_id.stage_title if task.stage_id else "—",
                        "total": total,
                        "done": done,
                        "stuck": stuck,
                        "progress": round((done / total * 100)),
                    }
                )
            tasks.sort(key=lambda item: item["progress"])
            tasks = tasks[:10]
    except Exception:
        pass

    return JsonResponse({"tasks": tasks})


@login_required
def onboarding_completion_trend(request):
    """Candidates in the final onboarding stage, for active recruitments,
    broken down by job position -- not time-windowed, since this reads as
    a current snapshot ("who's finished, where") rather than a trend.

    Includes every job position open on an active recruitment, not just
    ones with a nonzero count -- a single-category result renders as a
    lone dot with nothing to draw a line to, which defeats the point of
    a line chart. Zero-filling the rest gives it an actual line to draw.
    """
    if not _has_onboarding_permission(request):
        return JsonResponse({"no_permission": True})
    from onboarding.models import CandidateStage
    from recruitment.models import JobPosition, Recruitment

    active_recruitment_ids = Recruitment.objects.filter(
        closed=False, is_active=True
    ).values("id")
    position_qs = (
        JobPosition.objects.filter(open_positions__in=active_recruitment_ids)
        .distinct()
        .order_by("job_position")
    )

    final_stage_counts = dict(
        CandidateStage.objects.filter(
            onboarding_stage_id__is_final_stage=True,
            candidate_id__is_active=True,
            candidate_id__recruitment_id__closed=False,
            candidate_id__recruitment_id__is_active=True,
        )
        .exclude(candidate_id__converted_employee_id__isnull=False)
        .values("candidate_id__job_position_id")
        .annotate(count=Count("id"))
        .values_list("candidate_id__job_position_id", "count")
    )

    positions = [
        {
            "position": jp.job_position,
            "position_id": jp.id,
            "count": final_stage_counts.get(jp.id, 0),
        }
        for jp in position_qs
    ]
    return JsonResponse({"positions": positions})

# ---------------------------------------------------------------------------
# Restored for horilla_api ONBOARDING_WIDGETS (trimmed from module UI).
# ---------------------------------------------------------------------------

@login_required
def onboarding_stage_distribution(request):
    """Candidates grouped by onboarding stage name -- one tile per stage.

    OnboardingStage rows are per-recruitment (every recruitment seeds its
    own stage set -- see recruitment_expansion.py), so grouping by the
    stage *row*, as this endpoint used to, renders one duplicate tile per
    recruitment that happens to share a stage name (e.g. "Initial"
    appearing once per recruitment instead of once, total). Grouping by
    stage_title instead collapses that back to one tile per distinct step
    (same fix as offboarding_pipeline in offboarding/dashboard.py).

    This also sidesteps a second, sneakier bug: a plain
    .values_list("onboarding_stage_id__stage_title", flat=True) is NOT
    safe here either. HorillaCompanyManager.get_queryset() forces
    .distinct() under company scoping, which Django compiles as a real SQL
    `SELECT DISTINCT title`, silently deduplicating by VALUE rather than
    by row the moment two different CandidateStage rows share a title --
    undercounting exactly the case this fix is meant to aggregate
    correctly. Pulling `pk` alongside every field defeats that, since pk
    uniqueness keeps each row distinct regardless of which other columns
    repeat.
    """
    if not _has_onboarding_permission(request):
        return JsonResponse({"no_permission": True})
    from onboarding.models import CandidateStage

    period_candidates = _onboarding_candidates_in_period(request)
    rows = CandidateStage.objects.filter(
        candidate_id__in=period_candidates
    ).values_list(
        "pk",
        "onboarding_stage_id",
        "onboarding_stage_id__stage_title",
        "onboarding_stage_id__sequence",
        "onboarding_stage_id__is_final_stage",
        "onboarding_stage_id__recruitment_id__title",
    )

    groups = {}
    for _pk, stage_id, title, sequence, is_final, recruitment_title in rows:
        sequence = sequence if sequence is not None else 0
        group = groups.setdefault(
            title,
            {
                "id": stage_id,
                "stage": title,
                "count": 0,
                "is_final": False,
                "sequence": sequence,
                "recruitments": set(),
            },
        )
        group["count"] += 1
        group["is_final"] = group["is_final"] or bool(is_final)
        group["sequence"] = min(group["sequence"], sequence)
        if recruitment_title:
            group["recruitments"].add(recruitment_title)

    stages = [
        {
            "id": group["id"],
            "stage": group["stage"],
            "count": group["count"],
            "is_final": group["is_final"],
            "recruitment": (
                next(iter(group["recruitments"]))
                if len(group["recruitments"]) == 1
                else (
                    f"{len(group['recruitments'])} recruitments"
                    if group["recruitments"]
                    else "—"
                )
            ),
        }
        for group in sorted(groups.values(), key=lambda g: g["sequence"])
    ]

    return JsonResponse({"stages": stages})


@login_required
def onboarding_task_status(request):
    """Task status breakdown."""
    if not _has_onboarding_permission(request):
        return JsonResponse({"no_permission": True})
    from onboarding.models import CandidateTask

    period_candidates = _onboarding_candidates_in_period(request)
    period_tasks = CandidateTask.objects.filter(candidate_id__in=period_candidates)

    statuses = []
    task_choices = [
        ("todo", _("Todo")),
        ("scheduled", _("Scheduled")),
        ("ongoing", _("Ongoing")),
        ("stuck", _("Stuck")),
        ("done", _("Done")),
    ]

    for status, label in task_choices:
        count = period_tasks.filter(status=status).count()
        statuses.append({"status": status, "label": label, "count": count})

    return JsonResponse({"statuses": statuses})


@login_required
def onboarding_by_recruitment(request):
    """Candidates onboarding per recruitment."""
    if not _has_onboarding_permission(request):
        return JsonResponse({"no_permission": True})
    recruitments = []

    try:
        data = (
            _onboarding_candidates_in_period(request)
            .values("recruitment_id__title")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        for item in data:
            title = item["recruitment_id__title"]
            if title:
                recruitments.append({"recruitment": title, "count": item["count"]})
    except Exception:
        pass

    return JsonResponse({"recruitments": recruitments})


@login_required
def onboarding_candidates_list(request):
    """Current onboarding candidates with progress."""
    if not _has_onboarding_permission(request):
        return JsonResponse({"no_permission": True})
    from onboarding.models import CandidateTask

    candidates = []

    try:
        qs = (
            _onboarding_candidates_in_period(request)
            .select_related("recruitment_id", "job_position_id", "onboarding_stage")
            .order_by("-id")[:15]
        )

        for c in qs:
            stage_name = "—"
            try:
                cs = c.onboarding_stage
                stage_name = (
                    cs.onboarding_stage_id.stage_title
                    if cs and cs.onboarding_stage_id
                    else "—"
                )
            except Exception:
                pass

            # Task progress
            total = CandidateTask.objects.filter(candidate_id=c).count()
            done = CandidateTask.objects.filter(candidate_id=c, status="done").count()
            progress = round((done / total * 100)) if total > 0 else 0

            candidates.append(
                {
                    "id": c.id,
                    "name": c.name or "—",
                    "profile": c.profile.url if c.profile else None,
                    "recruitment": c.recruitment_id.title if c.recruitment_id else "—",
                    "position": (
                        c.job_position_id.job_position if c.job_position_id else "—"
                    ),
                    "stage": stage_name,
                    "progress": progress,
                    "tasks_done": done,
                    "tasks_total": total,
                }
            )
    except Exception:
        pass

    return JsonResponse({"candidates": candidates})


@login_required
def onboarding_portal_status(request):
    """Portal access status for onboarding candidates within the selected period."""
    if not _has_onboarding_permission(request):
        return JsonResponse({"no_permission": True})
    from onboarding.models import OnboardingPortal

    portals = []
    try:
        period_candidates = _onboarding_candidates_in_period(request)
        qs = (
            OnboardingPortal.objects.filter(candidate_id__in=period_candidates)
            .select_related("candidate_id")
            .order_by("-count")[:15]
        )
        for p in qs:
            cand = p.candidate_id
            portals.append(
                {
                    "id": cand.id if cand else None,
                    "name": cand.name if cand else "—",
                    "used": p.used,
                    "visits": p.count,
                }
            )
    except Exception:
        pass
    return JsonResponse({"portals": portals})

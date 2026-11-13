from base.forms import ModelForm, forms
from horilla_meet.models import *
from recruitment.models import Candidate


class GoogleCloudCredentialForm(ModelForm):
    class Meta:
        model = GoogleCloudCredential
        fields = "__all__"


class GoogleMeetingForm(ModelForm):
    attendees = forms.MultipleChoiceField(choices=[], widget=forms.SelectMultiple)

    class Meta:
        model = GoogleMeeting
        fields = ["title", "description", "start_time", "duration", "attendees"]
        widgets = {
            "start_time": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control oh-input"}
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        employees = []
        for emp in Employee.objects.all():
            mail = emp.get_mail()
            if mail:
                employees.append((mail, emp.get_full_name()))
        candidates = []
        for cand in Candidate.objects.all():
            mail = cand.get_mail()
            if mail:
                candidates.append((mail, cand.name))

        self.fields["attendees"].choices = [
            ("Employees", employees),
            ("Candidates", candidates),
        ]

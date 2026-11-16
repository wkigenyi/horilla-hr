# Generated manually for payroll accounting GL mappings.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0022_jobposition_headcount"),
        ("payroll", "0016_alter_payrollbatch_status_payadjustment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PayrollGLMapping",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True, null=True, verbose_name="Created At"
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Active"),
                ),
                ("line_key", models.CharField(max_length=80, verbose_name="Line key")),
                (
                    "gl_code",
                    models.CharField(
                        blank=True, default="", max_length=64, verbose_name="GL code"
                    ),
                ),
                (
                    "label",
                    models.CharField(
                        blank=True, default="", max_length=120, verbose_name="Label"
                    ),
                ),
                (
                    "company_id",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="base.company",
                        verbose_name="Company",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created By",
                    ),
                ),
                (
                    "modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Modified By",
                    ),
                ),
            ],
            options={
                "verbose_name": "Payroll GL mapping",
                "verbose_name_plural": "Payroll GL mappings",
                "unique_together": {("company_id", "line_key")},
            },
        ),
    ]

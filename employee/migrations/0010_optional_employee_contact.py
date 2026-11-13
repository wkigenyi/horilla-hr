import django.core.validators
from django.db import migrations, models


def empty_contact_to_null(apps, schema_editor):
    Employee = apps.get_model("employee", "Employee")
    Employee.objects.filter(email="").update(email=None)
    Employee.objects.filter(phone="").update(phone=None)


class Migration(migrations.Migration):

    dependencies = [
        ("employee", "0009_alter_actiontype_is_active_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employee",
            name="email",
            field=models.EmailField(blank=True, max_length=254, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="employee",
            name="phone",
            field=models.CharField(
                blank=True,
                max_length=25,
                null=True,
                validators=[
                    django.core.validators.RegexValidator(
                        message="Enter a valid phone number (7-20 characters, optional +).",
                        regex="^\\+?[\\d\\s\\-\\(\\)]{7,20}$",
                    )
                ],
            ),
        ),
        migrations.RunPython(empty_contact_to_null, migrations.RunPython.noop),
    ]

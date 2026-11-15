from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employee", "0012_employee_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="nssf_id",
            field=models.CharField(
                blank=True,
                max_length=32,
                null=True,
                unique=True,
                verbose_name="NSSF ID",
            ),
        ),
    ]

# Generated by Django 3.2.24 on 2024-03-11 05:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sso', '0006_add_new_fields_in_identityprovider'),
    ]

    operations = [
        migrations.AddField(
            model_name='identityprovider',
            name='always_show_user_api_keys',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='identityprovider',
            name='max_days_until_user_api_key_expiration',
            field=models.IntegerField(blank=True, choices=[(365, '1 Year'), (180, '180 Days'), (120, '120 Days'), (60, '60 Days'), (30, '30 Days')], default=None, null=True),
        ),
    ]

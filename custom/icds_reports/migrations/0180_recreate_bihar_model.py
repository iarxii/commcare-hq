# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-04-18 02:46
from __future__ import unicode_literals

import custom.icds_reports.models.aggregate
from django.db import migrations, models

from custom.icds_reports.utils.migrations import (
    get_composite_primary_key_migrations,
)
from corehq.sql_db.operations import RawSQLMigration
from custom.icds_reports.const import BIHAR_API_DEMOGRAPHICS_TABLE
from custom.icds_reports.utils.migrations import get_view_migrations


migrator = RawSQLMigration(('custom', 'icds_reports', 'migrations', 'sql_templates', 'database_views'))


class Migration(migrations.Migration):

    dependencies = [
        ('icds_reports', '0179_drop_bihar_model'),
    ]

    operations = [
        migrations.CreateModel(
            name='BiharAPIDemographics',
            fields=[
                ('state_id', models.TextField(null=True)),
                ('district_id', models.TextField(null=True)),
                ('block_id', models.TextField(null=True)),
                ('supervisor_id', models.TextField(null=True)),
                ('awc_id', models.TextField(null=True)),
                ('month', models.DateField()),
                ('household_id', models.TextField(null=True)),
                ('household_name', models.TextField(null=True)),
                ('hh_reg_date', models.TextField(null=True)),
                ('hh_num', models.IntegerField(null=True)),
                ('hh_gps_location', models.TextField(null=True)),
                ('hh_caste', models.TextField(null=True)),
                ('hh_bpl_apl', models.TextField(null=True)),
                ('hh_minority', models.SmallIntegerField(null=True)),
                ('hh_religion', models.TextField(null=True)),
                ('hh_member_number', models.IntegerField(null=True)),
                ('person_id', models.TextField(primary_key=True, serialize=False)),
                ('person_name', models.TextField(null=True)),
                ('has_adhaar', models.SmallIntegerField(null=True)),
                ('bank_account_number', models.TextField(null=True)),
                ('ifsc_code', models.TextField(null=True)),
                ('age_at_reg', models.SmallIntegerField(null=True)),
                ('dob', models.DateField(null=True)),
                ('gender', models.TextField(null=True)),
                ('blood_group', models.TextField(null=True)),
                ('disabled', models.SmallIntegerField(null=True)),
                ('disability_type', models.TextField(null=True)),
                ('referral_status', models.TextField(null=True)),
                ('migration_status', models.SmallIntegerField(null=True)),
                ('resident', models.SmallIntegerField(null=True)),
                ('registered_status', models.SmallIntegerField(null=True)),
                ('married', models.SmallIntegerField(null=True)),
                ('husband_name', models.TextField(null=True)),
                ('husband_id', models.TextField(null=True)),
                ('last_preg_tt', models.SmallIntegerField(null=True)),
                ('is_pregnant', models.SmallIntegerField(null=True)),
                ('rch_id', models.TextField(null=True)),
                ('mcts_id', models.TextField(null=True)),
                ('phone_number', models.TextField(null=True)),
                ('date_death', models.DateField(null=True)),
                ('site_death', models.TextField(null=True)),
                ('closed_on', models.DateField(null=True)),
                ('reason_closure', models.TextField(null=True)),
            ],
            options={
                'db_table': 'bihar_api_demographics',
            },
            bases=(models.Model, custom.icds_reports.models.aggregate.AggregateMixin),
        ),
        migrations.AlterUniqueTogether(
            name='biharapidemographics',
            unique_together=set([('supervisor_id', 'month', 'person_id')]),
        ),
    ]

    operations.extend(get_composite_primary_key_migrations(['biharapidemographics']))

    operations += [
        migrations.RunSQL(f"ALTER TABLE {BIHAR_API_DEMOGRAPHICS_TABLE} RENAME TO {BIHAR_API_DEMOGRAPHICS_TABLE}_old"),
        migrations.RunSQL(f"CREATE TABLE {BIHAR_API_DEMOGRAPHICS_TABLE} (LIKE {BIHAR_API_DEMOGRAPHICS_TABLE}_old INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES) PARTITION BY LIST (month)"),
        migrations.RunSQL(f"SELECT create_distributed_table('{BIHAR_API_DEMOGRAPHICS_TABLE}', 'supervisor_id')"),
        migrations.RunSQL(f"DROP TABLE {BIHAR_API_DEMOGRAPHICS_TABLE}_old"),
    ]

    operations += [
        migrations.RunSQL("ALTER TABLE ccs_record_monthly ADD COLUMN tt_booster date"),
        migrations.RunSQL("ALTER TABLE ccs_record_monthly ADD COLUMN last_preg_year integer")
    ]


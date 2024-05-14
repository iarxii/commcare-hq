# Generated by Django 4.2.11 on 2024-05-06 20:59

from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('repeaters', '0008_sqlrepeatrecords'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS repeaters_r_domain_02258c_idx"
                "    ON repeaters_repeatrecord (domain, registered_at)",
                "DROP INDEX CONCURRENTLY IF EXISTS repeaters_r_domain_3ae9ab_idx",
                "DROP INDEX CONCURRENTLY IF EXISTS repeaters_r_registe_b48c68_idx",
            ],
            reverse_sql=[
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS repeaters_r_domain_3ae9ab_idx"
                "    ON repeaters_repeatrecord (domain)",
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS repeaters_r_registe_b48c68_idx"
                "    ON repeaters_repeatrecord (registered_at)",
                "DROP INDEX CONCURRENTLY IF EXISTS repeaters_r_domain_02258c_idx",
            ],
            state_operations=[
                migrations.RemoveIndex(
                    model_name='sqlrepeatrecord',
                    name='repeaters_r_domain_3ae9ab_idx',
                ),
                migrations.RemoveIndex(
                    model_name='sqlrepeatrecord',
                    name='repeaters_r_registe_b48c68_idx',
                ),
                migrations.AddIndex(
                    model_name='sqlrepeatrecord',
                    index=models.Index(fields=['domain', 'registered_at'],
                                       name='repeaters_r_domain_02258c_idx'),
                ),
            ],
        ),
    ]

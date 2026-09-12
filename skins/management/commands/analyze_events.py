# skins/management/commands/analyze_events.py
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


QUERIES = [
    ("Event volume by type", """
        SELECT event_type, COUNT(*) AS total
        FROM skins_userevent
        GROUP BY event_type
        ORDER BY total DESC;
    """),
    ("Daily activity, last 30 days", """
        SELECT date_trunc('day', created_at) AS day, event_type, COUNT(*) AS total
        FROM skins_userevent
        WHERE created_at > NOW() - INTERVAL '30 days'
        GROUP BY day, event_type
        ORDER BY day DESC, total DESC;
    """),
    ("Most active users", """
        SELECT e.user_id, u.username, COUNT(*) AS total
        FROM skins_userevent e
        JOIN skins_bonkuser u ON u.id = e.user_id
        GROUP BY e.user_id, u.username
        ORDER BY total DESC
        LIMIT 20;
    """),
    ("Anonymous vs authenticated", """
        SELECT CASE WHEN user_id IS NULL THEN 'anonymous' ELSE 'authenticated' END AS actor,
               COUNT(*) AS total
        FROM skins_userevent
        GROUP BY actor;
    """),
    ("Top skins by engagement", """
        SELECT skin_id, event_type, COUNT(*) AS total
        FROM skins_userevent
        WHERE skin_id IS NOT NULL
        GROUP BY skin_id, event_type
        ORDER BY total DESC
        LIMIT 30;
    """),
    ("New vs returning users", """
        SELECT e.user_id, u.username, MIN(e.created_at) AS first_event, MAX(e.created_at) AS last_event,
               COUNT(*) AS total_events
        FROM skins_userevent e
        JOIN skins_bonkuser u ON u.id = e.user_id
        GROUP BY e.user_id, u.username
        ORDER BY total_events DESC
        LIMIT 20;
    """),
    ("User 229 event breakdown", """
        SELECT event_type, COUNT(*) AS total
        FROM skins_userevent
        WHERE user_id = 229
        GROUP BY event_type
        ORDER BY total DESC;
    """),
    ("Burst users 3235 and 3407 timeline", """
        SELECT user_id, event_type, created_at
        FROM skins_userevent
        WHERE user_id IN (3235, 3407)
        ORDER BY user_id, created_at;
    """),
    ("Aug 20 upload spike source", """
        SELECT user_id, COUNT(*) AS total
        FROM skins_userevent
        WHERE event_type = 'skin_uploaded'
          AND created_at::date = '2026-08-20'
        GROUP BY user_id
        ORDER BY total DESC;
    """),
    ("Retention proxy: multi-week vs single-burst users", """
        SELECT pattern, COUNT(*) AS user_count
        FROM (
          SELECT user_id,
                 CASE WHEN (MAX(created_at)::date - MIN(created_at)::date) >= 7
                      THEN 'multi_week' ELSE 'single_burst' END AS pattern
          FROM skins_userevent
          WHERE user_id IS NOT NULL
          GROUP BY user_id
        ) sub
        GROUP BY pattern;
    """),
    ("Top worn skin details (3273)", """
        SELECT id, name, creator, created_at
        FROM skins_skin
        WHERE id = 3273;
    """),
    ("First real action for single-burst users", """
        WITH burst_users AS (
          SELECT user_id
          FROM skins_userevent
          WHERE user_id IS NOT NULL
          GROUP BY user_id
          HAVING (MAX(created_at)::date - MIN(created_at)::date) < 7
        ),
        first_action AS (
          SELECT DISTINCT ON (user_id) user_id, event_type, created_at
          FROM skins_userevent
          WHERE user_id IN (SELECT user_id FROM burst_users)
            AND event_type NOT IN ('user_logged_in', 'friends_synced', 'flash_friends_synced')
          ORDER BY user_id, created_at
        )
        SELECT event_type, COUNT(*) AS total
        FROM first_action
        GROUP BY event_type
        ORDER BY total DESC;
    """),
    ("Single-burst users who never got past login/sync", """
        WITH burst_users AS (
          SELECT user_id
          FROM skins_userevent
          WHERE user_id IS NOT NULL
          GROUP BY user_id
          HAVING (MAX(created_at)::date - MIN(created_at)::date) < 7
        )
        SELECT COUNT(*) AS login_only_users
        FROM burst_users bu
        WHERE NOT EXISTS (
          SELECT 1 FROM skins_userevent e
          WHERE e.user_id = bu.user_id
            AND e.event_type NOT IN ('user_logged_in', 'friends_synced', 'flash_friends_synced')
        );
    """),
    ("Distinct event types tried per single-burst user", """
        WITH burst_users AS (
          SELECT user_id
          FROM skins_userevent
          WHERE user_id IS NOT NULL
          GROUP BY user_id
          HAVING (MAX(created_at)::date - MIN(created_at)::date) < 7
        )
        SELECT distinct_event_types, COUNT(*) AS user_count
        FROM (
          SELECT user_id, COUNT(DISTINCT event_type) AS distinct_event_types
          FROM skins_userevent
          WHERE user_id IN (SELECT user_id FROM burst_users)
          GROUP BY user_id
        ) sub
        GROUP BY distinct_event_types
        ORDER BY distinct_event_types;
    """),
    ("Session count per single-burst user (login events as proxy)", """
        WITH burst_users AS (
          SELECT user_id
          FROM skins_userevent
          WHERE user_id IS NOT NULL
          GROUP BY user_id
          HAVING (MAX(created_at)::date - MIN(created_at)::date) < 7
        )
        SELECT session_count, COUNT(*) AS user_count
        FROM (
          SELECT user_id, COUNT(*) AS session_count
          FROM skins_userevent
          WHERE user_id IN (SELECT user_id FROM burst_users)
            AND event_type = 'user_logged_in'
          GROUP BY user_id
        ) sub
        GROUP BY session_count
        ORDER BY session_count;
    """),
    ("Heavy single-burst users (15+ logins), with usernames", """
        SELECT
          e.user_id,
          u.username,
          u.date_joined,
          COUNT(*) AS logins
        FROM skins_userevent e
        JOIN skins_bonkuser u ON u.id = e.user_id
        WHERE e.event_type = 'user_logged_in'
        GROUP BY e.user_id, u.username, u.date_joined
        HAVING COUNT(*) >= 15
        ORDER BY logins DESC;
    """),
]


class Command(BaseCommand):
    help = "Run a batch of UserEvent analytics queries and write results to a text file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--outfile",
            type=str,
            default=None,
            help="Output file path (default: userevent_analysis_<timestamp>.txt)",
        )

    def handle(self, *args, **options):
        outfile = options["outfile"] or f"userevent_analysis_{timezone.now().strftime('%Y%m%d_%H%M%S')}.txt"

        with open(outfile, "w") as f, connection.cursor() as cursor:
            for label, sql in QUERIES:
                f.write(f"=== {label} ===\n")
                try:
                    cursor.execute(sql)
                    columns = [col[0] for col in cursor.description]
                    rows = cursor.fetchall()
                    f.write("\t".join(columns) + "\n")
                    for row in rows:
                        f.write("\t".join(str(v) for v in row) + "\n")
                except Exception as e:
                    f.write(f"ERROR: {e}\n")
                f.write("\n")

        self.stdout.write(self.style.SUCCESS(f"Done. Output written to {outfile}"))
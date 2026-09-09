```python
import os
import sqlite3
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone


class Database:

    TIER_POINTS = {
        "LT5": 100,
        "MT5": 200,
        "HT5": 300,

        "LT4": 400,
        "MT4": 500,
        "HT4": 600,

        "LT3": 700,
        "MT3": 800,
        "HT3": 900,

        "LT2": 1000,
        "MT2": 1100,
        "HT2": 1200,

        "LT1": 1300,
        "MT1": 1400,
        "HT1": 1500,
    }

    def __init__(self, path):

        self.path = path

        directory = os.path.dirname(
            os.path.abspath(path)
        )

        os.makedirs(
            directory,
            exist_ok=True
        )

        self.conn = sqlite3.connect(
            path,
            check_same_thread=False
        )

        self.conn.row_factory = sqlite3.Row

        self.conn.execute(
            "PRAGMA journal_mode=WAL"
        )

        self.conn.execute(
            "PRAGMA synchronous=NORMAL"
        )

        self.conn.execute(
            "PRAGMA foreign_keys=ON"
        )

        self.conn.execute(
            "PRAGMA busy_timeout=10000"
        )

        self.setup()

    # ==================================================
    # TRANSACTION
    # ==================================================

    @contextmanager
    def transaction(self):

        try:

            self.conn.execute(
                "BEGIN IMMEDIATE"
            )

            yield self.conn

            self.conn.commit()

        except Exception:

            self.conn.rollback()
            raise

    # ==================================================
    # SETUP
    # ==================================================

    def setup(self):

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                minecraft_username TEXT NOT NULL,
                region TEXT NOT NULL DEFAULT 'No Region',
                current_tier TEXT,
                total_points INTEGER NOT NULL DEFAULT 0,
                total_tests INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS queues (
                user_id INTEGER PRIMARY KEY,
                gamemode TEXT NOT NULL,
                minecraft_username TEXT NOT NULL,
                preferred_server TEXT NOT NULL,
                joined_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tickets (
                channel_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                gamemode TEXT NOT NULL,
                minecraft_username TEXT NOT NULL,
                preferred_server TEXT NOT NULL,
                tester_id INTEGER,
                status TEXT NOT NULL DEFAULT 'waiting',
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                closed_at TEXT,
                close_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                minecraft_username TEXT NOT NULL,
                gamemode TEXT NOT NULL,
                tier TEXT NOT NULL,
                tester_id INTEGER NOT NULL,
                points INTEGER NOT NULL,
                match_score TEXT,
                verdict TEXT,
                created_at TEXT NOT NULL,
                corrected INTEGER NOT NULL DEFAULT 0,
                corrected_at TEXT,
                corrected_by INTEGER
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_results_user
            ON results(user_id);

            CREATE INDEX IF NOT EXISTS idx_results_gamemode
            ON results(gamemode);

            CREATE INDEX IF NOT EXISTS idx_results_user_gamemode
            ON results(user_id, gamemode);

            CREATE INDEX IF NOT EXISTS idx_results_points
            ON results(points DESC);

            CREATE INDEX IF NOT EXISTS idx_tickets_user
            ON tickets(user_id);

            CREATE INDEX IF NOT EXISTS idx_tickets_status
            ON tickets(status);

            CREATE INDEX IF NOT EXISTS idx_queues_gamemode
            ON queues(gamemode);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_active_ticket_user
            ON tickets(user_id)
            WHERE status IN ('waiting', 'testing');
            """
        )

        self._migrate()

        self.conn.commit()

    # ==================================================
    # MIGRATIONS
    # ==================================================

    def _column_exists(self, table, column):

        rows = self.conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()

        return any(
            row["name"] == column
            for row in rows
        )

    def _migrate(self):

        migrations = [
            (
                "players",
                "region",
                "ALTER TABLE players ADD COLUMN region TEXT NOT NULL DEFAULT 'No Region'"
            ),
            (
                "players",
                "current_tier",
                "ALTER TABLE players ADD COLUMN current_tier TEXT"
            ),
            (
                "players",
                "total_points",
                "ALTER TABLE players ADD COLUMN total_points INTEGER NOT NULL DEFAULT 0"
            ),
            (
                "players",
                "total_tests",
                "ALTER TABLE players ADD COLUMN total_tests INTEGER NOT NULL DEFAULT 0"
            ),
            (
                "players",
                "updated_at",
                "ALTER TABLE players ADD COLUMN updated_at TEXT"
            ),
            (
                "tickets",
                "close_reason",
                "ALTER TABLE tickets ADD COLUMN close_reason TEXT"
            ),
            (
                "results",
                "corrected_at",
                "ALTER TABLE results ADD COLUMN corrected_at TEXT"
            ),
            (
                "results",
                "corrected_by",
                "ALTER TABLE results ADD COLUMN corrected_by INTEGER"
            ),
        ]

        for table, column, sql in migrations:

            if not self._column_exists(
                table,
                column
            ):

                try:
                    self.conn.execute(sql)
                except sqlite3.OperationalError:
                    pass

    # ==================================================
    # INTEGRITY
    # ==================================================

    def integrity_check(self):

        try:

            row = self.conn.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            return row[0] == "ok"

        except Exception:

            return False

    # ==================================================
    # BACKUP
    # ==================================================

    def backup(self, destination=None):

        if destination is None:

            destination = (
                self.path + ".backup"
            )

        backup_conn = sqlite3.connect(
            destination
        )

        try:

            self.conn.backup(
                backup_conn
            )

        finally:

            backup_conn.close()

        return destination

    # ==================================================
    # SETTINGS
    # ==================================================

    def get_setting(self, key):

        row = self.conn.execute(
            """
            SELECT value
            FROM settings
            WHERE key=?
            """,
            (key,)
        ).fetchone()

        if not row:
            return None

        return row["value"]

    def save_setting(self, key, value):

        now = datetime.now(
            timezone.utc
        ).isoformat()

        with self.transaction():

            self.conn.execute(
                """
                INSERT INTO settings(
                    key,
                    value,
                    updated_at
                )
                VALUES(?, ?, ?)

                ON CONFLICT(key)
                DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (
                    key,
                    str(value),
                    now
                )
            )

    # ==================================================
    # TIER POINTS
    # ==================================================

    def points_for_tier(self, tier):

        return self.TIER_POINTS.get(
            tier.upper(),
            0
        )

    # ==================================================
    # PLAYER
    # ==================================================

    def upsert_player(
        self,
        user_id,
        minecraft_username,
        region="No Region"
    ):

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        with self.transaction():

            self.conn.execute(
                """
                INSERT INTO players(
                    user_id,
                    minecraft_username,
                    region,
                    updated_at
                )
                VALUES(?, ?, ?, ?)

                ON CONFLICT(user_id)
                DO UPDATE SET
                    minecraft_username=excluded.minecraft_username,
                    region=excluded.region,
                    updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    minecraft_username,
                    region or "No Region",
                    timestamp
                )
            )

    def player(self, user_id):

        return self.conn.execute(
            """
            SELECT *
            FROM players
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchone()

    # ==================================================
    # QUEUES
    # ==================================================

    def queue_join(
        self,
        user_id,
        gamemode,
        minecraft_username,
        preferred_server,
        joined_at,
        limit=15
    ):

        minecraft_username = (
            minecraft_username.strip()
        )

        preferred_server = (
            preferred_server.strip()
        )

        if not minecraft_username:
            return False, "invalid_username"

        if not preferred_server:
            return False, "invalid_server"

        with self.transaction():

            existing = self.conn.execute(
                """
                SELECT user_id
                FROM queues
                WHERE user_id=?
                """,
                (user_id,)
            ).fetchone()

            if existing:
                return False, "already_queued"

            count = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM queues
                WHERE gamemode=?
                """,
                (gamemode,)
            ).fetchone()[0]

            if count >= limit:
                return False, "full"

            self.conn.execute(
                """
                INSERT INTO queues(
                    user_id,
                    gamemode,
                    minecraft_username,
                    preferred_server,
                    joined_at
                )
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    gamemode,
                    minecraft_username,
                    preferred_server,
                    joined_at
                )
            )

        return True, "ok"

    def queue_remove(self, user_id):

        with self.transaction():

            self.conn.execute(
                """
                DELETE FROM queues
                WHERE user_id=?
                """,
                (user_id,)
            )

    def queue_remove_mode_user(
        self,
        gamemode,
        user_id
    ):

        with self.transaction():

            self.conn.execute(
                """
                DELETE FROM queues
                WHERE gamemode=?
                AND user_id=?
                """,
                (
                    gamemode,
                    user_id
                )
            )

    def queue_for_user(self, user_id):

        return self.conn.execute(
            """
            SELECT *
            FROM queues
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchone()

    def queues(self, gamemode=None):

        if gamemode:

            return self.conn.execute(
                """
                SELECT *
                FROM queues
                WHERE gamemode=?
                ORDER BY joined_at ASC
                """,
                (gamemode,)
            ).fetchall()

        return self.conn.execute(
            """
            SELECT *
            FROM queues
            ORDER BY joined_at ASC
            """
        ).fetchall()

    def count(self, gamemode):

        return self.conn.execute(
            """
            SELECT COUNT(*)
            FROM queues
            WHERE gamemode=?
            """,
            (gamemode,)
        ).fetchone()[0]

    # ==================================================
    # TICKETS
    # ==================================================

    def active_ticket_for_user(
        self,
        user_id
    ):

        return self.conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE user_id=?
            AND status IN ('waiting', 'testing')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,)
        ).fetchone()

    def ticket_for_user(
        self,
        user_id
    ):

        return self.active_ticket_for_user(
            user_id
        )

    def ticket(self, channel_id):

        return self.conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE channel_id=?
            """,
            (channel_id,)
        ).fetchone()

    def create_ticket(
        self,
        channel_id,
        user_id,
        gamemode,
        minecraft_username,
        preferred_server,
        created_at
    ):

        try:

            with self.transaction():

                self.conn.execute(
                    """
                    INSERT INTO tickets(
                        channel_id,
                        user_id,
                        gamemode,
                        minecraft_username,
                        preferred_server,
                        status,
                        created_at
                    )
                    VALUES(?, ?, ?, ?, ?, 'waiting', ?)
                    """,
                    (
                        channel_id,
                        user_id,
                        gamemode,
                        minecraft_username,
                        preferred_server,
                        created_at
                    )
                )

                self.conn.execute(
                    """
                    INSERT INTO players(
                        user_id,
                        minecraft_username,
                        region,
                        updated_at
                    )
                    VALUES(?, ?, 'No Region', ?)

                    ON CONFLICT(user_id)
                    DO UPDATE SET
                        minecraft_username=excluded.minecraft_username,
                        updated_at=excluded.updated_at
                    """,
                    (
                        user_id,
                        minecraft_username,
                        created_at
                    )
                )

            return True

        except sqlite3.IntegrityError:

            return False

    def claim_ticket(
        self,
        channel_id,
        tester_id,
        claimed_at
    ):

        with self.transaction():

            cursor = self.conn.execute(
                """
                UPDATE tickets
                SET
                    tester_id=?,
                    status='testing',
                    claimed_at=?
                WHERE channel_id=?
                AND status='waiting'
                """,
                (
                    tester_id,
                    claimed_at,
                    channel_id
                )
            )

            return cursor.rowcount == 1

    def close_ticket(
        self,
        channel_id,
        closed_at,
        reason=None
    ):

        with self.transaction():

            self.conn.execute(
                """
                UPDATE tickets
                SET
                    status='closed',
                    closed_at=?,
                    close_reason=?
                WHERE channel_id=?
                AND status!='closed'
                """,
                (
                    closed_at,
                    reason,
                    channel_id
                )
            )

    # ==================================================
    # FINALIZE TEST
    # ==================================================

    def finalize_test(
        self,
        channel_id,
        user_id,
        minecraft_username,
        gamemode,
        tier,
        tester_id,
        points,
        match_score,
        verdict,
        created_at,
        closed_at
    ):

        tier = tier.upper()

        actual_points = self.points_for_tier(
            tier
        )

        if actual_points <= 0:
            return False

        with self.transaction():

            ticket = self.conn.execute(
                """
                SELECT *
                FROM tickets
                WHERE channel_id=?
                AND status='testing'
                AND user_id=?
                AND tester_id=?
                """,
                (
                    channel_id,
                    user_id,
                    tester_id
                )
            ).fetchone()

            if not ticket:
                return False

            self.conn.execute(
                """
                INSERT INTO results(
                    user_id,
                    minecraft_username,
                    gamemode,
                    tier,
                    tester_id,
                    points,
                    match_score,
                    verdict,
                    created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    minecraft_username,
                    gamemode,
                    tier,
                    tester_id,
                    actual_points,
                    match_score,
                    verdict,
                    created_at
                )
            )

            self.conn.execute(
                """
                UPDATE tickets
                SET
                    status='closed',
                    closed_at=?,
                    close_reason='test_completed'
                WHERE channel_id=?
                """,
                (
                    closed_at,
                    channel_id
                )
            )

            self._rebuild_player(
                user_id,
                minecraft_username
            )

        return True

    # ==================================================
    # PLAYER AGGREGATES
    # ==================================================

    def _rebuild_player(
        self,
        user_id,
        minecraft_username=None
    ):

        rows = self.conn.execute(
            """
            SELECT
                tier,
                points,
                created_at
            FROM results
            WHERE user_id=?
            AND corrected=0
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,)
        ).fetchall()

        total_points = sum(
            row["points"]
            for row in rows
        )

        total_tests = len(rows)

        current_tier = (
            rows[0]["tier"]
            if rows
            else None
        )

        if minecraft_username is None:

            existing = self.conn.execute(
                """
                SELECT minecraft_username
                FROM players
                WHERE user_id=?
                """,
                (user_id,)
            ).fetchone()

            minecraft_username = (
                existing["minecraft_username"]
                if existing
                else "Unknown"
            )

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        self.conn.execute(
            """
            INSERT INTO players(
                user_id,
                minecraft_username,
                region,
                current_tier,
                total_points,
                total_tests,
                updated_at
            )
            VALUES(
                ?,
                ?,
                'No Region',
                ?,
                ?,
                ?,
                ?
            )

            ON CONFLICT(user_id)
            DO UPDATE SET
                minecraft_username=excluded.minecraft_username,
                current_tier=excluded.current_tier,
                total_points=excluded.total_points,
                total_tests=excluded.total_tests,
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                minecraft_username,
                current_tier,
                total_points,
                total_tests,
                timestamp
            )
        )

    def rebuild_all_players(self):

        users = self.conn.execute(
            """
            SELECT DISTINCT user_id
            FROM results
            """
        ).fetchall()

        with self.transaction():

            for row in users:

                self._rebuild_player(
                    row["user_id"]
                )

    # ==================================================
    # RESULTS
    # ==================================================

    def latest_results(self, limit=100):

        return self.conn.execute(
            """
            SELECT *
            FROM results
            WHERE corrected=0
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

    def results_for_user(
        self,
        user_id
    ):

        return self.conn.execute(
            """
            SELECT *
            FROM results
            WHERE user_id=?
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,)
        ).fetchall()

    # ==================================================
    # STATS
    # ==================================================

    def stats_player(
        self,
        user_id
    ):

        player = self.conn.execute(
            """
            SELECT
                user_id,
                minecraft_username,
                region,
                current_tier,
                total_points,
                total_tests
            FROM players
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchone()

        if not player:

            return None

        return player

    def stats_gamemodes(
        self,
        user_id
    ):

        rows = self.conn.execute(
            """
            SELECT
                r.*
            FROM results r
            INNER JOIN (
                SELECT
                    gamemode,
                    MAX(id) AS latest_id
                FROM results
                WHERE user_id=?
                AND corrected=0
                GROUP BY gamemode
            ) latest
            ON latest.latest_id = r.id
            WHERE r.user_id=?
            AND r.corrected=0
            """,
            (
                user_id,
                user_id
            )
        ).fetchall()

        return {
            row["gamemode"]: row
            for row in rows
        }

    def global_rank(
        self,
        user_id
    ):

        rows = self.conn.execute(
            """
            SELECT
                user_id,
                SUM(points) AS total_points
            FROM results
            WHERE corrected=0
            GROUP BY user_id
            ORDER BY total_points DESC, user_id ASC
            """
        ).fetchall()

        for index, row in enumerate(
            rows,
            1
        ):

            if row["user_id"] == user_id:
                return index

        return None

    # ==================================================
    # GLOBAL LEADERBOARD
    # ==================================================

    def global_leaderboard(
        self,
        limit=100
    ):

        return self.conn.execute(
            """
            SELECT
                p.user_id,
                p.minecraft_username,
                COALESCE(
                    SUM(r.points),
                    0
                ) AS total_points,
                COUNT(r.id) AS tests
            FROM players p
            LEFT JOIN results r
                ON r.user_id=p.user_id
                AND r.corrected=0
            GROUP BY
                p.user_id
            ORDER BY
                total_points DESC,
                p.user_id ASC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

    # ==================================================
    # GAMEMODE LEADERBOARD
    # ==================================================

    def gamemode_leaderboard(
        self,
        gamemode,
        limit=100
    ):

        return self.conn.execute(
            """
            SELECT
                r.user_id,
                r.minecraft_username,
                MAX(r.points) AS total_points,
                COUNT(r.id) AS tests
            FROM results r
            WHERE r.gamemode=?
            AND r.corrected=0
            GROUP BY r.user_id
            ORDER BY
                total_points DESC,
                r.user_id ASC
            LIMIT ?
            """,
            (
                gamemode,
                limit
            )
        ).fetchall()

    # ==================================================
    # CORRECT RESULT
    # ==================================================

    def correct_result(
        self,
        result_id,
        tier,
        corrected_by=None
    ):

        tier = tier.upper()

        if tier not in self.TIER_POINTS:
            return False

        points = self.points_for_tier(
            tier
        )

        with self.transaction():

            row = self.conn.execute(
                """
                SELECT *
                FROM results
                WHERE id=?
                """,
                (result_id,)
            ).fetchone()

            if not row:
                return False

            timestamp = datetime.now(
                timezone.utc
            ).isoformat()

            self.conn.execute(
                """
                UPDATE results
                SET
                    tier=?,
                    points=?,
                    corrected=1,
                    corrected_at=?,
                    corrected_by=?
                WHERE id=?
                """,
                (
                    tier,
                    points,
                    timestamp,
                    corrected_by,
                    result_id
                )
            )

            # Recalculate the player.
            # Corrected records are excluded from totals.
            self._rebuild_player(
                row["user_id"]
            )

        return True
```

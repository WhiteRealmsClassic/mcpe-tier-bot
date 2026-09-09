import os
import sqlite3
from contextlib import contextmanager


class Database:

    # ======================================================
    # TIER POINTS
    # ======================================================

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

    VALID_STATUSES = {
        "waiting",
        "testing",
        "closed",
        "cancelled",
    }

    # ======================================================
    # INIT
    # ======================================================

    def __init__(self, path):

        self.path = path

        folder = os.path.dirname(path)

        if folder:
            os.makedirs(folder, exist_ok=True)

        self.conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            timeout=30
        )

        self.conn.row_factory = sqlite3.Row

        # SQLite reliability/performance.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        self.setup()

    # ======================================================
    # TRANSACTION
    # ======================================================

    @contextmanager
    def transaction(self):

        self.conn.execute("BEGIN IMMEDIATE")

        try:
            yield
            self.conn.commit()

        except Exception:
            self.conn.rollback()
            raise

    # ======================================================
    # SETUP / MIGRATIONS
    # ======================================================

    def setup(self):

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                minecraft_username TEXT NOT NULL,
                current_tier TEXT,
                current_points INTEGER NOT NULL DEFAULT 0,
                total_tests INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,
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

                points INTEGER NOT NULL DEFAULT 0,

                match_score TEXT NOT NULL DEFAULT 'N/A',
                verdict TEXT NOT NULL DEFAULT '',

                created_at TEXT NOT NULL,

                corrected INTEGER NOT NULL DEFAULT 0,
                corrected_at TEXT,
                corrected_by INTEGER,

                original_tier TEXT,
                original_points INTEGER
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_queue_gamemode
                ON queues(gamemode);

            CREATE INDEX IF NOT EXISTS idx_queue_joined
                ON queues(joined_at);

            CREATE INDEX IF NOT EXISTS idx_ticket_user
                ON tickets(user_id);

            CREATE INDEX IF NOT EXISTS idx_ticket_status
                ON tickets(status);

            CREATE INDEX IF NOT EXISTS idx_ticket_tester
                ON tickets(tester_id);

            CREATE INDEX IF NOT EXISTS idx_results_user
                ON results(user_id);

            CREATE INDEX IF NOT EXISTS idx_results_gamemode
                ON results(gamemode);

            CREATE INDEX IF NOT EXISTS idx_results_tier
                ON results(tier);

            CREATE INDEX IF NOT EXISTS idx_results_created
                ON results(created_at);

            CREATE INDEX IF NOT EXISTS idx_results_points
                ON results(points);
            """
        )

        self._migrate_old_results()

        self._rebuild_player_cache()

        self.conn.commit()

    # ======================================================
    # MIGRATION
    # ======================================================

    def _migrate_old_results(self):

        columns = {
            row["name"]
            for row in self.conn.execute(
                "PRAGMA table_info(results)"
            ).fetchall()
        }

        migrations = {

            "points": """
                ALTER TABLE results
                ADD COLUMN points INTEGER NOT NULL DEFAULT 0
            """,

            "match_score": """
                ALTER TABLE results
                ADD COLUMN match_score TEXT NOT NULL DEFAULT 'N/A'
            """,

            "verdict": """
                ALTER TABLE results
                ADD COLUMN verdict TEXT NOT NULL DEFAULT ''
            """,

            "corrected": """
                ALTER TABLE results
                ADD COLUMN corrected INTEGER NOT NULL DEFAULT 0
            """,

            "corrected_at": """
                ALTER TABLE results
                ADD COLUMN corrected_at TEXT
            """,

            "corrected_by": """
                ALTER TABLE results
                ADD COLUMN corrected_by INTEGER
            """,

            "original_tier": """
                ALTER TABLE results
                ADD COLUMN original_tier TEXT
            """,

            "original_points": """
                ALTER TABLE results
                ADD COLUMN original_points INTEGER
            """
        }

        for column, sql in migrations.items():

            if column not in columns:

                self.conn.execute(sql)

        # Repair old results whose point value may be wrong.
        rows = self.conn.execute(
            """
            SELECT id, tier, points
            FROM results
            """
        ).fetchall()

        for row in rows:

            tier = self.normalize_tier(row["tier"])

            points = self.points_for_tier(tier)

            if points is None:
                continue

            if row["points"] != points:

                self.conn.execute(
                    """
                    UPDATE results
                    SET
                        tier=?,
                        points=?
                    WHERE id=?
                    """,
                    (
                        tier,
                        points,
                        row["id"]
                    )
                )

    # ======================================================
    # PLAYER CACHE
    # ======================================================

    def _rebuild_player_cache(self):

        self.conn.execute(
            "DELETE FROM players"
        )

        users = self.conn.execute(
            """
            SELECT
                user_id,
                minecraft_username,
                created_at
            FROM results
            ORDER BY id ASC
            """
        ).fetchall()

        if not users:
            return

        grouped = {}

        for row in users:

            grouped[row["user_id"]] = row

        for user_id in grouped:

            latest = self.conn.execute(
                """
                SELECT
                    minecraft_username,
                    tier,
                    points,
                    created_at
                FROM results
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id,)
            ).fetchone()

            stats = self.conn.execute(
                """
                SELECT
                    COALESCE(SUM(points), 0) AS total_points,
                    COUNT(*) AS total_tests
                FROM results
                WHERE user_id=?
                """,
                (user_id,)
            ).fetchone()

            first = self.conn.execute(
                """
                SELECT created_at
                FROM results
                WHERE user_id=?
                ORDER BY id ASC
                LIMIT 1
                """,
                (user_id,)
            ).fetchone()

            self.conn.execute(
                """
                INSERT INTO players(
                    user_id,
                    minecraft_username,
                    current_tier,
                    current_points,
                    total_tests,
                    first_seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    latest["minecraft_username"],
                    latest["tier"],
                    stats["total_points"],
                    stats["total_tests"],
                    first["created_at"],
                    latest["created_at"]
                )
            )

    # ======================================================
    # NORMALIZATION
    # ======================================================

    @classmethod
    def normalize_tier(cls, tier):

        if tier is None:
            return None

        tier = str(tier).strip().upper()

        if tier not in cls.TIER_POINTS:
            return None

        return tier

    @classmethod
    def points_for_tier(cls, tier):

        tier = cls.normalize_tier(tier)

        if tier is None:
            return None

        return cls.TIER_POINTS[tier]

    # ======================================================
    # PLAYER
    # ======================================================

    def upsert_player(
        self,
        user_id,
        minecraft_username,
        timestamp
    ):

        with self.transaction():

            existing = self.conn.execute(
                """
                SELECT 1
                FROM players
                WHERE user_id=?
                """,
                (user_id,)
            ).fetchone()

            if existing:

                self.conn.execute(
                    """
                    UPDATE players
                    SET
                        minecraft_username=?,
                        updated_at=?
                    WHERE user_id=?
                    """,
                    (
                        minecraft_username,
                        timestamp,
                        user_id
                    )
                )

            else:

                self.conn.execute(
                    """
                    INSERT INTO players(
                        user_id,
                        minecraft_username,
                        current_tier,
                        current_points,
                        total_tests,
                        first_seen_at,
                        updated_at
                    )
                    VALUES (?, ?, NULL, 0, 0, ?, ?)
                    """,
                    (
                        user_id,
                        minecraft_username,
                        timestamp,
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

    # ======================================================
    # QUEUES
    # ======================================================

    def queue_join(
        self,
        user_id,
        gamemode,
        minecraft_username,
        preferred_server,
        joined_at,
        limit=15
    ):

        gamemode = str(gamemode).strip()
        minecraft_username = minecraft_username.strip()
        preferred_server = preferred_server.strip()

        if not minecraft_username:
            return False, "invalid_username"

        if not preferred_server:
            return False, "invalid_server"

        with self.transaction():

            existing = self.conn.execute(
                """
                SELECT 1
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
                VALUES (?, ?, ?, ?, ?)
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

            cursor = self.conn.execute(
                """
                DELETE FROM queues
                WHERE user_id=?
                """,
                (user_id,)
            )

            return cursor.rowcount == 1

    def queue_remove_mode_user(
        self,
        gamemode,
        user_id
    ):

        with self.transaction():

            cursor = self.conn.execute(
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

            return cursor.rowcount == 1

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

    # ======================================================
    # TICKETS
    # ======================================================

    def active_ticket_for_user(self, user_id):

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

    def ticket_for_user(self, user_id):

        return self.active_ticket_for_user(user_id)

    def create_ticket(
        self,
        channel_id,
        user_id,
        gamemode,
        minecraft_username,
        preferred_server,
        created_at
    ):

        with self.transaction():

            existing = self.conn.execute(
                """
                SELECT 1
                FROM tickets
                WHERE user_id=?
                AND status IN ('waiting', 'testing')
                LIMIT 1
                """,
                (user_id,)
            ).fetchone()

            if existing:
                return False

            self.conn.execute(
                """
                INSERT INTO tickets(
                    channel_id,
                    user_id,
                    gamemode,
                    minecraft_username,
                    preferred_server,
                    tester_id,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, 'waiting', ?)
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

        return True

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

    def ticket(self, channel_id):

        return self.conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE channel_id=?
            """,
            (channel_id,)
        ).fetchone()

    def close_ticket(
        self,
        channel_id,
        closed_at,
        reason="closed"
    ):

        with self.transaction():

            cursor = self.conn.execute(
                """
                UPDATE tickets
                SET
                    status='closed',
                    closed_at=?,
                    close_reason=?
                WHERE channel_id=?
                AND status != 'closed'
                """,
                (
                    closed_at,
                    reason,
                    channel_id
                )
            )

            return cursor.rowcount == 1

    # ======================================================
    # FINALIZE TEST
    # ======================================================

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

        tier = self.normalize_tier(tier)

        if tier is None:
            return False

        automatic_points = self.points_for_tier(
            tier
        )

        if automatic_points is None:
            return False

        # NEVER trust points supplied by Discord/modal code.
        points = automatic_points

        with self.transaction():

            ticket = self.conn.execute(
                """
                SELECT *
                FROM tickets
                WHERE channel_id=?
                AND status='testing'
                """,
                (channel_id,)
            ).fetchone()

            if not ticket:
                return False

            if ticket["user_id"] != user_id:
                return False

            if ticket["tester_id"] != tester_id:
                return False

            cursor = self.conn.execute(
                """
                UPDATE tickets
                SET
                    status='closed',
                    closed_at=?,
                    close_reason='test_completed'
                WHERE channel_id=?
                AND status='testing'
                AND tester_id=?
                """,
                (
                    closed_at,
                    channel_id,
                    tester_id
                )
            )

            if cursor.rowcount != 1:
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    minecraft_username,
                    gamemode,
                    tier,
                    tester_id,
                    automatic_points,
                    match_score,
                    verdict,
                    created_at
                )
            )

            # Update player cache.
            stats = self.conn.execute(
                """
                SELECT
                    COALESCE(SUM(points), 0) AS total_points,
                    COUNT(*) AS total_tests
                FROM results
                WHERE user_id=?
                """,
                (user_id,)
            ).fetchone()

            existing = self.conn.execute(
                """
                SELECT 1
                FROM players
                WHERE user_id=?
                """,
                (user_id,)
            ).fetchone()

            if existing:

                self.conn.execute(
                    """
                    UPDATE players
                    SET
                        minecraft_username=?,
                        current_tier=?,
                        current_points=?,
                        total_tests=?,
                        updated_at=?
                    WHERE user_id=?
                    """,
                    (
                        minecraft_username,
                        tier,
                        automatic_points,
                        stats["total_tests"],
                        created_at,
                        user_id
                    )
                )

            else:

                self.conn.execute(
                    """
                    INSERT INTO players(
                        user_id,
                        minecraft_username,
                        current_tier,
                        current_points,
                        total_tests,
                        first_seen_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        minecraft_username,
                        tier,
                        automatic_points,
                        stats["total_tests"],
                        created_at,
                        created_at
                    )
                )

        return True

    # ======================================================
    # RESULTS
    # ======================================================

    def latest_results(self):

        return self.conn.execute(
            """
            SELECT *
            FROM results
            ORDER BY id DESC
            """
        ).fetchall()

    def results_for_user(self, user_id):

        return self.conn.execute(
            """
            SELECT *
            FROM results
            WHERE user_id=?
            ORDER BY id DESC
            """,
            (user_id,)
        ).fetchall()

    def result(self, result_id):

        return self.conn.execute(
            """
            SELECT *
            FROM results
            WHERE id=?
            """,
            (result_id,)
        ).fetchone()

    # ======================================================
    # GLOBAL LEADERBOARD
    # ======================================================

    def global_leaderboard(self):

        return self.conn.execute(
            """
            SELECT
                user_id,
                MAX(minecraft_username) AS minecraft_username,
                SUM(points) AS total_points,
                COUNT(*) AS tests
            FROM results
            GROUP BY user_id
            ORDER BY
                total_points DESC,
                tests DESC,
                minecraft_username ASC
            """
        ).fetchall()

    def global_rank_for_user(self, user_id):

        rows = self.global_leaderboard()

        for position, row in enumerate(
            rows,
            start=1
        ):

            if row["user_id"] == user_id:

                return {
                    "rank": position,
                    "user_id": row["user_id"],
                    "minecraft_username": row["minecraft_username"],
                    "total_points": row["total_points"],
                    "tests": row["tests"]
                }

        return None

    def global_points_for_user(self, user_id):

        result = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(points), 0)
                AS total_points
            FROM results
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchone()

        return result["total_points"]

    # ======================================================
    # GAMEMODE LEADERBOARD
    # ======================================================

    def gamemode_leaderboard(
        self,
        gamemode
    ):

        return self.conn.execute(
            """
            SELECT
                user_id,
                MAX(minecraft_username) AS minecraft_username,
                SUM(points) AS total_points,
                COUNT(*) AS tests
            FROM results
            WHERE gamemode=?
            GROUP BY user_id
            ORDER BY
                total_points DESC,
                tests DESC,
                minecraft_username ASC
            """,
            (gamemode,)
        ).fetchall()

    # ======================================================
    # CORRECT RESULT
    # ======================================================

    def correct_result(
        self,
        result_id,
        tier,
        corrected_by=None,
        corrected_at=None
    ):

        tier = self.normalize_tier(tier)

        if tier is None:
            return False

        automatic_points = self.points_for_tier(
            tier
        )

        with self.transaction():

            old = self.conn.execute(
                """
                SELECT *
                FROM results
                WHERE id=?
                """,
                (result_id,)
            ).fetchone()

            if not old:
                return False

            original_tier = (
                old["original_tier"]
                or old["tier"]
            )

            original_points = (
                old["original_points"]
                if old["original_points"] is not None
                else old["points"]
            )

            self.conn.execute(
                """
                UPDATE results
                SET
                    tier=?,
                    points=?,
                    corrected=1,
                    corrected_at=?,
                    corrected_by=?,
                    original_tier=?,
                    original_points=?
                WHERE id=?
                """,
                (
                    tier,
                    automatic_points,
                    corrected_at,
                    corrected_by,
                    original_tier,
                    original_points,
                    result_id
                )
            )

            # Recalculate player's cached data.
            user_id = old["user_id"]

            stats = self.conn.execute(
                """
                SELECT
                    COALESCE(SUM(points), 0) AS total_points,
                    COUNT(*) AS total_tests
                FROM results
                WHERE user_id=?
                """,
                (user_id,)
            ).fetchone()

            latest = self.conn.execute(
                """
                SELECT
                    minecraft_username,
                    tier,
                    created_at
                FROM results
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id,)
            ).fetchone()

            if latest:

                self.conn.execute(
                    """
                    UPDATE players
                    SET
                        minecraft_username=?,
                        current_tier=?,
                        current_points=?,
                        total_tests=?,
                        updated_at=?
                    WHERE user_id=?
                    """,
                    (
                        latest["minecraft_username"],
                        latest["tier"],
                        stats["total_points"],
                        stats["total_tests"],
                        corrected_at or latest["created_at"],
                        user_id
                    )
                )

        return True

    # ======================================================
    # DATABASE HEALTH
    # ======================================================

    def integrity_check(self):

        return self.conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

    def vacuum(self):

        self.conn.execute(
            "VACUUM"
        )

    # ======================================================
    # CLOSE
    # ======================================================

    def close(self):

        try:
            self.conn.commit()
        finally:
            self.conn.close()

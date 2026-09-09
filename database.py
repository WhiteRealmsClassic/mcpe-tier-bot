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

    def __init__(self, path):
        self.path = path

        folder = os.path.dirname(path)

        if folder:
            os.makedirs(folder, exist_ok=True)

        self.conn = sqlite3.connect(
            self.path,
            check_same_thread=False
        )

        self.conn.row_factory = sqlite3.Row

        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

        self.setup()

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")

        try:
            yield
            self.conn.commit()

        except Exception:
            self.conn.rollback()
            raise

    def setup(self):

        self.conn.executescript(
            """
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
                closed_at TEXT
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
                corrected INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        # --------------------------------------------------
        # Upgrade old databases
        # --------------------------------------------------

        columns = {
            row["name"]
            for row in self.conn.execute(
                "PRAGMA table_info(results)"
            ).fetchall()
        }

        if "points" not in columns:
            self.conn.execute(
                """
                ALTER TABLE results
                ADD COLUMN points INTEGER NOT NULL DEFAULT 0
                """
            )

        if "match_score" not in columns:
            self.conn.execute(
                """
                ALTER TABLE results
                ADD COLUMN match_score TEXT NOT NULL DEFAULT 'N/A'
                """
            )

        if "verdict" not in columns:
            self.conn.execute(
                """
                ALTER TABLE results
                ADD COLUMN verdict TEXT NOT NULL DEFAULT ''
                """
            )

        if "corrected" not in columns:
            self.conn.execute(
                """
                ALTER TABLE results
                ADD COLUMN corrected INTEGER NOT NULL DEFAULT 0
                """
            )

        self.conn.commit()

    # ======================================================
    # POINT HELPERS
    # ======================================================

    @classmethod
    def points_for_tier(cls, tier):
        """
        Return the automatic point value for a tier.

        Example:
            LT5 -> 100
            LT4 -> 400
            HT1 -> 1500
        """

        if not tier:
            return None

        tier = str(tier).strip().upper()

        return cls.TIER_POINTS.get(tier)

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
        limit=10
    ):

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
        closed_at
    ):

        with self.transaction():

            self.conn.execute(
                """
                UPDATE tickets
                SET
                    status='closed',
                    closed_at=?
                WHERE channel_id=?
                AND status != 'closed'
                """,
                (
                    closed_at,
                    channel_id
                )
            )

    # ======================================================
    # RESULT SUBMISSION
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
        """
        Atomically completes the ticket and creates the result.

        Points are ALWAYS calculated from the tier here.
        The supplied points argument is intentionally ignored.
        """

        tier = str(tier).strip().upper()

        automatic_points = self.points_for_tier(tier)

        if automatic_points is None:
            return False

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

            cursor = self.conn.execute(
                """
                UPDATE tickets
                SET
                    status='closed',
                    closed_at=?
                WHERE channel_id=?
                AND status='testing'
                """,
                (
                    closed_at,
                    channel_id
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

    # ======================================================
    # GLOBAL LEADERBOARD
    # ======================================================

    def global_leaderboard(self):

        return self.conn.execute(
            """
            SELECT
                user_id,
                minecraft_username,
                SUM(points) AS total_points,
                COUNT(*) AS tests
            FROM results
            GROUP BY user_id, minecraft_username
            ORDER BY
                total_points DESC,
                tests DESC,
                minecraft_username ASC
            """
        ).fetchall()

    def global_rank_for_user(self, user_id):

        rows = self.global_leaderboard()

        for position, row in enumerate(rows, start=1):

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

    def gamemode_leaderboard(self, gamemode):

        return self.conn.execute(
            """
            SELECT
                user_id,
                minecraft_username,
                SUM(points) AS total_points,
                COUNT(*) AS tests
            FROM results
            WHERE gamemode=?
            GROUP BY user_id, minecraft_username
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
        tier
    ):

        tier = str(tier).strip().upper()

        automatic_points = self.points_for_tier(tier)

        if automatic_points is None:
            return False

        with self.transaction():

            cursor = self.conn.execute(
                """
                UPDATE results
                SET
                    tier=?,
                    points=?,
                    corrected=1
                WHERE id=?
                """,
                (
                    tier,
                    automatic_points,
                    result_id
                )
            )

            return cursor.rowcount == 1

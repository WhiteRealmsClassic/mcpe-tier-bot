import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor


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

    def __init__(self, database_url=None):

        self.database_url = (
            database_url
            or os.getenv("DATABASE_URL")
        )

        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL environment variable is missing."
            )

        self.pool = pool.SimpleConnectionPool(
            1,
            5,
            self.database_url,
            sslmode="require"
        )

        self.setup()

    # ======================================================
    # CONNECTION
    # ======================================================

    @contextmanager
    def connection(self):

        conn = self.pool.getconn()

        try:
            yield conn

        finally:
            self.pool.putconn(conn)

    @contextmanager
    def transaction(self):

        with self.connection() as conn:

            try:

                yield conn

                conn.commit()

            except Exception:

                conn.rollback()
                raise

    def fetchone(
        self,
        query,
        params=()
    ):

        with self.connection() as conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute(
                    query,
                    params
                )

                return cursor.fetchone()

    def fetchall(
        self,
        query,
        params=()
    ):

        with self.connection() as conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute(
                    query,
                    params
                )

                return cursor.fetchall()

    # ======================================================
    # SETUP
    # ======================================================

    def setup(self):

        with self.transaction() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS queues (
                        user_id BIGINT PRIMARY KEY,
                        gamemode TEXT NOT NULL,
                        minecraft_username TEXT NOT NULL,
                        preferred_server TEXT NOT NULL,
                        joined_at TIMESTAMPTZ NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS
                    idx_queues_gamemode
                    ON queues(gamemode);

                    CREATE TABLE IF NOT EXISTS tickets (
                        channel_id BIGINT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        gamemode TEXT NOT NULL,
                        minecraft_username TEXT NOT NULL,
                        preferred_server TEXT NOT NULL,
                        tester_id BIGINT,
                        status TEXT NOT NULL DEFAULT 'waiting',
                        created_at TIMESTAMPTZ NOT NULL,
                        claimed_at TIMESTAMPTZ,
                        closed_at TIMESTAMPTZ
                    );

                    CREATE INDEX IF NOT EXISTS
                    idx_tickets_user_status
                    ON tickets(user_id, status);

                    CREATE TABLE IF NOT EXISTS results (
                        id BIGSERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        minecraft_username TEXT NOT NULL,
                        gamemode TEXT NOT NULL,
                        tier TEXT NOT NULL,
                        tester_id BIGINT NOT NULL,
                        points INTEGER NOT NULL DEFAULT 0,
                        match_score TEXT NOT NULL DEFAULT 'N/A',
                        verdict TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL,
                        corrected BOOLEAN NOT NULL DEFAULT FALSE
                    );

                    CREATE INDEX IF NOT EXISTS
                    idx_results_user
                    ON results(user_id);

                    CREATE INDEX IF NOT EXISTS
                    idx_results_gamemode
                    ON results(gamemode);

                    CREATE INDEX IF NOT EXISTS
                    idx_results_points
                    ON results(points DESC);

                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    """
                )

    # ======================================================
    # POINT HELPERS
    # ======================================================

    @classmethod
    def points_for_tier(cls, tier):

        if not tier:
            return None

        tier = str(
            tier
        ).strip().upper()

        return cls.TIER_POINTS.get(
            tier
        )

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

        with self.transaction() as conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute(
                    """
                    SELECT 1
                    FROM queues
                    WHERE user_id=%s
                    """,
                    (user_id,)
                )

                if cursor.fetchone():
                    return False, "already_queued"

                cursor.execute(
                    """
                    SELECT COUNT(*)
                    AS count
                    FROM queues
                    WHERE gamemode=%s
                    """,
                    (gamemode,)
                )

                count = cursor.fetchone()["count"]

                if count >= limit:
                    return False, "full"

                cursor.execute(
                    """
                    INSERT INTO queues(
                        user_id,
                        gamemode,
                        minecraft_username,
                        preferred_server,
                        joined_at
                    )
                    VALUES(
                        %s, %s, %s, %s, %s
                    )
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

    def queue_remove(
        self,
        user_id
    ):

        with self.transaction() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    DELETE FROM queues
                    WHERE user_id=%s
                    """,
                    (user_id,)
                )

    def queue_remove_mode_user(
        self,
        gamemode,
        user_id
    ):

        with self.transaction() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    DELETE FROM queues
                    WHERE gamemode=%s
                    AND user_id=%s
                    """,
                    (
                        gamemode,
                        user_id
                    )
                )

    def queues(
        self,
        gamemode=None
    ):

        if gamemode:

            return self.fetchall(
                """
                SELECT *
                FROM queues
                WHERE gamemode=%s
                ORDER BY joined_at ASC
                """,
                (gamemode,)
            )

        return self.fetchall(
            """
            SELECT *
            FROM queues
            ORDER BY joined_at ASC
            """
        )

    def count(
        self,
        gamemode
    ):

        row = self.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM queues
            WHERE gamemode=%s
            """,
            (gamemode,)
        )

        return row["count"]

    # ======================================================
    # TICKETS
    # ======================================================

    def active_ticket_for_user(
        self,
        user_id
    ):

        return self.fetchone(
            """
            SELECT *
            FROM tickets
            WHERE user_id=%s
            AND status IN ('waiting', 'testing')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,)
        )

    def ticket_for_user(
        self,
        user_id
    ):

        return self.active_ticket_for_user(
            user_id
        )

    def create_ticket(
        self,
        channel_id,
        user_id,
        gamemode,
        minecraft_username,
        preferred_server,
        created_at
    ):

        with self.transaction() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
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
                    VALUES(
                        %s, %s, %s, %s, %s,
                        NULL, 'waiting', %s
                    )
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

        with self.transaction() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    UPDATE tickets
                    SET
                        tester_id=%s,
                        status='testing',
                        claimed_at=%s
                    WHERE channel_id=%s
                    AND status='waiting'
                    """,
                    (
                        tester_id,
                        claimed_at,
                        channel_id
                    )
                )

                return cursor.rowcount == 1

    def ticket(
        self,
        channel_id
    ):

        return self.fetchone(
            """
            SELECT *
            FROM tickets
            WHERE channel_id=%s
            """,
            (channel_id,)
        )

    def close_ticket(
        self,
        channel_id,
        closed_at
    ):

        with self.transaction() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    UPDATE tickets
                    SET
                        status='closed',
                        closed_at=%s
                    WHERE channel_id=%s
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

        tier = str(
            tier
        ).strip().upper()

        automatic_points = (
            self.points_for_tier(tier)
        )

        if automatic_points is None:
            return False

        with self.transaction() as conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                # ------------------------------------------
                # Lock ticket
                # ------------------------------------------

                cursor.execute(
                    """
                    SELECT *
                    FROM tickets
                    WHERE channel_id=%s
                    AND status='testing'
                    FOR UPDATE
                    """,
                    (channel_id,)
                )

                ticket = cursor.fetchone()

                if not ticket:
                    return False

                # ------------------------------------------
                # Close ticket
                # ------------------------------------------

                cursor.execute(
                    """
                    UPDATE tickets
                    SET
                        status='closed',
                        closed_at=%s
                    WHERE channel_id=%s
                    AND status='testing'
                    """,
                    (
                        closed_at,
                        channel_id
                    )
                )

                if cursor.rowcount != 1:
                    return False

                # ------------------------------------------
                # Save result
                # ------------------------------------------

                cursor.execute(
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
                    VALUES(
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
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

        return self.fetchall(
            """
            SELECT *
            FROM results
            ORDER BY id DESC
            """
        )

    def results_for_user(
        self,
        user_id
    ):

        return self.fetchall(
            """
            SELECT *
            FROM results
            WHERE user_id=%s
            ORDER BY id DESC
            """,
            (user_id,)
        )

    # ======================================================
    # GLOBAL LEADERBOARD
    # ======================================================

    def global_leaderboard(self):

        return self.fetchall(
            """
            SELECT
                user_id,
                MAX(minecraft_username)
                    AS minecraft_username,
                SUM(points)
                    AS total_points,
                COUNT(*) AS tests
            FROM results
            GROUP BY user_id
            ORDER BY
                total_points DESC,
                tests DESC,
                minecraft_username ASC
            """
        )

    def global_rank_for_user(
        self,
        user_id
    ):

        rows = self.global_leaderboard()

        for position, row in enumerate(
            rows,
            start=1
        ):

            if row["user_id"] == user_id:

                return {
                    "rank": position,
                    "user_id": row["user_id"],
                    "minecraft_username":
                        row["minecraft_username"],
                    "total_points":
                        row["total_points"],
                    "tests":
                        row["tests"]
                }

        return None

    def global_points_for_user(
        self,
        user_id
    ):

        row = self.fetchone(
            """
            SELECT
                COALESCE(
                    SUM(points),
                    0
                ) AS total_points
            FROM results
            WHERE user_id=%s
            """,
            (user_id,)
        )

        return row["total_points"]

    # ======================================================
    # GAMEMODE LEADERBOARD
    # ======================================================

    def gamemode_leaderboard(
        self,
        gamemode
    ):

        return self.fetchall(
            """
            SELECT
                user_id,
                MAX(minecraft_username)
                    AS minecraft_username,
                SUM(points)
                    AS total_points,
                COUNT(*) AS tests
            FROM results
            WHERE gamemode=%s
            GROUP BY user_id
            ORDER BY
                total_points DESC,
                tests DESC,
                minecraft_username ASC
            """,
            (gamemode,)
        )

    # ======================================================
    # CORRECT RESULT
    # ======================================================

    def correct_result(
        self,
        result_id,
        tier
    ):

        tier = str(
            tier
        ).strip().upper()

        automatic_points = (
            self.points_for_tier(tier)
        )

        if automatic_points is None:
            return False

        with self.transaction() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    UPDATE results
                    SET
                        tier=%s,
                        points=%s,
                        corrected=TRUE
                    WHERE id=%s
                    """,
                    (
                        tier,
                        automatic_points,
                        result_id
                    )
                )

                return cursor.rowcount == 1

    # ======================================================
    # SETTINGS
    # ======================================================

    def get_setting(
        self,
        key
    ):

        row = self.fetchone(
            """
            SELECT value
            FROM settings
            WHERE key=%s
            """,
            (key,)
        )

        if not row:
            return None

        return row["value"]

    def set_setting(
        self,
        key,
        value
    ):

        with self.transaction() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    INSERT INTO settings(
                        key,
                        value
                    )
                    VALUES(%s, %s)
                    ON CONFLICT(key)
                    DO UPDATE SET
                        value=EXCLUDED.value
                    """,
                    (
                        key,
                        str(value)
                    )
                )

    # ======================================================
    # MESSAGE IDs
    # ======================================================

    def get_message_id(
        self,
        key
    ):

        value = self.get_setting(key)

        if value is None:
            return None

        try:
            return int(value)

        except (
            ValueError,
            TypeError
        ):
            return None

    def save_message_id(
        self,
        key,
        message_id
    ):

        self.set_setting(
            key,
            message_id
        )

    # ======================================================
    # CLOSE
    # ======================================================

    def close(self):

        if self.pool:
            self.pool.closeall()

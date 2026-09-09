import os
import sqlite3
from contextlib import contextmanager


class Database:

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

        self.conn.commit()

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

        Only a ticket currently in 'testing' state can be
        finalized. This prevents duplicate result submissions.
        """

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
                    points,
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

    def correct_result(
        self,
        result_id,
        tier
    ):

        with self.transaction():

            self.conn.execute(
                """
                UPDATE results
                SET
                    tier=?,
                    corrected=1
                WHERE id=?
                """,
                (
                    tier,
                    result_id
                )
            )
import os

from dotenv import load_dotenv


load_dotenv()


# ======================================================
# ENV HELPER
# ======================================================

def req(name: str) -> int:

    value = os.getenv(
        name,
        "0"
    )

    try:

        return int(value)

    except ValueError:

        raise RuntimeError(
            f"{name} must be an integer"
        )


# ======================================================
# DISCORD
# ======================================================

TOKEN = os.getenv(
    "DISCORD_TOKEN",
    ""
)

GUILD_ID = req(
    "GUILD_ID"
)

TESTER_ROLE_ID = req(
    "TESTER_ROLE_ID"
)

STAFF_ROLE_ID = req(
    "STAFF_ROLE_ID"
)


# ======================================================
# CHANNELS
# ======================================================

APPLY_CHANNEL_ID = req(
    "APPLY_CHANNEL_ID"
)

QUEUE_CHANNEL_ID = req(
    "QUEUE_CHANNEL_ID"
)

RESULTS_CHANNEL_ID = req(
    "RESULTS_CHANNEL_ID"
)

LEADERBOARD_CHANNEL_ID = req(
    "LEADERBOARD_CHANNEL_ID"
)


# ======================================================
# TICKETS
# ======================================================

TICKET_CATEGORY_ID = req(
    "TICKET_CATEGORY_ID"
)

AUDIT_CHANNEL_ID = req(
    "AUDIT_CHANNEL_ID"
)

TICKET_CLOSE_DELAY = int(
    os.getenv(
        "TICKET_CLOSE_DELAY",
        "10"
    )
)


# ======================================================
# SERVER
# ======================================================

SERVER_LOGO_URL = os.getenv(
    "SERVER_LOGO_URL",
    ""
)


# ======================================================
# TTS
# ======================================================

TTS_ENABLED = os.getenv(
    "TTS_ENABLED",
    "true"
).lower() in (
    "true",
    "1",
    "yes",
    "on"
)

# Indian English male
TTS_VOICE = os.getenv(
    "TTS_VOICE",
    "en-IN-PrabhatNeural"
)

TTS_RATE = os.getenv(
    "TTS_RATE",
    "+0%"
)

TTS_VOLUME = os.getenv(
    "TTS_VOLUME",
    "+0%"
)

TTS_PITCH = os.getenv(
    "TTS_PITCH",
    "+0Hz"
)


# ======================================================
# VALIDATION
# ======================================================

if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN is missing"
    )


# ======================================================
# GAMEMODES
# ======================================================

GAMEMODES = {

    "axe": (
        "AXE PVP",
        "axe~1",
        1547043910214226050,
        1519551160803917914
    ),

    "cart": (
        "CART PVP",
        "cart",
        1547037441398149120,
        1519551160803917914
    ),

    "dia": (
        "DIA KIT",
        "diasmp",
        1547037463988674680,
        1519551160803917914
    ),

    "emace": (
        "E-MACE",
        "emace",
        1547037388197339187,
        1519551160803917914
    ),

    "netpot": (
        "NETPOT",
        "netpot",
        1547037320413323294,
        1519551112074756179
    ),

    "smp": (
        "SMP KIT",
        "smpkit",
        1547037590409056266,
        1519551160803917914
    ),

    "spear": (
        "SPEAR MACE",
        "soearmace",
        1547037363329306745,
        1519551160803917914
    ),

    "tank": (
        "TANK",
        "tank",
        1547037340789117041,
        1519551112074756179
    ),

    "uhc": (
        "UHC",
        "uhc",
        1547037410238664795,
        1519551160803917914
    ),

    "crystal": (
        "VANILLA CRYSTAL",
        "crystal",
        1547037297180938311,
        1519551160803917914
    ),
}


# ======================================================
# TIERS
# ======================================================

TIERS = [
    "HT1",
    "MT1",
    "LT1",

    "HT2",
    "MT2",
    "LT2",

    "HT3",
    "MT3",
    "LT3",

    "HT4",
    "MT4",
    "LT4",

    "HT5",
    "MT5",
    "LT5",
]


TIER_RANK = {
    tier: i
    for i, tier in enumerate(
        TIERS
    )
}


TIER_POINTS = {
    tier: (
        len(TIERS) - rank
    ) * 100

    for tier, rank in TIER_RANK.items()
}

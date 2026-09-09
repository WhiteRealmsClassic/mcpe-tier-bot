# MCPE Tier Testing Discord Bot

Python + discord.py bot for a Minecraft Bedrock/MCPE PvP tier-testing server.

## Included
- MCPE-only gamemodes
- 10-player cap per gamemode
- One active queue per player
- Persistent Queue button panel
- Gamemode dropdown
- Minecraft username + preferred server modal
- Private test tickets
- Tester claim with race-safe database update
- HT1/MT1/LT1 through HT5/MT5/LT5 results
- Tier role replacement using role names
- Results channel embeds
- Live queue list with the supplied custom emojis
- Live leaderboard
- SQLite persistence + WAL mode
- Restart-safe queues, tickets and results
- Staff commands: `/setup`, `/force-remove`, `/player-results`, `/close-ticket`
- Optional audit log channel

## Setup
1. Install Python 3.11+.
2. Run `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and fill in IDs/token.
4. Create the Discord roles named exactly `HT1`, `MT1`, `LT1`, ..., `HT5`, `MT5`, `LT5` if you want automatic tier roles.
5. Invite the bot with the required scopes/permissions: View Channels, Send Messages, Embed Links, Read Message History, Manage Channels, Manage Roles, and Use Application Commands.
6. Put the bot's role above the tier roles.
7. Run `python main.py`.
8. Run `/setup` as staff.

## Important Discord setup
The bot needs access to all configured channels. The ticket category must allow the bot to create channels. Testers/staff are granted access through their configured roles.

The exact queue line format is:
`separator | gamemode emoji NAME- count/10 progress`

Example:
`<:1000063781:1519551160803917914> | <:axe~1:1537313629496676412> AXE PVP- 2/10 ■■□□□□□□□□`

## Security/robustness notes
- Queue insertion and the 10-player capacity check occur in one SQLite write transaction.
- Tester claiming is an atomic conditional update, so two testers cannot both claim the same waiting ticket.
- If ticket creation fails after queue insertion, the queue entry is rolled back.
- Database survives bot restarts.
- Do not commit `.env` or the SQLite database to Git.
run SSL_CERT_FILE=$(/usr/local/bin/python3.14 -c "import certifi; print(certifi.where())") \
SSL_CERT_DIR="" \
/usr/local/bin/python3.14 \
/Users/ritvikchaudhry/Desktop/mcpe-tier-bot/main.py
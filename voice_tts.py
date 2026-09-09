import asyncio
import os
import tempfile
import uuid

import discord
import edge_tts
import imageio_ffmpeg

from config import GUILD_ID


# ============================================================
# CONFIG
# ============================================================

TTS_CHANNEL_ID = 1319664272334393388


# ============================================================
# VOICE TTS
# ============================================================

class VoiceTTS:

    def __init__(
        self,
        bot,
        voice="en-IN-PrabhatNeural",
        rate="+0%",
        volume="+0%",
        pitch="+0Hz"
    ):

        self.bot = bot

        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch

        self.queues = {}
        self.locks = {}
        self.workers = {}

    # ========================================================
    # GET GUILD
    # ========================================================

    def get_guild(self):

        guild = self.bot.get_guild(
            GUILD_ID
        )

        if guild is None:

            print(
                f"[TTS] ERROR: Guild {GUILD_ID} "
                f"was not found in cache."
            )

            return None

        return guild

    # ========================================================
    # GET VOICE CHANNEL
    # ========================================================

    def get_tts_channel(self):

        guild = self.get_guild()

        if guild is None:
            return None

        channel = guild.get_channel(
            TTS_CHANNEL_ID
        )

        if channel is None:

            print(
                f"[TTS] ERROR: Voice channel "
                f"{TTS_CHANNEL_ID} was not found."
            )

            print(
                "[TTS] Trying API fetch..."
            )

            return None

        if not isinstance(
            channel,
            discord.VoiceChannel
        ):

            print(
                f"[TTS] ERROR: Channel {TTS_CHANNEL_ID} "
                f"is not a normal VoiceChannel."
            )

            print(
                f"[TTS] Actual type: "
                f"{type(channel).__name__}"
            )

            return None

        print(
            f"[TTS] Target VC found: "
            f"{channel.name} ({channel.id})"
        )

        return channel

    # ========================================================
    # GET CONNECTION
    # ========================================================

    def get_connection(self):

        guild = self.get_guild()

        if guild is None:
            return None

        voice_client = guild.voice_client

        if voice_client is None:
            return None

        if not voice_client.is_connected():
            return None

        return voice_client

    # ========================================================
    # GET QUEUE
    # ========================================================

    def get_queue(self):

        if GUILD_ID not in self.queues:

            self.queues[GUILD_ID] = asyncio.Queue(
                maxsize=25
            )

        return self.queues[GUILD_ID]

    # ========================================================
    # GET LOCK
    # ========================================================

    def get_lock(self):

        if GUILD_ID not in self.locks:

            self.locks[GUILD_ID] = asyncio.Lock()

        return self.locks[GUILD_ID]

    # ========================================================
    # AUTO JOIN
    # ========================================================

    async def auto_join(self):

        print(
            "[TTS] ======================================="
        )

        print(
            "[TTS] AUTO JOIN STARTED"
        )

        print(
            f"[TTS] Guild ID: {GUILD_ID}"
        )

        print(
            f"[TTS] Target VC ID: {TTS_CHANNEL_ID}"
        )

        print(
            "[TTS] ======================================="
        )

        guild = self.get_guild()

        if guild is None:

            print(
                "[TTS] Cannot auto-join: guild unavailable."
            )

            return

        print(
            f"[TTS] Guild found: "
            f"{guild.name}"
        )

        # ----------------------------------------------------
        # Try cache first
        # ----------------------------------------------------

        channel = guild.get_channel(
            TTS_CHANNEL_ID
        )

        # ----------------------------------------------------
        # If cache failed, fetch from Discord API
        # ----------------------------------------------------

        if channel is None:

            print(
                "[TTS] Channel not in cache."
            )

            print(
                "[TTS] Fetching channel from Discord..."
            )

            try:

                channel = await self.bot.fetch_channel(
                    TTS_CHANNEL_ID
                )

            except discord.NotFound:

                print(
                    "[TTS] ERROR: Discord says this "
                    "channel does not exist."
                )

                return

            except discord.Forbidden:

                print(
                    "[TTS] ERROR: Bot does not have "
                    "permission to access this channel."
                )

                return

            except discord.HTTPException as error:

                print(
                    f"[TTS] ERROR fetching channel: "
                    f"{error}"
                )

                return

        # ----------------------------------------------------
        # Verify channel
        # ----------------------------------------------------

        print(
            f"[TTS] Channel fetched: "
            f"{channel}"
        )

        print(
            f"[TTS] Channel type: "
            f"{type(channel).__name__}"
        )

        if not isinstance(
            channel,
            discord.VoiceChannel
        ):

            print(
                "[TTS] ERROR: Target ID is not a "
                "VoiceChannel."
            )

            return

        # ----------------------------------------------------
        # Check existing connection
        # ----------------------------------------------------

        existing = guild.voice_client

        if existing:

            print(
                f"[TTS] Existing voice connection found: "
                f"{existing.channel}"
            )

            if (
                existing.channel
                and existing.channel.id
                == TTS_CHANNEL_ID
            ):

                print(
                    "[TTS] Already connected to "
                    "target VC."
                )

                self.start_worker()

                return

            print(
                "[TTS] Moving existing connection "
                "to target VC..."
            )

            try:

                await existing.move_to(
                    channel
                )

                print(
                    "[TTS] Successfully moved "
                    "to target VC."
                )

                self.start_worker()

                return

            except Exception as error:

                print(
                    f"[TTS] Move failed: {error}"
                )

        # ----------------------------------------------------
        # CONNECT
        # ----------------------------------------------------

        print(
            f"[TTS] Attempting to CONNECT to "
            f"{channel.name}..."
        )

        try:

            voice_client = await channel.connect(
                timeout=30,
                reconnect=True
            )

            print(
                "[TTS] ======================================="
            )

            print(
                "[TTS] SUCCESSFULLY JOINED VOICE CHANNEL"
            )

            print(
                f"[TTS] Channel: {channel.name}"
            )

            print(
                f"[TTS] Channel ID: {channel.id}"
            )

            print(
                "[TTS] ======================================="
            )

            self.start_worker()

        except discord.Forbidden as error:

            print(
                "[TTS] ======================================="
            )

            print(
                "[TTS] ERROR: FORBIDDEN"
            )

            print(
                "[TTS] The bot does not have permission "
                "to CONNECT to this VC."
            )

            print(
                "[TTS] Give the bot:"
            )

            print(
                "[TTS] - View Channel"
            )

            print(
                "[TTS] - Connect"
            )

            print(
                "[TTS] - Speak"
            )

            print(
                f"[TTS] Discord error: {error}"
            )

            print(
                "[TTS] ======================================="
            )

        except discord.ClientException as error:

            print(
                f"[TTS] ClientException while joining: "
                f"{error}"
            )

        except discord.HTTPException as error:

            print(
                f"[TTS] HTTPException while joining: "
                f"{error}"
            )

        except Exception as error:

            print(
                f"[TTS] UNKNOWN ERROR while joining: "
                f"{type(error).__name__}: {error}"
            )

    # ========================================================
    # CONNECT
    # ========================================================

    async def connect(
        self,
        channel
    ):

        if not isinstance(
            channel,
            discord.VoiceChannel
        ):

            print(
                "[TTS] connect() received invalid channel."
            )

            return False

        guild = channel.guild

        existing = guild.voice_client

        # ----------------------------------------------------
        # Already there
        # ----------------------------------------------------

        if existing:

            if (
                existing.is_connected()
                and existing.channel
                and existing.channel.id
                == channel.id
            ):

                print(
                    "[TTS] Already connected."
                )

                self.start_worker()

                return True

            # ------------------------------------------------
            # Move
            # ------------------------------------------------

            try:

                print(
                    f"[TTS] Moving bot to {channel.name}..."
                )

                await existing.move_to(
                    channel
                )

                self.start_worker()

                print(
                    "[TTS] Move successful."
                )

                return True

            except Exception as error:

                print(
                    f"[TTS] Move failed: {error}"
                )

                return False

        # ----------------------------------------------------
        # Fresh connection
        # ----------------------------------------------------

        try:

            print(
                f"[TTS] Connecting to {channel.name}..."
            )

            await channel.connect(
                timeout=30,
                reconnect=True
            )

            print(
                "[TTS] Connected successfully."
            )

            self.start_worker()

            return True

        except Exception as error:

            print(
                f"[TTS] Connection failed: "
                f"{type(error).__name__}: {error}"
            )

            return False

    # ========================================================
    # DISCONNECT
    # ========================================================

    async def disconnect(self):

        connection = self.get_connection()

        if connection:

            print(
                "[TTS] Disconnecting..."
            )

            try:

                if connection.is_playing():

                    connection.stop()

            except Exception:
                pass

            try:

                await connection.disconnect(
                    force=True
                )

            except Exception as error:

                print(
                    f"[TTS] Disconnect error: {error}"
                )

        # ----------------------------------------------------
        # Clear queue
        # ----------------------------------------------------

        queue = self.queues.get(
            GUILD_ID
        )

        if queue:

            while not queue.empty():

                try:

                    queue.get_nowait()
                    queue.task_done()

                except asyncio.QueueEmpty:

                    break

    # ========================================================
    # VOICE STATE UPDATE
    # ========================================================

    async def handle_voice_update(
        self,
        member,
        before,
        after
    ):

        if member.bot:
            return

        if member.guild.id != GUILD_ID:
            return

        # ----------------------------------------------------
        # User joined target VC
        # ----------------------------------------------------

        if after.channel:

            if after.channel.id == TTS_CHANNEL_ID:

                print(
                    f"[TTS] {member} joined target VC."
                )

                await self.connect(
                    after.channel
                )

        # ----------------------------------------------------
        # User left target VC
        # ----------------------------------------------------

        if before.channel:

            if before.channel.id == TTS_CHANNEL_ID:

                humans = [
                    m
                    for m in before.channel.members
                    if not m.bot
                ]

                print(
                    f"[TTS] Humans remaining in target VC: "
                    f"{len(humans)}"
                )

                if not humans:

                    print(
                        "[TTS] Nobody remains. "
                        "Disconnecting."
                    )

                    await self.disconnect()

    # ========================================================
    # START WORKER
    # ========================================================

    def start_worker(self):

        if GUILD_ID in self.workers:

            worker = self.workers[GUILD_ID]

            if not worker.done():

                return

        print(
            "[TTS] Starting audio worker..."
        )

        self.workers[GUILD_ID] = asyncio.create_task(
            self.worker()
        )

    # ========================================================
    # SPEAK
    # ========================================================

    async def speak(
        self,
        channel,
        text
    ):

        if not text:
            return

        if len(text) > 500:

            text = (
                text[:500]
                + "..."
            )

        # ----------------------------------------------------
        # Make sure we're in the correct VC
        # ----------------------------------------------------

        connection = self.get_connection()

        if (
            connection is None
            or connection.channel is None
            or connection.channel.id != channel.id
        ):

            success = await self.connect(
                channel
            )

            if not success:

                print(
                    "[TTS] Could not connect. "
                    "Message will not be spoken."
                )

                return

        queue = self.get_queue()

        try:

            queue.put_nowait(
                text
            )

            print(
                f"[TTS] Queued: {text}"
            )

        except asyncio.QueueFull:

            print(
                "[TTS] Queue full. "
                "Dropping message."
            )

    # ========================================================
    # WORKER
    # ========================================================

    async def worker(self):

        queue = self.get_queue()

        print(
            "[TTS] Worker running."
        )

        while True:

            try:

                text = await queue.get()

                try:

                    connection = self.get_connection()

                    if (
                        connection is None
                        or connection.channel is None
                    ):

                        print(
                            "[TTS] No voice connection."
                        )

                        continue

                    print(
                        f"[TTS] Speaking: {text}"
                    )

                    audio_file = (
                        await self.generate_audio(
                            text
                        )
                    )

                    if not audio_file:

                        print(
                            "[TTS] Audio generation failed."
                        )

                        continue

                    finished = asyncio.Event()

                    def after_playing(error):

                        if error:

                            print(
                                f"[TTS] Playback error: "
                                f"{error}"
                            )

                        self.bot.loop.call_soon_threadsafe(
                            finished.set
                        )

                    source = discord.FFmpegPCMAudio(
                        audio_file,
                        executable=imageio_ffmpeg.get_ffmpeg_exe(),
                        options="-vn"
                    )

                    connection.play(
                        source,
                        after=after_playing
                    )

                    await finished.wait()

                    # ------------------------------------------------
                    # Delete generated file
                    # ------------------------------------------------

                    try:

                        if os.path.exists(
                            audio_file
                        ):

                            os.remove(
                                audio_file
                            )

                    except Exception:

                        pass

                except Exception as error:

                    print(
                        f"[TTS] Worker error: "
                        f"{type(error).__name__}: {error}"
                    )

                finally:

                    queue.task_done()

            except asyncio.CancelledError:

                print(
                    "[TTS] Worker cancelled."
                )

                break

            except Exception as error:

                print(
                    f"[TTS] Worker loop error: "
                    f"{error}"
                )

    # ========================================================
    # GENERATE EDGE TTS AUDIO
    # ========================================================

    async def generate_audio(
        self,
        text
    ):

        filename = os.path.join(
            tempfile.gettempdir(),
            f"mcpe_tts_{uuid.uuid4().hex}.mp3"
        )

        try:

            communicate = edge_tts.Communicate(
                text,
                self.voice,
                rate=self.rate,
                volume=self.volume,
                pitch=self.pitch
            )

            await communicate.save(
                filename
            )

            print(
                f"[TTS] Generated audio: "
                f"{filename}"
            )

            return filename

        except Exception as error:

            print(
                f"[TTS] Edge TTS error: "
                f"{type(error).__name__}: {error}"
            )

            try:

                if os.path.exists(
                    filename
                ):

                    os.remove(
                        filename
                    )

            except Exception:

                pass

            return None

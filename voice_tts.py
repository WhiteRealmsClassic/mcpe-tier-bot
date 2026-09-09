import asyncio
import os
import tempfile
import uuid

import discord
import edge_tts
import imageio_ffmpeg

from config import GUILD_ID


TTS_CHANNEL_ID = 1319664272334393388


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
        self.workers = {}
        self.connections = {}
        self.connection_locks = {}

        self.queue_limit = 25

        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        print("[TTS] ===============================")
        print("[TTS] TTS system loaded")
        print(f"[TTS] Guild ID: {GUILD_ID}")
        print(f"[TTS] Voice channel ID: {TTS_CHANNEL_ID}")
        print(f"[TTS] Voice: {self.voice}")
        print(f"[TTS] FFmpeg: {self.ffmpeg}")
        print("[TTS] ===============================")

    # =========================================================
    # GET VOICE CHANNEL
    # =========================================================

    def get_tts_channel(self):

        guild = self.bot.get_guild(GUILD_ID)

        if guild is None:
            print(f"[TTS] ERROR: Guild {GUILD_ID} not found.")
            return None

        channel = guild.get_channel(TTS_CHANNEL_ID)

        if channel is None:
            print(
                f"[TTS] ERROR: Channel {TTS_CHANNEL_ID} "
                f"was not found in guild."
            )
            return None

        if not isinstance(channel, discord.VoiceChannel):
            print(
                f"[TTS] ERROR: Channel {TTS_CHANNEL_ID} "
                f"is not a voice channel."
            )
            return None

        return channel

    # =========================================================
    # QUEUE
    # =========================================================

    def get_queue(self, guild_id):

        if guild_id not in self.queues:
            self.queues[guild_id] = asyncio.Queue(
                maxsize=self.queue_limit
            )

        return self.queues[guild_id]

    # =========================================================
    # LOCK
    # =========================================================

    def get_lock(self, guild_id):

        if guild_id not in self.connection_locks:
            self.connection_locks[guild_id] = asyncio.Lock()

        return self.connection_locks[guild_id]

    # =========================================================
    # CURRENT CONNECTION
    # =========================================================

    def get_connection(self, guild_id):

        connection = self.connections.get(guild_id)

        if connection and connection.is_connected():
            return connection

        guild = self.bot.get_guild(guild_id)

        if guild:

            connection = discord.utils.get(
                self.bot.voice_clients,
                guild=guild
            )

            if connection and connection.is_connected():

                self.connections[guild_id] = connection

                return connection

        return None

    # =========================================================
    # CONNECT
    # =========================================================

    async def connect(self, channel):

        if channel is None:
            return None

        guild = channel.guild
        guild_id = guild.id

        async with self.get_lock(guild_id):

            voice_client = self.get_connection(guild_id)

            # Already connected to correct channel
            if voice_client:

                if (
                    voice_client.channel
                    and voice_client.channel.id == channel.id
                ):
                    print(
                        f"[TTS] Already connected to "
                        f"#{channel.name}"
                    )

                    return voice_client

                # Connected somewhere else
                try:

                    print(
                        f"[TTS] Moving from "
                        f"#{voice_client.channel.name} "
                        f"to #{channel.name}"
                    )

                    await voice_client.move_to(channel)

                    self.connections[guild_id] = voice_client

                    print(
                        f"[TTS] Moved to #{channel.name}"
                    )

                    return voice_client

                except Exception as error:

                    print(
                        f"[TTS] Move failed: "
                        f"{type(error).__name__}: {error}"
                    )

                    try:
                        await voice_client.disconnect(
                            force=True
                        )
                    except Exception:
                        pass

                    self.connections.pop(
                        guild_id,
                        None
                    )

            # New connection
            try:

                print(
                    f"[TTS] Attempting to join "
                    f"#{channel.name} "
                    f"({channel.id})"
                )

                voice_client = await channel.connect(
                    reconnect=True
                )

                self.connections[guild_id] = voice_client

                print(
                    f"[TTS] SUCCESS: Joined "
                    f"#{channel.name}"
                )

                return voice_client

            except discord.Forbidden as error:

                print(
                    "[TTS] FORBIDDEN: Bot does not have "
                    "permission to connect/speak."
                )
                print(f"[TTS] {error}")

            except discord.ClientException as error:

                print(
                    f"[TTS] CLIENT ERROR: {error}"
                )

            except discord.HTTPException as error:

                print(
                    f"[TTS] HTTP ERROR: {error}"
                )

            except Exception as error:

                print(
                    f"[TTS] UNKNOWN CONNECT ERROR: "
                    f"{type(error).__name__}: {error}"
                )

        return None

    # =========================================================
    # FORCE JOIN CONFIGURED CHANNEL
    # =========================================================

    async def auto_join(self):

        print("[TTS] Running auto-join...")

        channel = self.get_tts_channel()

        if channel is None:
            print("[TTS] Auto-join failed: channel unavailable.")
            return

        print(
            f"[TTS] Configured channel found: "
            f"#{channel.name} ({channel.id})"
        )

        # Only join if humans are actually inside
        humans = [
            member
            for member in channel.members
            if not member.bot
        ]

        if not humans:

            print(
                "[TTS] No human users in configured VC. "
                "Waiting."
            )

            return

        print(
            f"[TTS] {len(humans)} human(s) detected. "
            f"Joining."
        )

        await self.connect(channel)

    # =========================================================
    # DISCONNECT
    # =========================================================

    async def disconnect(self, guild_id):

        voice_client = self.connections.pop(
            guild_id,
            None
        )

        if voice_client is None:

            guild = self.bot.get_guild(guild_id)

            if guild:

                voice_client = discord.utils.get(
                    self.bot.voice_clients,
                    guild=guild
                )

        if voice_client:

            try:
                if voice_client.is_playing():
                    voice_client.stop()
            except Exception:
                pass

            try:

                if voice_client.is_connected():

                    await voice_client.disconnect(
                        force=True
                    )

                    print("[TTS] Disconnected.")

            except Exception as error:

                print(
                    f"[TTS] Disconnect error: {error}"
                )

        # Clear queue
        queue = self.queues.get(guild_id)

        if queue:

            while not queue.empty():

                try:

                    queue.get_nowait()
                    queue.task_done()

                except asyncio.QueueEmpty:
                    break

        # Stop worker
        worker = self.workers.pop(
            guild_id,
            None
        )

        if worker and not worker.done():
            worker.cancel()

    # =========================================================
    # SPEAK
    # =========================================================

    async def speak(self, voice_channel, text):

        if voice_channel is None:
            return False

        if not text:
            return False

        text = text.strip()

        if not text:
            return False

        if len(text) > 500:
            text = text[:500] + "..."

        guild_id = voice_channel.guild.id

        queue = self.get_queue(guild_id)

        if queue.full():

            print(
                "[TTS] Queue full. Message skipped."
            )

            return False

        try:

            queue.put_nowait(
                (
                    voice_channel,
                    text
                )
            )

        except asyncio.QueueFull:

            return False

        self.start_worker(guild_id)

        return True

    # =========================================================
    # WORKER
    # =========================================================

    def start_worker(self, guild_id):

        worker = self.workers.get(guild_id)

        if worker and not worker.done():
            return

        self.workers[guild_id] = asyncio.create_task(
            self.worker(guild_id)
        )

    # =========================================================
    # AUDIO WORKER
    # =========================================================

    async def worker(self, guild_id):

        queue = self.get_queue(guild_id)

        try:

            while True:

                try:

                    voice_channel, text = await asyncio.wait_for(
                        queue.get(),
                        timeout=300
                    )

                except asyncio.TimeoutError:
                    return

                filename = None

                try:

                    # Make sure bot is in VC
                    voice_client = await self.connect(
                        voice_channel
                    )

                    if (
                        not voice_client
                        or not voice_client.is_connected()
                    ):
                        continue

                    filename = os.path.join(
                        tempfile.gettempdir(),
                        f"mcpe_tts_{uuid.uuid4().hex}.mp3"
                    )

                    print(
                        f"[TTS] Generating: "
                        f"{text[:80]}"
                    )

                    await self.generate_audio(
                        text,
                        filename
                    )

                    if not os.path.exists(filename):

                        print(
                            "[TTS] ERROR: Audio file "
                            "was not created."
                        )

                        continue

                    # Stop old playback
                    if voice_client.is_playing():

                        voice_client.stop()

                    finished = asyncio.Event()

                    loop = asyncio.get_running_loop()

                    def after_play(error):

                        if error:

                            print(
                                f"[TTS] Playback error: "
                                f"{error}"
                            )

                        loop.call_soon_threadsafe(
                            finished.set
                        )

                    audio = discord.FFmpegPCMAudio(
                        filename,
                        executable=self.ffmpeg,
                        options="-vn -loglevel warning"
                    )

                    voice_client.play(
                        audio,
                        after=after_play
                    )

                    await finished.wait()

                except asyncio.CancelledError:

                    raise

                except Exception as error:

                    print(
                        f"[TTS] Worker error: "
                        f"{type(error).__name__}: {error}"
                    )

                finally:

                    if filename:

                        try:

                            if os.path.exists(filename):
                                os.remove(filename)

                        except OSError:
                            pass

                    try:
                        queue.task_done()
                    except ValueError:
                        pass

        finally:

            current = self.workers.get(
                guild_id
            )

            if current is asyncio.current_task():

                self.workers.pop(
                    guild_id,
                    None
                )

    # =========================================================
    # EDGE TTS
    # =========================================================

    async def generate_audio(
        self,
        text,
        filename
    ):

        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch
        )

        await communicate.save(filename)

    # =========================================================
    # VOICE STATE UPDATE
    # =========================================================

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

        # User joined / moved into VC
        if after.channel:

            print(
                f"[TTS] {member.display_name} "
                f"joined #{after.channel.name} "
                f"({after.channel.id})"
            )

            # ONLY use the configured channel
            if after.channel.id == TTS_CHANNEL_ID:

                print(
                    "[TTS] User entered configured "
                    "TTS channel."
                )

                await self.connect(
                    after.channel
                )

        # User left VC
        if before.channel:

            humans = [
                m
                for m in before.channel.members
                if not m.bot
            ]

            if not humans:

                connection = self.get_connection(
                    GUILD_ID
                )

                if (
                    connection
                    and connection.channel
                    and connection.channel.id
                    == before.channel.id
                ):

                    print(
                        f"[TTS] Nobody remains in "
                        f"#{before.channel.name}. "
                        f"Leaving."
                    )

                    await self.disconnect(
                        GUILD_ID
                    )

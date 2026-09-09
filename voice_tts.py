import asyncio
import os
import tempfile
import uuid

import discord
import edge_tts
import imageio_ffmpeg


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

        # Guild ID -> asyncio.Queue
        self.queues = {}

        # Guild ID -> worker task
        self.workers = {}

        # Guild ID -> VoiceClient
        self.connections = {}

        # Prevent two simultaneous connect/move operations
        self.connection_locks = {}

        # Maximum number of queued messages per guild
        self.queue_limit = 25

        # Bundled FFmpeg executable
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        print(
            f"[TTS] FFmpeg: {self.ffmpeg}"
        )

    # ==================================================
    # QUEUE
    # ==================================================

    def get_queue(
        self,
        guild_id
    ):

        if guild_id not in self.queues:

            self.queues[guild_id] = asyncio.Queue(
                maxsize=self.queue_limit
            )

        return self.queues[guild_id]

    # ==================================================
    # LOCK
    # ==================================================

    def get_lock(
        self,
        guild_id
    ):

        if guild_id not in self.connection_locks:

            self.connection_locks[guild_id] = (
                asyncio.Lock()
            )

        return self.connection_locks[guild_id]

    # ==================================================
    # FIND CONNECTION
    # ==================================================

    def get_connection(
        self,
        guild_id
    ):

        connection = self.connections.get(
            guild_id
        )

        if connection:

            if connection.is_connected():

                return connection

        guild = self.bot.get_guild(
            guild_id
        )

        if guild:

            connection = discord.utils.get(
                self.bot.voice_clients,
                guild=guild
            )

            if connection:

                if connection.is_connected():

                    self.connections[guild_id] = (
                        connection
                    )

                    return connection

        return None

    # ==================================================
    # CONNECT
    # ==================================================

    async def connect(
        self,
        channel
    ):

        if channel is None:
            return None

        guild = channel.guild
        guild_id = guild.id

        async with self.get_lock(guild_id):

            # --------------------------------------------------
            # Existing connection
            # --------------------------------------------------

            voice_client = self.get_connection(
                guild_id
            )

            if voice_client:

                try:

                    if (
                        voice_client.channel
                        and
                        voice_client.channel.id
                        == channel.id
                    ):

                        return voice_client

                    print(
                        f"[TTS] Moving to "
                        f"#{channel.name}"
                    )

                    await voice_client.move_to(
                        channel
                    )

                    self.connections[
                        guild_id
                    ] = voice_client

                    return voice_client

                except (
                    discord.ClientException,
                    discord.HTTPException
                ) as error:

                    print(
                        f"[TTS] Move failed: {error}"
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

            # --------------------------------------------------
            # Connect
            # --------------------------------------------------

            try:

                print(
                    f"[TTS] Joining "
                    f"#{channel.name}"
                )

                voice_client = await channel.connect(
                    reconnect=True
                )

                self.connections[
                    guild_id
                ] = voice_client

                print(
                    f"[TTS] Connected to "
                    f"#{channel.name}"
                )

                return voice_client

            except discord.ClientException as error:

                print(
                    f"[TTS] Discord client error: "
                    f"{error}"
                )

            except discord.Forbidden as error:

                print(
                    f"[TTS] Missing permission to "
                    f"join #{channel.name}: {error}"
                )

            except discord.HTTPException as error:

                print(
                    f"[TTS] Discord HTTP error: "
                    f"{error}"
                )

            except Exception as error:

                print(
                    f"[TTS] Unexpected connect error: "
                    f"{type(error).__name__}: {error}"
                )

        return None

    # ==================================================
    # DISCONNECT
    # ==================================================

    async def disconnect(
        self,
        guild_id
    ):

        voice_client = self.connections.pop(
            guild_id,
            None
        )

        if voice_client is None:

            guild = self.bot.get_guild(
                guild_id
            )

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

            except (
                discord.ClientException,
                discord.HTTPException
            ):

                pass

        # --------------------------------------------------
        # Clear queued messages
        # --------------------------------------------------

        queue = self.queues.get(
            guild_id
        )

        if queue:

            while not queue.empty():

                try:

                    queue.get_nowait()
                    queue.task_done()

                except asyncio.QueueEmpty:

                    break

        # --------------------------------------------------
        # Stop worker
        # --------------------------------------------------

        worker = self.workers.pop(
            guild_id,
            None
        )

        if (
            worker
            and not worker.done()
        ):

            worker.cancel()

    # ==================================================
    # SPEAK
    # ==================================================

    async def speak(
        self,
        voice_channel,
        text
    ):

        if voice_channel is None:
            return False

        if not text:
            return False

        text = text.strip()

        if not text:
            return False

        # Prevent enormous TTS messages
        if len(text) > 500:

            text = (
                text[:500]
                + "..."
            )

        queue = self.get_queue(
            voice_channel.guild.id
        )

        # --------------------------------------------------
        # Don't allow unlimited spam
        # --------------------------------------------------

        if queue.full():

            print(
                "[TTS] Queue full, "
                "message skipped."
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

        self.start_worker(
            voice_channel.guild.id
        )

        return True

    # ==================================================
    # WORKER
    # ==================================================

    def start_worker(
        self,
        guild_id
    ):

        worker = self.workers.get(
            guild_id
        )

        if (
            worker
            and not worker.done()
        ):

            return

        self.workers[guild_id] = (
            asyncio.create_task(
                self.worker(
                    guild_id
                )
            )
        )

    async def worker(
        self,
        guild_id
    ):

        queue = self.get_queue(
            guild_id
        )

        try:

            while True:

                try:

                    voice_channel, text = (
                        await asyncio.wait_for(
                            queue.get(),
                            timeout=300
                        )
                    )

                except asyncio.TimeoutError:

                    return

                filename = None

                try:

                    # --------------------------------------------------
                    # Make sure bot is still in the correct VC
                    # --------------------------------------------------

                    voice_client = (
                        await self.connect(
                            voice_channel
                        )
                    )

                    if not voice_client:

                        continue

                    if not voice_client.is_connected():

                        continue

                    # --------------------------------------------------
                    # Generate TTS
                    # --------------------------------------------------

                    filename = os.path.join(
                        tempfile.gettempdir(),
                        (
                            "mcpe_tts_"
                            f"{uuid.uuid4().hex}.mp3"
                        )
                    )

                    print(
                        f"[TTS] Generating: "
                        f"{text[:80]}"
                    )

                    await self.generate_audio(
                        text,
                        filename
                    )

                    if not os.path.exists(
                        filename
                    ):

                        print(
                            "[TTS] Audio file "
                            "was not created."
                        )

                        continue

                    # --------------------------------------------------
                    # Playback
                    # --------------------------------------------------

                    if voice_client.is_playing():

                        voice_client.stop()

                    finished = (
                        asyncio.Event()
                    )

                    loop = (
                        asyncio.get_running_loop()
                    )

                    def after_play(
                        error
                    ):

                        if error:

                            print(
                                f"[TTS] Playback error: "
                                f"{error}"
                            )

                        loop.call_soon_threadsafe(
                            finished.set
                        )

                    audio = (
                        discord.FFmpegPCMAudio(
                            filename,
                            executable=self.ffmpeg,
                            options=(
                                "-vn "
                                "-loglevel warning"
                            )
                        )
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
                        f"{type(error).__name__}: "
                        f"{error}"
                    )

                finally:

                    if filename:

                        try:

                            if os.path.exists(
                                filename
                            ):

                                os.remove(
                                    filename
                                )

                        except OSError:

                            pass

                    queue.task_done()

        finally:

            # Only remove ourselves if we're still
            # the active worker.
            current = self.workers.get(
                guild_id
            )

            if current is asyncio.current_task():

                self.workers.pop(
                    guild_id,
                    None
                )

    # ==================================================
    # GENERATE AUDIO
    # ==================================================

    async def generate_audio(
        self,
        text,
        filename
    ):

        communicate = (
            edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                volume=self.volume,
                pitch=self.pitch
            )
        )

        await communicate.save(
            filename
        )

    # ==================================================
    # VOICE STATE UPDATE
    # ==================================================

    async def handle_voice_update(
        self,
        member,
        before,
        after
    ):

        if member.bot:

            return

        guild = member.guild

        if guild.id != GUILD_ID:

            return

        # --------------------------------------------------
        # User joined / moved to a VC
        # --------------------------------------------------

        if after.channel:

            print(
                f"[TTS] {member.display_name} "
                f"joined #{after.channel.name}"
            )

            await self.connect(
                after.channel
            )

        # --------------------------------------------------
        # User left a VC
        # --------------------------------------------------

        if before.channel:

            humans = [
                m
                for m in before.channel.members
                if not m.bot
            ]

            # If nobody remains, disconnect.
            if not humans:

                connection = (
                    self.get_connection(
                        guild.id
                    )
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
                        guild.id
                    )

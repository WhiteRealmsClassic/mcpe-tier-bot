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

        self.queues = {}
        self.workers = {}
        self.connections = {}
        self.connection_locks = {}

        # imageio-ffmpeg provides FFmpeg automatically
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    # ==================================================
    # QUEUE
    # ==================================================

    def get_queue(self, guild_id):

        if guild_id not in self.queues:

            self.queues[guild_id] = asyncio.Queue(
                maxsize=25
            )

        return self.queues[guild_id]

    # ==================================================
    # CONNECTION LOCK
    # ==================================================

    def get_lock(self, guild_id):

        if guild_id not in self.connection_locks:

            self.connection_locks[guild_id] = asyncio.Lock()

        return self.connection_locks[guild_id]

    # ==================================================
    # CONNECT
    # ==================================================

    async def connect(self, channel):

        guild_id = channel.guild.id

        async with self.get_lock(guild_id):

            existing = self.connections.get(
                guild_id
            )

            # Already connected through our tracker
            if existing and existing.is_connected():

                if (
                    existing.channel
                    and existing.channel.id == channel.id
                ):

                    return existing

                try:

                    await existing.move_to(
                        channel
                    )

                    print(
                        f"[TTS] Moved to "
                        f"#{channel.name} "
                        f"in {channel.guild.name}"
                    )

                    return existing

                except Exception as error:

                    print(
                        f"[TTS] Failed to move: {error}"
                    )

            # Look for an existing Discord voice client
            voice_client = discord.utils.get(
                self.bot.voice_clients,
                guild=channel.guild
            )

            if voice_client:

                try:

                    if (
                        not voice_client.channel
                        or voice_client.channel.id != channel.id
                    ):

                        await voice_client.move_to(
                            channel
                        )

                    self.connections[guild_id] = voice_client

                    return voice_client

                except Exception as error:

                    print(
                        f"[TTS] Existing voice client error: "
                        f"{error}"
                    )

            # Connect from scratch
            try:

                voice_client = await channel.connect(
                    reconnect=True
                )

                self.connections[guild_id] = voice_client

                print(
                    f"[TTS] Joined "
                    f"#{channel.name} "
                    f"in {channel.guild.name}"
                )

                return voice_client

            except Exception as error:

                print(
                    f"[TTS] Failed to join "
                    f"#{channel.name}: {error}"
                )

                return None

    # ==================================================
    # DISCONNECT
    # ==================================================

    async def disconnect(self, guild_id):

        voice_client = self.connections.pop(
            guild_id,
            None
        )

        if not voice_client:

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

                await voice_client.disconnect(
                    force=True
                )

            except Exception as error:

                print(
                    f"[TTS] Disconnect error: {error}"
                )

        # Clear queued messages
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

        print(
            f"[TTS] Left voice channel "
            f"in guild {guild_id}"
        )

    # ==================================================
    # SPEAK
    # ==================================================

    async def speak(
        self,
        voice_channel,
        text
    ):

        if not text:
            return

        text = text.strip()

        if not text:
            return

        # Prevent enormous messages
        if len(text) > 500:

            text = text[:500] + "..."

        queue = self.get_queue(
            voice_channel.guild.id
        )

        # Don't let spam create an infinite queue
        if queue.full():

            print(
                f"[TTS] Queue full in "
                f"{voice_channel.guild.name}"
            )

            return

        await queue.put(
            (
                voice_channel,
                text
            )
        )

        self.start_worker(
            voice_channel.guild.id
        )

    # ==================================================
    # WORKER START
    # ==================================================

    def start_worker(self, guild_id):

        worker = self.workers.get(
            guild_id
        )

        if worker and not worker.done():

            return

        self.workers[guild_id] = asyncio.create_task(
            self.worker(guild_id)
        )

    # ==================================================
    # AUDIO WORKER
    # ==================================================

    async def worker(self, guild_id):

        queue = self.get_queue(
            guild_id
        )

        while True:

            try:

                voice_channel, text = await asyncio.wait_for(
                    queue.get(),
                    timeout=300
                )

            except asyncio.TimeoutError:

                self.workers.pop(
                    guild_id,
                    None
                )

                return

            filename = None

            try:

                voice_client = await self.connect(
                    voice_channel
                )

                if not voice_client:

                    continue

                filename = os.path.join(
                    tempfile.gettempdir(),
                    f"tierbot_tts_{uuid.uuid4().hex}.mp3"
                )

                # Generate speech
                await self.generate_audio(
                    text,
                    filename
                )

                if not os.path.exists(filename):

                    print(
                        "[TTS] Audio file was not created."
                    )

                    continue

                if not voice_client.is_connected():

                    continue

                if voice_client.is_playing():

                    voice_client.stop()

                    await asyncio.sleep(
                        0.1
                    )

                finished = asyncio.Event()

                def after_play(error):

                    if error:

                        print(
                            f"[TTS] Playback error: "
                            f"{error}"
                        )

                    try:

                        self.bot.loop.call_soon_threadsafe(
                            finished.set
                        )

                    except Exception:

                        pass

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
                    f"[TTS] Worker error: {error}"
                )

            finally:

                queue.task_done()

                if filename:

                    try:

                        if os.path.exists(filename):

                            os.remove(filename)

                    except OSError:

                        pass

    # ==================================================
    # EDGE TTS
    # ==================================================

    async def generate_audio(
        self,
        text,
        filename
    ):

        communicator = edge_tts.Communicate(
            text,
            self.voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch
        )

        await communicator.save(
            filename
        )

    # ==================================================
    # VOICE STATE
    # ==================================================

    async def handle_voice_update(
        self,
        member,
        before,
        after
    ):

        # Ignore bots
        if member.bot:

            return

        # Someone joined/moved into a VC
        if after.channel:

            await self.connect(
                after.channel
            )

        # Someone left/moved out of a VC
        if before.channel:

            channel = before.channel

            humans = [
                m
                for m in channel.members
                if not m.bot
            ]

            # Last human left
            if not humans:

                voice_client = self.connections.get(
                    member.guild.id
                )

                if (
                    voice_client
                    and voice_client.channel
                    and voice_client.channel.id
                    == channel.id
                ):

                    await self.disconnect(
                        member.guild.id
                    )

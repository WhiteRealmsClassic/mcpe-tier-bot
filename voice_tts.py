import asyncio
import os
import tempfile
import uuid

import discord
import edge_tts


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

        # guild_id -> asyncio.Queue
        self.queues = {}

        # guild_id -> worker task
        self.workers = {}

        # guild_id -> currently connected VoiceClient
        self.connections = {}

    # ==================================================
    # GET QUEUE
    # ==================================================

    def get_queue(self, guild_id):

        if guild_id not in self.queues:
            self.queues[guild_id] = asyncio.Queue()

        return self.queues[guild_id]

    # ==================================================
    # CONNECT
    # ==================================================

    async def connect(self, channel):

        guild_id = channel.guild.id

        existing = self.connections.get(
            guild_id
        )

        if existing:

            if existing.is_connected():

                if existing.channel.id == channel.id:
                    return existing

                try:
                    await existing.move_to(channel)
                    return existing

                except discord.HTTPException:
                    pass

        voice_client = discord.utils.get(
            self.bot.voice_clients,
            guild=channel.guild
        )

        if voice_client:

            try:
                if voice_client.channel.id != channel.id:
                    await voice_client.move_to(channel)

                self.connections[guild_id] = voice_client

                return voice_client

            except discord.HTTPException:
                pass

        try:

            voice_client = await channel.connect(
                reconnect=True
            )

            self.connections[guild_id] = voice_client

            return voice_client

        except (
            discord.ClientException,
            discord.HTTPException
        ):

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

            voice_client = discord.utils.get(
                self.bot.voice_clients,
                guild=self.bot.get_guild(guild_id)
            )

        if voice_client:

            try:
                await voice_client.disconnect(
                    force=True
                )

            except discord.HTTPException:
                pass

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

        # Discord messages can contain enormous amounts
        # of text. Don't make TTS read a novel.
        if len(text) > 500:

            text = text[:500] + "..."

        await self.get_queue(
            voice_channel.guild.id
        ).put(
            (
                voice_channel,
                text
            )
        )

        self.start_worker(
            voice_channel.guild.id
        )

    # ==================================================
    # START WORKER
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
    # WORKER
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

                try:

                    await self.generate_audio(
                        text,
                        filename
                    )

                    if not os.path.exists(filename):
                        continue

                    finished = asyncio.Event()

                    def after_play(error):

                        if error:
                            print(
                                f"[TTS] Playback error: {error}"
                            )

                        self.bot.loop.call_soon_threadsafe(
                            finished.set
                        )

                    audio = discord.FFmpegPCMAudio(
                        filename,
                        options=(
                            "-vn "
                            "-loglevel warning"
                        )
                    )

                    voice_client.play(
                        audio,
                        after=after_play
                    )

                    await finished.wait()

                except Exception as error:

                    print(
                        f"[TTS] Error: {error}"
                    )

                finally:

                    try:
                        if os.path.exists(filename):
                            os.remove(filename)
                    except OSError:
                        pass

            finally:

                queue.task_done()

    # ==================================================
    # GENERATE AUDIO
    # ==================================================

    async def generate_audio(
        self,
        text,
        filename
    ):

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

    # ==================================================
    # STOP WHEN EMPTY
    # ==================================================

    async def handle_voice_update(
        self,
        member,
        before,
        after
    ):

        guild = member.guild

        # Someone joined a VC.
        if after.channel:

            # Don't react to the bot itself.
            if member.bot:
                return

            # Automatically join the VC.
            await self.connect(
                after.channel
            )

        # Someone left/moved from a VC.
        if before.channel:

            channel = before.channel

            humans = [
                m
                for m in channel.members
                if not m.bot
            ]

            # Nobody is left.
            if not humans:

                voice_client = self.connections.get(
                    guild.id
                )

                if (
                    voice_client
                    and voice_client.channel
                    and voice_client.channel.id == channel.id
                ):

                    await self.disconnect(
                        guild.id
                    )

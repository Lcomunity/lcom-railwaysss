import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os
import time
import aiohttp
from pydub import AudioSegment

import os
# ... reszta importów ...

TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True 
bot = commands.Bot(command_prefix='!', intents=intents)

YDL_OPTIONS = {'format': 'bestaudio', 'noplaylist': 'True'}
FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}

async def send_to_webhook(file_path, user_list):
    """Sends the recording with an Embed listing the users."""
    try:
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
            
            # Tworzenie Embedu
            embed = discord.Embed(
                title="🎙️ New Recording Fragment",
                description=f"Audio captured from the voice channel.",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            # Lista użytkowników w Embedzie
            users_str = ", ".join(user_list) if user_list else "None (Silence/Error)"
            embed.add_field(name="Users present during recording:", value=users_str, inline=False)
            embed.set_footer(text="Music & Recorder Bot")

            with open(file_path, 'rb') as f:
                discord_file = discord.File(f, filename=f"recording_{int(time.time())}.mp3")
                await webhook.send(embed=embed, file=discord_file)
        print(f"[LOG] Sent {file_path} with Embed to webhook.")
    except Exception as e:
        print(f"[ERROR] Webhook failed: {e}")

def process_audio(recorded_files):
    print("[LOG] Merging audio files...")
    combined = AudioSegment.empty()
    for user_id, file in recorded_files.items():
        try:
            user_audio = AudioSegment.from_file(file.file, format="mp3")
            combined = user_audio if len(combined) == 0 else combined.overlay(user_audio)
        except Exception as e:
            print(f"[ERROR] Audio processing error for user {user_id}: {e}")

    if len(combined) > 0:
        filename = f"final_rec_{int(time.time())}.mp3"
        combined.export(filename, format="mp3")
        return filename
    return None

async def finished_callback(sink, channel, user_list):
    """Callback triggered after recording stops."""
    if not sink.audio_data:
        print("[LOG] No audio data received.")
        return

    loop = asyncio.get_event_loop()
    final_file = await loop.run_in_executor(None, process_audio, sink.audio_data)
    
    if final_file:
        await send_to_webhook(final_file, user_list)
        if os.path.exists(final_file):
            os.remove(final_file)

async def ensure_voice_connection():
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not channel: return None
    voice_client = discord.utils.get(bot.voice_clients, guild=channel.guild)
    if not voice_client:
        try: return await channel.connect()
        except: return None
    elif voice_client.channel.id != TARGET_CHANNEL_ID:
        await voice_client.move_to(channel)
    return voice_client

@tasks.loop(minutes=1)
async def recording_loop():
    try:
        vc = await ensure_voice_connection()
        if not vc: return

        # Lista osób (bez botów) obecnych W MOMENCIE startu/stopu
        current_members = [m.display_name for m in vc.channel.members if not m.bot]
        print(f"[DEBUG] People on channel: {len(current_members)}")

        # 1. Stopujemy stare nagranie
        if hasattr(vc, 'recording') and vc.recording:
            print("[LOG] Stopping old segment...")
            vc.stop_recording() 
            await asyncio.sleep(2) 

        # 2. Startujemy nowe nagranie - przekazujemy listę osób do callbacka
        if len(current_members) > 0:
            print("[LOG] Starting new segment...")
            vc.start_recording(discord.sinks.MP3Sink(), finished_callback, vc.channel, current_members)
        else:
            print("[LOG] Channel empty. Waiting...")

    except Exception as e:
        print(f"[ERROR] recording_loop error: {e}")

@bot.event
async def on_ready():
    print(f'--- Bot {bot.user} is ONLINE ---')
    await asyncio.sleep(2)
    if not recording_loop.is_running():
        recording_loop.start()

@bot.event
async def on_voice_state_update(member, before, after):
    if member.id == bot.user.id and (after.channel is None or after.channel.id != TARGET_CHANNEL_ID):
        await asyncio.sleep(1)
        await ensure_voice_connection()

@bot.command()
async def play(ctx, url):
    vc = await ensure_voice_connection()
    if not vc: return
    async with ctx.typing():
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)
            source = await discord.FFmpegOpusAudio.from_probe(info['url'], **FFMPEG_OPTIONS)
            if vc.is_playing(): vc.stop()
            vc.play(source)
    await ctx.send(f"Playing: **{info.get('title')}**")

bot.run(TOKEN)
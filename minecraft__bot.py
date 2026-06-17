import discord
from discord.ext import commands
from supabase import create_client, Client
import subprocess
import psutil
import asyncio
import os

PLAYIT_PATH = r"C:\Program Files\playit_gg\bin\playit.exe"
# ─── Configuration ───────────────────────────────────────────────────────────

TOKEN = os.getenv("TOKEN")  # Discord bot token from environment variable
RUN_BAT_PATH = r"C:\NEUROCRAFT\run.bat"

# ─── Supabase Setup ──────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ─── Bot Setup ───────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Holds the running server process so stopserver can write to its stdin
server_process: subprocess.Popen | None = None

# ─── Events ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print("─────────────────────────────────")

# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_minecraft_running() -> bool:
    """Returns True if Minecraft server Java process is running."""
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = proc.info["name"] or ""
            cmdline = " ".join(proc.info["cmdline"] or [])
            if (
                "java" in name.lower()
                and (
                    "paper" in cmdline.lower()
                    or "server.jar" in cmdline.lower()
                    or "paper-1.21" in cmdline.lower()
                )
            ):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def read_line_blocking(stdout):
    """Blocking readline — runs in a thread so it doesn't freeze the event loop."""
    return stdout.readline()

def update_server_status(status, players):
    supabase.table("server_status").upsert({
        "id": 1,
        "status": status,
        "players_online": players
    }).execute()
# ─── Commands ────────────────────────────────────────────────────────────────

@bot.command(name="startserver")
async def start_server(ctx: commands.Context):
    """Starts the Minecraft server and notifies when it's online."""
    if not os.path.exists(RUN_BAT_PATH):
        await ctx.send(f"❌ Batch file not found at `{RUN_BAT_PATH}`")
        return

    if is_minecraft_running():
        await ctx.send("⚠️ Server is already running!")
        return

    try:
        global server_process
        server_process = subprocess.Popen(
            RUN_BAT_PATH,
            cwd=r"C:\NEUROCRAFT",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            shell=True,
            bufsize=1,  # Line-buffered
        )
        process = server_process
        subprocess.Popen(PLAYIT_PATH)
        await ctx.send("🔥 Minecraft server is starting... I'll let you know when it's ready!")

        async def monitor_server():
            timeout = 300  # 5 minutes
            start_time = asyncio.get_event_loop().time()

            while True:
                # ✅ FIX: Run blocking readline in a thread — won't freeze the bot
                line = await asyncio.get_event_loop().run_in_executor(
                    None, read_line_blocking, process.stdout
                )

                if not line:
                    # Process ended / stdout closed
                    await ctx.send("❌ Server process exited unexpectedly.")
                    global server_process
                    server_process = None
                    return

                line_stripped = line.strip()
                print(line_stripped)  # Log to console

                # ✅ FIX: Broader "Done" check — catches all Minecraft variants
                if "Done (" in line_stripped and "help" in line_stripped.lower():
                    await ctx.send("🟢 **Server is ONLINE and fully loaded! Join now.**")
                    update_server_status("online", 0)  # Update Supabase status to online with 0 players
                    return

                # Timeout check
                if asyncio.get_event_loop().time() - start_time > timeout:
                    await ctx.send("⚠️ Server took too long to start (5 min timeout).")
                    return

        asyncio.create_task(monitor_server())

    except Exception as e:
        await ctx.send(f"❌ Failed to start server: `{e}`")


@bot.command(name="stopserver")
async def stop_server(ctx: commands.Context):
    """Gracefully stops the Minecraft server by sending 'stop' to its console."""
    global server_process

    if server_process is None or server_process.poll() is not None:
        # poll() returns None if still running, otherwise exit code
        await ctx.send("⚠️ No running server process found. Was it started with `!startserver`?")
        return

    try:
        # ✅ Write "stop" to the server's stdin — same as typing it in the console
        server_process.stdin.write("stop\n")
        server_process.stdin.flush()

        await ctx.send("🛑 Sent `stop` to the server console. Waiting for it to shut down...")

        # Wait up to 30 seconds for it to actually exit
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: server_process.wait(timeout=30))

        server_process = None
        await ctx.send("✅ Server has fully stopped.")
        update_server_status("offline", 0)  # Update Supabase status to offline with 0 players

    except subprocess.TimeoutExpired:
        await ctx.send("⚠️ Server didn't stop in 30 seconds. Force killing just the server process...")
        server_process.kill()
        server_process = None
        await ctx.send("🛑 Server force-killed.")

    except Exception as e:
        await ctx.send(f"❌ Error stopping server: `{e}`")


@bot.command(name="serverstatus")
async def server_status(ctx: commands.Context):
    """Checks if the Minecraft server Java process is currently running."""
    if is_minecraft_running():
        await ctx.send("🟢 Server is **ONLINE**")
    else:
        await ctx.send("🔴 Server is **OFFLINE**")


@bot.command(name="ping")
async def ping(ctx: commands.Context):
    """Check if the bot is online."""
    await ctx.send(f"🟢 Bot is online! Latency: `{round(bot.latency * 1000)}ms`")


# ─── Error Handling ──────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
    await ctx.send(f"❌ Error: `{error}`")


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)
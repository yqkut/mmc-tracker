import discord
from discord.ext import commands, tasks
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import json
import asyncio

TOKEN = 'ur token'
intents = discord.Intents.all()

bot = commands.Bot(command_prefix='ur prefix', intents=intents)

user_tracked_players = {}

CONFIG_FILE = 'config.json'


def load_config():
    try:
        with open(CONFIG_FILE, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.decoder.JSONDecodeError):
        return {'user_tracked_players': {}}


def save_config():
    config_data = {'user_tracked_players': {}}
    for user_id, tracked_players in user_tracked_players.items():
        config_data['user_tracked_players'][user_id] = {}
        for player_username, player_info in tracked_players.items():
            config_data['user_tracked_players'][user_id][player_username] = {'channel_id': player_info['channel_id'], 'status': None}

    with open(CONFIG_FILE, 'w') as file:
        json.dump(config_data, file)


async def send_status_update(user_id, player_username, current_status, last_status, channel_id):
    user = bot.get_user(int(user_id))
    channel = bot.get_channel(channel_id)

    if current_status == "Banned":
        message = f"{player_username} is currently banned."
    elif current_status:
        message = f"{player_username} status: {current_status}."
    else:
        message = f"{player_username} is offline. Last seen {get_last_seen(player_username)} ago."

    await channel.send(f'```{message}```')
    user_tracked_players[user_id][player_username]['status'] = current_status  # Update status


async def track_player_real_time(user_id, player_username, channel_id):
    while True:
        current_status = get_player_status(player_username)
        last_status = user_tracked_players[user_id][player_username]['status']

        if current_status != last_status and last_status is not None:
            await send_status_update(user_id, player_username, current_status, last_status, channel_id)

        user_tracked_players[user_id][player_username]['status'] = current_status  # Update status

        await asyncio.sleep(60)  # Check every 60 seconds


@bot.event
async def on_ready():
    for user_id, tracked_players in user_tracked_players.items():
        for player_username, player_info in tracked_players.items():
            if 'task' not in player_info:
                task = bot.loop.create_task(track_player_real_time(user_id, player_username, player_info['channel_id']))
                user_tracked_players[user_id][player_username]['task'] = task

    print(f'{bot.user.name} is connected to discord baby!')

    activity = discord.Activity(type=discord.ActivityType.playing, name="mmc tracker made by yakut")
    await bot.change_presence(activity=activity)


@bot.event
async def on_shutdown():
    save_config()


@bot.command(name='lookup')
async def lookup_player(ctx, player_username):
    try:
        player_status = get_player_status(player_username)

        if player_status:
            if player_status == "Banned":
                await ctx.send(f'```-  {player_username} is currently banned.```')
            else:
                await ctx.send(f'```+  {player_username} is online! {player_status}.```')
        else:
            last_seen_time = get_last_seen(player_username)
            if last_seen_time is not None:
                await ctx.send(f'```-  {player_username} is offline. Last seen {last_seen_time} ago.```')
            else:
                await ctx.send(f'```-  {player_username} is offline. Last seen information not available.```')
    except Exception as e:
        print(f'Error during lookup: {e}')
        await ctx.send('```An error occurred while looking up the player.```')


@bot.command(name='track')
async def track_player(ctx, *player_usernames):
    user_id = str(ctx.author.id)

    if user_id not in user_tracked_players:
        user_tracked_players[user_id] = {}

    for player_username in player_usernames:
        if player_username not in user_tracked_players[user_id]:
            user_tracked_players[user_id][player_username] = {'channel_id': ctx.channel.id, 'status': None}
            task = bot.loop.create_task(track_player_real_time(user_id, player_username, ctx.channel.id))
            user_tracked_players[user_id][player_username]['task'] = task
            await ctx.send(f'```Now tracking: {player_username}```')
        else:
            await ctx.send(f'```{player_username} is already being tracked.```')

    save_config()


@bot.command(name='untrack')
async def untrack_player(ctx, *player_usernames):
    user_id = str(ctx.author.id)

    if user_id in user_tracked_players:
        for player_username in player_usernames:
            if player_username in user_tracked_players[user_id]:
                task = user_tracked_players[user_id][player_username].get('task')
                if task:
                    task.cancel()
                    del user_tracked_players[user_id][player_username]['task']

                del user_tracked_players[user_id][player_username]
                await ctx.send(f'```Stopped tracking: {player_username}```')
            else:
                await ctx.send(f'{player_username} is not being tracked.```')

        save_config()
    else:
        await ctx.send('```You are not tracking any players.```')


@bot.command(name='trackinglist')
async def tracker_list(ctx):
    user_id = str(ctx.author.id)

    if user_id in user_tracked_players:
        tracked_players = user_tracked_players[user_id]
        if tracked_players:
            await ctx.send(f'```You are currently tracking: {", ".join(tracked_players)}```')
        else:
            await ctx.send('```You are not tracking any players.```')
    else:
        await ctx.send('```You are not tracking any players.```')


def get_player_status(player_username):
    try:
        player_url = f'http://minemen.club/player/{player_username}'
        response = requests.get(player_url)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            status_element = soup.find('span', {'class': 'player-status'})

            if status_element:
                status_text = status_element.text

                if "banned" in status_text:
                    return "Banned"
                elif "online" in status_element.attrs.get('class', []):
                    return status_text.strip()

    except Exception as e:
        print(f'Error checking player status: {e}')

    return None


def get_last_seen(player_username):
    try:
        player_url = f'http://minemen.club/player/{player_username}'
        response = requests.get(player_url)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            last_seen_element = soup.find('time', {'class': 'timeago'})

            if last_seen_element:
                dt = datetime.fromisoformat(last_seen_element['datetime'][:-1])
                now = datetime.now(timezone.utc)

                if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                    dt = dt.replace(tzinfo=timezone.utc)

                time_difference = now - dt
                days, seconds = divmod(time_difference.total_seconds(), 86400)
                hours, seconds = divmod(seconds, 3600)
                minutes, seconds = divmod(seconds, 60)

                formatted_time = ""
                if days:
                    formatted_time += f"{int(days)} days, "
                if hours:
                    formatted_time += f"{int(hours)} hours, "
                if minutes:
                    formatted_time += f"{int(minutes)} minutes"

                return formatted_time.strip()
            else:
                return None

    except Exception as e:
        print(f'Error checking player status: {e}')

    return None


tracked_players = load_config().get('user_tracked_players', {})
bot.run(TOKEN)

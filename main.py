import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction, Embed, ButtonStyle, SelectOption
from discord.ui import Button, View, Select, Modal, TextInput
import asyncio
import aiohttp
from datetime import datetime, timedelta
import random
import os
import json
import sqlite3
import hashlib
import re
from flask import Flask
from threading import Thread
import logging

# Flask for keeping bot alive
app = Flask('')

@app.route('/')
def home():
    return "🚀 AetherBot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Database setup
def init_db():
    conn = sqlite3.connect('aether.db')
    c = conn.cursor()

    # Guild configs
    c.execute('''CREATE TABLE IF NOT EXISTS guild_configs (
        guild_id TEXT PRIMARY KEY,
        logs_channel TEXT,
        welcome_channel TEXT,
        modlog_channel TEXT,
        automod_channel TEXT,
        xp_enabled BOOLEAN DEFAULT 1,
        welcome_enabled BOOLEAN DEFAULT 1,
        automod_enabled BOOLEAN DEFAULT 1,
        economy_enabled BOOLEAN DEFAULT 1,
        music_enabled BOOLEAN DEFAULT 1,
        prefix TEXT DEFAULT '!'
    )''')

    # User XP and levels
    c.execute('''CREATE TABLE IF NOT EXISTS user_xp (
        user_id TEXT,
        guild_id TEXT,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        coins INTEGER DEFAULT 100,
        last_daily DATE,
        PRIMARY KEY (user_id, guild_id)
    )''')

    # Warnings system
    c.execute('''CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        guild_id TEXT,
        moderator_id TEXT,
        reason TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    # Automod logs
    c.execute('''CREATE TABLE IF NOT EXISTS automod_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        guild_id TEXT,
        action TEXT,
        reason TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    # Reaction roles
    c.execute('''CREATE TABLE IF NOT EXISTS reaction_roles (
        guild_id TEXT,
        message_id TEXT,
        emoji TEXT,
        role_id TEXT,
        PRIMARY KEY (guild_id, message_id, emoji)
    )''')

    conn.commit()
    conn.close()

# Bot setup
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

OWNER_ID = 123456789012345678  # Replace with your Discord ID

# Utility functions
def get_db():
    return sqlite3.connect('aether.db')

def get_guild_config(guild_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM guild_configs WHERE guild_id = ?', (str(guild_id),))
    result = c.fetchone()
    conn.close()

    if not result:
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO guild_configs (guild_id) VALUES (?)''', (str(guild_id),))
        conn.commit()
        conn.close()
        return get_guild_config(guild_id)

    return {
        'guild_id': result[0],
        'logs_channel': result[1],
        'welcome_channel': result[2],
        'modlog_channel': result[3],
        'automod_channel': result[4],
        'xp_enabled': bool(result[5]),
        'welcome_enabled': bool(result[6]),
        'automod_enabled': bool(result[7]),
        'economy_enabled': bool(result[8]),
        'music_enabled': bool(result[9]),
        'prefix': result[10]
    }

def update_guild_config(guild_id, **kwargs):
    conn = get_db()
    c = conn.cursor()

    for key, value in kwargs.items():
        c.execute(f'UPDATE guild_configs SET {key} = ? WHERE guild_id = ?', (value, str(guild_id)))

    conn.commit()
    conn.close()

# Advanced security functions
def is_spam(message):
    """Advanced spam detection"""
    # Check for excessive caps
    if len(message.content) > 10 and sum(1 for c in message.content if c.isupper()) / len(message.content) > 0.7:
        return True

    # Check for repeated characters
    if re.search(r'(.)\1{4,}', message.content):
        return True

    # Check for excessive mentions
    if len(message.mentions) > 5:
        return True

    return False

def contains_bad_words(text):
    """Basic profanity filter"""
    bad_words = ['spam', 'scam', 'hack', 'free nitro', 'discord.gg/', 'bit.ly']
    return any(word in text.lower() for word in bad_words)

# Bot events
@bot.event
async def on_ready():
    init_db()
    print(f"🚀 AetherBot is online as {bot.user}")
    print(f"📊 Connected to {len(bot.guilds)} guilds")

    try:
        synced = await bot.tree.sync()
        print(f"⚡ Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

    # Start background tasks
    auto_backup.start()

@bot.event
async def on_guild_join(guild):
    """Initialize config when bot joins a guild"""
    get_guild_config(guild.id)

    # Send welcome message to owner
    try:
        embed = Embed(
            title="🚀 Thanks for adding AetherBot!",
            description=f"Use `/setup` to configure the bot for **{guild.name}**",
            color=0x00ff88
        )
        embed.add_field(name="📖 Getting Started", value="Run `/help` to see all commands", inline=False)
        await guild.owner.send(embed=embed)
    except:
        pass

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    config = get_guild_config(message.guild.id)

    # Automod system
    if config['automod_enabled']:
        if is_spam(message) or contains_bad_words(message.content):
            try:
                await message.delete()

                # Log automod action
                conn = get_db()
                c = conn.cursor()
                c.execute('''INSERT INTO automod_logs (user_id, guild_id, action, reason) 
                           VALUES (?, ?, ?, ?)''', 
                         (str(message.author.id), str(message.guild.id), 'message_deleted', 'spam/bad_words'))
                conn.commit()
                conn.close()

                # Send warning
                embed = Embed(
                    title="⚠️ Message Deleted",
                    description=f"{message.author.mention}, your message was deleted for violating server rules.",
                    color=0xff6b6b
                )
                await message.channel.send(embed=embed, delete_after=5)

            except discord.Forbidden:
                pass

    # XP System
    if config['xp_enabled'] and not message.content.startswith('!'):
        conn = get_db()
        c = conn.cursor()

        # Get or create user XP
        c.execute('SELECT * FROM user_xp WHERE user_id = ? AND guild_id = ?', 
                 (str(message.author.id), str(message.guild.id)))
        user_data = c.fetchone()

        if not user_data:
            c.execute('''INSERT INTO user_xp (user_id, guild_id, xp, level, coins) 
                       VALUES (?, ?, ?, ?, ?)''', 
                     (str(message.author.id), str(message.guild.id), 0, 1, 100))
            xp, level = 0, 1
        else:
            xp, level = user_data[2], user_data[3]

        # Add XP
        xp_gain = random.randint(10, 25)
        xp += xp_gain

        # Check for level up
        xp_needed = level * 150 + 50
        if xp >= xp_needed:
            level += 1
            coins_reward = level * 50

            c.execute('''UPDATE user_xp SET xp = ?, level = ?, coins = coins + ? 
                       WHERE user_id = ? AND guild_id = ?''', 
                     (xp, level, coins_reward, str(message.author.id), str(message.guild.id)))

            # Level up message
            embed = Embed(
                title="🎉 Level Up!",
                description=f"{message.author.mention} reached **Level {level}**!",
                color=0xffd700
            )
            embed.add_field(name="💰 Reward", value=f"+{coins_reward} coins", inline=True)
            embed.add_field(name="📊 XP", value=f"{xp}/{(level * 150 + 50)}", inline=True)
            await message.channel.send(embed=embed)
        else:
            c.execute('''UPDATE user_xp SET xp = ? WHERE user_id = ? AND guild_id = ?''', 
                     (xp, str(message.author.id), str(message.guild.id)))

        conn.commit()
        conn.close()

    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    """Welcome new members"""
    config = get_guild_config(member.guild.id)

    if config['welcome_enabled'] and config['welcome_channel']:
        try:
            channel = bot.get_channel(int(config['welcome_channel']))
            if channel:
                embed = Embed(
                    title="🎉 Welcome to the server!",
                    description=f"Hey {member.mention}! Welcome to **{member.guild.name}**",
                    color=0x00ff88
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.add_field(name="👤 Member Count", value=f"You are member #{member.guild.member_count}", inline=False)
                embed.set_footer(text=f"Joined • {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                await channel.send(embed=embed)
        except:
            pass

# Advanced Setup Modal
class SetupModal(Modal, title="🚀 AetherBot Setup"):
    def __init__(self):
        super().__init__()

        self.logs_channel = TextInput(
            label="📋 Logs Channel ID",
            placeholder="Enter channel ID for logs...",
            required=False,
            max_length=20
        )

        self.welcome_channel = TextInput(
            label="👋 Welcome Channel ID", 
            placeholder="Enter channel ID for welcomes...",
            required=False,
            max_length=20
        )

        self.modlog_channel = TextInput(
            label="🛡️ Modlog Channel ID",
            placeholder="Enter channel ID for mod logs...",
            required=False,
            max_length=20
        )

        self.automod_channel = TextInput(
            label="🤖 Automod Channel ID",
            placeholder="Enter channel ID for automod alerts...",
            required=False,
            max_length=20
        )

        # Add the TextInput components to the modal
        self.add_item(self.logs_channel)
        self.add_item(self.welcome_channel)
        self.add_item(self.modlog_channel)
        self.add_item(self.automod_channel)

    async def on_submit(self, interaction: Interaction):
        try:
            update_data = {}

            if self.logs_channel.value:
                update_data['logs_channel'] = self.logs_channel.value
            if self.welcome_channel.value:
                update_data['welcome_channel'] = self.welcome_channel.value
            if self.modlog_channel.value:
                update_data['modlog_channel'] = self.modlog_channel.value
            if self.automod_channel.value:
                update_data['automod_channel'] = self.automod_channel.value

            update_guild_config(interaction.guild.id, **update_data)

            embed = Embed(
                title="✅ Setup Complete!",
                description="AetherBot has been configured successfully!",
                color=0x00ff88
            )

            for key, value in update_data.items():
                if value:
                    channel = bot.get_channel(int(value))
                    embed.add_field(
                        name=key.replace('_', ' ').title(),
                        value=f"#{channel.name}" if channel else "Invalid Channel",
                        inline=True
                    )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Setup failed: {str(e)}", ephemeral=True
            )

# Setup Command
@bot.tree.command(name="setup", description="🚀 Complete bot setup wizard")
async def setup(interaction: Interaction):
    if not interaction.user.guild_permissions.administrator:
        embed = Embed(
            title="❌ Permission Denied",
            description="You need **Administrator** permissions to use this command.",
            color=0xff6b6b
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    modal = SetupModal()
    await interaction.response.send_modal(modal)

# Feature Toggle Command
@bot.tree.command(name="toggle", description="🔧 Toggle bot features on/off")
@app_commands.describe(feature="Choose a feature to toggle")
@app_commands.choices(feature=[
    app_commands.Choice(name="XP System", value="xp_enabled"),
    app_commands.Choice(name="Welcome Messages", value="welcome_enabled"),
    app_commands.Choice(name="Auto Moderation", value="automod_enabled"),
    app_commands.Choice(name="Economy System", value="economy_enabled"),
    app_commands.Choice(name="Music Commands", value="music_enabled")
])
async def toggle(interaction: Interaction, feature: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.administrator:
        embed = Embed(
            title="❌ Permission Denied",
            description="You need **Administrator** permissions to use this command.",
            color=0xff6b6b
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    config = get_guild_config(interaction.guild.id)
    current_status = config[feature.value]
    new_status = not current_status

    update_guild_config(interaction.guild.id, **{feature.value: new_status})

    embed = Embed(
        title="🔧 Feature Toggled",
        description=f"**{feature.name}** is now {'✅ Enabled' if new_status else '❌ Disabled'}",
        color=0x00ff88 if new_status else 0xff6b6b
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# Advanced Help Command with Navigation
class HelpView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.current_page = "main"

    @discord.ui.button(label="🏠 Main", style=ButtonStyle.primary)
    async def main_page(self, interaction: Interaction, button: Button):
        embed = Embed(
            title="🚀 AetherBot - Command Center",
            description="**The most advanced Discord bot for your server!**",
            color=0x7289da
        )
        embed.add_field(
            name="⚡ Quick Start",
            value="• `/setup` - Configure the bot\n• `/toggle` - Enable/disable features\n• `/help` - View this menu",
            inline=False
        )
        embed.add_field(
            name="📊 Categories",
            value="Use the buttons below to explore different command categories!",
            inline=False
        )
        embed.set_footer(text="Click the buttons below to navigate • Made with ⚡ by AetherBot")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🛡️ Moderation", style=ButtonStyle.secondary)
    async def mod_page(self, interaction: Interaction, button: Button):
        embed = Embed(
            title="🛡️ Moderation Commands",
            description="Keep your server safe and organized",
            color=0xff6b6b
        )
        embed.add_field(name="/ban", value="Ban a user from the server", inline=False)
        embed.add_field(name="/kick", value="Kick a user from the server", inline=False)
        embed.add_field(name="/warn", value="Warn a user for misconduct", inline=False)
        embed.add_field(name="/warnings", value="View user's warning history", inline=False)
        embed.add_field(name="/purge", value="Delete multiple messages", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📊 Levels & XP", style=ButtonStyle.success)
    async def xp_page(self, interaction: Interaction, button: Button):
        embed = Embed(
            title="📊 Levels & XP System",
            description="Engage your community with leveling",
            color=0xffd700
        )
        embed.add_field(name="/rank", value="Check your current rank", inline=False)
        embed.add_field(name="/leaderboard", value="View server leaderboard", inline=False)
        embed.add_field(name="/daily", value="Claim daily coins", inline=False)
        embed.add_field(name="Auto XP", value="Gain XP by chatting!", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="💰 Economy", style=ButtonStyle.success)
    async def economy_page(self, interaction: Interaction, button: Button):
        embed = Embed(
            title="💰 Economy System",
            description="Virtual economy for your server",
            color=0x00ff88
        )
        embed.add_field(name="/balance", value="Check your coin balance", inline=False)
        embed.add_field(name="/daily", value="Get daily coins", inline=False)
        embed.add_field(name="/gamble", value="Risk coins for more!", inline=False)
        embed.add_field(name="/shop", value="Buy items with coins", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

@bot.tree.command(name="help", description="📖 View all bot commands and features")
async def help_command(interaction: Interaction):
    view = HelpView()
    embed = Embed(
        title="🚀 AetherBot - Command Center",
        description="**The most advanced Discord bot for your server!**",
        color=0x7289da
    )
    embed.add_field(
        name="⚡ Quick Start",
        value="• `/setup` - Configure the bot\n• `/toggle` - Enable/disable features\n• `/help` - View this menu",
        inline=False
    )
    embed.add_field(
        name="📊 Categories",
        value="Use the buttons below to explore different command categories!",
        inline=False
    )
    embed.set_footer(text="Click the buttons below to navigate • Made with ⚡ by AetherBot")

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# User Info Command
@bot.tree.command(name="userinfo", description="👤 Get detailed info about a user")
async def userinfo(interaction: Interaction, user: discord.Member = None):
    if not user:
        user = interaction.user

    # Get user XP data
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM user_xp WHERE user_id = ? AND guild_id = ?', 
             (str(user.id), str(interaction.guild.id)))
    xp_data = c.fetchone()
    conn.close()

    embed = Embed(
        title=f"👤 {user.display_name}",
        color=user.color if user.color != discord.Color.default() else 0x7289da
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    # Basic info
    embed.add_field(name="🆔 User ID", value=user.id, inline=True)
    embed.add_field(name="📅 Account Created", value=user.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="📅 Joined Server", value=user.joined_at.strftime("%Y-%m-%d"), inline=True)

    # XP info
    if xp_data:
        embed.add_field(name="📊 Level", value=xp_data[3], inline=True)
        embed.add_field(name="⚡ XP", value=xp_data[2], inline=True)
        embed.add_field(name="💰 Coins", value=xp_data[4], inline=True)

    # Roles
    roles = [role.mention for role in user.roles[1:]]  # Exclude @everyone
    if roles:
        embed.add_field(name="🎭 Roles", value=" ".join(roles[:10]), inline=False)

    await interaction.response.send_message(embed=embed)

# Rank Command
@bot.tree.command(name="rank", description="📊 Check your server rank and XP")
async def rank(interaction: Interaction, user: discord.Member = None):
    if not user:
        user = interaction.user

    conn = get_db()
    c = conn.cursor()

    # Get user data
    c.execute('SELECT * FROM user_xp WHERE user_id = ? AND guild_id = ?', 
             (str(user.id), str(interaction.guild.id)))
    user_data = c.fetchone()

    if not user_data:
        embed = Embed(
            title="❌ No Data Found",
            description=f"{user.display_name} hasn't gained any XP yet!",
            color=0xff6b6b
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Get rank
    c.execute('''SELECT COUNT(*) + 1 FROM user_xp 
               WHERE guild_id = ? AND xp > ?''', 
             (str(interaction.guild.id), user_data[2]))
    rank = c.fetchone()[0]

    conn.close()

    level = user_data[3]
    xp = user_data[2]
    coins = user_data[4]
    next_level_xp = level * 150 + 50

    embed = Embed(
        title=f"📊 {user.display_name}'s Rank",
        color=user.color if user.color != discord.Color.default() else 0x7289da
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(name="🏆 Rank", value=f"#{rank}", inline=True)
    embed.add_field(name="📊 Level", value=level, inline=True)
    embed.add_field(name="💰 Coins", value=coins, inline=True)
    embed.add_field(name="⚡ XP Progress", value=f"{xp}/{next_level_xp}", inline=False)

    # Progress bar
    progress = min(xp / next_level_xp, 1.0)
    bar_length = 20
    filled = int(progress * bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)
    embed.add_field(name="📈 Progress Bar", value=f"`{bar}` {progress:.1%}", inline=False)

    await interaction.response.send_message(embed=embed)

# Daily Coins Command
@bot.tree.command(name="daily", description="💰 Claim your daily coins")
async def daily(interaction: Interaction):
    conn = get_db()
    c = conn.cursor()

    # Check if user exists
    c.execute('SELECT * FROM user_xp WHERE user_id = ? AND guild_id = ?', 
             (str(interaction.user.id), str(interaction.guild.id)))
    user_data = c.fetchone()

    if not user_data:
        c.execute('''INSERT INTO user_xp (user_id, guild_id, xp, level, coins, last_daily) 
                   VALUES (?, ?, ?, ?, ?, ?)''', 
                 (str(interaction.user.id), str(interaction.guild.id), 0, 1, 100, datetime.now().date()))
        daily_reward = 100
    else:
        last_daily = user_data[5]
        if last_daily and datetime.strptime(last_daily, '%Y-%m-%d').date() == datetime.now().date():
            embed = Embed(
                title="⏰ Already Claimed",
                description="You've already claimed your daily coins today! Come back tomorrow.",
                color=0xff6b6b
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            conn.close()
            return

        # Calculate daily reward based on level
        level = user_data[3]
        daily_reward = 50 + (level * 10)

        c.execute('''UPDATE user_xp SET coins = coins + ?, last_daily = ? 
                   WHERE user_id = ? AND guild_id = ?''', 
                 (daily_reward, datetime.now().date(), str(interaction.user.id), str(interaction.guild.id)))

    conn.commit()
    conn.close()

    embed = Embed(
        title="💰 Daily Coins Claimed!",
        description=f"You received **{daily_reward}** coins!",
        color=0x00ff88
    )
    embed.add_field(name="💡 Tip", value="Higher levels give more daily coins!", inline=False)
    embed.set_footer(text="Come back tomorrow for more coins!")

    await interaction.response.send_message(embed=embed)

# Leaderboard Command
@bot.tree.command(name="leaderboard", description="🏆 View the server leaderboard")
async def leaderboard(interaction: Interaction):
    conn = get_db()
    c = conn.cursor()

    c.execute('''SELECT user_id, xp, level, coins FROM user_xp 
               WHERE guild_id = ? ORDER BY xp DESC LIMIT 10''', 
             (str(interaction.guild.id),))

    top_users = c.fetchall()
    conn.close()

    if not top_users:
        embed = Embed(
            title="📊 Server Leaderboard",
            description="No users with XP found yet!",
            color=0x7289da
        )
        await interaction.response.send_message(embed=embed)
        return

    embed = Embed(
        title="🏆 Server Leaderboard",
        description="Top 10 users by XP",
        color=0xffd700
    )

    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7

    for i, (user_id, xp, level, coins) in enumerate(top_users):
        user = bot.get_user(int(user_id))
        name = user.display_name if user else f"User {user_id}"

        embed.add_field(
            name=f"{medals[i]} #{i+1} {name}",
            value=f"Level {level} • {xp} XP • {coins} 💰",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

# Moderation Commands
@bot.tree.command(name="warn", description="⚠️ Warn a user")
@app_commands.describe(user="User to warn", reason="Reason for the warning")
async def warn(interaction: Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.moderate_members:
        embed = Embed(
            title="❌ Permission Denied",
            description="You need **Moderate Members** permission to use this command.",
            color=0xff6b6b
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO warnings (user_id, guild_id, moderator_id, reason) 
               VALUES (?, ?, ?, ?)''', 
             (str(user.id), str(interaction.guild.id), str(interaction.user.id), reason))
    conn.commit()

    # Count total warnings
    c.execute('SELECT COUNT(*) FROM warnings WHERE user_id = ? AND guild_id = ?', 
             (str(user.id), str(interaction.guild.id)))
    warning_count = c.fetchone()[0]
    conn.close()

    embed = Embed(
        title="⚠️ User Warned",
        description=f"{user.mention} has been warned",
        color=0xffa500
    )
    embed.add_field(name="👮 Moderator", value=interaction.user.mention, inline=True)
    embed.add_field(name="📋 Reason", value=reason, inline=True)
    embed.add_field(name="📊 Total Warnings", value=warning_count, inline=True)

    await interaction.response.send_message(embed=embed)

    # Try to DM the user
    try:
        dm_embed = Embed(
            title="⚠️ Warning Received",
            description=f"You have been warned in **{interaction.guild.name}**",
            color=0xffa500
        )
        dm_embed.add_field(name="📋 Reason", value=reason, inline=False)
        dm_embed.add_field(name="📊 Total Warnings", value=warning_count, inline=False)
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        pass

@bot.tree.command(name="warnings", description="📋 View a user's warning history")
@app_commands.describe(user="User to check warnings for")
async def warnings(interaction: Interaction, user: discord.Member):
    if not interaction.user.guild_permissions.moderate_members:
        embed = Embed(
            title="❌ Permission Denied",
            description="You need **Moderate Members** permission to use this command.",
            color=0xff6b6b
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT moderator_id, reason, timestamp FROM warnings 
               WHERE user_id = ? AND guild_id = ? ORDER BY timestamp DESC LIMIT 10''', 
             (str(user.id), str(interaction.guild.id)))

    warnings_list = c.fetchall()
    conn.close()

    embed = Embed(
        title=f"📋 Warnings for {user.display_name}",
        description=f"Total warnings: **{len(warnings_list)}**",
        color=0xffa500
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    if not warnings_list:
        embed.add_field(name="✅ Clean Record", value="No warnings found!", inline=False)
    else:
        for i, (mod_id, reason, timestamp) in enumerate(warnings_list[:5], 1):
            moderator = bot.get_user(int(mod_id))
            mod_name = moderator.display_name if moderator else f"Unknown Moderator"

            embed.add_field(
                name=f"Warning #{i}",
                value=f"**Moderator:** {mod_name}\n**Reason:** {reason}\n**Date:** {timestamp[:10]}",
                inline=False
            )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="purge", description="🗑️ Delete multiple messages")
@app_commands.describe(amount="Number of messages to delete (1-100)")
async def purge(interaction: Interaction, amount: int):
    if not interaction.user.guild_permissions.manage_messages:
        embed = Embed(
            title="❌ Permission Denied",
            description="You need **Manage Messages** permission to use this command.",
            color=0xff6b6b
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if amount < 1 or amount > 100:
        embed = Embed(
            title="❌ Invalid Amount",
            description="Please specify a number between 1 and 100.",
            color=0xff6b6b
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    deleted = await interaction.followup.channel.purge(limit=amount)

    embed = Embed(
        title="🗑️ Messages Purged",
        description=f"Successfully deleted **{len(deleted)}** messages.",
        color=0x00ff88
    )
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")

    await interaction.followup.send(embed=embed, ephemeral=True)

# Economy Commands
@bot.tree.command(name="balance", description="💰 Check your coin balance")
async def balance(interaction: Interaction, user: discord.Member = None):
    if not user:
        user = interaction.user

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT coins FROM user_xp WHERE user_id = ? AND guild_id = ?', 
             (str(user.id), str(interaction.guild.id)))

    result = c.fetchone()
    conn.close()

    coins = result[0] if result else 0

    embed = Embed(
        title=f"💰 {user.display_name}'s Balance",
        description=f"**{coins:,}** coins",
        color=0xffd700
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    if coins < 100:
        embed.add_field(name="💡 Tip", value="Use `/daily` to get more coins!", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="gamble", description="🎰 Gamble your coins for a chance to win big!")
@app_commands.describe(amount="Amount to gamble")
async def gamble(interaction: Interaction, amount: int):
    if amount < 10:
        embed = Embed(
            title="❌ Invalid Amount",
            description="Minimum gamble amount is 10 coins.",
            color=0xff6b6b
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT coins FROM user_xp WHERE user_id = ? AND guild_id = ?', 
             (str(interaction.user.id), str(interaction.guild.id)))

    result = c.fetchone()
    if not result or result[0] < amount:
        embed = Embed(
            title="❌ Insufficient Funds",
            description="You don't have enough coins to gamble that amount!",
            color=0xff6b6b
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        conn.close()
        return

    # Gambling logic
    roll = random.randint(1, 100)

    if roll <= 45:  # 45% chance to lose
        outcome = "lose"
        multiplier = 0
        result_coins = -amount
    elif roll <= 80:  # 35% chance to win small
        outcome = "win_small"
        multiplier = 1.5
        result_coins = int(amount * 0.5)
    elif roll <= 95:  # 15% chance to win big
        outcome = "win_big"
        multiplier = 2
        result_coins = amount
    else:  # 5% chance to jackpot
        outcome = "jackpot"
        multiplier = 5
        result_coins = amount * 4

    # Update coins
    c.execute('''UPDATE user_xp SET coins = coins + ? 
               WHERE user_id = ? AND guild_id = ?''', 
             (result_coins, str(interaction.user.id), str(interaction.guild.id)))

    new_balance = result[0] + result_coins
    conn.commit()
    conn.close()

    # Create response embed
    if outcome == "lose":
        embed = Embed(
            title="💸 You Lost!",
            description=f"You lost **{amount}** coins!",
            color=0xff6b6b
        )
        embed.add_field(name="🎲 Roll", value=f"{roll}/100", inline=True)
    elif outcome == "win_small":
        embed = Embed(
            title="💰 Small Win!",
            description=f"You won **{result_coins}** coins!",
            color=0xffa500
        )
        embed.add_field(name="🎲 Roll", value=f"{roll}/100", inline=True)
    elif outcome == "win_big":
        embed = Embed(
            title="🎉 Big Win!",
            description=f"You won **{result_coins}** coins!",
            color=0x00ff88
        )
        embed.add_field(name="🎲 Roll", value=f"{roll}/100", inline=True)
    else:  # jackpot
        embed = Embed(
            title="🎰 JACKPOT! 🎰",
            description=f"AMAZING! You won **{result_coins}** coins!",
            color=0xffd700
        )
        embed.add_field(name="🎲 Roll", value=f"{roll}/100 (JACKPOT!)", inline=True)

    embed.add_field(name="💰 New Balance", value=f"{new_balance:,} coins", inline=True)

    await interaction.response.send_message(embed=embed)

# Server Info Command
@bot.tree.command(name="serverinfo", description="ℹ️ Get detailed server information")
async def serverinfo(interaction: Interaction):
    guild = interaction.guild

    # Count different channel types
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    categories = len(guild.categories)

    # Count members by status
    online = sum(1 for m in guild.members if m.status == discord.Status.online)
    idle = sum(1 for m in guild.members if m.status == discord.Status.idle)
    dnd = sum(1 for m in guild.members if m.status == discord.Status.dnd)
    offline = len(guild.members) - online - idle - dnd

    embed = Embed(
        title=f"ℹ️ {guild.name}",
        description=guild.description or "No server description set",
        color=0x7289da
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="👑 Owner", value=guild.owner.mention, inline=True)
    embed.add_field(name="🆔 Server ID", value=guild.id, inline=True)
    embed.add_field(name="📅 Created", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)

    embed.add_field(
        name="👥 Members",
        value=f"**{guild.member_count}** total\n🟢 {online} online\n🟡 {idle} idle\n🔴 {dnd} dnd\n⚫ {offline} offline",
        inline=True
    )

    embed.add_field(
        name="📁 Channels",
        value=f"**{text_channels + voice_channels}** total\n💬 {text_channels} text\n🔊 {voice_channels} voice\n📂 {categories} categories",
        inline=True
    )

    embed.add_field(name="🎭 Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="😀 Emojis", value=len(guild.emojis), inline=True)
    embed.add_field(name="⚡ Boost Level", value=guild.premium_tier, inline=True)
    embed.add_field(name="💎 Boosts", value=guild.premium_subscription_count, inline=True)

    await interaction.response.send_message(embed=embed)

# Fun Commands
@bot.tree.command(name="8ball", description="🎱 Ask the magic 8-ball a question")
@app_commands.describe(question="Your question for the 8-ball")
async def eight_ball(interaction: Interaction, question: str):
    responses = [
        "It is certain.", "It is decidedly so.", "Without a doubt.", "Yes definitely.",
        "You may rely on it.", "As I see it, yes.", "Most likely.", "Outlook good.",
        "Yes.", "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
        "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
        "Don't count on it.", "My reply is no.", "My sources say no.",
        "Outlook not so good.", "Very doubtful."
    ]

    embed = Embed(
        title="🎱 Magic 8-Ball",
        color=0x7289da
    )
    embed.add_field(name="❓ Question", value=question, inline=False)
    embed.add_field(name="🔮 Answer", value=random.choice(responses), inline=False)
    embed.set_footer(text=f"Asked by {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="flip", description="🪙 Flip a coin")
async def flip(interaction: Interaction):
    result = random.choice(["Heads", "Tails"])
    emoji = "🪙" if result == "Heads" else "🎯"

    embed = Embed(
        title="🪙 Coin Flip",
        description=f"{emoji} **{result}**!",
        color=0xffd700
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="roll", description="🎲 Roll a dice")
@app_commands.describe(sides="Number of sides (default: 6)")
async def roll(interaction: Interaction, sides: int = 6):
    if sides < 2 or sides > 100:
        embed = Embed(
            title="❌ Invalid Dice",
            description="Dice must have between 2 and 100 sides!",
            color=0xff6b6b
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    result = random.randint(1, sides)

    embed = Embed(
        title="🎲 Dice Roll",
        description=f"You rolled a **{result}** on a {sides}-sided die!",
        color=0x00ff88
    )

    await interaction.response.send_message(embed=embed)

# Background tasks
@tasks.loop(hours=24)
async def auto_backup():
    """Daily backup of database"""
    try:
        import shutil
        shutil.copy2('aether.db', f'backup_aether_{datetime.now().strftime("%Y%m%d")}.db')
        print("🔄 Database backup completed")
    except Exception as e:
        print(f"❌ Backup failed: {e}")

@auto_backup.before_loop
async def before_backup():
    await bot.wait_until_ready()

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    embed = Embed(
        title="❌ Error Occurred",
        description=str(error),
        color=0xff6b6b
    )
    await ctx.send(embed=embed, delete_after=10)

@bot.event
async def on_app_command_error(interaction: Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        embed = Embed(
            title="⏰ Command on Cooldown",
            description=f"Try again in {error.retry_after:.2f} seconds.",
            color=0xffa500
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = Embed(
            title="❌ Error Occurred",
            description="An error occurred while processing your command.",
            color=0xff6b6b
        )
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except:
            await interaction.followup.send(embed=embed, ephemeral=True)

# Special owner commands
@bot.tree.command(name="broadcast", description="📢 Send a message to all servers (Owner only)")
@app_commands.describe(message="Message to broadcast")
async def broadcast(interaction: Interaction, message: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ Owner only command.", ephemeral=True)
        return

    sent = 0
    failed = 0

    embed = Embed(
        title="📢 Broadcast from AetherBot",
        description=message,
        color=0x7289da
    )
    embed.set_footer(text="This is a broadcast message from the bot owner")

    for guild in bot.guilds:
        try:
            # Find a suitable channel to send to
            channel = None
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break

            if channel:
                await channel.send(embed=embed)
                sent += 1
            else:
                failed += 1
        except:
            failed += 1

    result_embed = Embed(
        title="📊 Broadcast Results",
        description=f"✅ Sent to {sent} servers\n❌ Failed: {failed} servers",
        color=0x00ff88
    )
    await interaction.response.send_message(embed=result_embed, ephemeral=True)

# Music placeholder commands (structure for future implementation)
@bot.tree.command(name="play", description="🎵 Play music (Coming Soon!)")
async def play(interaction: Interaction):
    embed = Embed(
        title="🎵 Music System",
        description="🚧 Music commands are coming soon!\n\nStay tuned for updates!",
        color=0x7289da
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="queue", description="📋 View music queue (Coming Soon!)")
async def queue(interaction: Interaction):
    embed = Embed(
        title="📋 Music Queue",
        description="🚧 Music commands are coming soon!",
        color=0x7289da
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Auto role system placeholder
@bot.tree.command(name="autorole", description="🎭 Setup automatic roles (Coming Soon!)")
async def autorole(interaction: Interaction):
    embed = Embed(
        title="🎭 Auto Role System",
        description="🚧 Auto role system coming soon!",
        color=0x7289da
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Start the bot
if __name__ == "__main__":
    print("🚀 Starting AetherBot...")
    print("📊 Features loaded:")
    print("   • Advanced XP & Leveling System")
    print("   • Economy with Daily Rewards")
    print("   • Comprehensive Moderation")
    print("   • Auto-moderation & Spam Protection")
    print("   • Interactive Help System")
    print("   • Fun Commands & Games")
    print("   • Server Management Tools")
    print("   • Owner-only Admin Commands")
    print("=" * 50)

    keep_alive()

    try:
        bot.run(os.getenv("DISCORD_TOKEN"))
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        print("💡 Make sure your DISCORD_TOKEN environment variable is set correctly!")                                                                                                                                                                                                                                                 
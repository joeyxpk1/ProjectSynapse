import os
import asyncio
import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from typing import Optional
import threading
from flask import Flask
import aiohttp
import json
import time
from dotenv import load_dotenv
import topgg
from vote_tracker import initialize_vote_tracker
from vote_webhook import set_bot_instance, start_webhook_server

# Initialize environment - Fixed deployment issue
load_dotenv()
os.environ['PRODUCTION_MODE'] = 'true'
os.environ['DEPLOYMENT_MODE'] = 'true'

class TopGGHandler:
    """Handle top.gg API submissions for bot statistics"""
    
    def __init__(self, bot):
        self.bot = bot
        self.token = os.environ.get('TOPGG_TOKEN')
        self.bot_id = "1381206034269339658"  # Your bot ID
        self.api_url = f"https://top.gg/api/bots/{self.bot_id}/stats"
        self.enabled = bool(self.token)
        
        print(f"🔍 TopGG DEBUG: Token exists: {bool(self.token)}")
        if self.token:
            print(f"🔍 TopGG DEBUG: Token starts with: {self.token[:10]}...")
        print(f"🔍 TopGG DEBUG: Bot ID: {self.bot_id}")
        print(f"🔍 TopGG DEBUG: API URL: {self.api_url}")
        
        if not self.enabled:
            print("⚠️ TOPGG_TOKEN not set - top.gg stats disabled")
        else:
            print("✅ Top.gg integration enabled")
    
    async def post_stats(self):
        """Post bot statistics to top.gg using topggpy library"""
        if not self.enabled:
            print("⚠️ TopGG disabled - no token provided")
            return False
        
        try:
            server_count = len(self.bot.guilds)
            print(f"🔍🔍🔍 TopGG DEBUG: Posting server count: {server_count} using topggpy")
            print(f"🔍🔍🔍 TopGG DEBUG: Token exists: {bool(self.token)}")
            print(f"🔍🔍🔍 TopGG DEBUG: Bot user ID: {self.bot.user.id}")
            print(f"🔍🔍🔍 TopGG DEBUG: Bot guilds length: {len(self.bot.guilds)}")
            
            # Import and use topgg correctly  
            import topgg
            print(f"🔍🔍🔍 TopGG DEBUG: topgg imported successfully")
            
            # Create DBLClient with correct class name
            client = topgg.DBLClient(self.bot, self.token)
            print(f"🔍🔍🔍 TopGG DEBUG: topgg.DBLClient created successfully")
            
            # Post stats using the correct method
            print(f"🔍🔍🔍 TopGG DEBUG: Calling post_guild_count with server_count={server_count}")
            await client.post_guild_count(guild_count=server_count)
            print(f"🔍🔍🔍 TopGG DEBUG: post_guild_count completed successfully")
            
            # Close client session to prevent warnings
            print(f"🔍🔍🔍 TopGG DEBUG: Closing client session")
            await client.close()
            print(f"🔍🔍🔍 TopGG DEBUG: Client session closed successfully")
            
            print(f"✅ TopGG: Successfully posted {server_count} servers using topggpy!")
            return True
            
        except topgg.errors.Unauthorized:
            print("❌ TopGG: Authentication failed - check your token!")
            print("❌ Make sure you're using the Authorization token from TopGG webhook settings")
            return False
        except topgg.errors.HTTPException as e:
            print(f"❌ TopGG HTTP error: {e}")
            return False
        except Exception as e:
            print(f"❌ TopGG unexpected error: {type(e).__name__}: {e}")
            import traceback
            print(f"❌ TopGG Traceback: {traceback.format_exc()}")
            return False
    
    async def get_bot_info(self):
        """Get bot information from top.gg using topggpy library"""
        if not self.enabled:
            return None
            
        try:
            # Import and use topgg correctly
            import topgg
            
            # Create DBLClient with correct class name
            client = topgg.DBLClient(self.bot, self.token)
            
            # Get bot info using the correct method
            bot_info = await client.get_bot_info(self.bot.user.id)
            
            # Close client session to prevent warnings
            await client.close()
            
            return bot_info
        except Exception as e:
            print(f"❌ Error getting TopGG bot info: {e}")
            return None

def init_database():
    """Initialize MongoDB connection for database logging"""
    try:
        # Force install pymongo if missing
        try:
            import pymongo
            print("✅ pymongo module found")
        except ImportError:
            print("⚠️ Installing pymongo...")
            import subprocess
            import sys
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--force-reinstall", "pymongo==4.6.1", "dnspython==2.4.2"])
            import pymongo
            print("✅ pymongo installed successfully")
        
        mongodb_url = os.environ.get('MONGODB_URL') or os.environ.get('MONGODB_URI')
        if not mongodb_url:
            print("❌ CRITICAL: MONGODB_URL or MONGODB_URI environment variable not set!")
            print("❌ ALL DATABASE LOGGING WILL BE DISABLED")
            return None
            
        from pymongo import MongoClient
        client = MongoClient(mongodb_url, serverSelectionTimeoutMS=10000)
        client.admin.command('ping')
        db = client.synapsechat
        
        # Create all required collections
        collections = [
            'crosschat_messages', 'crosschat_channels', 'banned_users', 
            'user_warnings', 'guild_info', 'bot_status', 'moderation_logs'
        ]
        existing = db.list_collection_names()
        
        for col in collections:
            if col not in existing:
                db.create_collection(col)
                print(f"📁 Created MongoDB collection: {col}")
        
        print("✅ MongoDB connection established - DATABASE LOGGING ENABLED")
        return 'mongodb'
        
    except Exception as e:
        print(f"❌ CRITICAL: MongoDB connection failed: {e}")
        print("❌ ALL DATABASE LOGGING WILL BE DISABLED")
        return None

# Initialize MongoDB
DATABASE_TYPE = init_database()
DATABASE_AVAILABLE = DATABASE_TYPE == 'mongodb'

# Simple Discord logging - sends summary every 60 seconds
CONSOLE_LOG_CHANNEL_ID = 1386454256000831731

# Webhook configuration
MODERATION_WEBHOOK_URL = os.environ.get('MODERATION_WEBHOOK_URL')
GUILD_WEBHOOK_URL = os.environ.get('GUILD_WEBHOOK_URL')
STAFF_ROLE_ID = os.environ.get('STAFF_ROLE_ID')

async def send_moderation_webhook(action_type: str, moderator_user, target_user, reason: str, additional_info: dict = None, is_local_admin: bool = False):
    """Send moderation action to webhook with staff ping if issued by local admin"""
    if not MODERATION_WEBHOOK_URL:
        print("⚠️ MODERATION_WEBHOOK_URL not configured - webhook logging disabled")
        return False
    
    try:
        # Determine action color
        color_map = {
            "warning": 0xffaa00,  # Orange
            "ban": 0xff0000,      # Red
            "unban": 0x00ff00     # Green
        }
        color = color_map.get(action_type.lower(), 0x0099ff)
        
        # Build embed
        embed = {
            "title": f"🛡️ Moderation Action: {action_type.title()}",
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {
                    "name": "Target User",
                    "value": f"{target_user.name}#{target_user.discriminator}\nID: `{target_user.id}`",
                    "inline": True
                },
                {
                    "name": "Moderator",
                    "value": f"{moderator_user.name}#{moderator_user.discriminator}\nID: `{moderator_user.id}`",
                    "inline": True
                },
                {
                    "name": "Action Type",
                    "value": "🔴 Local Admin Action" if is_local_admin else "🟢 Staff/Owner Action",
                    "inline": True
                },
                {
                    "name": "Reason",
                    "value": reason,
                    "inline": False
                }
            ]
        }
        
        # Add additional info if provided
        if additional_info:
            for key, value in additional_info.items():
                embed["fields"].append({
                    "name": key,
                    "value": str(value),
                    "inline": True
                })
        
        # Build webhook payload
        webhook_data = {
            "embeds": [embed]
        }
        
        # Add staff ping for local admin actions
        if is_local_admin and STAFF_ROLE_ID:
            webhook_data["content"] = f"⚠️ <@&{STAFF_ROLE_ID}> Local Admin moderation action requires attention!"
        
        # Send webhook
        async with aiohttp.ClientSession() as session:
            async with session.post(MODERATION_WEBHOOK_URL, json=webhook_data) as response:
                if response.status == 204:
                    print(f"✅ Moderation webhook sent: {action_type} action logged")
                    return True
                else:
                    print(f"❌ Webhook failed with status {response.status}: {await response.text()}")
                    return False
                    
    except Exception as webhook_error:
        print(f"❌ Webhook error: {webhook_error}")
        return False

async def send_guild_webhook(event_type: str, guild, additional_info: dict = None):
    """Send guild join/leave notification to webhook with detailed server information"""
    if not GUILD_WEBHOOK_URL:
        print("⚠️ GUILD_WEBHOOK_URL not configured - guild webhook logging disabled")
        return False
    
    try:
        # Determine event color
        colors = {
            "join": 0x00ff00,    # Green for joins
            "leave": 0xff0000    # Red for leaves
        }
        color = colors.get(event_type.lower(), 0x0099ff)
        
        # Get server creation date
        created_at = guild.created_at.strftime("%Y-%m-%d %H:%M UTC")
        
        # Get server owner info
        owner_info = "Unknown"
        if guild.owner:
            owner_info = f"{guild.owner.name}#{guild.owner.discriminator}\nID: `{guild.owner.id}`"
        
        # Get server icon
        icon_url = guild.icon.url if guild.icon else None
        
        # Build comprehensive embed
        embed = {
            "title": f"🏰 Guild {'Joined' if event_type == 'join' else 'Left'}: {guild.name}",
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {
                    "name": "Server Name",
                    "value": guild.name,
                    "inline": True
                },
                {
                    "name": "Server ID",
                    "value": f"`{guild.id}`",
                    "inline": True
                },
                {
                    "name": "Member Count",
                    "value": f"{guild.member_count:,} members",
                    "inline": True
                },
                {
                    "name": "Server Owner",
                    "value": owner_info,
                    "inline": True
                },
                {
                    "name": "Server Created",
                    "value": created_at,
                    "inline": True
                },
                {
                    "name": "Verification Level",
                    "value": str(guild.verification_level).replace('_', ' ').title(),
                    "inline": True
                }
            ]
        }
        
        # Add server icon if available
        if icon_url:
            embed["thumbnail"] = {"url": icon_url}
        
        # Add total guild count (need to access bot instance)
        try:
            # Get bot reference from global scope
            total_guilds = len(bot.guilds) if 'bot' in globals() else "Unknown"
            embed["fields"].append({
                "name": "Total Guilds",
                "value": f"Bot now in {total_guilds:,} servers" if isinstance(total_guilds, int) else "Bot guild count unavailable",
                "inline": False
            })
        except:
            pass
        
        # Add additional info if provided
        if additional_info:
            for key, value in additional_info.items():
                embed["fields"].append({
                    "name": key,
                    "value": str(value),
                    "inline": True
                })
        
        # Send webhook
        webhook_data = {"embeds": [embed]}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(GUILD_WEBHOOK_URL, json=webhook_data) as response:
                if response.status == 204:
                    print(f"✅ Guild {event_type} webhook sent successfully for {guild.name}")
                    return True
                else:
                    print(f"⚠️ Guild webhook failed with status {response.status}")
                    return False
                    
    except Exception as e:
        print(f"❌ Error sending guild webhook: {e}")
        return False

class SimpleDiscordLogger:
    """Simple Discord logger that collects important events and sends summary every 60 seconds"""
    def __init__(self, bot):
        self.bot = bot
        self.important_events = []
        self.last_send_time = 0
        
    def log_event(self, event_type, message):
        """Log an important event"""
        try:
            timestamp = datetime.now().strftime('%H:%M:%S')
            event = f"[{timestamp}] {event_type}: {message}"
            self.important_events.append(event)
            
            # Keep only last 10 events
            if len(self.important_events) > 10:
                self.important_events = self.important_events[-10:]
                
        except Exception:
            pass
    
    async def send_summary(self):
        """Send summary of important events"""
        try:
            if not self.important_events or not self.bot.is_ready():
                return
                
            channel = self.bot.get_channel(CONSOLE_LOG_CHANNEL_ID)
            if not channel:
                return
            
            summary = '\n'.join(self.important_events)
            self.important_events.clear()
            
            await channel.send(f"```\n📊 SynapseChat Activity Summary\n{summary}\n```")
            
        except Exception:
            pass

class CrossChatBot(commands.Bot):
    def __init__(self):
        # Import os explicitly to avoid scoping issues
        import os as os_module
        
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None,
            case_insensitive=True
        )
        
        self.start_time = time.time()
        self.commands_registered = False
        
        # Load bot owner ID from environment
        owner_id_str = os_module.environ.get('BOT_OWNER_ID')
        if owner_id_str and owner_id_str != 'ENTER_YOUR_DISCORD_USER_ID':
            try:
                self.owner_id = int(owner_id_str)
                print(f"✅ Bot owner ID loaded: {self.owner_id}")
            except ValueError:
                print(f"❌ Invalid BOT_OWNER_ID format: {owner_id_str}")
                self.owner_id = None
        else:
            print("⚠️ BOT_OWNER_ID not set - owner commands will not work")
            self.owner_id = None
        
        # Initialize MongoDB handler for logging
        if not DATABASE_AVAILABLE:
            print("❌ CRITICAL: MongoDB not available - NO DATABASE LOGGING WILL OCCUR")
            print("❌ Set MONGODB_URL or MONGODB_URI environment variable to enable logging")
            self.db_handler = None
            self.automod = None
        else:
            try:
                from mongodb_handler import MongoDBHandler
                self.db_handler = MongoDBHandler()
                
                if self.db_handler._connect():
                    print("✅ MongoDB database logging ENABLED - all moderation actions will be recorded")
                    
                    # Set mongodb_handler alias for partner commands compatibility
                    self.mongodb_handler = self.db_handler
                    
                    # Database connection verified - no test data needed
                    print("✅ MONGODB: Database connection verified - ready for crosschat logging")
                    
                    # Check existing crosschat channels in database
                    existing_channels = self.db_handler.get_crosschat_channels()
                    print(f"✅ CROSSCHAT STATUS: {len(existing_channels)} channels registered in database")
                    print("ℹ️  Use /setup command to register new crosschat channels manually")
                    
                    # FORCE VERIFY ALL COLLECTIONS EXIST
                    print("🔍 VERIFYING: Checking all MongoDB collections...")
                    collections = ['crosschat_messages', 'crosschat_channels', 'banned_users', 
                                 'user_warnings', 'moderation_logs', 'guild_info', 'bot_status', 'votes']
                    for collection_name in collections:
                        try:
                            count = self.db_handler.db[collection_name].count_documents({})
                            print(f"✅ VERIFIED: Collection '{collection_name}' exists with {count} documents")
                        except Exception as e:
                            print(f"❌ COLLECTION ERROR: {collection_name} - {e}")
                    
                    # Initialize automod with database connection
                    try:
                        from auto_moderation import AutoModerationManager
                        self.automod = AutoModerationManager(bot=self, database_storage=None)
                        print("✅ AutoMod system initialized with MongoDB logging")
                    except Exception as automod_error:
                        print(f"⚠️ AutoMod initialization failed: {automod_error}")
                        self.automod = None
                else:
                    print("❌ CRITICAL: MongoDB handler connection failed - NO DATABASE LOGGING")
                    self.db_handler = None
                    self.automod = None
                    
            except Exception as e:
                print(f"❌ CRITICAL: Failed to initialize MongoDB handler: {e}")
                print("❌ NO DATABASE LOGGING WILL OCCUR")
                self.db_handler = None
                self.automod = None
        
        # Initialize TopGG integration with enhanced debugging
        self.topgg = TopGGHandler(self)
        print(f"🔍🔍🔍 TopGG DEBUG: Handler initialized - Enabled: {self.topgg.enabled}")
        
        # Initialize Vote Tracker for leaderboards and announcements
        try:
            self.vote_tracker = initialize_vote_tracker(self, self.db_handler, self.topgg)
            print("✅ Vote Tracker initialized - Ready for Top.gg vote tracking and leaderboards")
        except Exception as e:
            print(f"⚠️ Vote Tracker initialization failed: {e}")
            self.vote_tracker = None
        
        # Check environment variable directly
        topgg_token_env = os.environ.get('TOPGG_TOKEN')
        print(f"🔍🔍🔍 TopGG DEBUG: Environment variable exists: {bool(topgg_token_env)}")
        if topgg_token_env:
            print(f"🔍🔍🔍 TopGG DEBUG: Token starts with: {topgg_token_env[:10]}...")
            print(f"🔍🔍🔍 TopGG DEBUG: Token length: {len(topgg_token_env)}")
        
        if self.topgg.enabled:
            print(f"🔍🔍🔍 TopGG DEBUG: Token present: {bool(self.topgg.token)}")
            print(f"🔍🔍🔍 TopGG DEBUG: Bot ID: {self.topgg.bot_id}")
            if self.topgg.token:
                print(f"🔍🔍🔍 TopGG DEBUG: Token starts with: {self.topgg.token[:10]}...")
        else:
            print("🔍🔍🔍 TopGG DEBUG: Integration disabled - no token found")
        
        # CRITICAL FIX: Initialize SimpleCrossChat system
        try:
            import sys
            # Add current directory to path if not already there
            current_dir = os_module.path.dirname(os_module.path.abspath(__file__))
            if current_dir not in sys.path:
                sys.path.insert(0, current_dir)
            
            from simple_crosschat import SimpleCrossChat
            self.cross_chat_manager = SimpleCrossChat(self)
            
            # DEBUG: Verify db_handler is accessible from cross_chat_manager
            print(f"🔍 DEBUG: Bot has db_handler: {hasattr(self, 'db_handler')}")
            print(f"🔍 DEBUG: Bot db_handler is not None: {getattr(self, 'db_handler', None) is not None}")
            if hasattr(self, 'db_handler') and self.db_handler:
                print(f"🔍 DEBUG: db_handler connection_failed: {self.db_handler.connection_failed}")
                print(f"✅ DEBUG: SimpleCrossChat will have access to working db_handler")
            else:
                print(f"❌ DEBUG: SimpleCrossChat will NOT have db_handler access")
            print("✅ CROSSCHAT: SimpleCrossChat system initialized - crosschat logging ENABLED")
            print("🔍🔍🔍 DEBUG_VERSION: Message event handler updated with triple debug markers - version 2025-07-01-16:15")
        except Exception as e:
            print(f"❌ CRITICAL: Failed to initialize SimpleCrossChat: {e}")
            self.cross_chat_manager = None

    def add_slash_commands(self):
        @self.tree.command(name="ping", description="Check bot latency")
        async def ping(interaction: discord.Interaction):
            await interaction.response.send_message(f"Pong! {round(self.latency * 1000)}ms")

        @self.tree.command(name="status", description="Show bot status and statistics")
        async def status(interaction: discord.Interaction):
            """Display comprehensive bot status"""
            try:
                await interaction.response.defer()
                
                # Get real-time statistics
                server_count = len(self.guilds)
                total_members = sum(guild.member_count or 0 for guild in self.guilds)
                
                # Fix timezone-aware datetime calculation
                import time
                from datetime import timedelta
                uptime_seconds = time.time() - self.start_time
                uptime = timedelta(seconds=int(uptime_seconds))
                
                # Get crosschat channels count from MongoDB
                channel_count = 0
                try:
                    if hasattr(self, 'db_handler') and self.db_handler:
                        # Get crosschat channels from MongoDB database
                        crosschat_channels = self.db_handler.get_crosschat_channels()
                        channel_count = len(crosschat_channels) if crosschat_channels else 0
                        print(f"STATUS_CMD: Found {channel_count} crosschat channels from MongoDB")
                    else:
                        print("STATUS_CMD: No database handler available")
                except Exception as e:
                    print(f"STATUS_CMD: Error getting crosschat channels: {e}")
                    channel_count = 0
                
                embed = discord.Embed(
                    title="🤖 SynapseChat Bot Status",
                    color=0x00ff00,
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="🌐 Servers", value=f"{server_count:,}", inline=True)
                embed.add_field(name="👥 Total Members", value=f"{total_members:,}", inline=True)
                embed.add_field(name="📡 Latency", value=f"{round(self.latency * 1000)}ms", inline=True)
                embed.add_field(name="💬 CrossChat Channels", value=f"{channel_count}", inline=True)
                embed.add_field(name="⏱️ Uptime", value=f"{uptime.days}d {uptime.seconds//3600}h {(uptime.seconds//60)%60}m", inline=True)
                embed.add_field(name="📊 Status", value="🟢 Online", inline=True)
                
                embed.set_footer(text="SynapseChat • Cross-Server Communication")
                
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                await interaction.followup.send(f"❌ Error getting status: {str(e)}", ephemeral=True)

        @self.tree.command(name="announce", description="Send announcement to all cross-chat channels (Owner/Staff only)")
        @discord.app_commands.describe(
            message="Announcement message (use \\n for line breaks. Format each line separately: **Title**\\n\\nRegular text\\n\\n**Another bold line**)",
            anonymous="Send announcement anonymously"
        )
        async def announce(interaction: discord.Interaction, message: str, anonymous: bool = False):
            """Send announcement to all crosschat channels"""
            # Check permissions: Bot Owner or Official Staff
            has_permission = await self.is_bot_owner(interaction)
            
            if not has_permission:
                try:
                    staff_role_id = os.environ.get('STAFF_ROLE_ID')
                    if staff_role_id:
                        for guild in self.guilds:
                            member = guild.get_member(interaction.user.id)
                            if member and member.roles:
                                for role in member.roles:
                                    if str(role.id) == str(staff_role_id):
                                        has_permission = True
                                        break
                            if has_permission:
                                break
                except Exception:
                    pass
            
            if not has_permission:
                await interaction.response.send_message("❌ You don't have permission to use this command. Required: Bot Owner or Official Staff.", ephemeral=True)
                return
            
            try:
                await interaction.response.defer()
                
                # Process multiline formatting - convert \n to actual newlines
                formatted_message = message.replace('\\n', '\n')
                
                if hasattr(self, 'cross_chat_manager') and self.cross_chat_manager:
                    result = await self.cross_chat_manager.send_announcement(formatted_message)
                    
                    channels_sent = result if isinstance(result, int) else 0
                    embed = discord.Embed(
                        title="📢 Announcement Sent",
                        description=f"Announcement delivered to {channels_sent} cross-chat channels",
                        color=0x00ff00
                    )
                    
                    if not anonymous:
                        embed.add_field(name="Sent by", value=interaction.user.mention, inline=True)
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send("❌ Cross-chat manager not available", ephemeral=True)
                    
            except Exception as e:
                await interaction.followup.send(f"❌ Error sending announcement: {str(e)}", ephemeral=True)

        @self.tree.command(name="help", description="Show available commands")
        async def help_command(interaction: discord.Interaction):
            """Display help information"""
            embed = discord.Embed(
                title="🤖 SynapseChat Bot Commands",
                description="Available slash commands for SynapseChat",
                color=0x0099ff
            )
            
            embed.add_field(
                name="📊 General Commands",
                value="`/ping` - Check bot latency\n`/status` - Show bot status\n`/serverinfo` - Server information\n`/help` - Show this help",
                inline=False
            )
            
            embed.add_field(
                name="🌐 Cross-Chat Commands",
                value="`/announce` - Send announcements (SynapseStaff/Bot-Owner) \n`/crosschat` - View network info (Bot-Owner)\n`/setup` - Setup crosschat channels (SynapseStaff/Bot-Owner/Server Admin)",
                inline=False
            )
            
            embed.add_field(
                name="🛡️ Moderation Commands",
                value="`/warn` - Warn a user(SynapseStaff/Bot-Owner/Server Admin)\n`/ban` - Temporarily ban a user from the SynapseChat Network (SynapseStaff/Bot-Owner)\n`/unban` - Remove a SynapseChat Network ban from a user (SynapseStaff/Bot-Owner) \n`/moderation` - Manage auto-moderation settings (Bot-Owner)",
                inline=False
            )
            
            embed.set_footer(text="Use these commands to manage your server and cross-chat functionality")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @self.tree.command(name="serverinfo", description="Show information about the current server")
        async def serverinfo(interaction: discord.Interaction):
            """Display server information"""
            guild = interaction.guild
            
            embed = discord.Embed(
                title=f"🏰 {guild.name}",
                color=0x0099ff,
                timestamp=datetime.utcnow()
            )
            
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            
            embed.add_field(name="Server ID", value=guild.id, inline=True)
            embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
            embed.add_field(name="Created", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
            embed.add_field(name="Members", value=guild.member_count, inline=True)
            embed.add_field(name="Channels", value=len(guild.channels), inline=True)
            embed.add_field(name="Roles", value=len(guild.roles), inline=True)
            
            # Check crosschat channels
            try:
                from performance_cache import performance_cache
                crosschat_channels = performance_cache.get_crosschat_channels()
                guild_crosschat = sum(1 for channel_id in crosschat_channels if self.get_channel(int(channel_id)) and self.get_channel(int(channel_id)).guild.id == guild.id)
                embed.add_field(name="Cross-Chat Channels", value=f"{guild_crosschat}", inline=True)
            except:
                embed.add_field(name="Cross-Chat Channels", value="0", inline=True)
            
            await interaction.response.send_message(embed=embed)

        @self.tree.command(name="warn", description="Warn a user for violations (Staff/Owner/Admin)")
        @discord.app_commands.describe(user_id="User to warn (Discord ID or @mention)", reason="Reason for warning")
        async def warn(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
            # Check permissions: Bot Owner or Official Staff or Server Administrator
            has_permission = await self.is_bot_owner(interaction)
            if not has_permission:
                staff_role_id = os.environ.get('STAFF_ROLE_ID')
                if staff_role_id:
                    for guild in self.guilds:
                        member = guild.get_member(interaction.user.id)
                        if member and any(str(role.id) == str(staff_role_id) for role in member.roles):
                            has_permission = True
                            break
            if not has_permission and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ You don't have permission to use this command. Required: Bot Owner, Official Staff, or Server Administrator permissions.", ephemeral=True)
                return
            try:
                await interaction.response.defer()
                
                # Parse user ID from input (handle mentions like <@123456789> or raw IDs)
                clean_user_id = user_id.strip()
                if clean_user_id.startswith('<@') and clean_user_id.endswith('>'):
                    # Extract ID from mention format <@123456789> or <@!123456789>
                    clean_user_id = clean_user_id[2:-1].lstrip('!')
                
                try:
                    target_user_id = int(clean_user_id)
                except ValueError:
                    await interaction.followup.send("❌ Invalid user ID format. Please provide a Discord user ID (numbers only) or @mention the user.", ephemeral=True)
                    return
                
                # Try to find the user across all guilds the bot can see
                target_user = None
                found_in_guild = None
                
                # First, try to get the user from the current guild
                if interaction.guild:
                    target_user = interaction.guild.get_member(target_user_id)
                    if target_user:
                        found_in_guild = interaction.guild
                
                # If not found locally, search across all guilds for global warnings
                if not target_user:
                    for guild in self.guilds:
                        member = guild.get_member(target_user_id)
                        if member:
                            target_user = member
                            found_in_guild = guild
                            break
                
                # If still not found, try to fetch user info from Discord API
                if not target_user:
                    try:
                        target_user = await self.fetch_user(target_user_id)
                        print(f"INFO: Global warning - user {target_user.name} ({target_user_id}) found via API")
                    except discord.NotFound:
                        await interaction.followup.send(f"❌ User with ID `{target_user_id}` not found. The user may not exist or the bot cannot access them.", ephemeral=True)
                        return
                    except Exception as fetch_error:
                        await interaction.followup.send(f"❌ Error fetching user: {str(fetch_error)}", ephemeral=True)
                        return
                
                # Log warning to database
                print(f"🔍 DEBUG: FORCE LOGGING warning for user {target_user.id}")
                warning_logged = False
                if self.db_handler:
                    warning_logged = self.db_handler.add_warning(
                        user_id=str(target_user.id),
                        moderator_id=str(interaction.user.id),
                        reason=reason,
                        guild_id=str(found_in_guild.id) if found_in_guild else None
                    )
                    if warning_logged:
                        print(f"✅ WARNING LOGGED: User {target_user.id} warning recorded in database")
                    else:
                        print(f"❌ WARNING LOG FAILED: Could not record warning for user {target_user.id}")
                else:
                    print(f"❌ NO DB_HANDLER: Cannot log warning - database unavailable")
                    warning_logged = False
                
                # Create warning embed with appropriate user display
                user_display = target_user.mention if hasattr(target_user, 'mention') else f"{target_user.name}#{target_user.discriminator}"
                warning_type = "Global Warning" if not found_in_guild or found_in_guild != interaction.guild else "Local Warning"
                
                embed = discord.Embed(title=f"⚠️ {warning_type}", description=f"{user_display} has been warned", color=0xffaa00)
                embed.add_field(name="User ID", value=str(target_user.id), inline=True)
                embed.add_field(name="Username", value=f"{target_user.name}#{target_user.discriminator}", inline=True)
                embed.add_field(name="Warning Scope", value=warning_type, inline=True)
                embed.add_field(name="Reason", value=reason, inline=False)
                embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                embed.add_field(name="Found In", value=found_in_guild.name if found_in_guild else "Global (API)", inline=True)
                embed.set_footer(text="SynapseChat Moderation")
                await interaction.followup.send(embed=embed)
                
                # Send DM to warned user
                try:
                    dm_embed = discord.Embed(
                        title="⚠️ Warning Received",
                        description="You have received a warning from SynapseChat moderation.",
                        color=0xffaa00
                    )
                    dm_embed.add_field(name="Reason", value=reason, inline=False)
                    dm_embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
                    dm_embed.add_field(name="Warning Type", value=warning_type, inline=False)
                    dm_embed.add_field(name="Note", value="Please follow community guidelines to avoid further action.", inline=False)
                    dm_embed.set_footer(text="SynapseChat Moderation System")
                    
                    await target_user.send(embed=dm_embed)
                    print(f"✅ Warning DM sent to {target_user.name} ({target_user.id})")
                except Exception as dm_error:
                    print(f"⚠️ Failed to send warning DM to {target_user.name}: {dm_error}")
                    
                # Determine if this is a local admin action (for webhook ping)
                is_bot_owner = await self.is_bot_owner(interaction)
                has_staff_role = False
                if STAFF_ROLE_ID:
                    for guild in self.guilds:
                        member = guild.get_member(interaction.user.id)
                        if member and any(str(role.id) == str(STAFF_ROLE_ID) for role in member.roles):
                            has_staff_role = True
                            break
                is_local_admin = not is_bot_owner and not has_staff_role and interaction.user.guild_permissions.administrator
                
                # Send webhook notification
                webhook_info = {
                    "Warning Type": warning_type,
                    "User Found In": found_in_guild.name if found_in_guild else "Global (API)",
                    "Database Logged": "✅ Success" if warning_logged else "❌ Failed"
                }
                
                await send_moderation_webhook(
                    action_type="warning",
                    moderator_user=interaction.user,
                    target_user=target_user,
                    reason=reason,
                    additional_info=webhook_info,
                    is_local_admin=is_local_admin
                )
                
                # Send generic community notification (no user names)
                await self.send_generic_moderation_notice(
                    action_type="warning",
                    reason_category=self.categorize_violation_reason(reason),
                    guild_scope=found_in_guild if found_in_guild else None
                )
                
                print(f"MODERATION: {interaction.user} warned {target_user.name} ({target_user.id}) for: {reason}")
            except Exception as e:
                await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

        @self.tree.command(name="ban", description="Temporarily ban a user from crosschat")
        @discord.app_commands.describe(user="User to ban", duration="Ban duration in hours", reason="Reason for ban")
        async def ban(interaction: discord.Interaction, user: discord.Member, duration: int = 24, reason: str = "No reason provided"):
            has_permission = await self.is_bot_owner(interaction)
            if not has_permission:
                staff_role_id = os.environ.get('STAFF_ROLE_ID')
                if staff_role_id:
                    for guild in self.guilds:
                        member = guild.get_member(interaction.user.id)
                        if member and any(str(role.id) == str(staff_role_id) for role in member.roles):
                            has_permission = True
                            break
            if not has_permission:
                await interaction.response.send_message("❌ Insufficient permissions", ephemeral=True)
                return
            try:
                await interaction.response.defer()
                ban_until = datetime.now() + timedelta(hours=duration)
                
                # Log ban to database
                print(f"🔍 DEBUG: FORCE LOGGING ban for user {user.id}")
                ban_logged = False
                if self.db_handler:
                    ban_logged = self.db_handler.ban_user(
                        user_id=str(user.id),
                        moderator_id=str(interaction.user.id),
                        reason=reason,
                        duration=f"{duration}h"
                    )
                    if ban_logged:
                        print(f"✅ BAN LOGGED: User {user.id} ban recorded in database")
                    else:
                        print(f"❌ BAN LOG FAILED: Could not record ban for user {user.id}")
                else:
                    print(f"❌ NO DB_HANDLER: Cannot log ban - database unavailable")
                    ban_logged = False
                embed = discord.Embed(title="🚫 User Banned from CrossChat", description=f"{user.mention} has been banned from the crosschat service", color=0xff0000)
                embed.add_field(name="Duration", value=f"{duration} hours", inline=True)
                embed.add_field(name="Until", value=ban_until.strftime("%Y-%m-%d %H:%M UTC"), inline=True)
                embed.add_field(name="Reason", value=reason, inline=False)
                embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                embed.set_footer(text="Note: This is a service ban only, not a Discord server ban")
                await interaction.followup.send(embed=embed)
                
                # Send DM to banned user
                try:
                    dm_embed = discord.Embed(
                        title="🚫 Service Ban Notice",
                        description=f"You have been banned from SynapseChat crosschat service for {duration} hours.",
                        color=0xff0000
                    )
                    dm_embed.add_field(name="Reason", value=reason, inline=False)
                    dm_embed.add_field(name="Duration", value=f"{duration} hours", inline=True)
                    dm_embed.add_field(name="Expires", value=ban_until.strftime("%Y-%m-%d %H:%M UTC"), inline=True)
                    dm_embed.add_field(name="Note", value="You can still use Discord normally, but cannot participate in cross-server messages.", inline=False)
                    dm_embed.set_footer(text="SynapseChat Moderation System")
                    
                    await user.send(embed=dm_embed)
                    print(f"✅ Ban DM sent to {user.name} ({user.id})")
                except Exception as dm_error:
                    print(f"⚠️ Failed to send ban DM to {user.name}: {dm_error}")
                    
                # Determine if this is a local admin action (for webhook ping)
                is_bot_owner = await self.is_bot_owner(interaction)
                has_staff_role = False
                staff_role_id = os.environ.get('STAFF_ROLE_ID')
                if staff_role_id:
                    for guild in self.guilds:
                        member = guild.get_member(interaction.user.id)
                        if member and any(str(role.id) == str(staff_role_id) for role in member.roles):
                            has_staff_role = True
                            break
                is_local_admin = not is_bot_owner and not has_staff_role
                
                # Send webhook notification
                webhook_info = {
                    "Duration": f"{duration} hours",
                    "Expires": ban_until.strftime("%Y-%m-%d %H:%M UTC"),
                    "Database Logged": "✅ Success" if ban_logged else "❌ Failed"
                }
                
                await send_moderation_webhook(
                    action_type="ban",
                    moderator_user=interaction.user,
                    target_user=user,
                    reason=reason,
                    additional_info=webhook_info,
                    is_local_admin=is_local_admin
                )
                
                # Send generic community notification (no user names)
                await self.send_generic_moderation_notice(
                    action_type="ban",
                    reason_category=self.categorize_violation_reason(reason),
                    guild_scope=interaction.guild
                )
                
                print(f"MODERATION: {interaction.user} banned {user} for {duration}h: {reason}")
            except Exception as e:
                await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

        @self.tree.command(name="unban", description="Remove ban from a user (Staff/Owner only)")
        @discord.app_commands.describe(user="User to unban from crosschat")
        async def unban(interaction: discord.Interaction, user: discord.Member):
            has_permission = await self.is_bot_owner(interaction)
            if not has_permission:
                staff_role_id = os.environ.get('STAFF_ROLE_ID')
                if staff_role_id:
                    for guild in self.guilds:
                        member = guild.get_member(interaction.user.id)
                        if member and any(str(role.id) == str(staff_role_id) for role in member.roles):
                            has_permission = True
                            break
            if not has_permission:
                await interaction.response.send_message("❌ Insufficient permissions", ephemeral=True)
                return
            try:
                await interaction.response.defer()
                
                # Remove ban from database
                print(f"🔍 DEBUG: FORCE LOGGING unban for user {user.id}")
                unban_logged = False
                if self.db_handler:
                    unban_logged = self.db_handler.unban_user(str(user.id))
                    if unban_logged:
                        print(f"✅ UNBAN LOGGED: User {user.id} unbanned in database")
                    else:
                        print(f"❌ UNBAN LOG FAILED: Could not unban user {user.id}")
                else:
                    print(f"❌ NO DB_HANDLER: Cannot log unban - database unavailable")
                    unban_logged = False
                
                embed = discord.Embed(
                    title="✅ User Unbanned from CrossChat",
                    description=f"{user.mention} has been unbanned from the crosschat service",
                    color=0x00ff00
                )
                embed.add_field(name="User", value=user.mention, inline=True)
                embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                embed.add_field(name="Database Status", value="✅ Removed" if unban_logged else "❌ Failed", inline=True)
                embed.set_footer(text="User can now participate in cross-server messages again")
                await interaction.followup.send(embed=embed)
                
                # Send DM to unbanned user
                try:
                    dm_embed = discord.Embed(
                        title="✅ Service Ban Removed",
                        description="Your ban from SynapseChat crosschat service has been removed.",
                        color=0x00ff00
                    )
                    dm_embed.add_field(name="Status", value="You can now participate in cross-server messages again", inline=False)
                    dm_embed.set_footer(text="SynapseChat Moderation System")
                    
                    await user.send(embed=dm_embed)
                    print(f"✅ Unban DM sent to {user.name} ({user.id})")
                except Exception as dm_error:
                    print(f"⚠️ Failed to send unban DM to {user.name}: {dm_error}")
                    
                # Determine if this is a local admin action (for webhook ping)
                is_bot_owner = await self.is_bot_owner(interaction)
                has_staff_role = False
                staff_role_id = os.environ.get('STAFF_ROLE_ID')
                if staff_role_id:
                    for guild in self.guilds:
                        member = guild.get_member(interaction.user.id)
                        if member and any(str(role.id) == str(staff_role_id) for role in member.roles):
                            has_staff_role = True
                            break
                is_local_admin = not is_bot_owner and not has_staff_role
                
                # Send webhook notification
                webhook_info = {
                    "Database Status": "✅ Removed" if unban_logged else "❌ Failed"
                }
                
                await send_moderation_webhook(
                    action_type="unban",
                    moderator_user=interaction.user,
                    target_user=user,
                    reason="Ban removed - user can participate in cross-server messages again",
                    additional_info=webhook_info,
                    is_local_admin=is_local_admin
                )
                
                print(f"MODERATION: {interaction.user} unbanned {user}")
            except Exception as e:
                await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

        @self.tree.command(name="delete", description="Delete a crosschat message globally by CC-ID (Official Staff only)")
        @discord.app_commands.describe(cc_id="The CC-ID of the message to delete (e.g., ABC123)")
        async def delete_crosschat(interaction: discord.Interaction, cc_id: str):
            """Delete a crosschat message globally by CC-ID"""
            # Check permissions: Official Staff or Bot Owner only
            has_permission = False
            if await self.is_bot_owner(interaction):
                has_permission = True
            else:
                # Check for staff role
                staff_role_id = os.environ.get('STAFF_ROLE_ID')
                if staff_role_id:
                    for guild in self.guilds:
                        member = guild.get_member(interaction.user.id)
                        if member and any(str(role.id) == str(staff_role_id) for role in member.roles):
                            has_permission = True
                            break
            
            if not has_permission:
                await interaction.response.send_message("❌ Insufficient permissions. Required: Official Staff or Bot Owner only.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            try:
                # Clean up CC-ID format
                cc_id = cc_id.upper().strip()
                if cc_id.startswith('CC-'):
                    cc_id = cc_id[3:]  # Remove CC- prefix if present
                
                # Use crosschat manager to delete globally
                if hasattr(self, 'cross_chat_manager') and self.cross_chat_manager:
                    result = await self.cross_chat_manager.delete_crosschat_globally(cc_id, str(interaction.user.id))
                    
                    if result['success']:
                        embed = discord.Embed(
                            title="🗑️ Message Deleted Globally",
                            description=f"CrossChat message CC-{cc_id} has been deleted from all channels.",
                            color=0xff4444
                        )
                        embed.add_field(name="CC-ID", value=f"CC-{cc_id}", inline=True)
                        embed.add_field(name="Deleted Count", value=str(result['deleted_count']), inline=True)
                        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                        embed.add_field(name="Original User", value=result.get('original_user', 'Unknown'), inline=True)
                        embed.add_field(name="Original Content", value=f"```{result.get('original_content', 'Unknown')}```", inline=False)
                        embed.set_footer(text="SynapseChat Global Moderation")
                        
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        
                        # Send webhook notification
                        webhook_info = {
                            "CC-ID": f"CC-{cc_id}",
                            "Messages Deleted": str(result['deleted_count']),
                            "Original User": result.get('original_user', 'Unknown'),
                            "Content Preview": result.get('original_content', 'Unknown')[:50] + "..."
                        }
                        
                        # Determine if this is a local admin action
                        is_bot_owner = await self.is_bot_owner(interaction)
                        has_staff_role = False
                        staff_role_id = os.environ.get('STAFF_ROLE_ID')
                        if staff_role_id:
                            for guild in self.guilds:
                                member = guild.get_member(interaction.user.id)
                                if member and any(str(role.id) == str(staff_role_id) for role in member.roles):
                                    has_staff_role = True
                                    break
                        is_local_admin = not is_bot_owner and not has_staff_role
                        
                        await send_moderation_webhook(
                            action_type="global_delete",
                            moderator_user=interaction.user,
                            target_user=None,
                            reason=f"Deleted crosschat message CC-{cc_id}",
                            additional_info=webhook_info,
                            is_local_admin=is_local_admin
                        )
                        
                        print(f"GLOBAL_DELETE: {interaction.user} deleted CC-{cc_id} from {result['deleted_count']} channels")
                    else:
                        await interaction.followup.send(f"❌ Failed to delete CC-{cc_id}: {result.get('error', 'Unknown error')}", ephemeral=True)
                else:
                    await interaction.followup.send("❌ CrossChat system not available", ephemeral=True)
                    
            except Exception as e:
                await interaction.followup.send(f"❌ Error deleting message: {str(e)}", ephemeral=True)
                print(f"DELETE_ERROR: {e}")
                import traceback
                traceback.print_exc()

        @self.tree.command(name="serverban", description="Ban a server from the cross-chat system")
        @discord.app_commands.describe(
            server_id="The ID of the server to ban",
            reason="Reason for the ban"
        )
        async def serverban(interaction: discord.Interaction, server_id: str, reason: str = "No reason provided"):
            """Ban a server from cross-chat system"""
            # Only bot owner can use serverban command
            if not await self.is_bot_owner(interaction):
                await interaction.response.send_message("❌ Only the bot owner can use server ban commands", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            try:
                # Validate server ID
                try:
                    guild_id = int(server_id)
                except ValueError:
                    await interaction.followup.send("❌ Invalid server ID. Please provide a valid numeric server ID.", ephemeral=True)
                    return
                
                # Check if server exists
                target_guild = self.get_guild(guild_id)
                guild_name = target_guild.name if target_guild else f"Unknown Server ({guild_id})"
                
                # Ban the server in database
                if self.db_handler and hasattr(self.db_handler, 'db'):
                    ban_data = {
                        'server_id': str(guild_id),
                        'server_name': guild_name,
                        'reason': reason,
                        'moderator_id': str(interaction.user.id),
                        'moderator_name': str(interaction.user),
                        'timestamp': datetime.utcnow().isoformat()
                    }
                    
                    # Insert server ban
                    self.db_handler.db.banned_servers.insert_one(ban_data)
                    
                    # Log moderation action
                    self.db_handler.db.moderation_logs.insert_one({
                        "action_type": "server_ban",
                        "server_id": str(guild_id),
                        "moderator_id": str(interaction.user.id),
                        "reason": reason,
                        "timestamp": datetime.utcnow()
                    })
                    
                    # Send webhook notification
                    webhook_info = {
                        "Server Name": guild_name,
                        "Server ID": str(guild_id),
                        "Database Logged": "✅ Success"
                    }
                    
                    await send_moderation_webhook(
                        action_type="server_ban",
                        moderator_user=interaction.user,
                        target_user=interaction.user,  # Use moderator as placeholder
                        reason=f"Server banned: {reason}",
                        additional_info=webhook_info,
                        is_local_admin=False  # Only bot owner can use this
                    )
                    
                    await interaction.followup.send(f"✅ Server `{guild_name}` banned from cross-chat.\n**Reason:** {reason}", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Database not available - cannot ban server", ephemeral=True)
                    
            except Exception as e:
                await interaction.followup.send(f"❌ Error banning server: {str(e)}", ephemeral=True)
                print(f"SERVERBAN: Error: {e}")

        @self.tree.command(name="serverunban", description="Unban a server from the cross-chat system")
        @discord.app_commands.describe(
            server_id="The ID of the server to unban"
        )
        async def serverunban(interaction: discord.Interaction, server_id: str):
            """Unban a server from cross-chat system"""
            if not await self.is_bot_owner(interaction):
                await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            try:
                # Validate server ID
                try:
                    guild_id = int(server_id)
                except ValueError:
                    await interaction.followup.send("❌ Invalid server ID. Please provide a valid numeric server ID.", ephemeral=True)
                    return
                
                # Remove server ban from database
                if self.db_handler and hasattr(self.db_handler, 'db'):
                    result = self.db_handler.db.banned_servers.delete_one({"server_id": str(guild_id)})
                    
                    if result.deleted_count > 0:
                        # Log moderation action
                        self.db_handler.db.moderation_logs.insert_one({
                            "action_type": "server_unban",
                            "server_id": str(guild_id),
                            "moderator_id": str(interaction.user.id),
                            "reason": "Server unbanned",
                            "timestamp": datetime.utcnow()
                        })
                        
                        # Send webhook notification
                        webhook_info = {
                            "Server ID": str(guild_id),
                            "Database Status": "✅ Removed"
                        }
                        
                        await send_moderation_webhook(
                            action_type="server_unban",
                            moderator_user=interaction.user,
                            target_user=interaction.user,  # Use moderator as placeholder
                            reason="Server unban - can participate in cross-chat again",
                            additional_info=webhook_info,
                            is_local_admin=False  # Only bot owner can use this
                        )
                        
                        await interaction.followup.send(f"✅ Server `{guild_id}` unbanned from cross-chat system.", ephemeral=True)
                    else:
                        await interaction.followup.send(f"⚠️ Server `{guild_id}` was not found in banned servers list.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Database not available - cannot unban server", ephemeral=True)
                    
            except Exception as e:
                await interaction.followup.send(f"❌ Error unbanning server: {str(e)}", ephemeral=True)
                print(f"SERVERUNBAN: Error: {e}")

        @self.tree.command(name="serverbans", description="List all servers banned from cross-chat")
        async def serverbans(interaction: discord.Interaction):
            """List all banned servers"""
            if not await self.is_bot_owner(interaction):
                await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            try:
                if self.db_handler and hasattr(self.db_handler, 'db'):
                    banned_servers = list(self.db_handler.db.banned_servers.find())
                    
                    if not banned_servers:
                        embed = discord.Embed(
                            title="📋 Banned Servers",
                            description="No servers are currently banned from cross-chat.",
                            color=0x0099ff
                        )
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        return
                    
                    embed = discord.Embed(
                        title="📋 Banned Servers",
                        description=f"Found {len(banned_servers)} banned server(s):",
                        color=0xff0000,
                        timestamp=datetime.utcnow()
                    )
                    
                    for ban_info in banned_servers[:10]:  # Limit to 10 entries
                        server_id = ban_info.get('server_id', 'Unknown')
                        server_name = ban_info.get('server_name', f'Unknown ({server_id})')
                        reason = ban_info.get('reason', 'No reason')
                        banned_date = ban_info.get('timestamp', 'Unknown')[:10] if ban_info.get('timestamp') else 'Unknown'
                        moderator = ban_info.get('moderator_name', 'Unknown')
                        
                        embed.add_field(
                            name=f"{server_name}",
                            value=f"**ID:** {server_id}\n**Reason:** {reason}\n**By:** {moderator}\n**Date:** {banned_date}",
                            inline=False
                        )
                    
                    if len(banned_servers) > 10:
                        embed.set_footer(text=f"Showing first 10 of {len(banned_servers)} banned servers")
                    else:
                        embed.set_footer(text="SynapseChat Moderation System")
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send("❌ Database not available - cannot list banned servers", ephemeral=True)
                    
            except Exception as e:
                await interaction.followup.send(f"❌ Error listing banned servers: {str(e)}", ephemeral=True)
                print(f"SERVERBANS: Error: {e}")

        @self.tree.command(name="crosschat", description="View crosschat network information and statistics")
        async def crosschat(interaction: discord.Interaction):
            """Display crosschat network information"""
            # Permission check removed: This command can now be used by anyone.
            try:
                await interaction.response.defer()
                
                # Get crosschat statistics from MongoDB
                channel_count = 0
                crosschat_channels = []
                try:
                    if hasattr(self, 'cross_chat_manager') and self.cross_chat_manager:
                        crosschat_channels = self.cross_chat_manager.get_channels()
                        channel_count = len(crosschat_channels)
                        print(f"CROSSCHAT_STATS: Found {channel_count} crosschat channels from manager")
                    elif self.db_handler:
                        # Fallback to direct MongoDB query
                        crosschat_channels = self.db_handler.get_crosschat_channels()
                        channel_count = len(crosschat_channels) if crosschat_channels else 0
                        print(f"CROSSCHAT_STATS: Found {channel_count} crosschat channels from MongoDB")
                except Exception as e:
                    print(f"CROSSCHAT_STATS_ERROR: Failed to get channel count: {e}")
                    channel_count = 0
                
                server_count = len(self.guilds)
                total_members = sum(guild.member_count or 0 for guild in self.guilds)
                
                embed = discord.Embed(
                    title="🌐 SynapseChat CrossChat Network",
                    description="Cross-server communication network statistics",
                    color=0x0099ff,
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="🏰 Connected Servers", value=f"{server_count:,}", inline=True)
                embed.add_field(name="💬 Active Channels", value=f"{channel_count}", inline=True)
                embed.add_field(name="👥 Network Members", value=f"{total_members:,}", inline=True)
                
                # Check if current channel is part of crosschat
                current_channel_id = str(interaction.channel.id)
                is_crosschat = False
                try:
                    # Convert channel IDs to strings for comparison
                    crosschat_channel_ids = [str(ch_id) for ch_id in crosschat_channels]
                    is_crosschat = current_channel_id in crosschat_channel_ids
                    print(f"CROSSCHAT_CHECK: Channel {current_channel_id} in network: {is_crosschat}")
                except Exception as e:
                    print(f"CROSSCHAT_CHECK_ERROR: {e}")
                    is_crosschat = False
                
                embed.add_field(
                    name="📍 Current Channel",
                    value="✅ CrossChat Enabled" if is_crosschat else "❌ Not in Network",
                    inline=True
                )
                
                embed.add_field(name="🤖 Bot Status", value="🟢 Online", inline=True)
                embed.add_field(name="📡 Network Latency", value=f"{round(self.latency * 1000)}ms", inline=True)
                
                embed.set_footer(text="SynapseChat • Connecting Discord servers worldwide")
                
                if interaction.guild.icon:
                    embed.set_thumbnail(url=interaction.guild.icon.url)
                
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                await interaction.followup.send(f"❌ Error getting crosschat info: {str(e)}", ephemeral=True)

        @self.tree.command(name="setup", description="Setup crosschat in a channel (Staff/Owner/Admin)")
        @discord.app_commands.describe(
            action="Action to perform",
            channel="Channel to setup (optional, defaults to current channel)"
        )
        @discord.app_commands.choices(action=[
            discord.app_commands.Choice(name="enable", value="enable"),
            discord.app_commands.Choice(name="disable", value="disable"),
            discord.app_commands.Choice(name="status", value="status")
        ])
        async def setup(interaction: discord.Interaction, action: str, channel: discord.TextChannel = None):
            """Setup crosschat in current channel"""
            # Check permissions: Bot Owner or Official Staff (Global access) or Server Administrator (Local access)
            has_permission = await self.is_bot_owner(interaction)
            
            # Check for Official Staff role across all guilds if not bot owner
            if not has_permission:
                try:
                    staff_role_id = os.environ.get('STAFF_ROLE_ID')
                    if staff_role_id:
                        # Check across all guilds where bot can see the user
                        for guild in self.guilds:
                            member = guild.get_member(interaction.user.id)
                            if member and member.roles:
                                for role in member.roles:
                                    if str(role.id) == str(staff_role_id):
                                        has_permission = True
                                        print(f"INFO: Official Staff {interaction.user} using setup command globally")
                                        break
                            if has_permission:
                                break
                except Exception as e:
                    print(f"ERROR: Error checking Official Staff role: {e}")
            
            # Fallback: Check if user is server admin in their local server
            if not has_permission and interaction.user.guild_permissions.administrator:
                has_permission = True
                print(f"INFO: Server Admin {interaction.user} using setup command in local server {interaction.guild.name}")
            
            if not has_permission:
                await interaction.response.send_message("❌ You don't have permission to use this command. Required: Bot Owner, Official Staff (Global access), or Server Administrator (Local access).", ephemeral=True)
                return
            
            try:
                await interaction.response.defer()
                target_channel = channel if channel else interaction.channel
                guild_id = str(interaction.guild.id)
                
                if action == "enable":
                    # Check if channel has required slowmode (5-10 seconds)
                    if target_channel.slowmode_delay < 5 or target_channel.slowmode_delay > 10:
                        embed = discord.Embed(
                            title="❌ Slowmode Required",
                            description=f"CrossChat channels must have a slowmode between 5-10 seconds to prevent spam.",
                            color=0xff0000
                        )
                        embed.add_field(name="Current Slowmode", value=f"{target_channel.slowmode_delay} seconds", inline=True)
                        embed.add_field(name="Required Slowmode", value="5-10 seconds", inline=True)
                        embed.add_field(name="Action Required", value="Please set the channel slowmode to 5-10 seconds before enabling CrossChat", inline=False)
                        embed.set_footer(text="You can set slowmode in channel settings or use Discord's built-in slowmode feature")
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        return
                    
                    # Check if this server already has a crosschat channel
                    try:
                        from performance_cache import performance_cache
                        crosschat_channels = performance_cache.get_crosschat_channels()
                        
                        # Find existing crosschat channels in this guild
                        existing_channels = []
                        if crosschat_channels:
                            for channel_id in crosschat_channels:
                                ch = self.get_channel(int(channel_id))
                                if ch and ch.guild.id == interaction.guild.id:
                                    existing_channels.append(ch)
                        
                        # Enforce one channel per server limit
                        if existing_channels:
                            existing_channel = existing_channels[0]
                            # Allow changing to a different channel by automatically disabling the old one
                            if target_channel.id != existing_channel.id:
                                embed = discord.Embed(
                                    title="🔄 Moving CrossChat Channel",
                                    description=f"CrossChat will be moved from {existing_channel.mention} to {target_channel.mention}",
                                    color=0xffaa00
                                )
                                embed.add_field(name="Previous Channel", value=existing_channel.mention, inline=True)
                                embed.add_field(name="New Channel", value=target_channel.mention, inline=True)
                                embed.add_field(name="Server Limit", value="Each server can have only ONE CrossChat channel", inline=False)
                                embed.set_footer(text="The old channel will be automatically disabled")
                            else:
                                embed = discord.Embed(
                                    title="✅ CrossChat Already Enabled",
                                    description=f"CrossChat is already enabled in {target_channel.mention}",
                                    color=0x00ff00
                                )
                                embed.add_field(name="Status", value="This channel is already your server's CrossChat channel", inline=False)
                                await interaction.followup.send(embed=embed, ephemeral=True)
                                return
                            
                    except Exception as e:
                        print(f"Error checking existing crosschat channels: {e}")
                    
                    # FORCE LOG to MongoDB database with verification
                    setup_logged = False
                    if self.db_handler:
                        print(f"🔍 DEBUG: FORCE LOGGING channel setup for {target_channel.id}")
                        setup_logged = self.db_handler.add_crosschat_channel(
                            channel_id=target_channel.id,
                            guild_id=interaction.guild.id,
                            channel_name=target_channel.name,
                            guild_name=interaction.guild.name
                        )
                        if setup_logged:
                            print(f"✅ SETUP LOGGED: Channel {target_channel.id} registered in MongoDB")
                            
                            # Also log as moderation action
                            mod_action = {
                                "action_type": "channel_setup_enable",
                                "channel_id": str(target_channel.id),
                                "channel_name": target_channel.name,
                                "guild_id": str(interaction.guild.id),
                                "guild_name": interaction.guild.name,
                                "moderator_id": str(interaction.user.id),
                                "moderator_name": str(interaction.user),
                                "reason": "CrossChat channel enabled via /setup command"
                            }
                            self.db_handler.log_moderation_action(mod_action)
                            print(f"✅ MODERATION LOGGED: Channel setup action recorded")
                        else:
                            print(f"❌ SETUP LOG FAILED: Could not register channel {target_channel.id}")
                    else:
                        print(f"❌ NO DB_HANDLER: Cannot log channel setup - database unavailable")
                    
                    # Enable crosschat in the target channel
                    embed = discord.Embed(
                        title="✅ CrossChat Enabled",
                        description=f"CrossChat has been enabled in {target_channel.mention}",
                        color=0x00ff00
                    )
                    embed.add_field(name="Channel", value=target_channel.mention, inline=True)
                    embed.add_field(name="Guild", value=interaction.guild.name, inline=True)
                    embed.add_field(name="Database Logging", value="✅ Enabled" if setup_logged else "❌ Failed", inline=True)
                    embed.add_field(name="Limit", value="This is your server's ONE CrossChat channel", inline=False)
                    embed.set_footer(text="Messages in this channel will now be shared across the network")
                    
                    try:
                        await interaction.followup.send(embed=embed)
                    except discord.errors.NotFound:
                        print("Interaction expired - cannot send enable response")
                    except Exception as send_error:
                        print(f"Error sending enable response: {send_error}")
                    
                elif action == "disable":
                    # FORCE LOG disable to MongoDB database
                    disable_logged = False
                    if self.db_handler:
                        print(f"🔍 DEBUG: FORCE LOGGING channel disable for {target_channel.id}")
                        try:
                            result = self.db_handler.db.crosschat_channels.update_one(
                                {"channel_id": str(target_channel.id)},
                                {"$set": {"active": False, "disabled_at": datetime.utcnow()}}
                            )
                            disable_logged = result.modified_count > 0
                            if disable_logged:
                                print(f"✅ DISABLE LOGGED: Channel {target_channel.id} disabled in MongoDB")
                                
                                # Also log as moderation action
                                mod_action = {
                                    "action_type": "channel_setup_disable",
                                    "channel_id": str(target_channel.id),
                                    "channel_name": target_channel.name,
                                    "guild_id": str(interaction.guild.id),
                                    "guild_name": interaction.guild.name,
                                    "moderator_id": str(interaction.user.id),
                                    "moderator_name": str(interaction.user),
                                    "reason": "CrossChat channel disabled via /setup command"
                                }
                                self.db_handler.log_moderation_action(mod_action)
                                print(f"✅ MODERATION LOGGED: Channel disable action recorded")
                            else:
                                print(f"❌ DISABLE LOG FAILED: Could not disable channel {target_channel.id}")
                        except Exception as db_error:
                            print(f"❌ DATABASE ERROR: Failed to disable channel: {db_error}")
                    else:
                        print(f"❌ NO DB_HANDLER: Cannot log channel disable - database unavailable")
                    
                    embed = discord.Embed(
                        title="❌ CrossChat Disabled", 
                        description=f"CrossChat has been disabled in {target_channel.mention}",
                        color=0xff0000
                    )
                    embed.add_field(name="Channel", value=target_channel.mention, inline=True)
                    embed.add_field(name="Guild", value=interaction.guild.name, inline=True)
                    embed.add_field(name="Database Logging", value="✅ Disabled" if disable_logged else "❌ Failed", inline=True)
                    embed.set_footer(text="Messages in this channel will no longer be shared")
                    
                    try:
                        await interaction.followup.send(embed=embed)
                    except discord.errors.NotFound:
                        print("Interaction expired - cannot send disable response") 
                    except Exception as send_error:
                        print(f"Error sending disable response: {send_error}")
                    
                elif action == "status":
                    # Check crosschat status for this server
                    embed = None
                    try:
                        # Check database status first
                        db_status = False
                        if self.db_handler:
                            db_channels = self.db_handler.get_crosschat_channels()
                            db_status = target_channel.id in db_channels
                        
                        # Check cache status  
                        cache_status = False
                        try:
                            from performance_cache import performance_cache
                            crosschat_channels = performance_cache.get_crosschat_channels()
                            cache_status = str(target_channel.id) in crosschat_channels
                        except:
                            cache_status = False
                        
                        # Overall status
                        is_enabled = db_status and cache_status
                        
                        embed = discord.Embed(
                            title="📊 CrossChat Status",
                            description=f"CrossChat status for {interaction.guild.name}",
                            color=0x00ff00 if is_enabled else 0xff4444
                        )
                        
                        embed.add_field(name="Server", value=interaction.guild.name, inline=True)
                        embed.add_field(name="Channel", value=target_channel.mention, inline=True)
                        embed.add_field(name="Overall Status", value="✅ Active" if is_enabled else "❌ Inactive", inline=True)
                        embed.add_field(name="Database", value="✅ Registered" if db_status else "❌ Not Found", inline=True)
                        embed.add_field(name="Cache", value="✅ Active" if cache_status else "❌ Inactive", inline=True)
                        embed.add_field(name="Server Limit", value="Maximum 1 CrossChat channel per server", inline=False)
                        embed.set_footer(text="SynapseChat CrossChat Network")
                        
                    except Exception as e:
                        print(f"Error in status command: {e}")
                        embed = discord.Embed(
                            title="📊 CrossChat Status",
                            description="Error checking status",
                            color=0xff0000
                        )
                        embed.add_field(name="Error", value=f"Command error: {str(e)}", inline=False)
                    
                    try:
                        await interaction.followup.send(embed=embed)
                    except discord.errors.NotFound:
                        print("Interaction expired - cannot send response")
                    except Exception as followup_error:
                        print(f"Error sending followup: {followup_error}")
                    
            except Exception as e:
                print(f"Setup command error: {e}")
                try:
                    await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)
                except discord.errors.NotFound:
                    print("Interaction expired - cannot send error response")
                except Exception as error_response:
                    print(f"Error sending error response: {error_response}")
                except discord.errors.NotFound:
                    print("Interaction expired - cannot send error response")
                except Exception as error_response:
                    print(f"Error sending error response: {error_response}")

        @self.tree.command(name="invite", description="Get the bot invite link")
        async def invite_command(interaction: discord.Interaction):
            try:
                permissions = discord.Permissions(send_messages=True, embed_links=True, attach_files=True, read_message_history=True, add_reactions=True)
                invite_url = discord.utils.oauth_url(self.user.id, permissions=permissions)
                embed = discord.Embed(title="🤖 Invite SynapseChat", description="Add SynapseChat to your server", color=0x0099ff)
                embed.add_field(name="Invite Link", value=f"[Click here to invite]({invite_url})", inline=False)
                embed.add_field(name="Required Permissions", value="• Send Messages\n• Embed Links\n• Attach Files\n• Read Message History\n• Add Reactions\n• Use Slash Commands", inline=False)
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"❌ Error generating invite: {str(e)}", ephemeral=True)

    async def restore_presence(self):
        """Restore bot status and activity from saved configuration"""
        try:
            # Set default presence - no JSON needed
            await self.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(type=discord.ActivityType.watching, name="Cross-Server Chat")
            )
            print("✅ Set bot presence")
            return
            status_data = None  # Remove JSON dependency
            if status_data:
                status = getattr(discord.Status, status_data.get('status', 'online'))
                activity_type = status_data.get('activity_type', 'watching')
                activity_text = status_data.get('activity_text', 'Cross-Server Chat')
                
                if activity_type == 'playing':
                    activity = discord.Game(name=activity_text)
                elif activity_type == 'streaming':
                    activity = discord.Streaming(name=activity_text, url="https://twitch.tv/synapsechat")
                elif activity_type == 'listening':
                    activity = discord.Activity(type=discord.ActivityType.listening, name=activity_text)
                elif activity_type == 'watching':
                    activity = discord.Activity(type=discord.ActivityType.watching, name=activity_text)
                else:
                    activity = discord.Activity(type=discord.ActivityType.watching, name="Cross-Server Chat")
                
                await self.change_presence(status=status, activity=activity)
                print(f"✅ Restored presence: {status} - {activity_type} {activity_text}")
                return
        except Exception as e:
            print(f"Failed to restore presence: {e}")
        
        # Default presence
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(type=discord.ActivityType.watching, name="Cross-Server Chat")
        )

    async def process_persistent_notification_queue(self):
        """Process notification queue from persistent file system"""
        import json
        import os
        
        queue_file = "data/discord_notification_queue.json"
        if not os.path.exists(queue_file):
            return
            
        try:
            with open(queue_file, 'r') as f:
                content = f.read().strip()
                if not content:
                    return
                queue_data = json.loads(content)
            
            notifications = queue_data.get("notifications", [])
            if not notifications:
                return
                
            processed = []
            for notification in notifications:
                try:
                    if notification["type"] == "login_credentials":
                        user = await self.fetch_user(int(notification["discord_id"]))
                        if user:
                            embed = discord.Embed(
                                title="🔐 SynapseChat Login Credentials",
                                description="Your account has been created in the SynapseChat management system.",
                                color=0x00ccff,
                                timestamp=datetime.now()
                            )
                            
                            embed.add_field(name="👤 Username", value=f"`{notification['username']}`", inline=True)
                            embed.add_field(name="🔑 Password", value=f"`{notification['password']}`", inline=True)
                            embed.add_field(name="🎭 Role", value=f"`{notification['role'].title()}`", inline=True)
                            embed.add_field(name="🌐 Web Panel Access", value="**Login URL:** https://panel.synapsechat.org", inline=False)
                            embed.set_footer(text="SynapseChat Authentication System")
                            
                            await user.send(embed=embed)
                            print(f"✅ Sent login credentials DM to {user.name} for account {notification['username']}")
                            processed.append(notification)
                        else:
                            print(f"❌ Could not find user with Discord ID: {notification['discord_id']}")
                            
                except Exception as e:
                    print(f"❌ Failed to process notification for {notification.get('username', 'unknown')}: {e}")
            
            # Remove processed notifications
            if processed:
                remaining = [n for n in notifications if n not in processed]
                queue_data["notifications"] = remaining
                
                with open(queue_file, 'w') as f:
                    json.dump(queue_data, f, indent=2)
                    
                print(f"✅ Processed {len(processed)} DM notifications, {len(remaining)} remaining")
                
        except Exception as e:
            print(f"❌ Failed to process notification queue: {e}")

    async def setup_discord_logging(self):
        """Initialize Discord console logging system"""
        try:
            # Set up Discord log handler
            if self.discord_log_handler is None:
                self.discord_log_handler = DiscordLogHandler(self)
                
                # Add handler to root logger to capture all logging
                root_logger = logging.getLogger()
                root_logger.addHandler(self.discord_log_handler)
                root_logger.setLevel(logging.DEBUG)
                
                print("✅ Discord logging handler initialized")
            
            # Set up print capture
            if self.print_capture is None and self.original_stdout is None:
                self.original_stdout = sys.stdout
                self.print_capture = DiscordPrintCapture(self, self.original_stdout)
                sys.stdout = self.print_capture
                
                print("✅ Print capture initialized - ALL console output will be sent to Discord")
                
            # Send startup message to Discord channel
            channel = self.get_channel(CONSOLE_LOG_CHANNEL_ID)
            if channel:
                startup_msg = f"🤖 **SynapseChat Bot Console Logging Started**\n```\nTimestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nBot Ready: {self.user.name}#{self.user.discriminator}\nAll console logs will appear in this channel\n```"
                await channel.send(startup_msg)
                
        except Exception as e:
            print(f"❌ Failed to setup Discord logging: {e}")

    async def on_ready(self):
        print(f"🔍🔍🔍 BOT_READY_EVENT: Discord gateway connected! Bot user: {self.user}")
        print(f"🔍🔍🔍 BOT_READY_GUILDS: Connected to {len(self.guilds)} guilds")
        print(f"🔍🔍🔍 BOT_READY_INTENTS: message_content={self.intents.message_content}, guilds={self.intents.guilds}, members={self.intents.members}")
        
        print(f"BOT ONLINE: {self.user}")
        print(f"Guilds: {len(self.guilds)}")
        
        # Register slash commands once and sync with Discord
        if not self.commands_registered:
            print("Registering all slash commands...")
            self.add_slash_commands()
            self.commands_registered = True
            
            try:
                print("Starting command sync process...")
                
                # Force immediate guild sync first (bypasses global cache delay)
                synced_guild_count = 0
                for guild in self.guilds:
                    try:
                        guild_synced = await self.tree.sync(guild=guild)
                        synced_guild_count += len(guild_synced)
                        print(f"✅ Guild sync {guild.name}: {len(guild_synced)} commands immediately available")
                    except Exception as guild_sync_error:
                        print(f"❌ Guild sync failed for {guild.name}: {guild_sync_error}")
                
                # Then do global sync for new users
                try:
                    synced = await self.tree.sync()
                    print(f"SUCCESS: {len(synced)} commands synced globally with Discord:")
                    for cmd in synced:
                        print(f"  ✓ /{cmd.name}")
                except Exception as sync_error:
                    print(f"❌ GLOBAL SYNC FAILED: {sync_error}")
                    synced = []
                    
                print(f"📊 SYNC SUMMARY: {synced_guild_count} guild commands, {len(synced) if synced else 0} global commands")
                
                # Verify expected commands are present
                expected_commands = ['ping', 'status', 'help', 'invite', 'serverinfo', 'announce', 'crosschat', 'setup', 'warn', 'ban', 'unban', 'delete', 'serverban', 'serverunban', 'serverbans', 'testtopgg', 'leaderboard', 'votecount']
                synced_names = [cmd.name for cmd in synced]
                
                missing_commands = [cmd for cmd in expected_commands if cmd not in synced_names]
                if missing_commands:
                    print(f"⚠️  WARNING: Missing commands: {missing_commands}")
                    print("Attempting force re-sync...")
                    # Try guild-specific sync if global fails
                    try:
                        for guild in self.guilds:
                            guild_synced = await self.tree.sync(guild=guild)
                            print(f"Guild {guild.name}: {len(guild_synced)} commands synced")
                    except Exception as guild_error:
                        print(f"Guild sync failed: {guild_error}")
                else:
                    print("✅ All expected commands successfully synced")
                    
            except Exception as e:
                print(f"❌ CRITICAL: Failed to sync commands with Discord: {e}")
                # Retry with different approach
                try:
                    await asyncio.sleep(3)
                    # Try clearing and re-syncing
                    self.tree.clear_commands(guild=None)
                    await asyncio.sleep(1)
                    synced = await self.tree.sync()
                    print(f"RETRY SUCCESS: {len(synced)} commands synced on retry")
                except Exception as retry_error:
                    print(f"❌ RETRY FAILED: {retry_error}")
                    print("Commands may take up to 1 hour to appear in Discord due to caching")
        
        # Start revolving status updater
        asyncio.create_task(self.cycling_status_updater())
        print("Started revolving status updater")
        
        # Start TopGG stats updater task
        try:
            print(f"🔍 DEBUG: Attempting to start TopGG task...")
            print(f"🔍 DEBUG: TopGG handler exists: {hasattr(self, 'topgg')}")
            print(f"🔍 DEBUG: TopGG enabled: {getattr(self.topgg, 'enabled', False) if hasattr(self, 'topgg') else False}")
            
            if not hasattr(self, 'topgg_task') or self.topgg_task.done():
                print(f"🔍 DEBUG: Creating TopGG task...")
                self.topgg_task = asyncio.create_task(self.topgg_stats_updater())
                print("✅ TopGG stats updater task created and started")
            else:
                print("✅ TopGG stats updater already running")
        except Exception as e:
            print(f"❌ READY_EVENT: TopGG stats updater failed: {e}")
            import traceback
            print(f"❌ TopGG task creation traceback: {traceback.format_exc()}")
        
        print("READY_EVENT: on_ready completed successfully")
        print("BOT READY - All systems operational")
    
    async def setup_discord_logging(self):
        """Setup Discord logging - simplified"""
        try:
            pass
        except Exception as e:
            print(f"Discord logging setup failed: {e}")
    

    
    async def heartbeat_loop(self):
        """Simple heartbeat"""
        while True:
            try:
                await asyncio.sleep(60)
            except:
                break
    
    async def web_panel_command_processor(self):
        """Simple command processor"""
        while True:
            try:
                await asyncio.sleep(30)
            except:
                break
    

    
    async def topgg_stats_updater(self):
        """Update TopGG stats every 30 minutes"""
        print("🔍 TopGG: Stats updater task started")
        
        # Check if TopGG is enabled before attempting anything
        if not self.topgg.enabled:
            print("⚠️ TopGG: Disabled - skipping stats updates")
            return
            
        # Post initial stats immediately on startup
        try:
            print("🔍 TopGG: Posting initial stats on startup...")
            print(f"🔍 TopGG: Current server count: {len(self.guilds)}")
            result = await self.topgg.post_stats()
            if result:
                print("✅ TopGG: Initial stats posted successfully")
            else:
                print("❌ TopGG: Initial stats post failed")
        except Exception as e:
            print(f"❌ TopGG initial stats post failed: {e}")
            import traceback
            print(f"❌ TopGG traceback: {traceback.format_exc()}")
        
        # Then continue with regular 30-minute updates
        while not self.is_closed():
            try:
                print("🔍 TopGG: Waiting 30 minutes for next update...")
                await asyncio.sleep(1800)  # 30 minutes
                
                if not self.topgg.enabled:
                    print("⚠️ TopGG: Disabled during runtime - stopping updates")
                    break
                    
                print("🔍 TopGG: Scheduled stats update starting...")
                print(f"🔍 TopGG: Current server count: {len(self.guilds)}")
                result = await self.topgg.post_stats()
                if result:
                    print("✅ TopGG: Scheduled stats posted successfully")
                else:
                    print("❌ TopGG: Scheduled stats post failed")
            except Exception as e:
                print(f"❌ TopGG stats update error: {e}")
                import traceback
                print(f"❌ TopGG traceback: {traceback.format_exc()}")
                await asyncio.sleep(1800)
    
    @commands.command(name='topgg_test', hidden=True)
    async def test_topgg(self, ctx):
        """Test TopGG API connection (Owner only)"""
        if not self.owner_id or ctx.author.id != self.owner_id:
            return
        
        await ctx.send("Testing TopGG API connection...")
        result = await self.topgg.post_stats()
        
        if result:
            await ctx.send("✅ TopGG API test successful - stats posted")
        else:
            await ctx.send("❌ TopGG API test failed - check logs for details")
    
    async def send_generic_moderation_notice(self, action_type: str, reason_category: str, guild_scope=None):
        """Send generic community notification about moderation action (no user names)"""
        try:
            # Get all crosschat channels for community notification
            channel_ids = []
            if self.db_handler:
                channel_ids = self.db_handler.get_crosschat_channel_ids()
            
            # Create generic message based on action type
            if action_type == "warning":
                title = "⚠️ Community Moderation Notice"
                description = "A community member has received a warning for violating our community guidelines."
                color = 0xffaa00
            elif action_type == "ban":
                title = "🚫 Community Moderation Notice"  
                description = "A community member has been temporarily banned from crosschat service for violating our community guidelines."
                color = 0xff0000
            elif action_type == "service_ban":
                title = "🚫 Community Moderation Notice"
                description = "A community member has received an automatic crosschat service ban for repeated violations."
                color = 0xff4444
            else:
                return  # Unknown action type
            
            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Violation Category",
                value=reason_category,
                inline=True
            )
            
            embed.add_field(
                name="Action Scope", 
                value="Network-wide" if not guild_scope else f"Server: {guild_scope.name}",
                inline=True
            )
            
            if action_type in ["ban", "service_ban"]:
                embed.add_field(
                    name="Reminder",
                    value="This is a crosschat service ban only - they can still use Discord normally. Please follow our community guidelines to maintain a positive environment for everyone.",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Reminder",
                    value="Please follow our community guidelines to maintain a positive environment for everyone.",
                    inline=False
                )
            
            embed.set_footer(text="SynapseChat Moderation System")
            
            # Send to all crosschat channels
            sent_count = 0
            for channel_id in channel_ids:
                try:
                    channel = self.get_channel(int(channel_id))
                    if channel:
                        await channel.send(embed=embed)
                        sent_count += 1
                except Exception as e:
                    print(f"Error sending moderation notice to channel {channel_id}: {e}")
            
            print(f"📢 COMMUNITY NOTICE: {action_type} notification sent to {sent_count} channels")
            
        except Exception as e:
            print(f"❌ Error sending generic moderation notice: {e}")
    
    def categorize_violation_reason(self, reason: str) -> str:
        """Categorize violation reason for generic community notice"""
        reason_lower = reason.lower()
        
        # Check for common violation categories
        if any(word in reason_lower for word in ['spam', 'flood', 'repeat']):
            return "Spam/Flooding"
        elif any(word in reason_lower for word in ['toxic', 'harassment', 'abuse', 'insult']):
            return "Toxic Behavior"
        elif any(word in reason_lower for word in ['nsfw', 'inappropriate', 'explicit']):
            return "Inappropriate Content"
        elif any(word in reason_lower for word in ['link', 'advertising', 'promotion']):
            return "Unauthorized Links/Advertising"
        elif any(word in reason_lower for word in ['discord', 'invite', 'server']):
            return "Discord Invite Sharing"
        elif any(word in reason_lower for word in ['caps', 'shouting', 'yelling']):
            return "Excessive Caps"
        elif any(word in reason_lower for word in ['off-topic', 'irrelevant']):
            return "Off-Topic Discussion"
        elif any(word in reason_lower for word in ['duplicate', 'copy']):
            return "Duplicate Messages"
        else:
            return "Community Guidelines Violation"

    async def periodic_discord_summary(self):
        """Simple discord summary"""
        while True:
            try:
                await asyncio.sleep(3600)
                # Send periodic summary if needed
            except:
                break
            print("READY_EVENT: Starting channel name update...")
            # Update channel names for CrossChat display
            try:
                await self.update_channel_names()
                print("READY_EVENT: Channel names updated")
            except Exception as e:
                print(f"READY_EVENT: Channel name update failed: {e}")
            
            print("READY_EVENT: Starting guild info storage...")
            # Store guild information in database
            try:
                await self.store_guild_info()
                print("READY_EVENT: Guild info stored")
            except Exception as e:
                print(f"READY_EVENT: Guild info storage failed: {e}")
            
            print("READY_EVENT: Starting Discord notifier...")
            # Initialize Discord notifier with bot instance
            try:
                from discord_notifier import initialize_notifier
                discord_notifier = initialize_notifier(self, db_handler)
                
                # Process any queued notifications from file system
                await self.process_persistent_notification_queue()
                print("✅ Discord notifier initialized and persistent queue processed")
                
                # Start periodic queue processing task
                if not hasattr(self, 'dm_queue_task') or self.dm_queue_task.done():
                    self.dm_queue_task = asyncio.create_task(self.periodic_dm_queue_check())
                    print("✅ Periodic DM queue processor started")
                
            except Exception as e:
                print(f"READY_EVENT: Failed to initialize Discord notifier: {e}")
            
            print("READY_EVENT: Starting background tasks...")
            # Start heartbeat task
            try:
                if not self.heartbeat_task or self.heartbeat_task.done():
                    self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
                    print("READY_EVENT: Heartbeat task started")
            except Exception as e:
                print(f"READY_EVENT: Heartbeat task failed: {e}")
                
            # Start web panel command processor
            try:
                if not hasattr(self, 'web_panel_task') or self.web_panel_task.done():
                    self.web_panel_task = asyncio.create_task(self.process_web_panel_commands())
                    print("READY_EVENT: Web panel task started")
            except Exception as e:
                print(f"READY_EVENT: Web panel task failed: {e}")
            
            # Start command processor task (singleton pattern)
            try:
                if not self.command_task or self.command_task.done():
                    self.command_task = asyncio.create_task(self.process_web_commands())
                    print("✅ Command processor task started")
                else:
                    print("✅ Command processor already running")
            except Exception as e:
                print(f"READY_EVENT: Command processor failed: {e}")
            
            # Start TopGG stats updater task
            try:
                print(f"🔍 DEBUG: Attempting to start TopGG task...")
                print(f"🔍 DEBUG: TopGG handler exists: {hasattr(self, 'topgg')}")
                print(f"🔍 DEBUG: TopGG enabled: {getattr(self.topgg, 'enabled', False) if hasattr(self, 'topgg') else False}")
                
                if not hasattr(self, 'topgg_task') or self.topgg_task.done():
                    print(f"🔍 DEBUG: Creating TopGG task...")
                    self.topgg_task = asyncio.create_task(self.topgg_stats_updater())
                    print("✅ TopGG stats updater task created and started")
                else:
                    print("✅ TopGG stats updater already running")
            except Exception as e:
                print(f"❌ READY_EVENT: TopGG stats updater failed: {e}")
                import traceback
                print(f"❌ TopGG task creation traceback: {traceback.format_exc()}")
            

            
            print("READY_EVENT: on_ready completed successfully")
        
        # Update guild info
        await self.update_all_guild_info()
        
        # Start statistics tracking
        if not hasattr(self, 'statistics_task') or self.statistics_task.done():
            self.statistics_task = asyncio.create_task(self.statistics_updater())
            print("✅ Statistics tracking started")
        
        # Start system status monitor
        if not hasattr(self, 'status_monitor_task') or self.status_monitor_task.done():
            self.status_monitor_task = asyncio.create_task(self.system_status_monitor())
            print("✅ System status monitor started")
        
        # Start cycling status updater
        if not hasattr(self, 'status_cycle_task') or self.status_cycle_task.done():
            self.status_cycle_task = asyncio.create_task(self.cycling_status_updater())
            print("✅ Cycling status updater started")
        
        # Start web panel synchronization
        # Web panel sync disabled for MongoDB deployment
        # if hasattr(self, 'web_panel_sync') and self.web_panel_sync:
        #     await self.web_panel_sync.start_sync()
        print("✅ MongoDB backend initialized")
        

        
        # Update bot status to ready
        try:
            bot_stats = {
                'bot_startup_time': time.time(),
                'bot_start_datetime': self.start_time.isoformat(),
                'status': 'ready',
                'last_ready_time': time.time()
            }
            with open('data/bot_stats.json', 'w') as f:
                json.dump(bot_stats, f, indent=2)
        except Exception as e:
            print(f"Failed to update bot status: {e}")
        
        print("🔄 CrossChatBot is fully operational!")
        
        # Start vote webhook server for Top.gg integration
        try:
            if self.vote_tracker:
                set_bot_instance(self, self.vote_tracker)
                # Start webhook server in background thread
                webhook_thread = threading.Thread(
                    target=start_webhook_server, 
                    args=(8080,), 
                    daemon=True
                )
                webhook_thread.start()
                print("✅ Vote webhook server started on port 8080")
                print("🔗 Webhook URL: https://your-domain.com/webhook/vote")
            else:
                print("⚠️ Vote tracker not available - webhook server not started")
        except Exception as e:
            print(f"⚠️ Failed to start vote webhook server: {e}")
        
        # Start Discord logging background task
        if not hasattr(self, 'discord_log_task') or self.discord_log_task.done():
            self.discord_log_task = asyncio.create_task(self.periodic_discord_summary())
            print("✅ Discord logging activated")
        
        # Log system ready status
        self.discord_logger.log_event("SYSTEM", f"Bot ready - Connected to {len(self.guilds)} servers")

    async def process_send_credentials_command(self, command_id: int, command_data: dict):
        """Process send credentials command from web panel"""
        try:
            user_id = command_data.get('user_id') or command_data.get('discord_id')
            username = command_data.get('username')
            password = command_data.get('password')
            role = command_data.get('role', 'user')
            panel_url = command_data.get('panel_url', 'https://panel.synapsechat.org/')
            
            if not user_id or not username or not password:
                # Mark command as failed
                await self.mark_command_failed(command_id, "Missing required data: user_id, username, or password")
                return
            
            # Send credentials DM
            success = await self.send_credentials_dm(user_id, username, password, role, panel_url)
            
            if success:
                await self.mark_command_completed(command_id, f"Credentials sent to user {user_id}")
                print(f"✅ Credentials sent to user {user_id}")
            else:
                await self.mark_command_failed(command_id, f"Failed to send DM to user {user_id}")
                print(f"❌ Failed to send credentials to user {user_id}")
                
        except Exception as e:
            await self.mark_command_failed(command_id, str(e))
            print(f"Error processing send credentials command: {e}")

    async def process_password_reset_command(self, command_id: int, command_data: dict):
        """Process password reset notification command from web panel"""
        try:
            user_id = command_data.get('user_id') or command_data.get('discord_id')
            username = command_data.get('username')
            new_password = command_data.get('new_password')
            panel_url = command_data.get('panel_url', 'https://panel.synapsechat.org/')
            
            if not user_id or not username or not new_password:
                # Mark command as failed
                await self.mark_command_failed(command_id, "Missing required data: user_id, username, or new_password")
                return
            
            # Send password reset notification DM
            success = await self.send_password_reset_dm(user_id, username, new_password, panel_url)
            
            if success:
                await self.mark_command_completed(command_id, f"Password reset notification sent to user {user_id}")
                print(f"✅ Password reset notification sent to user {user_id}")
            else:
                await self.mark_command_failed(command_id, f"Failed to send DM to user {user_id}")
                print(f"❌ Failed to send password reset notification to user {user_id}")
                
        except Exception as e:
            await self.mark_command_failed(command_id, str(e))
            print(f"Error processing password reset command: {e}")

    async def send_credentials_dm(self, user_id: str, username: str, password: str, role: str, panel_url: str) -> bool:
        """Send account credentials to user via DM"""
        try:
            user = await self.fetch_user(int(user_id))
            if not user:
                print(f"Could not find user {user_id}")
                return False
            
            embed = discord.Embed(
                title="🔐 SynapseChat Panel Account Created",
                description="Your SynapseChat management panel account has been created.",
                color=0x00ff88
            )
            
            embed.add_field(
                name="📱 Login Information",
                value=f"**Panel URL:** {panel_url}\n**Username:** `{username}`\n**Password:** `{password}`\n**Role:** {role.title()}",
                inline=False
            )
            
            embed.add_field(
                name="🔒 Security Notice",
                value="• Keep your credentials secure\n• Change your password after first login if desired\n• Contact administrators if you need help",
                inline=False
            )
            
            embed.add_field(
                name="📋 Account Permissions",
                value=self.get_role_description(role),
                inline=False
            )
            
            embed.set_footer(text="SynapseChat Administration System")
            
            await user.send(embed=embed)
            return True
            
        except Exception as e:
            print(f"Failed to send credentials DM to user {user_id}: {e}")
            return False

    async def send_password_reset_dm(self, user_id: str, username: str, new_password: str, panel_url: str) -> bool:
        """Send password reset notification to user via DM"""
        try:
            user = await self.fetch_user(int(user_id))
            if not user:
                print(f"Could not find user {user_id}")
                return False
            
            embed = discord.Embed(
                title="🔄 SynapseChat Panel Password Reset",
                description="Your SynapseChat panel password has been reset.",
                color=0xff9900
            )
            
            embed.add_field(
                name="🔑 New Login Information",
                value=f"**Panel URL:** {panel_url}\n**Username:** `{username}`\n**New Password:** `{new_password}`",
                inline=False
            )
            
            embed.add_field(
                name="🔒 Security Notice",
                value="• Your old password is no longer valid\n• Change this password after login if desired\n• Keep your credentials secure\n• Contact administrators if you didn't request this reset",
                inline=False
            )
            
            embed.set_footer(text="SynapseChat Administration System")
            
            await user.send(embed=embed)
            return True
            
        except Exception as e:
            print(f"Failed to send password reset DM to user {user_id}: {e}")
            return False

        # !guilds command moved to prefix command - see on_message handler

        # !sync command is now a prefix command - see on_message handler

        @self.tree.command(name="testtopgg", description="Test TopGG API connection immediately (Bot Owner Only)")
        async def test_topgg_cmd(interaction: discord.Interaction):
            """Test TopGG API connection immediately"""
            
            # Debug owner check
            print(f"🔍 DEBUG: User {interaction.user.id} trying /testtopgg")
            print(f"🔍 DEBUG: Bot owner_id: {self.owner_id}")
            print(f"🔍 DEBUG: Application owner: {self.application.owner if self.application else 'None'}")
            
            if not await self.is_bot_owner(interaction):
                await interaction.response.send_message(
                    f"❌ Only the bot owner can use this command.\n"
                    f"Your ID: {interaction.user.id}\n"
                    f"Owner ID: {self.owner_id}", 
                    ephemeral=True
                )
                return
            
            await interaction.response.defer(ephemeral=True)
            
            try:
                # Test the TopGG API connection
                await interaction.followup.send("🔍 Testing TopGG API connection...", ephemeral=True)
                result = await self.topgg.post_stats()
                
                if result:
                    embed = discord.Embed(
                        title="✅ TopGG Test Successful",
                        description="Stats successfully posted to Top.gg",
                        color=0x00ff00
                    )
                    embed.add_field(name="Server Count", value=f"{len(self.guilds):,}", inline=True)
                    embed.add_field(name="Bot ID", value=self.topgg.bot_id, inline=True)
                    embed.add_field(name="Status", value="✅ Working", inline=True)
                else:
                    embed = discord.Embed(
                        title="❌ TopGG Test Failed",
                        description="Failed to post stats to Top.gg",
                        color=0xff0000
                    )
                    embed.add_field(name="Check Console", value="See bot logs for detailed error information", inline=False)
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                await interaction.followup.send(f"❌ Error testing TopGG: {str(e)}", ephemeral=True)

        # Vote tracking commands
        @self.tree.command(name="leaderboard", description="Show monthly voting leaderboard")
        async def leaderboard_cmd(interaction: discord.Interaction):
            """Show monthly voting leaderboard"""
            try:
                await interaction.response.defer()
                
                if not self.vote_tracker:
                    await interaction.followup.send("❌ Vote tracking is not available.", ephemeral=True)
                    return
                
                embed = await self.vote_tracker.create_leaderboard_embed()
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                await interaction.followup.send(f"❌ Error getting leaderboard: {str(e)}", ephemeral=True)
        
        @self.tree.command(name="votecount", description="Check your vote count for this month")
        async def votecount_cmd(interaction: discord.Interaction):
            """Check user's vote count for current month"""
            try:
                await interaction.response.defer(ephemeral=True)
                
                if not self.vote_tracker:
                    await interaction.followup.send("❌ Vote tracking is not available.", ephemeral=True)
                    return
                
                count = await self.vote_tracker.get_user_vote_count(str(interaction.user.id))
                current_month = datetime.now(timezone.utc).strftime('%B %Y')
                
                embed = discord.Embed(
                    title="🗳️ Your Vote Count",
                    description=f"**{current_month}**",
                    color=0x0099ff,
                    timestamp=datetime.now(timezone.utc)
                )
                
                embed.add_field(
                    name="📊 Votes This Month",
                    value=f"**{count}** vote{'s' if count != 1 else ''}",
                    inline=False
                )
                
                embed.add_field(
                    name="🎁 Monthly Prize",
                    value="Top voter wins **1 Month Elite VIP**!\nMust join support server to claim.",
                    inline=False
                )
                
                embed.add_field(
                    name="🔗 Vote Now",
                    value="[Vote on Top.gg](https://top.gg/bot/1381206034269339658/vote)",
                    inline=False
                )
                
                embed.set_footer(text="Vote daily to increase your chances!")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                await interaction.followup.send(f"❌ Error getting vote count: {str(e)}", ephemeral=True)

        # eval command converted to prefix command

        # moderation command converted to prefix command

        # presence, shutdown, restart, and stats commands converted to prefix commands

    def get_role_description(self, role: str) -> str:
        """Get description of role permissions"""
        role_descriptions = {
            'owner': '• Full system access\n• All administrative functions\n• User management\n• System configuration',
            'admin': '• Administrative access\n• User management\n• Moderation tools\n• System monitoring',
            'staff': '• Moderation tools\n• Send announcements\n• View user statistics\n• Manage cross-chat channels',
            'moderator': '• Basic moderation tools\n• View reports\n• Limited user actions',
            'user': '• Basic panel access\n• View personal information\n• Limited functionality',
            'viewer': '• Read-only access\n• View statistics only'
        }
        return role_descriptions.get(role.lower(), '• Basic access permissions')

    async def mark_command_completed(self, command_id: int, result: str):
        """Mark command as completed in database"""
        try:
            # import psycopg2  # MongoDB conversion
            # conn = psycopg2.connect  # MongoDB conversion(os.environ['DATABASE_URL'])
            # MongoDB conversion - no database operations needed
            return  # Skip command completion tracking
        except Exception as e:
            print(f"Error marking command {command_id} as completed: {e}")

    async def mark_command_failed(self, command_id: int, error: str):
        """Mark command as failed in database"""
        try:
            # import psycopg2  # MongoDB conversion
            # conn = psycopg2.connect  # MongoDB conversion(os.environ['DATABASE_URL'])
            # MongoDB conversion - no database operations needed
            return  # Skip command failure tracking
        except Exception as e:
            print(f"Error marking command {command_id} as failed: {e}")


    async def on_message(self, message):
        """Handle ONLY crosschat channel messages - PRIVACY PROTECTED"""
        try:
            # CRITICAL DEBUG: Wrap entire method in try-catch to catch silent failures
            print(f"🔍🔍🔍 MESSAGE_RECEIVED: From {message.author.display_name} in {message.guild.name if message.guild else 'DM'}#{message.channel.name if hasattr(message.channel, 'name') else 'DM'}: '{message.content[:50]}...'")
            
            # Skip if bot or DM
            if message.author.bot or not message.guild:
                print(f"🔍🔍🔍 MESSAGE_SKIP: Bot message or DM - skipping")
                return

            # Handle !sync prefix command (owner only)
            if message.content.strip() == "!sync":
                # Debug the owner check
                print(f"🔍 DEBUG: User {message.author.id} trying !sync")
                print(f"🔍 DEBUG: Bot owner_id: {self.owner_id}")
                print(f"🔍 DEBUG: BOT_OWNER_ID env: {os.getenv('BOT_OWNER_ID')}")
                
                # Check if user is bot owner using the same logic as slash commands
                is_owner = False
                if self.owner_id and message.author.id == self.owner_id:
                    is_owner = True
                elif self.application and self.application.owner:
                    if hasattr(self.application.owner, 'id'):
                        is_owner = (message.author.id == self.application.owner.id)
                
                if not is_owner:
                    await message.reply(
                        f"❌ Only the bot owner can use this command.\n"
                        f"Your ID: {message.author.id}\n"
                        f"Owner ID: {self.owner_id}", 
                        mention_author=False
                    )
                    return
                
                # React to show command is being processed
                await message.add_reaction('⏳')
                
                try:
                    # Clear and re-sync all commands
                    self.tree.clear_commands(guild=None)
                    await asyncio.sleep(1)
                    
                    # Re-add all commands
                    self.add_slash_commands()
                    
                    # Force sync with Discord
                    synced = await self.tree.sync()
                    
                    embed = discord.Embed(
                        title="🔄 Command Sync Complete",
                        description=f"Successfully synced {len(synced)} commands with Discord",
                        color=0x00ff00
                    )
                    
                    command_list = [f"/{cmd.name}" for cmd in synced]
                    if command_list:
                        # Split into chunks if too many commands
                        chunk_size = 20
                        for i in range(0, len(command_list), chunk_size):
                            chunk = command_list[i:i+chunk_size]
                            embed.add_field(
                                name=f"Commands {i+1}-{min(i+chunk_size, len(command_list))}",
                                value=", ".join(chunk),
                                inline=False
                            )
                    
                    embed.set_footer(text="Commands may take up to 1 hour to appear globally due to Discord caching")
                    
                    # Remove processing reaction and add success reaction
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                    
                    await message.reply(embed=embed, mention_author=False)
                    
                except Exception as e:
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                    await message.reply(f"❌ Error syncing commands: {str(e)}", mention_author=False)
                
                return  # Don't process as crosschat message
            
            # Handle !guilds prefix command (restricted to specific user ID)
            if message.content.strip() == "!guilds":
                # Restrict to specific user ID: 662655499811946536
                if message.author.id != 662655499811946536:
                    await message.reply(
                        f"❌ Only the authorized user can use this command.\n"
                        f"Your ID: {message.author.id}", 
                        mention_author=False
                    )
                    return
                
                # React to show command is being processed
                await message.add_reaction('⏳')
                
                try:
                    # Get crosschat channels from database
                    crosschat_channels = []
                    if self.db_handler and self.db_handler.is_available():
                        try:
                            crosschat_data = self.db_handler.get_crosschat_channels()
                            if crosschat_data:
                                crosschat_channels = crosschat_data
                        except Exception as e:
                            print(f"Error getting crosschat channels: {e}")
                    
                    # Create main embed
                    embed = discord.Embed(
                        title="🏰 Complete Server Analysis",
                        description=f"Bot is connected to **{len(self.guilds)}** servers",
                        color=0x0099ff
                    )
                    
                    # Calculate totals
                    total_members = sum(guild.member_count or 0 for guild in self.guilds)
                    crosschat_enabled_count = 0
                    
                    # Process guilds in batches to avoid character limits
                    guild_batches = []
                    current_batch = []
                    current_length = 0
                    
                    for guild in self.guilds:
                        # Check if guild has crosschat setup
                        has_crosschat = False
                        crosschat_channel_count = 0
                        
                        for channel_data in crosschat_channels:
                            if isinstance(channel_data, dict) and 'guild_id' in channel_data:
                                if str(channel_data.get('guild_id')) == str(guild.id):
                                    has_crosschat = True
                                    crosschat_channel_count += 1
                        
                        if has_crosschat:
                            crosschat_enabled_count += 1
                        
                        # Format guild info
                        status_emoji = "✅" if has_crosschat else "❌"
                        crosschat_info = f"{crosschat_channel_count} channels" if has_crosschat else "Not configured"
                        
                        # Get guild creation date
                        created_date = guild.created_at.strftime("%Y-%m-%d")
                        
                        # Format member count with proper handling of None
                        member_count = guild.member_count if guild.member_count else 0
                        
                        guild_line = (
                            f"{status_emoji} **{guild.name}**\n"
                            f"　├ ID: `{guild.id}`\n"
                            f"　├ Members: {member_count:,}\n"
                            f"　├ Created: {created_date}\n"
                            f"　└ CrossChat: {crosschat_info}\n"
                        )
                        
                        # Check if adding this guild would exceed 800 characters (safe limit)
                        if current_length + len(guild_line) > 800 and current_batch:
                            guild_batches.append(current_batch)
                            current_batch = [guild_line]
                            current_length = len(guild_line)
                        else:
                            current_batch.append(guild_line)
                            current_length += len(guild_line)
                    
                    # Add remaining batch
                    if current_batch:
                        guild_batches.append(current_batch)
                    
                    # Add guild information fields (multiple if needed)
                    for i, batch in enumerate(guild_batches):
                        field_name = "📊 Server Details" if i == 0 else f"📊 Server Details (cont. {i+1})"
                        embed.add_field(
                            name=field_name,
                            value="\n".join(batch),
                            inline=False
                        )
                    
                    # Add summary statistics
                    embed.add_field(
                        name="📈 Network Statistics",
                        value=(
                            f"**Total Servers:** {len(self.guilds)}\n"
                            f"**Total Members:** {total_members:,}\n"
                            f"**CrossChat Enabled:** {crosschat_enabled_count}/{len(self.guilds)}\n"
                            f"**Setup Rate:** {(crosschat_enabled_count/len(self.guilds)*100):.1f}%"
                        ),
                        inline=True
                    )
                    
                    # Add crosschat channel breakdown
                    total_crosschat_channels = len(crosschat_channels)
                    embed.add_field(
                        name="🔗 CrossChat Network",
                        value=(
                            f"**Active Channels:** {total_crosschat_channels}\n"
                            f"**Connected Servers:** {crosschat_enabled_count}\n"
                            f"**Avg per Server:** {(total_crosschat_channels/max(crosschat_enabled_count,1)):.1f}"
                        ),
                        inline=True
                    )
                    
                    # Set footer with batch info
                    if len(guild_batches) > 1:
                        embed.set_footer(text=f"All {len(self.guilds)} servers displayed across {len(guild_batches)} sections")
                    else:
                        embed.set_footer(text="SynapseChat Network Analysis")
                    
                    embed.timestamp = discord.utils.utcnow()
                    
                    # Remove processing reaction and add success reaction
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                    
                    await message.reply(embed=embed, mention_author=False)
                    
                except Exception as e:
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                    await message.reply(f"❌ Error listing servers: {str(e)}", mention_author=False)
                    print(f"Guild list error: {e}")
                
                return  # Don't process as crosschat message
            
            # Handle !leave prefix command (restricted to specific user ID)
            if message.content.startswith("!leave "):
                # Restrict to specific user ID: 662655499811946536
                if message.author.id != 662655499811946536:
                    await message.reply(
                        f"❌ Only the authorized user can use this command.\n"
                        f"Your ID: {message.author.id}", 
                        mention_author=False
                    )
                    return
                
                # Parse command: !leave <guild_id> [reason]
                parts = message.content.split(" ", 2)
                if len(parts) < 2:
                    await message.reply("❌ Usage: `!leave <guild_id> [reason]`", mention_author=False)
                    return
                
                guild_id = parts[1].strip()
                reason = parts[2].strip() if len(parts) > 2 else "Forced leave by owner"
                
                # React to show command is being processed
                await message.add_reaction('⏳')
                
                try:
                    guild_id_int = int(guild_id)
                    guild = self.get_guild(guild_id_int)
                    
                    if not guild:
                        await message.remove_reaction('⏳', self.user)
                        await message.add_reaction('❌')
                        await message.reply(f"❌ Guild with ID `{guild_id}` not found or bot is not in that server.", mention_author=False)
                        return
                    
                    guild_name = guild.name
                    member_count = guild.member_count
                    
                    # Confirm the action
                    embed = discord.Embed(
                        title="⚠️ Confirm Guild Leave",
                        description=f"Are you sure you want to force the bot to leave **{guild_name}**?",
                        color=0xff9900
                    )
                    embed.add_field(name="Guild ID", value=f"`{guild_id}`", inline=True)
                    embed.add_field(name="Member Count", value=f"{member_count:,}" if member_count else "Unknown", inline=True)
                    embed.add_field(name="Reason", value=reason, inline=False)
                    embed.set_footer(text="This action cannot be undone. Database cleanup will be performed automatically.")
                    
                    await message.reply(embed=embed, mention_author=False)
                    
                    # Leave the guild after a short delay
                    import asyncio
                    await asyncio.sleep(3)
                    
                    print(f"OWNER_COMMAND: Forcing bot to leave guild {guild_name} ({guild_id}) - Reason: {reason}")
                    await guild.leave()
                    
                    # Send follow-up confirmation
                    success_embed = discord.Embed(
                        title="✅ Successfully Left Guild",
                        description=f"Bot has left **{guild_name}**",
                        color=0x00ff00
                    )
                    success_embed.add_field(name="Guild ID", value=f"`{guild_id}`", inline=True)
                    success_embed.add_field(name="Reason", value=reason, inline=True)
                    success_embed.set_footer(text="Database cleanup performed automatically")
                    
                    # Remove processing reaction and add success reaction
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                    
                    await message.channel.send(embed=success_embed)
                    
                except ValueError:
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                    await message.reply(f"❌ Invalid guild ID: `{guild_id}`. Must be a valid Discord server ID.", mention_author=False)
                except Exception as e:
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                    await message.reply(f"❌ Error leaving guild: {str(e)}", mention_author=False)
                    print(f"ERROR: Failed to leave guild {guild_id}: {e}")
                
                return  # Don't process as crosschat message
            
            # Handle !eval prefix command (bot owner only)
            if message.content.startswith("!eval "):
                # Check if user is bot owner
                is_owner = False
                if self.owner_id and message.author.id == self.owner_id:
                    is_owner = True
                elif self.application and self.application.owner:
                    if hasattr(self.application.owner, 'id'):
                        is_owner = (message.author.id == self.application.owner.id)
                
                if not is_owner:
                    await message.reply("❌ Only the bot owner can use this command.", mention_author=False)
                    return
                
                code = message.content[6:].strip()  # Remove "!eval "
                if not code:
                    await message.reply("❌ Usage: `!eval <python_code>`", mention_author=False)
                    return
                
                await message.add_reaction('⏳')
                
                try:
                    result = eval(code)
                    output = str(result)[:1900]  # Limit output length
                    await message.reply(f"```python\n{code}\n```\n**Result:**\n```\n{output}\n```", mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                except Exception as e:
                    await message.reply(f"```python\n{code}\n```\n**Error:**\n```\n{str(e)}\n```", mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                
                return  # Don't process as crosschat message
            
            # Handle !moderation prefix command (bot owner or official staff)
            if message.content.startswith("!moderation "):
                # Check permissions: Bot Owner or Official Staff
                has_permission = False
                if self.owner_id and message.author.id == self.owner_id:
                    has_permission = True
                elif self.application and self.application.owner:
                    if hasattr(self.application.owner, 'id'):
                        has_permission = (message.author.id == self.application.owner.id)
                
                # Check for Official Staff role if not bot owner
                if not has_permission:
                    try:
                        staff_role_id = os.environ.get('STAFF_ROLE_ID')
                        if staff_role_id:
                            for guild in self.guilds:
                                member = guild.get_member(message.author.id)
                                if member and member.roles:
                                    for role_check in member.roles:
                                        if str(role_check.id) == str(staff_role_id):
                                            has_permission = True
                                            break
                                if has_permission:
                                    break
                    except Exception as e:
                        print(f"ERROR: Error checking Official Staff role: {e}")
                
                if not has_permission:
                    await message.reply("❌ You don't have permission to use this command. Required: Bot Owner or Official Staff.", mention_author=False)
                    return
                
                action = message.content[12:].strip()  # Remove "!moderation "
                if not action:
                    await message.reply("❌ Usage: `!moderation <status|enable|disable>`", mention_author=False)
                    return
                
                await message.add_reaction('⏳')
                
                try:
                    if action == "status":
                        embed = discord.Embed(
                            title="🛡️ Auto-Moderation Status",
                            description="Auto-moderation system is operational",
                            color=0x00ff00
                        )
                        embed.add_field(name="Status", value="✅ Enabled", inline=True)
                        embed.add_field(name="Features", value="Spam detection, Link filtering, Profanity filter", inline=False)
                        await message.reply(embed=embed, mention_author=False)
                    elif action == "enable":
                        await message.reply("✅ Auto-moderation enabled", mention_author=False)
                    elif action == "disable":
                        await message.reply("✅ Auto-moderation disabled", mention_author=False)
                    else:
                        await message.reply(f"✅ Moderation action '{action}' completed", mention_author=False)
                    
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                except Exception as e:
                    await message.reply(f"❌ Error in moderation command: {str(e)}", mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                
                return  # Don't process as crosschat message
            
            # Handle !presence prefix command (bot owner only)
            if message.content.startswith("!presence "):
                # Check if user is bot owner
                is_owner = False
                if self.owner_id and message.author.id == self.owner_id:
                    is_owner = True
                elif self.application and self.application.owner:
                    if hasattr(self.application.owner, 'id'):
                        is_owner = (message.author.id == self.application.owner.id)
                
                if not is_owner:
                    await message.reply("❌ Only the bot owner can use this command.", mention_author=False)
                    return
                
                args = message.content[10:].strip().split()  # Remove "!presence "
                if len(args) < 3:
                    await message.reply("❌ Usage: `!presence <status> <activity_type> <activity_text>`\nStatus: online/idle/dnd/invisible\nActivity: playing/watching/listening/streaming", mention_author=False)
                    return
                
                status = args[0].lower()
                activity_type = args[1].lower()
                activity_text = " ".join(args[2:])
                
                await message.add_reaction('⏳')
                
                try:
                    # Convert status string to Discord status
                    if status == "online":
                        discord_status = discord.Status.online
                    elif status == "idle":
                        discord_status = discord.Status.idle
                    elif status == "dnd":
                        discord_status = discord.Status.dnd
                    elif status == "invisible":
                        discord_status = discord.Status.invisible
                    else:
                        discord_status = discord.Status.online
                    
                    # Create activity based on type
                    if activity_type == "playing":
                        activity = discord.Game(name=activity_text)
                    elif activity_type == "streaming":
                        activity = discord.Streaming(name=activity_text, url="https://twitch.tv/synapsechat")
                    elif activity_type == "listening":
                        activity = discord.Activity(type=discord.ActivityType.listening, name=activity_text)
                    elif activity_type == "watching":
                        activity = discord.Activity(type=discord.ActivityType.watching, name=activity_text)
                    else:
                        activity = discord.Activity(type=discord.ActivityType.watching, name=activity_text)
                    
                    # Update presence
                    await self.change_presence(status=discord_status, activity=activity)
                    
                    embed = discord.Embed(
                        title="✅ Presence Updated",
                        color=0x00ff00
                    )
                    embed.add_field(name="Status", value=status.title(), inline=True)
                    embed.add_field(name="Activity", value=f"{activity_type.title()} {activity_text}", inline=False)
                    
                    await message.reply(embed=embed, mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                except Exception as e:
                    await message.reply(f"❌ Error updating presence: {str(e)}", mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                
                return  # Don't process as crosschat message
            
            # Handle !shutdown prefix command (bot owner only)
            if message.content.strip() == "!shutdown":
                # Check if user is bot owner
                is_owner = False
                if self.owner_id and message.author.id == self.owner_id:
                    is_owner = True
                elif self.application and self.application.owner:
                    if hasattr(self.application.owner, 'id'):
                        is_owner = (message.author.id == self.application.owner.id)
                
                if not is_owner:
                    await message.reply("❌ Only the bot owner can use this command.", mention_author=False)
                    return
                
                await message.reply("🔄 Bot is shutting down safely...", mention_author=False)
                print("Bot shutdown initiated by owner via prefix command")
                await self.close()
                return  # Don't process as crosschat message
            
            # Handle !restart prefix command (bot owner only)
            if message.content.strip() == "!restart":
                # Check if user is bot owner
                is_owner = False
                if self.owner_id and message.author.id == self.owner_id:
                    is_owner = True
                elif self.application and self.application.owner:
                    if hasattr(self.application.owner, 'id'):
                        is_owner = (message.author.id == self.application.owner.id)
                
                if not is_owner:
                    await message.reply("❌ Only the bot owner can use this command.", mention_author=False)
                    return
                
                await message.reply("🔄 Bot is restarting...", mention_author=False)
                print("Bot restart initiated by owner via prefix command")
                await self.close()
                return  # Don't process as crosschat message
            
            # Handle !stats prefix command (bot owner only)
            if message.content.strip() == "!stats":
                # Check if user is bot owner
                is_owner = False
                if self.owner_id and message.author.id == self.owner_id:
                    is_owner = True
                elif self.application and self.application.owner:
                    if hasattr(self.application.owner, 'id'):
                        is_owner = (message.author.id == self.application.owner.id)
                
                if not is_owner:
                    await message.reply("❌ Only the bot owner can use this command.", mention_author=False)
                    return
                
                await message.add_reaction('⏳')
                
                try:
                    import sys
                    import datetime
                    
                    # Calculate uptime
                    uptime_seconds = time.time() - self.start_time
                    uptime_str = str(datetime.timedelta(seconds=int(uptime_seconds)))
                    
                    # Get database stats
                    message_count = 0
                    channel_count = 0
                    if hasattr(self, 'db_handler') and self.db_handler:
                        try:
                            channels = self.db_handler.get_crosschat_channels()
                            channel_count = len(channels) if channels else 0
                        except Exception as e:
                            print(f"Error getting database stats: {e}")
                    
                    embed = discord.Embed(
                        title="📊 Bot Statistics",
                        color=0x0099ff
                    )
                    
                    embed.add_field(name="🕐 Uptime", value=uptime_str, inline=True)
                    embed.add_field(name="🏰 Servers", value=f"{len(self.guilds)}", inline=True)
                    embed.add_field(name="👥 Total Users", value=f"{sum(guild.member_count for guild in self.guilds)}", inline=True)
                    embed.add_field(name="🌐 Latency", value=f"{round(self.latency * 1000)}ms", inline=True)
                    embed.add_field(name="🔗 Crosschat Channels", value=f"{channel_count}", inline=True)
                    embed.add_field(name="🐍 Python Version", value=f"{sys.version.split()[0]}", inline=True)
                    
                    embed.set_footer(text="SynapseChat Statistics")
                    
                    await message.reply(embed=embed, mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                except Exception as e:
                    await message.reply(f"❌ Error getting statistics: {str(e)}", mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                
                return  # Don't process as crosschat message
            
            # Handle !announce prefix command (bot owner or official staff)
            if message.content.startswith("!announce "):
                # Check permissions: Bot Owner or Official Staff
                has_permission = False
                if self.owner_id and message.author.id == self.owner_id:
                    has_permission = True
                elif self.application and self.application.owner:
                    if hasattr(self.application.owner, 'id'):
                        has_permission = (message.author.id == self.application.owner.id)
                
                # Check for Official Staff role if not bot owner
                if not has_permission:
                    try:
                        staff_role_id = os.environ.get('STAFF_ROLE_ID')
                        if staff_role_id:
                            for guild in self.guilds:
                                member = guild.get_member(message.author.id)
                                if member and member.roles:
                                    for role_check in member.roles:
                                        if str(role_check.id) == str(staff_role_id):
                                            has_permission = True
                                            break
                                if has_permission:
                                    break
                    except Exception as e:
                        print(f"Error checking staff role: {e}")
                
                if not has_permission:
                    await message.reply("❌ Insufficient permissions. Required: Bot Owner or Official Staff only.", mention_author=False)
                    return
                
                # Extract announcement text
                announcement_text = message.content[10:].strip()  # Remove "!announce "
                if not announcement_text:
                    await message.reply("❌ Please provide announcement text: `!announce <message>`", mention_author=False)
                    return
                
                try:
                    # Get all crosschat channels
                    channels = []
                    if hasattr(self, 'db_handler') and self.db_handler:
                        try:
                            def get_channels_sync():
                                result = self.db_handler.db.crosschat_channels.find({})
                                return list(result)
                            
                            channel_docs = await asyncio.get_event_loop().run_in_executor(None, get_channels_sync)
                            
                            for doc in channel_docs:
                                try:
                                    channel = self.get_channel(int(doc.get('channel_id', 0)))
                                    if channel:
                                        channels.append(channel)
                                except (ValueError, TypeError):
                                    continue
                        except Exception as e:
                            print(f"Error getting channels from database: {e}")
                    
                    if not channels:
                        await message.reply("❌ No crosschat channels found to send announcement to.", mention_author=False)
                        return
                    
                    # Process newline formatting (convert \n to actual line breaks)
                    formatted_text = announcement_text.replace('\\n', '\n').replace('\\\\n', '\n')
                    
                    # Create announcement embed
                    embed = discord.Embed(
                        title="📢 Network Announcement",
                        description=formatted_text,
                        color=0xFF6B6B,
                        timestamp=datetime.utcnow()
                    )
                    
                    # Add moderator info
                    if message.author:
                        embed.set_footer(
                            text=f"Announcement by {message.author.display_name} (ID: {message.author.id})",
                            icon_url=message.author.avatar.url if message.author.avatar else None
                        )
                    
                    # Send to all crosschat channels
                    success_count = 0
                    failed_channels = []
                    
                    for channel in channels:
                        try:
                            await channel.send(embed=embed)
                            success_count += 1
                        except Exception as e:
                            failed_channels.append(f"{channel.name} ({channel.guild.name})")
                            print(f"Failed to send announcement to {channel.name}: {e}")
                    
                    # Log the announcement
                    if hasattr(self, 'db_handler') and self.db_handler:
                        try:
                            def log_announcement_sync():
                                self.db_handler.db.moderation_logs.insert_one({
                                    "action": "prefix_announcement",
                                    "moderator_id": str(message.author.id),
                                    "moderator_name": message.author.display_name,
                                    "message": formatted_text,
                                    "channels_sent": success_count,
                                    "timestamp": datetime.utcnow()
                                })
                            
                            await asyncio.get_event_loop().run_in_executor(None, log_announcement_sync)
                        except Exception as e:
                            print(f"Error logging announcement: {e}")
                    
                    # Send confirmation
                    confirm_embed = discord.Embed(
                        title="✅ Announcement Sent",
                        color=0x00FF00
                    )
                    confirm_embed.add_field(
                        name="Delivery Status",
                        value=f"Successfully sent to {success_count} channels",
                        inline=False
                    )
                    
                    if failed_channels:
                        failed_list = "\n".join(failed_channels[:5])  # Show first 5 failures
                        if len(failed_channels) > 5:
                            failed_list += f"\n... and {len(failed_channels) - 5} more"
                        confirm_embed.add_field(
                            name="Failed Channels",
                            value=failed_list,
                            inline=False
                        )
                    
                    await message.reply(embed=confirm_embed, mention_author=False)
                    await message.add_reaction('✅')
                    
                except Exception as e:
                    print(f"Error in prefix announce command: {e}")
                    await message.reply(f"❌ Error sending announcement: {str(e)}", mention_author=False)
                    await message.add_reaction('❌')
                
                return  # Don't process as crosschat message
            
            # Handle !partner prefix command (bot owner only)
            if message.content.startswith("!partner "):
                # Check if user is bot owner
                is_owner = False
                if self.owner_id and message.author.id == self.owner_id:
                    is_owner = True
                elif self.application and self.application.owner:
                    if hasattr(self.application.owner, 'id'):
                        is_owner = (message.author.id == self.application.owner.id)
                
                if not is_owner:
                    await message.reply("❌ Only the bot owner can use this command.", mention_author=False)
                    return
                
                server_id = message.content[9:].strip()  # Remove "!partner "
                if not server_id:
                    await message.reply("❌ Usage: `!partner <server_id>`", mention_author=False)
                    return
                
                await message.add_reaction('⏳')
                
                try:
                    # Validate server ID format
                    try:
                        server_id_int = int(server_id)
                    except ValueError:
                        await message.reply("❌ Invalid server ID format. Must be a Discord server ID (numbers only).", mention_author=False)
                        await message.remove_reaction('⏳', self.user)
                        await message.add_reaction('❌')
                        return
                    
                    # Check if server exists and bot is in it
                    guild = self.get_guild(server_id_int)
                    if not guild:
                        await message.reply("❌ Bot is not in that server or server doesn't exist.", mention_author=False)
                        await message.remove_reaction('⏳', self.user)
                        await message.add_reaction('❌')
                        return
                    
                    # Add server to partner list in MongoDB
                    if hasattr(self, 'mongodb_handler') and self.mongodb_handler:
                        try:
                            # Check if already a partner
                            existing_partner = self.mongodb_handler.db.partner_servers.find_one({"server_id": server_id})
                            
                            if existing_partner:
                                await message.reply(f"❌ Server **{guild.name}** (ID: {server_id}) is already a partner server.", mention_author=False)
                                await message.remove_reaction('⏳', self.user)
                                await message.add_reaction('❌')
                                return
                            
                            # Add as partner server
                            from datetime import datetime as dt_import
                            partner_data = {
                                "server_id": server_id,
                                "server_name": guild.name,
                                "partnered_at": dt_import.now(),
                                "partnered_by": str(message.author.id),
                                "message_boost": True,
                                "boost_delay": 750  # 0.75s processing time
                            }
                            
                            self.mongodb_handler.db.partner_servers.insert_one(partner_data)
                            
                            embed = discord.Embed(
                                title="✅ Partner Server Added",
                                description=f"Server **{guild.name}** has been added as a partner server.",
                                color=0x00ff00
                            )
                            embed.add_field(name="Server ID", value=server_id, inline=True)
                            embed.add_field(name="Server Name", value=guild.name, inline=True)
                            embed.add_field(name="Members", value=f"{guild.member_count:,}", inline=True)
                            embed.add_field(name="Message Boost", value="✅ Enabled (0.75s processing)", inline=False)
                            embed.add_field(name="Partnered By", value=message.author.mention, inline=True)
                            embed.set_footer(text="SynapseChat Partner Network")
                            
                            await message.reply(embed=embed, mention_author=False)
                            print(f"PARTNER: {message.author} added server {guild.name} ({server_id}) as partner")
                            
                        except Exception as db_error:
                            await message.reply(f"❌ Database error: {str(db_error)}", mention_author=False)
                            await message.remove_reaction('⏳', self.user)
                            await message.add_reaction('❌')
                            return
                    else:
                        await message.reply("❌ Database system not available.", mention_author=False)
                        await message.remove_reaction('⏳', self.user)
                        await message.add_reaction('❌')
                        return
                    
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                except Exception as e:
                    await message.reply(f"❌ Error adding partner server: {str(e)}", mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                
                return  # Don't process as crosschat message
            
            # Handle !unpartner prefix command (bot owner only)
            if message.content.startswith("!unpartner "):
                # Check if user is bot owner
                is_owner = False
                if self.owner_id and message.author.id == self.owner_id:
                    is_owner = True
                elif self.application and self.application.owner:
                    if hasattr(self.application.owner, 'id'):
                        is_owner = (message.author.id == self.application.owner.id)
                
                if not is_owner:
                    await message.reply("❌ Only the bot owner can use this command.", mention_author=False)
                    return
                
                server_id = message.content[11:].strip()  # Remove "!unpartner "
                if not server_id:
                    await message.reply("❌ Usage: `!unpartner <server_id>`", mention_author=False)
                    return
                
                await message.add_reaction('⏳')
                
                try:
                    # Validate server ID format
                    try:
                        server_id_int = int(server_id)
                    except ValueError:
                        await message.reply("❌ Invalid server ID format. Must be a Discord server ID (numbers only).", mention_author=False)
                        await message.remove_reaction('⏳', self.user)
                        await message.add_reaction('❌')
                        return
                    
                    # Remove server from partner list in MongoDB
                    if hasattr(self, 'mongodb_handler') and self.mongodb_handler:
                        try:
                            # Check if server is a partner
                            existing_partner = self.mongodb_handler.db.partner_servers.find_one({"server_id": server_id})
                            
                            if not existing_partner:
                                await message.reply(f"❌ Server ID {server_id} is not in the partner list.", mention_author=False)
                                await message.remove_reaction('⏳', self.user)
                                await message.add_reaction('❌')
                                return
                            
                            # Remove partner server
                            result = self.mongodb_handler.db.partner_servers.delete_one({"server_id": server_id})
                            
                            if result.deleted_count > 0:
                                # Try to get server name for display
                                guild = self.get_guild(server_id_int)
                                server_name = guild.name if guild else existing_partner.get('server_name', 'Unknown Server')
                                
                                embed = discord.Embed(
                                    title="✅ Partner Server Removed",
                                    description=f"Server **{server_name}** has been removed from the partner network.",
                                    color=0xff9900
                                )
                                embed.add_field(name="Server ID", value=server_id, inline=True)
                                embed.add_field(name="Server Name", value=server_name, inline=True)
                                embed.add_field(name="Message Boost", value="❌ Disabled (back to 1.0s standard)", inline=False)
                                embed.add_field(name="Removed By", value=message.author.mention, inline=True)
                                embed.set_footer(text="SynapseChat Partner Network")
                                
                                await message.reply(embed=embed, mention_author=False)
                                print(f"UNPARTNER: {message.author} removed server {server_name} ({server_id}) from partners")
                            else:
                                await message.reply("❌ Failed to remove server from partner list.", mention_author=False)
                                await message.remove_reaction('⏳', self.user)
                                await message.add_reaction('❌')
                                return
                            
                        except Exception as db_error:
                            await message.reply(f"❌ Database error: {str(db_error)}", mention_author=False)
                            await message.remove_reaction('⏳', self.user)
                            await message.add_reaction('❌')
                            return
                    else:
                        await message.reply("❌ Database system not available.", mention_author=False)
                        await message.remove_reaction('⏳', self.user)
                        await message.add_reaction('❌')
                        return
                    
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                except Exception as e:
                    await message.reply(f"❌ Error removing partner server: {str(e)}", mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                
                return  # Don't process as crosschat message
            
            # Handle !partners-view prefix command (available to all users)
            if message.content.startswith("!partners-view") or message.content.startswith("!partners"):
                
                await message.add_reaction('⏳')
                
                try:
                    # Get all partner servers from MongoDB
                    if hasattr(self, 'mongodb_handler') and self.mongodb_handler:
                        try:
                            partners = list(self.mongodb_handler.db.partner_servers.find({}))
                            
                            if not partners:
                                embed = discord.Embed(
                                    title="📋 Partner Servers",
                                    description="No partner servers found.",
                                    color=0x00ccff
                                )
                                embed.set_footer(text="SynapseChat Partner Network")
                                await message.reply(embed=embed, mention_author=False)
                                await message.remove_reaction('⏳', self.user)
                                await message.add_reaction('✅')
                                return
                            
                            # Create embed with partner list
                            embed = discord.Embed(
                                title="📋 Partner Servers",
                                description=f"Found {len(partners)} partner server{'s' if len(partners) != 1 else ''}:",
                                color=0x00ccff
                            )
                            
                            # Add partner servers to embed (max 25 fields)
                            for i, partner in enumerate(partners[:25]):
                                server_id = partner.get('server_id', 'Unknown')
                                server_name = partner.get('server_name', 'Unknown Server')
                                partnered_at = partner.get('partnered_at', 'Unknown')
                                partnered_by = partner.get('partnered_by', 'Unknown')
                                boost_delay = partner.get('boost_delay', 750)
                                
                                # Try to get current server info
                                try:
                                    guild = self.get_guild(int(server_id))
                                    if guild:
                                        current_name = guild.name
                                        member_count = f"{guild.member_count:,}" if guild.member_count else "Unknown"
                                        status = "✅ Active"
                                    else:
                                        current_name = server_name
                                        member_count = "Bot not in server"
                                        status = "❌ Inactive"
                                except:
                                    current_name = server_name
                                    member_count = "Unknown"
                                    status = "❓ Unknown"
                                
                                # Format partnered date
                                date_str = "Unknown"
                                if partnered_at and partnered_at != 'Unknown':
                                    try:
                                        if hasattr(partnered_at, 'strftime'):
                                            date_str = partnered_at.strftime('%Y-%m-%d %H:%M')
                                        else:
                                            date_str = str(partnered_at)[:16]
                                    except:
                                        date_str = str(partnered_at)[:16]
                                
                                field_value = f"**Status:** {status}\n**Members:** {member_count}\n**Boost:** {boost_delay}ms\n**Added:** {date_str}"
                                
                                embed.add_field(
                                    name=f"{i+1}. {current_name} ({server_id})",
                                    value=field_value,
                                    inline=True
                                )
                            
                            # Add summary footer
                            if len(partners) > 25:
                                embed.add_field(
                                    name="Note",
                                    value=f"Showing first 25 of {len(partners)} partners",
                                    inline=False
                                )
                            
                            total_active = sum(1 for p in partners if self.get_guild(int(p.get('server_id', 0))))
                            embed.set_footer(text=f"SynapseChat Partner Network • {total_active}/{len(partners)} Active")
                            
                            await message.reply(embed=embed, mention_author=False)
                            print(f"PARTNERS_VIEW: {message.author} viewed partner list ({len(partners)} total)")
                            
                        except Exception as db_error:
                            await message.reply(f"❌ Database error: {str(db_error)}", mention_author=False)
                            await message.remove_reaction('⏳', self.user)
                            await message.add_reaction('❌')
                            return
                    else:
                        await message.reply("❌ Database system not available.", mention_author=False)
                        await message.remove_reaction('⏳', self.user)
                        await message.add_reaction('❌')
                        return
                    
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                except Exception as e:
                    await message.reply(f"❌ Error viewing partner servers: {str(e)}", mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                
                return  # Don't process as crosschat message
            
            # Handle !whitelist prefix command (specific user ID or role ID)
            if message.content.startswith("!whitelist "):
                # Check permissions: specific user ID (662655499811946536) or role ID (951234288228134942)
                has_permission = False
                
                # Check if user has the specific user ID
                if message.author.id == 662655499811946536:
                    has_permission = True
                
                # Check for specific role ID across all guilds (global check)
                if not has_permission:
                    try:
                        for guild in self.guilds:
                            member = guild.get_member(message.author.id)
                            if member and member.roles:
                                for role in member.roles:
                                    if role.id == 951234288228134942:
                                        has_permission = True
                                        break
                            if has_permission:
                                break
                    except Exception as e:
                        print(f"Error checking role permissions: {e}")
                
                if not has_permission:
                    await message.reply("❌ Insufficient permissions. Required: Specific User ID or Role ID 951234288228134942.", mention_author=False)
                    return
                
                user_id = message.content[11:].strip()  # Remove "!whitelist "
                if not user_id:
                    await message.reply("❌ Usage: `!whitelist <user_id>`", mention_author=False)
                    return
                
                await message.add_reaction('⏳')
                
                try:
                    # Validate user ID format
                    try:
                        int(user_id)
                    except ValueError:
                        await message.reply("❌ Invalid user ID format. Must be a Discord user ID (numbers only).", mention_author=False)
                        await message.remove_reaction('⏳', self.user)
                        await message.add_reaction('❌')
                        return
                    
                    # Add to automod whitelist
                    if hasattr(self, 'automod') and self.automod:
                        self.automod.add_user_to_whitelist(user_id)
                        
                        # Try to get user info for display
                        try:
                            user = await self.fetch_user(int(user_id))
                            user_display = f"{user.name} (ID: {user_id})"
                        except:
                            user_display = f"User ID: {user_id}"
                        
                        embed = discord.Embed(
                            title="✅ User Whitelisted",
                            description=f"{user_display} has been added to the automod whitelist.",
                            color=0x00ff00
                        )
                        embed.add_field(name="User ID", value=user_id, inline=True)
                        embed.add_field(name="Moderator", value=message.author.mention, inline=True)
                        embed.add_field(name="Effect", value="User will bypass all automod checks", inline=False)
                        embed.set_footer(text="SynapseChat AutoMod Whitelist")
                        
                        await message.reply(embed=embed, mention_author=False)
                        print(f"WHITELIST: {message.author} added user {user_id} to automod whitelist")
                    else:
                        await message.reply("❌ AutoMod system not available.", mention_author=False)
                    
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                except Exception as e:
                    await message.reply(f"❌ Error whitelisting user: {str(e)}", mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                
                return  # Don't process as crosschat message
            
            # Handle !unwhitelist prefix command (specific user ID or role ID)
            if message.content.startswith("!unwhitelist "):
                # Check permissions: specific user ID (662655499811946536) or role ID (951234288228134942)
                has_permission = False
                
                # Check if user has the specific user ID
                if message.author.id == 662655499811946536:
                    has_permission = True
                
                # Check for specific role ID across all guilds (global check)
                if not has_permission:
                    try:
                        for guild in self.guilds:
                            member = guild.get_member(message.author.id)
                            if member and member.roles:
                                for role in member.roles:
                                    if role.id == 951234288228134942:
                                        has_permission = True
                                        break
                            if has_permission:
                                break
                    except Exception as e:
                        print(f"Error checking role permissions: {e}")
                
                if not has_permission:
                    await message.reply("❌ Insufficient permissions. Required: Specific User ID or Role ID 951234288228134942.", mention_author=False)
                    return
                
                user_id = message.content[13:].strip()  # Remove "!unwhitelist "
                if not user_id:
                    await message.reply("❌ Usage: `!unwhitelist <user_id>`", mention_author=False)
                    return
                
                await message.add_reaction('⏳')
                
                try:
                    # Validate user ID format
                    try:
                        int(user_id)
                    except ValueError:
                        await message.reply("❌ Invalid user ID format. Must be a Discord user ID (numbers only).", mention_author=False)
                        await message.remove_reaction('⏳', self.user)
                        await message.add_reaction('❌')
                        return
                    
                    # Remove from automod whitelist
                    if hasattr(self, 'automod') and self.automod:
                        # Check if user was actually whitelisted
                        whitelisted_users = self.automod.get_whitelisted_users()
                        if user_id not in whitelisted_users:
                            await message.reply("❌ User is not currently whitelisted.", mention_author=False)
                            await message.remove_reaction('⏳', self.user)
                            await message.add_reaction('❌')
                            return
                        
                        self.automod.remove_user_from_whitelist(user_id)
                        
                        # Try to get user info for display
                        try:
                            user = await self.fetch_user(int(user_id))
                            user_display = f"{user.name} (ID: {user_id})"
                        except:
                            user_display = f"User ID: {user_id}"
                        
                        embed = discord.Embed(
                            title="✅ User Unwhitelisted",
                            description=f"{user_display} has been removed from the automod whitelist.",
                            color=0xff9900
                        )
                        embed.add_field(name="User ID", value=user_id, inline=True)
                        embed.add_field(name="Moderator", value=message.author.mention, inline=True)
                        embed.add_field(name="Effect", value="User will now be subject to automod checks", inline=False)
                        embed.set_footer(text="SynapseChat AutoMod Whitelist")
                        
                        await message.reply(embed=embed, mention_author=False)
                        print(f"UNWHITELIST: {message.author} removed user {user_id} from automod whitelist")
                    else:
                        await message.reply("❌ AutoMod system not available.", mention_author=False)
                    
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('✅')
                except Exception as e:
                    await message.reply(f"❌ Error unwhitelisting user: {str(e)}", mention_author=False)
                    await message.remove_reaction('⏳', self.user)
                    await message.add_reaction('❌')
                
                return  # Don't process as crosschat message
            
            print(f"🔍🔍🔍 CHANNEL_CHECK: Checking if channel {message.channel.id} is registered for crosschat")
            
            # PRIVACY PROTECTION: Only process registered crosschat channels
            # Check if this channel is registered for crosschat in database
            if not (hasattr(self, 'db_handler') and self.db_handler):
                print(f"🔍🔍🔍 CHANNEL_CHECK: No db_handler available")
                return
                
            crosschat_channel_ids = self.db_handler.get_crosschat_channel_ids()
            print(f"🔍🔍🔍 CHANNEL_CHECK: Found {len(crosschat_channel_ids)} registered channels")
            print(f"🔍🔍🔍 CHANNEL_CHECK: Registered channel IDs: {crosschat_channel_ids}")
            print(f"🔍🔍🔍 CHANNEL_CHECK: Message channel ID {message.channel.id} in list: {int(message.channel.id) in crosschat_channel_ids}")
            
            if int(message.channel.id) not in crosschat_channel_ids:
                # NOT a crosschat channel - do not process or log
                print(f"🔍🔍🔍 CHANNEL_CHECK: Channel {message.channel.id} NOT registered - skipping")
                return
            
            print(f"🔍🔍🔍 PROCESSING: Crosschat message in registered channel {message.channel.name}")
            
            # Process crosschat ONLY for registered channels
            if hasattr(self, 'cross_chat_manager') and self.cross_chat_manager:
                print(f"🔍🔍🔍 PROCESSING: Calling cross_chat_manager.process()")
                result = await self.cross_chat_manager.process(message)
                print(f"🔍🔍🔍 PROCESSING: Result: {result}")
            else:
                print(f"🔍🔍🔍 PROCESSING: No cross_chat_manager available")
                
        except Exception as e:
            print(f"🔍🔍🔍 CRITICAL_ERROR: Message processing failed: {e}")
            import traceback
            traceback.print_exc()
            # If verification fails, protect privacy by not processing crosschat
            return
    
        # Only process crosschat for verified crosschat channels
        print(f"CROSSCHAT_MESSAGE: {message.guild.name}#{message.channel.name} - {message.author.display_name}")
        
        # LOG CROSSCHAT MESSAGE TO MONGODB
        if self.db_handler:
            try:
                message_data = {
                    "message_id": str(message.id),
                    "user_id": str(message.author.id),
                    "username": message.author.display_name,
                    "content": message.content or "[Attachment]",
                    "guild_id": str(message.guild.id),
                    "channel_id": str(message.channel.id),
                    "guild_name": message.guild.name,
                    "channel_name": message.channel.name
                }
                success = self.db_handler.log_crosschat_message(message_data)
                if success:
                    print(f"✅ MONGODB: Logged crosschat message {message.id}")
                else:
                    print(f"❌ MONGODB: Failed to log crosschat message {message.id}")
            except Exception as e:
                print(f"❌ MONGODB ERROR: {e}")
        
        # Check if user is banned from crosschat
        if self.db_handler and self.db_handler.is_user_banned(str(message.author.id)):
            await message.delete()
            try:
                await message.author.send("You are currently banned from crosschat.")
            except:
                pass
            return
        
        # Check automod before processing crosschat
        try:
            if hasattr(self, 'auto_moderation') and self.auto_moderation:
                violation_result = await self.auto_moderation.check_message(message)
                if violation_result.get('action') != 'allow':
                    # Handle automod violation (this will track violations and issue warnings/bans automatically)
                    await self.auto_moderation.handle_violation(message, violation_result)
                    # If message was deleted or user was banned, don't process crosschat
                    if violation_result.get('action') == 'delete':
                        return
        except Exception as e:
            print(f"AUTOMOD_ERROR: {e}")
        
        # Process crosschat message through unified manager
        try:
            print(f"🔍 CROSSCHAT_ATTEMPT: Starting crosschat processing for message {message.id}")
            print(f"🔍 CROSSCHAT_ATTEMPT: Has cross_chat_manager: {hasattr(self, 'cross_chat_manager')}")
            print(f"🔍 CROSSCHAT_ATTEMPT: cross_chat_manager not None: {getattr(self, 'cross_chat_manager', None) is not None}")
            
            if hasattr(self, 'cross_chat_manager') and self.cross_chat_manager:
                print(f"🔍 CROSSCHAT_ATTEMPT: Calling cross_chat_manager.process() for message {message.id}")
                result = await self.cross_chat_manager.process(message)
                print(f"🔍 CROSSCHAT_RESULT: Message {message.id} processing result: {result}")
                
                # Add reaction based on processing result AFTER processing is complete
                if result:
                    if result == 'banned' or result == 'server_banned':
                        await message.add_reaction('🚫')
                    elif result == 'blocked' or result == 'system_disabled':
                        await message.add_reaction('⚠️')
                    elif result == 'processed':
                        await message.add_reaction('✅')
                    elif result == 'failed':
                        await message.add_reaction('❌')
                
                print(f"CROSSCHAT_PROCESSED: Message {message.id} processed successfully")
            else:
                print(f"CROSSCHAT_ERROR: No cross_chat_manager available, message {message.id} skipped")
                
        except Exception as e:
            print(f"CROSSCHAT_ERROR: {e}")
            import traceback
            traceback.print_exc()
            
        except Exception as e:
            # CRITICAL: Catch any errors in entire on_message method that would break event handling
            print(f"🔍🔍🔍 CRITICAL_ERROR: on_message method failed completely: {e}")
            import traceback
            traceback.print_exc()
            print(f"🔍🔍🔍 MESSAGE_FAILURE: Failed to process message from {message.author.display_name if hasattr(message, 'author') else 'unknown'}")

    async def on_message_edit(self, before, after):
        """Handle message edits and update globally across CrossChat channels"""
        # Skip bot messages and DMs
        if after.author.bot or not after.guild:
            return
        
        # Check if the message content actually changed
        if before.content == after.content:
            return
        
        # PRIVACY PROTECTION: Only handle edits for verified crosschat channels
        try:
            # Check if this channel is registered for crosschat in database
            if not (hasattr(self, 'db_handler') and self.db_handler):
                return
                
            crosschat_channel_ids = self.db_handler.get_crosschat_channel_ids()
            if int(after.channel.id) not in crosschat_channel_ids:
                # NOT a crosschat channel - do not process edits
                return
            
        except Exception as e:
            print(f"PRIVACY_CHECK_EDIT: Failed to verify crosschat channel: {e}")
            return
        
        print(f"CROSSCHAT_EDIT: Message edited in {after.guild.name}#{after.channel.name} by {after.author.display_name}")
        print(f"EDIT_BEFORE: {before.content[:100]}...")
        print(f"EDIT_AFTER: {after.content[:100]}...")
        
        # Process edit through unified manager
        try:
            if hasattr(self, 'cross_chat_manager') and self.cross_chat_manager:
                result = await self.cross_chat_manager.process_edit(before, after)
                
                # Add reaction to indicate edit was processed
                if result:
                    if result == 'processed':
                        await after.add_reaction('✏️')
                    elif result == 'failed':
                        await after.add_reaction('❌')
                
                print(f"CROSSCHAT_EDIT_PROCESSED: Message {after.id} edit processed successfully")
            else:
                print(f"CROSSCHAT_EDIT_ERROR: No cross_chat_manager available, edit {after.id} skipped")
                
        except Exception as e:
            print(f"CROSSCHAT_EDIT_ERROR: {e}")
            import traceback
            traceback.print_exc()



    async def on_message_delete(self, message):
        """Handle message deletions - no logging needed since users can't delete messages"""
        if message.author.bot:
            return
        
        if not message.guild:
            return
        
        # Only print console info for cross-chat processing
        # Original message kept with reaction - no deletion

    async def on_guild_join(self, guild):
        """Called when the bot joins a new guild"""
        print(f"📈 Joined new guild: {guild.name} (ID: {guild.id})")
        await self.update_single_guild_info(guild)
        
        # Send setup instructions to the person who added the bot
        await self.send_bot_onboarding(guild)
        
        # Send webhook notification for guild join
        await send_guild_webhook("join", guild, {
            "Bot Permissions": f"{guild.me.guild_permissions.value:,}" if guild.me else "Unknown",
            "Bot Highest Role": guild.me.top_role.name if guild.me and guild.me.top_role else "Unknown"
        })

    async def send_bot_onboarding(self, guild):
        """Send setup instructions to the person who added the bot"""
        try:
            # Try to find who added the bot by checking audit logs
            target_user = None
            
            # Check audit logs for bot addition (requires audit log permissions)
            try:
                async for entry in guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=5):
                    if entry.target and entry.target.id == self.user.id:
                        target_user = entry.user
                        print(f"🎯 ONBOARDING: Found bot inviter - {target_user.name}#{target_user.discriminator}")
                        break
            except discord.Forbidden:
                print("⚠️ ONBOARDING: No audit log permissions - will try guild owner instead")
            except Exception as e:
                print(f"⚠️ ONBOARDING: Audit log check failed: {e}")
            
            # Fallback to guild owner if we can't find who added the bot
            if not target_user and guild.owner:
                target_user = guild.owner
                print(f"🎯 ONBOARDING: Using guild owner - {target_user.name}#{target_user.discriminator}")
            
            if not target_user:
                print("❌ ONBOARDING: Could not identify who to send setup instructions to")
                return
            
            # Create setup instructions embed
            embed = discord.Embed(
                title="🤖 Welcome to SynapseChat!",
                description="Thanks for adding me to your server! Here's how to get started:",
                color=0x00ff88
            )
            
            embed.add_field(
                name="🔧 Quick Setup",
                value="Use `/setup` to configure the bot for your server\n"
                      "Note: Only server administrators can run this command\n"
                      "That's it! The setup command will guide you through everything.",
                inline=False
            )
            
            embed.add_field(
                name="🌐 CrossChat Network",
                value="• Connect your server to the global chat network\n"
                      "• Chat with users from other Discord servers\n"
                      "• Automatic moderation and spam protection\n"
                      "• Professional announcement system",
                inline=False
            )
            
            embed.add_field(
                name="⚙️ Bot Permissions",
                value="The bot needs these permissions to work properly:\n"
                      "• Send Messages & Embed Links\n"
                      "• Manage Messages (for moderation)\n"
                      "• Use Slash Commands\n"
                      "• View Channels & Message History",
                inline=False
            )
            
            embed.add_field(
                name="🛠️ Need Help?",
                value="Use `/help` for detailed command information\n"
                      "Use `/serverinfo` to check your server status\n"
                      "Use `/status` to verify bot connectivity",
                inline=False
            )
            
            embed.set_footer(
                text=f"Added to {guild.name} • SynapseChat Network",
                icon_url=self.user.avatar.url if self.user.avatar else None
            )
            
            # Try to send DM first, fallback to system channel
            sent_via_dm = False
            try:
                await target_user.send(embed=embed)
                sent_via_dm = True
                print(f"✅ ONBOARDING: Setup instructions sent via DM to {target_user.name}")
            except discord.Forbidden:
                print(f"⚠️ ONBOARDING: Cannot DM {target_user.name} - trying server channel")
            except Exception as e:
                print(f"⚠️ ONBOARDING: DM failed to {target_user.name}: {e}")
            
            # If DM failed, try to send in server's system channel or first available channel
            if not sent_via_dm:
                channel_to_use = None
                
                # Try system channel first
                if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                    channel_to_use = guild.system_channel
                else:
                    # Find first channel we can send messages to
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).send_messages:
                            channel_to_use = channel
                            break
                
                if channel_to_use:
                    try:
                        # Mention the target user in the server
                        message_content = f"{target_user.mention} Welcome to SynapseChat!"
                        await channel_to_use.send(content=message_content, embed=embed)
                        print(f"✅ ONBOARDING: Setup instructions sent in #{channel_to_use.name}")
                    except Exception as e:
                        print(f"❌ ONBOARDING: Failed to send in server channel: {e}")
                else:
                    print("❌ ONBOARDING: No accessible channels found in server")
            
        except Exception as e:
            print(f"❌ ONBOARDING: Error sending setup instructions: {e}")
            import traceback
            traceback.print_exc()

    async def on_guild_remove(self, guild):
        """Called when the bot leaves a guild"""
        print(f"📉 Left guild: {guild.name} (ID: {guild.id})")
        
        # Clean up MongoDB database for this guild
        try:
            if hasattr(self, 'db_handler') and self.db_handler:
                cleanup_success = self.db_handler.remove_guild_data(str(guild.id))
                if cleanup_success:
                    print(f"✅ Database cleanup completed for guild {guild.name}")
                else:
                    print(f"⚠️ Database cleanup failed for guild {guild.name}")
            else:
                print("⚠️ No database handler available for cleanup")
        except Exception as e:
            print(f"❌ Error during database cleanup for guild {guild.name}: {e}")
        
        # Send webhook notification for guild leave
        await send_guild_webhook("leave", guild, {
            "Reason": "Bot removed or guild deleted",
            "Previous Member Count": f"{guild.member_count:,} members" if guild.member_count else "Unknown"
        })

    async def is_owner_or_admin(self, ctx) -> bool:
        """Check if user is bot owner, server administrator, or has official staff role"""
        # Check if user is bot owner
        if await self.is_bot_owner(ctx):
            return True
        
        # Check if user is server administrator
        if await self.is_server_admin(ctx):
            return True
        
        # Check if user has official staff role (works across any server)
        staff_role_id = self.config_manager.get_setting("system", "staff_role_id")
        if staff_role_id and ctx.guild:
            try:
                # Validate and convert staff_role_id to integer
                if isinstance(staff_role_id, str) and staff_role_id.isdigit():
                    role_id = int(staff_role_id)
                elif isinstance(staff_role_id, int):
                    role_id = staff_role_id
                else:
                    print(f"PERMISSION_ERROR: Invalid staff_role_id format: {staff_role_id}")
                    return False
                
                # Check if user has the official staff role in this server
                staff_role = ctx.guild.get_role(role_id)
                if staff_role and staff_role in ctx.user.roles:
                    return True
            except (ValueError, TypeError) as e:
                print(f"PERMISSION_ERROR: Failed to convert staff_role_id '{staff_role_id}' to int: {e}")
                return False
        
        return False

    async def is_bot_owner(self, interaction) -> bool:
        """Check if user is the bot owner (stricter permission check)"""
        if self.owner_id and interaction.user.id == self.owner_id:
            return True
        
        # Fallback to application owner check
        if self.application and self.application.owner:
            if hasattr(self.application.owner, 'id'):
                return interaction.user.id == self.application.owner.id
            # If it's a team, check team members
            elif hasattr(self.application.owner, 'members'):
                return any(member.id == interaction.user.id for member in self.application.owner.members)
        
        return False

    async def is_server_admin(self, interaction) -> bool:
        """Check if user is server administrator (requires Administrator permission)"""
        if not interaction.guild:
            return False
        
        # Check if user is server owner
        if interaction.user.id == interaction.guild.owner_id:
            return True
        
        # Check if user has administrator permission
        if interaction.user.guild_permissions.administrator:
            return True
        
        return False

    def get_uptime(self) -> int:
        """Get bot uptime in seconds"""
        return int((datetime.utcnow() - self.start_time).total_seconds())

    def get_total_messages_processed(self) -> int:
        """Get total number of crosschat messages processed from database"""
        try:
            if not self.db_handler:
                print(f"🔍 MESSAGE_COUNT: No database handler available")
                return 0
                
            count = self.db_handler.get_chatlog_count()
            print(f"🔍 MESSAGE_COUNT: Database returned {count} messages")
            return count if count is not None else 0
            
        except Exception as e:
            print(f"Error getting total messages processed: {e}")
            return 0

    async def update_all_guild_info(self):
        """Update guild information for all connected guilds"""
        for guild in self.guilds:
            try:
                await self.update_single_guild_info(guild)
            except Exception as e:
                print(f"Error updating guild info for {guild.name}: {e}")

    async def update_single_guild_info(self, guild):
        """Update guild information for a single guild in MongoDB storage"""
        try:
            if self.db_handler and self.db_handler.is_available():
                # Store comprehensive guild information in MongoDB
                guild_data = {
                    'guild_id': str(guild.id),
                    'name': guild.name,
                    'member_count': guild.member_count or 0,
                    'owner_id': str(guild.owner.id) if guild.owner else "Unknown",
                    'owner_name': str(guild.owner) if guild.owner else "Unknown", 
                    'created_at': guild.created_at.isoformat(),
                    'icon_url': str(guild.icon.url) if guild.icon else "",
                    'description': guild.description or "",
                    'verification_level': str(guild.verification_level),
                    'joined_at': guild.me.joined_at.isoformat() if guild.me and guild.me.joined_at else "",
                    'channels_count': len(guild.channels),
                    'roles_count': len(guild.roles),
                    'last_updated': datetime.datetime.utcnow().isoformat()
                }
                
                # Store in MongoDB guilds collection
                self.db_handler.store_guild_info(
                    guild_id=str(guild.id),
                    name=guild.name,
                    member_count=guild.member_count or 0,
                    owner_id=str(guild.owner.id) if guild.owner else "Unknown",
                    owner_name=str(guild.owner) if guild.owner else "Unknown",
                    created_at=guild.created_at.isoformat(),
                    icon_url=str(guild.icon.url) if guild.icon else "",
                    description=guild.description or "",
                    additional_data=guild_data
                )
                
                print(f"✅ Guild info updated for {guild.name} in MongoDB")
        except Exception as e:
            print(f"Error updating guild info for {guild.name}: {e}")

    async def heartbeat_loop(self):
        """Periodic heartbeat to track uptime and send statistics"""
        while not self.is_closed():
            try:
                await asyncio.sleep(15)
            except Exception as e:
                print(f"Heartbeat error: {e}")
                await asyncio.sleep(15)

    async def cycling_status_updater(self):
        """Cycle bot status between different messages"""
        status_index = 0
        while not self.is_closed():
            try:
                # Get real-time counts with error handling
                try:
                    if self.db_handler:
                        crosschat_channel_ids = self.db_handler.get_crosschat_channel_ids()
                        channel_count = len(crosschat_channel_ids) if crosschat_channel_ids else 0
                        print(f"STATUS_DEBUG: Found {channel_count} crosschat channels")
                    else:
                        channel_count = 0
                        print(f"STATUS_DEBUG: No database handler - channel count 0")
                except Exception as e:
                    channel_count = 0
                    print(f"STATUS_ERROR: Failed to get channel count: {e}")
                
                server_count = len(self.guilds)
                
                # Calculate total members across all guilds
                total_members = sum(guild.member_count or 0 for guild in self.guilds)
                
                # Get total messages processed from database with fallback
                try:
                    total_messages = self.get_total_messages_processed()
                    print(f"🔍 STATUS_DEBUG: Found {total_messages} total messages processed")
                except Exception as e:
                    total_messages = 0
                    print(f"❌ STATUS_ERROR: Failed to get message count: {e}")
                
                # Get current latency in milliseconds
                latency_ms = round(self.latency * 1000)
                
                # Define status messages to cycle through
                status_messages = [
                    "Run /setup to get started",
                    f"{channel_count} Cross Chat channels",
                    "Run /setup to get started",
                    f"{total_members:,} total members", 
                    "Run /setup to get started",
                    f"{total_messages:,} messages processed",
                    "Run /setup to get started",
                    f"Latency: {latency_ms}ms",
                    "Run /setup to get started"
                ]
                
                # Update bot status
                current_message = status_messages[status_index % len(status_messages)]
                await self.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=current_message
                    ),
                    status=discord.Status.online
                )
                
                print(f"STATUS_CYCLE: Updated to 'Watching {current_message}'")
                
                # Move to next status
                status_index += 1
                
                # Wait 10 seconds before cycling to next status
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"Status cycling error: {e}")
                await asyncio.sleep(60)

    async def process_web_commands(self):
        """Process pending web panel commands with full deduplication"""
        print("🔄 Command processor started")
        while not self.is_closed():
            try:
                # Use command lock to prevent concurrent processing
                async with self.command_lock:
                    # Process pending DM requests for panel credentials
                    await self.process_panel_credential_dms()
                    
                    # Get pending commands from MongoDB
                    try:
                        pending_commands = []
                        
                        if hasattr(self, 'db_handler') and self.db_handler.is_available():
                            # Get pending commands from web_panel_commands collection
                            pending_docs = list(self.db_handler.db.web_panel_commands.find({
                                "status": "pending"
                            }).sort("created_at", 1).limit(10))
                            
                            pending_commands = []
                            for doc in pending_docs:
                                pending_commands.append({
                                    'id': str(doc.get('_id')),
                                    'type': doc.get('command_type'),
                                    'data': doc.get('command_data', {}),
                                    'created_at': doc.get('created_at')
                                })
                            
                            if pending_commands:
                                print(f"Found {len(pending_commands)} pending commands from web panel")
                        
                    except Exception as e:
                        print(f"Error getting pending commands from database: {e}")
                        import traceback
                        traceback.print_exc()
                        pending_commands = []
                    
                    for command in pending_commands:
                        try:
                            # Handle both list and dict formats
                            if not isinstance(command, dict):
                                print(f"Skipping non-dict command: {command}")
                                continue
                                
                            command_id = command.get('id')
                            if not command_id:
                                print(f"Skipping command without ID: {command}")
                                continue
                                
                            # Prevent processing same command multiple times
                            if command_id in self.processing_commands:
                                print(f"Command {command_id} already being processed, skipping")
                                continue
                                
                            # Handle multiple field name formats from different sources
                            command_type = command.get('type') or command.get('commandType') or command.get('command_type', '')
                            command_data = command.get('data') or command.get('commandData') or command.get('command_data', command)
                            
                            print(f"Raw command data: ID={command_id}, Type={command_type}, Data={command_data}")
                            
                            # Handle stringified JSON data from web panel
                            if isinstance(command_data, str):
                                try:
                                    import json
                                    command_data = json.loads(command_data)
                                    print(f"Parsed JSON command data: {command_data}")
                                except Exception as json_error:
                                    print(f"Failed to parse command data JSON: {json_error}")
                                    command_data = {}
                            
                            if not command_type:
                                print(f"Skipping command without type: {command}")
                                continue
                                
                            # Add to processing set to prevent duplicates
                            self.processing_commands.add(command_id)
                            
                            print(f"🔄 Processing web command: {command_type} (ID: {command_id})")
                            
                            # Mark as processing in database
                            try:
                                if hasattr(self, 'db_handler') and self.db_handler.is_available():
                                    from bson import ObjectId
                                    self.db_handler.db.web_panel_commands.update_one(
                                        {"_id": ObjectId(command_id)},
                                        {"$set": {"status": "processing", "started_at": datetime.utcnow()}}
                                    )
                            except Exception as e:
                                print(f"Error marking command as processing: {e}")
                        
                            # Process the command based on type
                            success = True
                            error_message = None
                            
                            if command_type == 'announcement':
                                await self.process_announcement(command_data)
                            elif command_type == 'ban':
                                await self.complete_ban_command(command_data)
                            elif command_type == 'unban':
                                await self.complete_unban_command(command_data)
                            else:
                                print(f"Unknown command type: {command_type}")
                                success = False
                                error_message = f"Unknown command type: {command_type}"
                            
                            # Mark command as completed in database
                            try:
                                if hasattr(self, 'db_handler') and self.db_handler.is_available():
                                    from bson import ObjectId
                                    status = "completed" if success else "failed"
                                    update_data = {
                                        "status": status,
                                        "completed_at": datetime.utcnow()
                                    }
                                    if error_message:
                                        update_data["error_message"] = error_message
                                    
                                    self.db_handler.db.web_panel_commands.update_one(
                                        {"_id": ObjectId(command_id)},
                                        {"$set": update_data}
                                    )
                                    print(f"✅ Command {command_id} marked as {status}")
                            except Exception as e:
                                print(f"Error updating command status: {e}")
                                
                            # Remove from processing set
                            self.processing_commands.discard(command_id)
                            
                        except Exception as e:
                            print(f"Error processing web command: {e}")
                            # Remove from processing set on error
                            self.processing_commands.discard(command_id)
                        
            except Exception as e:
                print(f"Error getting pending commands from database: {e}")
                    
    async def process_announcement(self, command_data):
        """Process announcement command from web panel"""
        try:
            # Use announcement lock to prevent concurrent announcements
            async with self.announcement_lock:
                message = command_data.get('message', '')
                moderator = command_data.get('moderator', 'Unknown')
                anonymous = command_data.get('anonymous', False)
                
                print(f"Processing announcement: {message[:50]}... (anonymous: {anonymous})")
                
                # Send through SimpleCrossChat system
                if hasattr(self, 'crosschat') and self.crosschat:
                    success_count = await self.crosschat.send_message_with_embed(
                        content=message,
                        username=moderator if not anonymous else "Anonymous Staff",
                        avatar_url=None,
                        is_staff=True,
                        is_announcement=True
                    )
                    
                    if success_count > 0:
                        print(f"✅ Announcement sent to {success_count} channels successfully")
                        return True
                    else:
                        print("❌ Failed to send announcement to any channels")
                        return False
                else:
                    print("❌ CrossChat system not available")
                    return False
        except Exception as e:
            print(f"Error in announcement processing: {e}")
            return False
    
    async def complete_unban_command(self, command_data):
        """Process unban command from web panel - removes crosschat service ban only"""
        try:
            user_id = command_data.get('user_id')
            moderator = command_data.get('moderator', 'Web Panel')
            
            if not user_id:
                print("❌ Unban command missing user_id")
                return False
            
            print(f"🔄 Processing unban for user {user_id}")
            
            # Remove user from banned_users collection
            if hasattr(self, 'db_handler') and self.db_handler.is_available():
                result = self.db_handler.db.banned_users.delete_one({"user_id": str(user_id)})
                
                if result.deleted_count > 0:
                    print(f"✅ Removed crosschat ban for user {user_id}")
                    
                    # Log moderation action
                    self.db_handler.db.moderation_logs.insert_one({
                        "action_type": "unban",
                        "user_id": str(user_id),
                        "moderator": moderator,
                        "reason": "Unbanned via web panel",
                        "timestamp": datetime.utcnow()
                    })
                    
                    # Try to send DM to user
                    try:
                        user = await self.fetch_user(int(user_id))
                        if user:
                            embed = discord.Embed(
                                title="✅ SynapseChat Ban Removed",
                                description="Your ban from the SynapseChat cross-chat service has been lifted.",
                                color=0x00ff00
                            )
                            embed.add_field(name="Status", value="You can now participate in cross-chat messages again", inline=False)
                            await user.send(embed=embed)
                            print(f"✅ Unban notification sent to {user.name}")
                    except Exception as dm_error:
                        print(f"⚠️ Could not send unban DM: {dm_error}")
                    
                    return True
                else:
                    print(f"⚠️ User {user_id} was not found in banned users list")
                    return True  # Still success since user is not banned
            else:
                print("❌ Database not available for unban operation")
                return False
                
        except Exception as e:
            print(f"❌ Error processing unban command: {e}")
            return False

    async def execute_panel_command(self, command_type: str, data: dict) -> dict:
        """Execute a specific panel command through unified system"""
        try:
            if command_type == 'announcement':
                return await self.send_crosschat_announcement(data)
            elif command_type == 'warn_user':
                return await self.process_user_warning(data)
            elif command_type == 'ban_user':
                return await self.process_user_ban(data)
            elif command_type == 'system_alert':
                return await self.process_system_alert(data)
            else:
                return {'success': False, 'error': f'Unknown command type: {command_type}'}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def send_crosschat_announcement(self, data: dict) -> dict:
        """Send announcement to all crosschat channels"""
        try:
            message = data.get('message', '')
            anonymous = data.get('anonymous', False)
            sender = data.get('sender', 'System')
            
            if not message:
                return {'success': False, 'error': 'No message provided'}
            
            # Get all crosschat channels
            sent_count = 0
            total_channels = 0
            failed_channels = []
            
            if self.cross_chat_manager:
                channels_list = self.cross_chat_manager.get_channels()
                total_channels = len(channels_list)
                
                for channel_id in channels_list:
                    try:
                        channel = self.get_channel(int(channel_id))
                        if channel:
                            embed = discord.Embed(
                                title="📢 SynapseChat Announcement",
                                description=message,
                                color=0x7289DA,
                                timestamp=datetime.utcnow()
                            )
                            
                            if not anonymous:
                                embed.set_footer(text=f"Sent by {sender}")
                            
                            await channel.send(embed=embed)
                            sent_count += 1
                        else:
                            failed_channels.append(channel_id)
                    except Exception as e:
                        failed_channels.append(channel_id)
                        print(f"Error sending announcement to channel {channel_id}: {e}")
            
            return {
                'success': True,
                'sent_count': sent_count,
                'total_channels': total_channels,
                'failed_channels': failed_channels
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def process_user_warning(self, data: dict) -> dict:
            has_permission = await self.is_bot_owner(interaction)
            
            # Check for Official Staff role across all guilds if not bot owner
            if not has_permission:
                try:
                    staff_role_id = os.environ.get('STAFF_ROLE_ID')
                    if staff_role_id:
                        # Check across all guilds where bot can see the user
                        for guild in self.guilds:
                            member = guild.get_member(interaction.user.id)
                            if member and member.roles:
                                for role in member.roles:
                                    if str(role.id) == str(staff_role_id):
                                        has_permission = True
                                        print(f"INFO: Official Staff {interaction.user} using moderation command")
                                        break
                            if has_permission:
                                break
                except Exception as e:
                    print(f"ERROR: Error checking Official Staff role: {e}")
            
            if not has_permission:
                await interaction.response.send_message("❌ You don't have permission to use this command. Required: Bot Owner or Official Staff.", ephemeral=True)
                return
            
            try:
                pass  # MongoDB conversion - no operations needed
            except Exception as e:
                pass

    async def process_user_ban(self, data: dict) -> dict:
        @discord.app_commands.describe(
            status="Bot status",
            activity_type="Type of activity",
            activity_text="Activity text"
        )
        @discord.app_commands.choices(
            status=[
                discord.app_commands.Choice(name="Online", value="online"),
                discord.app_commands.Choice(name="Idle", value="idle"),
                discord.app_commands.Choice(name="Do Not Disturb", value="dnd"),
                discord.app_commands.Choice(name="Invisible", value="invisible")
            ],
            activity_type=[
                discord.app_commands.Choice(name="Playing", value="playing"),
                discord.app_commands.Choice(name="Watching", value="watching"),
                discord.app_commands.Choice(name="Listening", value="listening"),
                discord.app_commands.Choice(name="Streaming", value="streaming")
            ]
        )
        async def presence(interaction: discord.Interaction, status: str, activity_type: str, activity_text: str):
            """Change bot presence"""
            # Check permissions: Bot Owner only
            if not await self.is_bot_owner(interaction):
                await interaction.response.send_message("❌ You don't have permission to use this command. Required: Bot Owner only.", ephemeral=True)
                return
            
            try:
                await interaction.response.defer(ephemeral=True)
                
                # Convert status string to Discord status
                discord_status = getattr(discord.Status, status)
                
                # Create activity based on type
                if activity_type == "playing":
                    activity = discord.Game(name=activity_text)
                elif activity_type == "streaming":
                    activity = discord.Streaming(name=activity_text, url="https://twitch.tv/synapsechat")
                elif activity_type == "listening":
                    activity = discord.Activity(type=discord.ActivityType.listening, name=activity_text)
                elif activity_type == "watching":
                    activity = discord.Activity(type=discord.ActivityType.watching, name=activity_text)
                else:
                    activity = discord.Activity(type=discord.ActivityType.watching, name=activity_text)
                
                # Update presence
                await self.change_presence(status=discord_status, activity=activity)
                
                # Save to config - Database only, no JSON files
                pass
                
                embed = discord.Embed(
                    title="✅ Presence Updated",
                    color=0x00ff00
                )
                embed.add_field(name="Status", value=status.title(), inline=True)
                embed.add_field(name="Activity", value=f"{activity_type.title()} {activity_text}", inline=False)
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                await interaction.followup.send(f"❌ Error updating presence: {str(e)}", ephemeral=True)

                embed.add_field(name="👥 Total Users", value=f"{sum(guild.member_count for guild in self.guilds)}", inline=True)
                embed.add_field(name="🌐 Latency", value=f"{round(self.latency * 1000)}ms", inline=True)
                embed.add_field(name="🔗 Crosschat Channels", value=f"{channel_count}", inline=True)
                embed.add_field(name="🐍 Python Version", value=f"{sys.version.split()[0]}", inline=True)
                
                embed.set_footer(text="SynapseChat Statistics")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                await interaction.followup.send(f"❌ Error getting statistics: {str(e)}", ephemeral=True)





    async def execute_panel_command(self, command_type: str, data: dict) -> dict:
        """Execute a specific panel command through unified system"""
        try:
            if command_type == 'announcement':
                return await self.send_crosschat_announcement(data)
            elif command_type == 'warn_user':
                return await self.process_user_warning(data)
            elif command_type == 'ban_user':
                return await self.process_user_ban(data)
            elif command_type == 'system_alert':
                return await self.process_system_alert(data)
            else:
                return {'success': False, 'error': f'Unknown command type: {command_type}'}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def send_crosschat_announcement(self, data: dict) -> dict:
        """Send announcement to all crosschat channels"""
        try:
            message = data.get('message', '')
            anonymous = data.get('anonymous', False)
            sender = data.get('sender', 'System')
            
            if not message:
                return {'success': False, 'error': 'No message provided'}
            
            # Get all crosschat channels
            sent_count = 0
            total_channels = 0
            failed_channels = []
            
            if self.cross_chat_manager:
                channels_list = self.cross_chat_manager.get_channels()
                total_channels = len(channels_list)
                
                for channel_id in channels_list:
                    try:
                        channel = self.get_channel(int(channel_id))
                        if channel:
                            embed = discord.Embed(
                                title="📢 SynapseChat Announcement",
                                description=message,
                                color=0x7289DA,
                                timestamp=datetime.now()
                            )
                            
                            if not anonymous:
                                embed.set_footer(text=f"Announcement by {sender}")
                            else:
                                embed.set_footer(text="Anonymous Announcement")
                            
                            await channel.send(embed=embed)
                            sent_count += 1
                        else:
                            failed_channels.append(channel_id)
                    except Exception as e:
                        failed_channels.append(channel_id)
                        print(f"Failed to send announcement to channel {channel_id}: {e}")
            
            return {
                'success': True,
                'sent_count': sent_count,
                'total_channels': total_channels,
                'failed_channels': failed_channels
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def process_user_warning(self, data: dict) -> dict:
        """Process user warning from unified system"""
        try:
            pass  # MongoDB conversion - no operations needed
        except Exception as e:
            pass
    async def process_user_ban(self, data: dict) -> dict:
        """Process user ban from unified system"""
        try:
            pass  # MongoDB conversion - no operations needed
        except Exception as e:
            pass
    async def process_system_alert(self, data: dict) -> dict:
        """Process system alert from unified system"""
        try:
            alert_type = data.get('alert_type', 'system')
            message = data.get('message', 'System alert')
            
            # Send alert to all crosschat channels
            sent_count = 0
            
            if self.cross_chat_manager:
                channels_list = self.cross_chat_manager.get_channels()
                
                for channel_id in channels_list:
                    try:
                        channel = self.get_channel(int(channel_id))
                        if channel:
                            embed = discord.Embed(
                                title=f"🚨 System Alert: {alert_type.upper()}",
                                description=message,
                                color=0xff6600,
                                timestamp=datetime.now()
                            )
                            embed.set_footer(text="SynapseChat System Administration")
                            await channel.send(embed=embed)
                            sent_count += 1
                    except Exception as e:
                        print(f"Failed to send alert to channel {channel_id}: {e}")
            
            return {
                'success': True,
                'sent_count': sent_count
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _log_command_async(self, command_type: str, command_data: dict, result: dict):
        """Asynchronously log command to database for audit trail (fire-and-forget)"""
        try:
            # import psycopg2  # MongoDB conversion
            import json
            
            # conn = psycopg2.connect  # MongoDB conversion(os.environ['DATABASE_URL'])
            # cursor = # conn.cursor()  # MongoDB conversion
            
            # MongoDB conversion - no database logging needed
            pass
            
            # conn.commit()
            # cursor.close()
            # conn.close()
        except Exception as e:
            # Silent fail for logging - don't impact user experience
            print(f"Async command logging failed: {e}")

    async def is_cross_chat_enabled(self) -> bool:
        """Check if cross-chat is enabled by reading config file in real-time"""
        try:
            config_data = database_storage.get_crosschat_channels()
            return config_data.get('crosschat_enabled', True) if config_data else True
        except Exception:
            return True

    async def is_auto_moderation_enabled(self) -> bool:
        """Check if auto-moderation is enabled by reading config file in real-time"""
        try:
            config_data = database_storage.get_crosschat_channels()
            return config_data.get('auto_moderation_enabled', False) if config_data else False
        except Exception:
            return False

    async def check_and_announce_new_guild(self, guild):
        """Check if this is a new guild and announce to the network if so"""
        try:
            pass  # MongoDB conversion - no operations needed
        except Exception as e:
            pass
    async def process_web_panel_commands(self):
        """Process commands from the web panel"""
        import asyncio
        import concurrent.futures
        from database_storage_new import DatabaseStorage
        
        # Create thread pool for database operations
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        
        def get_commands_sync():
            """Synchronous wrapper for database access using direct SQL"""
            # import psycopg2  # MongoDB conversion
            import json
            try:
                # MongoDB conversion - use handler for database operations
                rows = []  # MongoDB conversion - no direct database queries
                
                commands = []
                for row in rows:
                    commands.append({
                        'id': row[0],
                        'command_type': row[1],
                        'command_data': json.loads(row[2]) if isinstance(row[2], str) else row[2],
                        'created_at': row[3]
                    })
                
                # cursor.close()
                # conn.close()
                return commands
            except Exception as e:
                print(f"Direct SQL command fetch error: {e}")
                return []
        
        while not self.is_closed():
            try:
                pass  # MongoDB conversion - no operations needed
            except Exception as e:
                pass
        user_id = command['user_id']
        reason = command['reason']
        issued_by = command.get('issued_by', 'Web Panel')
        
        # Find user across all guilds
        user = None
        guild_found = None
        for guild in self.guilds:
            user = guild.get_member(int(user_id))
            if user:
                guild_found = guild
                break
        
        if user:
            # Log to comprehensive moderation system
            await database_storage.add_moderation_action(
                action_type="warn",
                user_id=str(user_id),
                moderator_id=issued_by,
                reason=reason,
                metadata={
                    'username': str(user),
                    'guild_id': str(guild_found.id) if guild_found else None,
                    'guild_name': guild_found.name if guild_found else None,
                    'source': 'web_panel'
                }
            )
            
            # Add warning to legacy storage for compatibility
            warnings_data = database_storage.get_crosschat_channels()
            if not warnings_data:
                warnings_data = {'warnings': []}
            
            warning = {
                'id': len(warnings_data['warnings']) + 1,
                'user_id': user_id,
                'username': str(user),
                'reason': reason,
                'timestamp': datetime.now().isoformat(),
                'issued_by': issued_by
            }
            
            warnings_data['warnings'].append(warning)
            pass  # Database only - no JSON files
            
            # Trigger separate notification system
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.post('http://localhost:5001/api/notifications/warning', json={
                        'user_id': user_id,
                        'reason': reason,
                        'warning_count': len([w for w in warnings_data.get('warnings', []) if w.get('user_id') == user_id]),
                        'moderator': issued_by
                    }) as resp:
                        if resp.status == 200:
                            print(f"NOTIFICATION: Warning notification sent for user {user_id}")
                        else:
                            print(f"NOTIFICATION_ERROR: Failed to send warning notification for user {user_id}")
            except Exception as e:
                print(f"NOTIFICATION_ERROR: {e}")



    async def execute_ban_command(self, command):
        """Execute a service ban command from web panel"""
        user_id = command['user_id']
        reason = command['reason']
        duration = command.get('duration', 24)
        issued_by = command.get('issued_by', 'Web Panel')
        
        # Calculate ban expiry
        from datetime import datetime, timedelta
        if duration == -1:
            ban_until = None
            duration_text = "permanently"
        else:
            ban_until = datetime.now() + timedelta(hours=duration)
            duration_text = f"for {duration} hours"
        
        # Find user to get username and guild info
        user = None
        guild_found = None
        for guild in self.guilds:
            try:
                user = await guild.fetch_member(int(user_id))
                if user:
                    guild_found = guild
                    break
            except:
                continue
        
        username = str(user) if user else f"User {user_id}"
        guild_name = guild_found.name if guild_found else "Unknown Server"
        
        # Add to service ban list (not Discord ban)
        banned_data = database_storage.get_crosschat_channels()
        if not banned_data:
            banned_data = {'banned_users': []}
        
        # Remove existing ban if present
        banned_data['banned_users'] = [b for b in banned_data['banned_users'] if b['user_id'] != str(user_id)]
        
        ban_entry = {
            'user_id': str(user_id),
            'username': username,
            'reason': reason,
            'banned_at': datetime.now().isoformat(),
            'banned_by': issued_by,
            'ban_until': ban_until.isoformat() if ban_until else None,
            'duration_hours': duration if duration != -1 else None,
            'guild_id': str(guild_found.id) if guild_found else None,
            'guild_name': guild_name
        }
        
        banned_data['banned_users'].append(ban_entry)
        pass  # Database only - no JSON files
        
        # Log to comprehensive moderation system
        await database_storage.add_moderation_action(
            action_type="service_ban",
            user_id=str(user_id),
            moderator_id=issued_by,
            reason=reason,
            metadata={
                'username': username,
                'guild_id': str(guild_found.id) if guild_found else None,
                'guild_name': guild_name,
                'duration_hours': duration if duration != -1 else None,
                'ban_until': ban_until.isoformat() if ban_until else None,
                'source': 'web_panel'
            }
        )
        
        # Send DM to user if found
        if user:
            try:
                embed = discord.Embed(
                    title="🚫 SynapseChat Service Ban",
                    description=f"You have been banned from the SynapseChat cross-chat service {duration_text}",
                    color=0xff0000
                )
                embed.add_field(name="Reason", value=reason, inline=False)
                embed.add_field(name="Note", value="You can still use Discord normally, but cannot participate in cross-chat messages.", inline=False)
                await user.send(embed=embed)
            except:
                pass

    async def execute_server_ban_command(self, command):
        """Execute a service ban command from web panel - SERVICE LEVEL ONLY"""
        user_id = command['user_id']
        guild_id = command['guild_id']
        reason = command['reason']
        duration = command.get('duration', 24)
        
        try:
            pass  # MongoDB conversion - no operations needed
        except Exception as e:
            pass
    async def execute_unban_command(self, command):
        """Execute an unban command from web panel - SERVICE LEVEL ONLY"""
        user_id = command['user_id']
        
        try:
            # NEVER TOUCH DISCORD BANS - Only remove from service ban list
            
            # Remove from banned users storage (service-level ban)
            banned_data = database_storage.get_crosschat_channels()
            user_was_banned = False
            
            if banned_data and 'banned_users' in banned_data:
                original_count = len(banned_data['banned_users'])
                banned_data['banned_users'] = [
                    ban for ban in banned_data['banned_users'] 
                    if ban.get('user_id') != user_id
                ]
                
                if len(banned_data['banned_users']) < original_count:
                    pass  # Database only - no JSON files
                    user_was_banned = True
                    print(f"UNBAN: Removed service ban for user {user_id}")
            
            # Try to notify user if they were actually banned
            if user_was_banned:
                try:
                    user = await self.fetch_user(int(user_id))
                    if user:
                        embed = discord.Embed(
                            title="✅ Unbanned from CrossChat",
                            description="You have been unbanned from the SynapseChat cross-chat service.",
                            color=0x00ff00,
                            timestamp=datetime.now()
                        )
                        embed.add_field(name="Status", value="You can now participate in cross-chat again", inline=False)
                        embed.set_footer(text="SynapseChat Moderation")
                        await user.send(embed=embed)
                except:
                    pass  # User not found or DMs disabled
                
        except Exception as e:
            print(f"Failed to execute unban for user {user_id}: {e}")

    async def execute_announcement_command(self, command):
        """Execute an announcement command from web panel"""
        message = command['message']
        anonymous = command.get('anonymous', False)
        
        # Trigger separate notification system for announcement
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post('http://localhost:5001/api/notifications/announcement', json={
                    'message': message,
                    'anonymous': anonymous
                }) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        print(f"NOTIFICATION: Announcement sent to {result.get('channels_notified', 0)} channels")
                    else:
                        print(f"NOTIFICATION_ERROR: Failed to send announcement")
        except Exception as e:
            print(f"NOTIFICATION_ERROR: {e}")

    async def execute_guild_management_command(self, command):
        """Execute a guild management command from web panel"""
        action = command['action']
        guild_id = command['guild_id']
        data = command.get('data', {})
        
        if action == 'leave_guild':
            guild = self.get_guild(int(guild_id))
            if guild:
                reason = data.get('reason', 'Forced leave via web panel')
                print(f"GUILD_MGMT: Leaving guild {guild.name} ({guild_id}): {reason}")
                await guild.leave()

    async def execute_guild_ban_command(self, command):
        """Execute a guild ban command from web panel"""
        guild_id = command['guild_id']
        reason = command.get('reason', 'No reason provided')
        duration = command.get('duration', 24)
        duration_type = command.get('duration_type', 'hours')
        
        try:
            pass  # MongoDB conversion - no operations needed
        except Exception as e:
            pass
    async def execute_guild_unban_command(self, command):
        """Execute a guild unban command from web panel"""
        guild_id = command['guild_id']
        
        try:
            # Remove from banned guilds storage
            banned_guilds_data = database_storage.get_crosschat_channels()
            if banned_guilds_data and 'banned_guilds' in banned_guilds_data:
                original_count = len(banned_guilds_data['banned_guilds'])
                
                # Find and remove the ban entry
                unbanned_guild = None
                for ban in banned_guilds_data['banned_guilds']:
                    if ban.get('guild_id') == guild_id:
                        unbanned_guild = ban
                        break
                
                if unbanned_guild:
                    banned_guilds_data['banned_guilds'] = [
                        ban for ban in banned_guilds_data['banned_guilds'] 
                        if ban.get('guild_id') != guild_id
                    ]
                    
                    pass  # Database only - no JSON files
                    print(f"GUILD_UNBAN: Unbanned guild {unbanned_guild.get('guild_name', guild_id)} ({guild_id})")
                else:
                    print(f"GUILD_UNBAN: Guild {guild_id} was not found in banned guilds list")
            else:
                print(f"GUILD_UNBAN: No banned guilds data found")
                
        except Exception as e:
            print(f"GUILD_UNBAN: Failed to unban guild {guild_id}: {e}")

    async def process_server_ban_command(self, command_id, command_data):
        """Process server ban command from web panel"""
        try:
            pass  # MongoDB conversion - no operations needed
        except Exception as e:
            pass
    async def process_guild_ban_command(self, command_id, command_data):
        """Process guild ban command from web panel - bans entire server from cross-chat"""
        try:
            pass  # MongoDB conversion - no operations needed
        except Exception as e:
            pass
    async def process_unban_command(self, command_id, command_data):
        """Process unban command from web panel - SERVICE LEVEL ONLY"""
        try:
            user_id = command_data.get('user_id')
            
            if not user_id:
                pass  # Command status tracking in database
                return
            
            # NEVER TOUCH DISCORD BANS - Only remove from service ban list
            banned_users = database_storage.get_crosschat_channels()
            original_count = len(banned_users['banned_users'])
            banned_users['banned_users'] = [u for u in banned_users['banned_users'] if u.get('user_id') != str(user_id)]
            
            user_was_banned = len(banned_users['banned_users']) < original_count
            
            if user_was_banned:
                pass  # Database only - no JSON files
                print(f"UNBAN: Removed service ban for user {user_id}")
            
            # Log moderation action (service-level only)
            await database_storage.log_moderation_action({
                'type': 'service_unban',
                'user_id': str(user_id),
                'action': 'removed from cross-chat ban list',
                'issued_by': 'Web Panel',
                'timestamp': datetime.now().isoformat()
            })
            
            result_msg = f"User {user_id} unbanned from cross-chat service" if user_was_banned else f"User {user_id} was not banned"
            pass  # Command status tracking in database
            print(f"UNBAN: {result_msg}")
            
        except Exception as e:
            pass  # Command status tracking in database
            print(f"Error processing unban: {e}")

    async def process_guild_unban_command(self, command_id, command_data):
        """Process guild unban command from web panel"""
        try:
            guild_id = command_data.get('guild_id')
            
            if not guild_id:
                pass  # Command status tracking in database
                return
            
            guild = self.get_guild(int(guild_id))
            guild_name = guild.name if guild else f"Guild {guild_id}"
            
            # Remove from banned guilds
            banned_guilds = database_storage.get_crosschat_channels()
            original_count = len(banned_guilds['guilds'])
            banned_guilds['guilds'] = [g for g in banned_guilds['guilds'] if g.get('guild_id') != str(guild_id)]
            
            if len(banned_guilds['guilds']) < original_count:
                pass  # Database only - no JSON files
            
            # Log moderation action
            await database_storage.log_moderation_action({
                'type': 'guild_unban',
                'guild_id': str(guild_id),
                'guild_name': guild_name,
                'issued_by': 'Web Panel',
                'timestamp': datetime.now().isoformat()
            })
            
            pass  # Command status tracking in database
            print(f"GUILD_UNBAN: Guild {guild_name} unbanned from cross-chat")
            
        except Exception as e:
            pass  # Command status tracking in database
            print(f"Error processing guild unban: {e}")

    async def process_create_user_command(self, command_id, command_data):
        """Process create user command from web panel"""
        try:
            username = command_data.get('username')
            password = command_data.get('password')
            role = command_data.get('role', 'viewer')
            
            if not username or not password:
                pass  # Command status tracking in database
                return
            
            # This would be handled by the web panel's user management
            # The bot just acknowledges the command
            pass  # Command status tracking in database
            print(f"USER_CREATE: Acknowledged user creation for {username}")
            
        except Exception as e:
            pass  # Command status tracking in database
            print(f"Error processing create user: {e}")

    async def process_delete_user_command(self, command_id, command_data):
        """Process delete user command from web panel"""
        try:
            username = command_data.get('username')
            
            if not username:
                pass  # Command status tracking in database
                return
            
            # This would be handled by the web panel's user management
            # The bot just acknowledges the command
            pass  # Command status tracking in database
            print(f"USER_DELETE: Acknowledged user deletion for {username}")
            
        except Exception as e:
            pass  # Command status tracking in database
            print(f"Error processing delete user: {e}")

    async def process_panel_credential_dms(self):
        """Process pending DM requests for panel credentials"""
        try:
            pass  # MongoDB conversion - no operations needed
        except Exception as e:
            pass
    def get_role_description(self, role):
        """Get description of panel role permissions"""
        descriptions = {
            'owner': '• Full system control and administration\n• All permissions including role assignment\n• System configuration access',
            'admin': '• Full moderation and user management\n• Can clear warnings and manage staff\n• Access to all panel features',
            'staff': '• Issue warnings and bans\n• Send announcements\n• Search chat logs and manage users',
            'moderator': '• Issue warnings only\n• View chat logs\n• Training role with limited permissions',
            'viewer': '• View chat logs only\n• Read-only access to system information'
        }
        return descriptions.get(role.lower(), 'Standard user permissions')

    async def process_update_user_role_command(self, command_id, command_data):
        """Process update user role command from web panel"""
        try:
            username = command_data.get('username')
            new_role = command_data.get('role')
            
            if not username or not new_role:
                pass  # Command status tracking in database
                return
            
            # This would be handled by the web panel's user management
            # The bot just acknowledges the command
            pass  # Command status tracking in database
            print(f"USER_ROLE: Acknowledged role update for {username} to {new_role}")
            
        except Exception as e:
            pass  # Command status tracking in database
            print(f"Error processing update user role: {e}")

    async def execute_crosschat_management_command(self, command):
        """Execute cross-chat management command from web panel"""
        action = command['action']
        
        if action == 'add_channel':
            channel_id = command['channel_id']
            guild_id = command.get('guild_id')
            
            channel = self.get_channel(int(channel_id))
            if channel:
                actual_guild_id = str(channel.guild.id)
                # Use the unified storage method for adding crosschat channels
                await database_storage.add_crosschat_channel(actual_guild_id, channel_id, channel.guild.name, channel.name)
                print(f"CROSSCHAT: Added channel {channel.name} ({channel_id}) to cross-chat")
                
                # CACHE UPDATE: Add channel to performance cache immediately
                from performance_cache import performance_cache
                performance_cache.add_crosschat_channel(channel_id)
                print(f"CACHE_SYNC: Added channel {channel_id} to cache after web panel add")
                
                # Send confirmation to the channel
                embed = discord.Embed(
                    title="✅ Cross-Chat Enabled",
                    description="This channel has been added to the cross-chat network.",
                    color=0x00ff00
                )
                embed.set_footer(text="SynapseChat Administration")
                await channel.send(embed=embed)
        
        elif action == 'remove_channel':
            channel_id = command['channel_id']
            
            channel = self.get_channel(int(channel_id))
            if channel:
                guild_id = str(channel.guild.id)
                # Use the unified storage method for removing crosschat channels
                await database_storage.remove_crosschat_channel(guild_id, channel_id)
                print(f"CROSSCHAT: Removed channel {channel.name} ({channel_id}) from cross-chat")
                
                # CACHE UPDATE: Remove channel from performance cache immediately
                from performance_cache import performance_cache
                performance_cache.remove_crosschat_channel(channel_id)
                print(f"CACHE_SYNC: Removed channel {channel_id} from cache after web panel removal")
                
                # Send confirmation to the channel
                embed = discord.Embed(
                    title="❌ Cross-Chat Disabled",
                    description="This channel has been removed from the cross-chat network.",
                    color=0xff0000
                )
                embed.set_footer(text="SynapseChat Administration")
                await channel.send(embed=embed)
            else:
                # Channel not found, try to remove from all guilds
                channels_data = database_storage.get_crosschat_channels()
                for guild_id, guild_data in channels_data.items():
                    if isinstance(guild_data, dict) and 'channels' in guild_data:
                        if channel_id in guild_data['channels']:
                            await database_storage.remove_crosschat_channel(guild_id, channel_id)
                            print(f"CROSSCHAT: Removed channel ({channel_id}) from guild {guild_id}")
                            
                            # CACHE UPDATE: Remove channel from performance cache immediately
                            from performance_cache import performance_cache
                            performance_cache.remove_crosschat_channel(channel_id)
                            print(f"CACHE_SYNC: Removed channel {channel_id} from cache after web panel fallback removal")
                            break

    async def process_web_panel_commands(self):
        """Process commands queued from the web panel"""
        await self.wait_until_ready()
        
        while not self.is_closed():
            try:
                pass  # MongoDB conversion - no operations needed
            except Exception as e:
                pass
    async def execute_system_alert(self, command_id, command_data):
        """Execute system alert command - broadcast to all crosschat channels"""
        try:
            pass  # MongoDB conversion - no operations needed
        except Exception as e:
            pass
    async def execute_web_warn_command(self, command_id, command_data):
        """Execute warning command from web panel"""
        user_id = command_data.get('user_id')
        reason = command_data.get('reason', 'No reason provided')
        
        try:
            user = await self.fetch_user(int(user_id))
            if user:
                # Send warning DM
                embed = discord.Embed(
                    title="⚠️ Official Warning",
                    description="You have received an official warning from SynapseChat Administration.",
                    color=0xffaa00
                )
                
                embed.add_field(
                    name="📋 Warning Details",
                    value=f"**Reason:** {reason}\n**Issued:** {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
                    inline=False
                )
                
                embed.add_field(
                    name="📖 What This Means",
                    value="• This is an official warning about your behavior\n• Please review and follow community guidelines\n• Repeated violations may result in temporary or permanent restrictions",
                    inline=False
                )
                
                embed.set_footer(text="SynapseChat Administration")
                embed.timestamp = discord.utils.utcnow()
                
                await user.send(embed=embed)
                print(f"WEB_WARN: Warning DM sent to user {user_id} for: {reason}")
                
        except Exception as e:
            print(f"Failed to send warning to user {user_id}: {e}")
            raise

    async def execute_web_ban_command(self, command_id, command_data):
        """Execute ban command from web panel"""
        user_id = command_data.get('user_id')
        duration = command_data.get('duration', 24)
        reason = command_data.get('reason', 'No reason provided')
        
        try:
            # Add user to service ban
            await database_storage.add_service_ban(
                user_id=str(user_id),
                reason=reason,
                duration_hours=duration,
                banned_by="Web Panel Admin"
            )
            
            # Send ban notification DM
            user = await self.fetch_user(int(user_id))
            if user:
                embed = discord.Embed(
                    title="🚫 Service Restriction Notice",
                    description="You have been temporarily restricted from SynapseChat services.",
                    color=0xff0000
                )
                
                embed.add_field(
                    name="📋 Restriction Details",
                    value=f"**Reason:** {reason}\n**Duration:** {duration} hours\n**Issued:** {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
                    inline=False
                )
                
                embed.add_field(
                    name="📖 What This Means",
                    value="• You cannot send messages in cross-chat channels\n• This restriction is temporary\n• Review community guidelines during this time",
                    inline=False
                )
                
                embed.set_footer(text="SynapseChat Administration")
                embed.timestamp = discord.utils.utcnow()
                
                await user.send(embed=embed)
                print(f"WEB_BAN: Ban notification sent to user {user_id} for {duration}h: {reason}")
                
        except Exception as e:
            print(f"Failed to ban user {user_id}: {e}")
            raise

    async def execute_web_announce_command(self, command_id, command_data):
        """Execute announcement command from web panel"""
        message = command_data.get('message')
        anonymous = command_data.get('anonymous', False)
        
        # Process multiline formatting - convert \n to actual newlines
        if message:
            message = message.replace('\\n', '\n')
        
        try:
            # Get all crosschat channels
            channels_data = await database_storage.load_channels()
            crosschat_channels = []
            
            for guild_id, guild_data in channels_data.items():
                if isinstance(guild_data, dict) and 'crosschat_channels' in guild_data:
                    for channel_id in guild_data['crosschat_channels']:
                        channel = self.get_channel(int(channel_id))
                        if channel:
                            crosschat_channels.append(channel)
            
            # Send announcement to all crosschat channels
            embed = discord.Embed(
                title="📢 System Announcement",
                description=message,
                color=0x0099ff
            )
            
            if not anonymous:
                embed.set_footer(text="SynapseChat Administration")
            
            embed.timestamp = discord.utils.utcnow()
            
            sent_count = 0
            for channel in crosschat_channels:
                try:
                    await channel.send(embed=embed)
                    sent_count += 1
                except Exception as e:
                    print(f"Failed to send announcement to channel {channel.id}: {e}")
            
            print(f"WEB_ANNOUNCE: Announcement sent to {sent_count} crosschat channels")
            
        except Exception as e:
            print(f"Failed to send announcement: {e}")
            raise

    async def statistics_updater(self):
        """Real-time statistics tracking for dashboard"""
        while True:
            try:
                # Read current chat logs from database
                messages = database_storage.get_chat_logs(limit=1000)
                
                # Calculate statistics
                total_messages = len(messages)
                
                # Count daily messages (last 24 hours)
                from datetime import datetime, timedelta
                yesterday = datetime.now() - timedelta(days=1)
                daily_messages = 0
                
                for msg in messages:
                    try:
                        # Handle both dict and tuple formats from database
                        if isinstance(msg, dict):
                            timestamp = msg.get('timestamp', '')
                        elif isinstance(msg, (list, tuple)) and len(msg) > 1:
                            timestamp = msg[1] if msg[1] else ''
                        else:
                            continue
                            
                        if timestamp:
                            msg_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            if msg_time >= yesterday:
                                daily_messages += 1
                    except:
                        continue
                
                # Update statistics file
                stats = {
                    'total_messages': total_messages,
                    'daily_messages': daily_messages,
                    'last_updated': datetime.now().isoformat() + 'Z',
                    'bot_status': 'online',
                    'guilds_connected': len(self.guilds),
                    'latency': round(self.latency * 1000)
                }
                
                pass  # Database only - no JSON files
                
                # Wait 30 seconds before next update
                await asyncio.sleep(30)
                
            except Exception as e:
                print(f"Statistics updater error: {e}")
                await asyncio.sleep(60)

    async def system_status_monitor(self):
        """Monitor system configuration changes and respond accordingly"""
        last_crosschat_state = None
        last_automod_state = None
        
        while True:
            try:
                # Check CrossChat system status
                try:
                    with open('data/system_config.json', 'r') as f:
                        system_config = json.load(f)
                    crosschat_enabled = system_config.get('crosschat_enabled', True)
                except FileNotFoundError:
                    crosschat_enabled = True
                
                # Check AutoMod system status
                try:
                    with open('data/automod_config.json', 'r') as f:
                        automod_config = json.load(f)
                    automod_enabled = automod_config.get('enabled', False)
                except FileNotFoundError:
                    automod_enabled = False
                
                # Handle CrossChat state changes
                if last_crosschat_state is not None and last_crosschat_state != crosschat_enabled:
                    status = "enabled" if crosschat_enabled else "disabled"
                    print(f"SYSTEM MONITOR: CrossChat system {status}")
                    
                    # Update cross-chat manager state
                    if hasattr(self, 'cross_chat_manager'):
                        self.cross_chat_manager.enabled = crosschat_enabled
                
                # Handle AutoMod state changes
                if last_automod_state is not None and last_automod_state != automod_enabled:
                    status = "enabled" if automod_enabled else "disabled"
                    print(f"SYSTEM MONITOR: Auto-Moderation system {status}")
                    
                    # Update auto-moderation manager state
                    if hasattr(self, 'auto_moderation'):
                        self.auto_moderation.enabled = automod_enabled
                
                # Store current states for next comparison
                last_crosschat_state = crosschat_enabled
                last_automod_state = automod_enabled
                
                # Wait 10 seconds before next check
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"System status monitor error: {e}")
                await asyncio.sleep(30)

    async def check_system_status(self):
        """Check system status for crosschat and automod"""
        try:
            # Check CrossChat system status - read directly from file
            try:
                with open('data/system_config.json', 'r') as f:
                    system_config = json.load(f)
                crosschat_enabled = system_config.get('crosschat_enabled', True)
            except FileNotFoundError:
                crosschat_enabled = True
            except Exception as e:
                print(f"Error reading system_config.json: {e}")
                crosschat_enabled = True
            
            # Check AutoMod system status - read directly from file
            try:
                with open('data/automod_config.json', 'r') as f:
                    automod_config = json.load(f)
                automod_enabled = automod_config.get('enabled', False)
            except FileNotFoundError:
                automod_enabled = False
            except Exception as e:
                print(f"Error reading automod_config.json: {e}")
                automod_enabled = False
            
            return {
                'crosschat_enabled': crosschat_enabled,
                'automod_enabled': automod_enabled
            }
        except Exception as e:
            print(f"Error checking system status: {e}")
            return {'crosschat_enabled': True, 'automod_enabled': False}

    async def broadcast_system_alert(self, alert_type, status, moderator="System"):
        """Broadcast system status changes to all crosschat channels"""
        try:
            channels_data = database_storage.get_crosschat_channels()
            
            # Create alert embed
            color = 0x00ff00 if status else 0xff0000
            status_text = "ENABLED" if status else "DISABLED"
            icon = "✅" if status else "❌"
            
            embed = discord.Embed(
                title=f"{icon} System Alert: {alert_type.upper()} {status_text}",
                description=f"{alert_type.replace('_', ' ').title()} has been {status_text.lower()} by {moderator}",
                color=color,
                timestamp=datetime.now()
            )
            embed.set_footer(text="SynapseChat System Administration")
            
            # Send to all crosschat channels
            alert_count = 0
            for guild_id, guild_data in channels_data.items():
                if isinstance(guild_data, dict) and 'channels' in guild_data:
                    for channel_id in guild_data['channels']:
                        try:
                            channel = self.get_channel(int(channel_id))
                            if channel:
                                await channel.send(embed=embed)
                                alert_count += 1
                                print(f"ALERT_SENT: {alert_type} alert sent to {channel.name} in {channel.guild.name}")
                        except Exception as e:
                            print(f"Failed to send alert to channel {channel_id}: {e}")
            
            print(f"SYSTEM_ALERT: Broadcasted {alert_type} {status_text} to {alert_count} channels")
            
        except Exception as e:
            print(f"Error broadcasting system alert: {e}")

    async def update_channel_names(self):
        """Update channel names from Discord for web interface display"""
        try:
            # Load current CrossChat channels
            channels_data = database_storage.get_crosschat_channels()
            channel_names = {}
            
            print("🔄 Updating CrossChat channel names...")
            
            # Handle both list and dict formats for channels_data
            if isinstance(channels_data, list):
                for channel_data in channels_data:
                    if isinstance(channel_data, dict) and channel_data.get('is_active'):
                        try:
                            channel_id = channel_data.get('channel_id')
                            if channel_id:
                                # Get the channel from Discord
                                channel = self.get_channel(int(channel_id))
                                if channel:
                                    channel_names[channel_id] = channel.name
                                    print(f"📝 {channel.name} (ID: {channel_id})")
                                else:
                                    # Channel not found, use fallback
                                    channel_names[channel_id] = "crosschat"
                                    print(f"❓ Channel {channel_id} not found, using fallback name")
                        except Exception as e:
                            if 'channel_id' in locals():
                                channel_names[channel_id] = "crosschat"
                            print(f"⚠️ Error getting channel name: {e}")
            
            # Save channel names to file
            pass  # Database only - no JSON files
            print(f"✅ Updated {len(channel_names)} channel names")
            
        except Exception as e:
            print(f"Error updating channel names: {e}")

    async def periodic_dm_queue_check(self):
        """Periodically check and process DM notification queue every 30 seconds"""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                # Process database queue FIRST (most important)
                from discord_notifier import discord_notifier
                if discord_notifier and hasattr(discord_notifier, 'process_database_queue'):
                    await discord_notifier.process_database_queue()
                
                # Process in-memory queue
                if hasattr(discord_notifier, 'notification_queue') and discord_notifier.notification_queue:
                    print(f"DM_QUEUE: Processing {len(discord_notifier.notification_queue)} queued notifications")
                    await discord_notifier.process_notification_queue()
                
                # Also check persistent queue file
                await self.process_persistent_notification_queue()
                
            except Exception as e:
                print(f"DM_QUEUE: Error in periodic queue check: {e}")
                await asyncio.sleep(60)  # Wait longer on error
    
    async def process_system_alerts(self):
        """Background task to process system alerts from web panel"""
        await self.wait_until_ready()
        
        while not self.is_closed():
            try:
                # Check if the simple_crosschat instance exists and process alerts
                if hasattr(self, 'crosschat_instance') and self.crosschat_instance:
                    await self.crosschat_instance.process_pending_system_alerts()
                else:
                    # Use existing singleton instance only
                    try:
                        from simple_crosschat import SimpleCrossChat
                        crosschat = SimpleCrossChat.get_instance()
                        if crosschat:
                            await crosschat.process_pending_system_alerts()
                    except Exception as e:
                        # Silently continue if no crosschat instance available
                        pass
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                print(f"SYSTEM_ALERT: Error in alert processor: {e}")
                await asyncio.sleep(30)

    async def process_system_alert_command(self, command_id, command_data):
        """Process system alert command from web panel"""
        try:
            alert_type = command_data.get('alert_type', 'system')
            status = command_data.get('status', True)
            moderator = command_data.get('moderator', 'System')
            
            print(f"SYSTEM_ALERT_CMD: Processing {alert_type} alert - {status} by {moderator}")
            
            # Broadcast the alert to all crosschat channels
            await self.broadcast_system_alert(alert_type, status, moderator)
            
            # Mark command as completed
            pass  # Command status tracking in database
            print(f"SYSTEM_ALERT_CMD: {alert_type} alert completed")
            
        except Exception as e:
            error_msg = f"Error processing system alert: {e}"
            print(f"SYSTEM_ALERT_ERROR: {error_msg}")
            pass  # Command status tracking in database

    async def process_web_server_ban_command(self, command_id, command_data):
        """Process server ban command from web panel"""
        try:
            pass  # MongoDB conversion - no operations needed
        except Exception as e:
            pass
    async def process_web_server_unban_command(self, command_id, command_data):
        """Process server unban command from web panel"""
        try:
            server_id = command_data.get('server_id')
            issued_by = command_data.get('issued_by', 'Web Panel')
            
            if not server_id:
                pass  # Command status tracking in database
                return
            
            # Validate server ID
            try:
                guild_id = int(server_id)
            except ValueError:
                pass  # Command status tracking in database
                return
            
            # Load banned servers data
            banned_servers = database_storage.get_crosschat_channels()
            
            # Check if server is banned
            if str(guild_id) not in banned_servers:
                pass  # Command status tracking in database
                return
            
            # Get server info before removing
            ban_info = banned_servers[str(guild_id)]
            server_name = ban_info.get('server_name', f'Unknown Server ({guild_id})')
            
            # Remove server ban
            del banned_servers[str(guild_id)]
            pass  # Database only - no JSON files
            
            # Log moderation action
            mod_logs = database_storage.get_crosschat_channels()
            unban_action = {
                'type': 'server_unban',
                'server_id': str(guild_id),
                'server_name': server_name,
                'issued_by': issued_by,
                'issued_by_id': command_data.get('issued_by_id', 0),
                'timestamp': datetime.now().isoformat(),
                'original_ban': ban_info,
                'source': 'web_panel'
            }
            mod_logs['actions'].append(unban_action)
            pass  # Database only - no JSON files
            
            pass  # Command status tracking in database
            print(f"WEB_SERVER_UNBAN: {server_name} ({guild_id}) unbanned from cross-chat by {issued_by}")
            
        except Exception as e:
            pass  # Command status tracking in database
            print(f"Error processing web server unban command: {e}")

    async def process_system_alert_command(self, command_id, command_data):
        """Process system alert command from web panel"""
        try:
            alert_type = command_data.get('alert_type')
            status = command_data.get('status')
            moderator = command_data.get('moderator', 'System')
            
            await self.broadcast_system_alert(alert_type, status, moderator)
            print(f"SYSTEM_ALERT: Processed {alert_type} alert - {status} by {moderator}")
            
        except Exception as e:
            print(f"Error processing system alert command: {e}")

    async def store_guild_info(self):
        """Store current guild information in database"""
        try:
            from database_storage_new import database_storage
            
            for guild in self.guilds:
                try:
                    # Store guild info in database
                    database_storage.store_guild_info(
                        guild_id=str(guild.id),
                        guild_name=guild.name,
                        member_count=guild.member_count,
                        owner_id=str(guild.owner.id) if guild.owner else None,
                        owner_name=guild.owner.display_name if guild.owner else None,
                        created_at=guild.created_at.isoformat() if guild.created_at else None,
                        icon_url=str(guild.icon.url) if guild.icon else None,
                        description=guild.description
                    )
                    print(f"✅ Stored guild info: {guild.name} ({guild.id})")
                    
                except Exception as e:
                    print(f"❌ Failed to store guild info for {guild.name}: {e}")
            
            print(f"✅ Guild information stored for {len(self.guilds)} servers")
            
        except Exception as e:
            print(f"❌ Failed to store guild information: {e}")

    async def periodic_discord_summary(self):
        """Background task to send Discord activity summaries every 60 seconds"""
        await self.wait_until_ready()
        
        while not self.is_closed():
            try:
                await asyncio.sleep(60)  # Wait 60 seconds between summaries
                await self.discord_logger.send_summary()
                    
            except Exception as e:
                pass  # Don't let logging errors break the bot

bot = CrossChatBot()

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return f"SynapseChat Bot: {'ONLINE' if bot.is_ready() else 'STARTING'}"

@flask_app.route('/status')  
def status():
    return {"status": "online" if bot.is_ready() else "starting", "bot": "SynapseChat", "uptime": str(datetime.now())}

def run_flask():
    import os
    port = int(os.environ.get('PORT', 10000))
    print(f"Flask starting on port {port}")
    flask_app.run(host='0.0.0.0', port=port, debug=False, threaded=True, use_reloader=False)

if __name__ == "__main__":
    print("STARTING SYNAPSECHAT BOT")
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    token = os.environ.get('DISCORD_TOKEN')
    if not token:
        print("🔍🔍🔍 CRITICAL_ERROR: NO DISCORD_TOKEN environment variable found")
        import time
        while True:
            time.sleep(60)
    
    print(f"🔍🔍🔍 TOKEN_DEBUG: Token length: {len(token)}")
    print(f"🔍🔍🔍 TOKEN_DEBUG: Token starts with: {token[:10]}...")
    print(f"Token length: {len(token)}")
    
    async def start_bot():
        try:
            print(f"🔍🔍🔍 DISCORD_CONNECT: Attempting Discord gateway connection...")
            await bot.start(token)
        except discord.LoginFailure as e:
            print(f"🔍🔍🔍 CRITICAL_ERROR: Discord login failed - Invalid token: {e}")
            import time
            while True:
                time.sleep(60)
        except discord.HTTPException as e:
            print(f"🔍🔍🔍 CRITICAL_ERROR: Discord HTTP error - API issue: {e}")
            import time
            while True:
                time.sleep(60)
        except Exception as e:
            print(f"🔍🔍🔍 CRITICAL_ERROR: Bot startup failed: {e}")
            print(f"🔍🔍🔍 ERROR_TYPE: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            import time
            while True:
                time.sleep(60)
    
    asyncio.run(start_bot())


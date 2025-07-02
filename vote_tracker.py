"""
Top.gg Vote Tracker - SynapseChat Bot
Handles vote detection, announcements, and monthly leaderboards
"""

import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import calendar
import logging

class VoteTracker:
    """Manages Top.gg vote tracking and rewards system"""
    
    def __init__(self, bot, database_handler, topgg_updater=None):
        self.bot = bot
        self.db_handler = database_handler
        self.topgg_updater = topgg_updater
        self.support_server_id = None  # Will be set from config
        self.announcement_channels = []  # Crosschat channels for announcements
        self.leaderboard_channel_id = 1389721837042143365  # Dedicated leaderboard channel
        self.last_leaderboard_message_id = None  # Track last message for editing
        
        # Start background tasks
        self.monthly_leaderboard_task.start()
        self.hourly_leaderboard_update.start()
        
        print("✅ VoteTracker initialized successfully")
    
    def set_support_server(self, server_id: str):
        """Set the support server ID for prize claiming"""
        self.support_server_id = server_id
        print(f"🏆 Support server set to: {server_id}")
    
    async def record_vote(self, user_id: str, user_data: Dict[str, Any] = None) -> bool:
        """
        Record a user vote in the database
        Returns True if successfully recorded
        """
        try:
            vote_data = {
                'user_id': str(user_id),
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'month': datetime.now(timezone.utc).strftime('%Y-%m'),
                'username': user_data.get('username', 'Unknown') if user_data else 'Unknown',
                'discriminator': user_data.get('discriminator', '0000') if user_data else '0000'
            }
            
            # Store in MongoDB votes collection
            def store_vote():
                try:
                    if hasattr(self.db_handler, 'mongodb_handler') and self.db_handler.mongodb_handler:
                        # Use MongoDB
                        votes_collection = self.db_handler.mongodb_handler.db['votes']
                        votes_collection.insert_one(vote_data)
                        return True
                    else:
                        # Fallback to PostgreSQL if available
                        query = """
                        INSERT INTO votes (user_id, timestamp, month, username, discriminator)
                        VALUES (%s, %s, %s, %s, %s)
                        """
                        self.db_handler.execute_query(query, (
                            vote_data['user_id'],
                            vote_data['timestamp'],
                            vote_data['month'],
                            vote_data['username'],
                            vote_data['discriminator']
                        ))
                        return True
                except Exception as e:
                    print(f"❌ Error storing vote: {e}")
                    return False
            
            # Execute database operation
            success = await asyncio.get_event_loop().run_in_executor(None, store_vote)
            
            if success:
                print(f"✅ Vote recorded for user {user_id}")
                # Send announcement
                await self.announce_vote(user_id, user_data)
                # Trigger immediate leaderboard update
                await self.update_leaderboard_immediately()
                return True
            else:
                print(f"❌ Failed to record vote for user {user_id}")
                return False
                
        except Exception as e:
            print(f"❌ Error in record_vote: {e}")
            return False
    
    async def announce_vote(self, user_id: str, user_data: Dict[str, Any] = None):
        """Send vote announcement to crosschat channels"""
        try:
            # Get user object for better display
            user = self.bot.get_user(int(user_id))
            
            if user_data:
                display_name = f"{user_data.get('username', 'Unknown')}#{user_data.get('discriminator', '0000')}"
            elif user:
                display_name = f"{user.name}#{user.discriminator}"
            else:
                display_name = f"User {user_id}"
            
            # Create announcement embed
            embed = discord.Embed(
                title="🗳️ New Vote Received!",
                description=f"**{display_name}** just voted for SynapseChat on Top.gg!",
                color=0x00ff00,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(
                name="💎 Monthly Elite VIP Prize",
                value="Top voter this month wins **1 month Elite VIP**!\nMust join support server to claim.",
                inline=False
            )
            
            embed.add_field(
                name="🔗 Vote Links",
                value="[Vote on Top.gg](https://top.gg/bot/1381206034269339658/vote)\n[Join Support Server](https://discord.gg/your-invite)",
                inline=False
            )
            
            embed.set_footer(text="Thank you for supporting SynapseChat!")
            
            # Send to all crosschat channels
            await self.send_to_crosschat_channels(embed)
            
        except Exception as e:
            print(f"❌ Error in announce_vote: {e}")
    
    async def send_to_crosschat_channels(self, embed: discord.Embed):
        """Send embed to all crosschat channels"""
        try:
            # Get crosschat channels from database
            def get_channels():
                try:
                    if hasattr(self.db_handler, 'mongodb_handler') and self.db_handler.mongodb_handler:
                        channels_collection = self.db_handler.mongodb_handler.db['crosschat_channels']
                        return list(channels_collection.find({}, {'channel_id': 1}))
                    else:
                        query = "SELECT channel_id FROM crosschat_channels"
                        result = self.db_handler.fetch_all(query)
                        return [{'channel_id': row[0]} for row in result] if result else []
                except Exception as e:
                    print(f"❌ Error getting crosschat channels: {e}")
                    return []
            
            channels_data = await asyncio.get_event_loop().run_in_executor(None, get_channels)
            
            sent_count = 0
            for channel_data in channels_data:
                try:
                    channel_id = int(channel_data['channel_id'])
                    channel = self.bot.get_channel(channel_id)
                    
                    if channel:
                        await channel.send(embed=embed)
                        sent_count += 1
                        # Small delay to prevent rate limiting
                        await asyncio.sleep(0.1)
                        
                except Exception as e:
                    print(f"❌ Error sending to channel {channel_data.get('channel_id')}: {e}")
                    continue
            
            print(f"✅ Vote announcement sent to {sent_count} crosschat channels")
            
        except Exception as e:
            print(f"❌ Error in send_to_crosschat_channels: {e}")
    
    async def get_monthly_leaderboard(self, month: str = None) -> List[Dict[str, Any]]:
        """
        Get monthly vote leaderboard
        Month format: 'YYYY-MM' (e.g., '2025-07')
        """
        if not month:
            month = datetime.now(timezone.utc).strftime('%Y-%m')
        
        try:
            def get_leaderboard():
                try:
                    if hasattr(self.db_handler, 'mongodb_handler') and self.db_handler.mongodb_handler:
                        # MongoDB aggregation pipeline
                        votes_collection = self.db_handler.mongodb_handler.db['votes']
                        pipeline = [
                            {'$match': {'month': month}},
                            {'$group': {
                                '_id': '$user_id',
                                'vote_count': {'$sum': 1},
                                'username': {'$first': '$username'},
                                'discriminator': {'$first': '$discriminator'},
                                'last_vote': {'$max': '$timestamp'}
                            }},
                            {'$sort': {'vote_count': -1}},
                            {'$limit': 10}
                        ]
                        return list(votes_collection.aggregate(pipeline))
                    else:
                        # PostgreSQL query
                        query = """
                        SELECT user_id, COUNT(*) as vote_count, 
                               MAX(username) as username, MAX(discriminator) as discriminator,
                               MAX(timestamp) as last_vote
                        FROM votes 
                        WHERE month = %s 
                        GROUP BY user_id 
                        ORDER BY vote_count DESC 
                        LIMIT 10
                        """
                        result = self.db_handler.fetch_all(query, (month,))
                        if result:
                            return [
                                {
                                    '_id': row[0],
                                    'vote_count': row[1],
                                    'username': row[2],
                                    'discriminator': row[3],
                                    'last_vote': row[4]
                                }
                                for row in result
                            ]
                        return []
                except Exception as e:
                    print(f"❌ Error getting leaderboard: {e}")
                    return []
            
            leaderboard = await asyncio.get_event_loop().run_in_executor(None, get_leaderboard)
            return leaderboard
            
        except Exception as e:
            print(f"❌ Error in get_monthly_leaderboard: {e}")
            return []
    
    async def create_leaderboard_embed(self, month: str = None) -> discord.Embed:
        """Create a formatted leaderboard embed"""
        if not month:
            month = datetime.now(timezone.utc).strftime('%Y-%m')
        
        # Parse month for display
        year, month_num = month.split('-')
        month_name = calendar.month_name[int(month_num)]
        
        leaderboard = await self.get_monthly_leaderboard(month)
        
        embed = discord.Embed(
            title=f"🏆 Top.gg Vote Leaderboard - {month_name} {year}",
            description="Monthly voting champions! Top voter wins **1 month Elite VIP**!",
            color=0xffd700,
            timestamp=datetime.now(timezone.utc)
        )
        
        if not leaderboard:
            embed.add_field(
                name="📊 No Votes Yet",
                value="Be the first to vote this month!",
                inline=False
            )
        else:
            leaderboard_text = ""
            
            for i, voter in enumerate(leaderboard[:10], 1):
                # Get user for current display name
                try:
                    user = self.bot.get_user(int(voter['_id']))
                    if user:
                        display_name = f"{user.name}#{user.discriminator}"
                    else:
                        display_name = f"{voter.get('username', 'Unknown')}#{voter.get('discriminator', '0000')}"
                except:
                    display_name = f"{voter.get('username', 'Unknown')}#{voter.get('discriminator', '0000')}"
                
                # Add trophy emoji for top 3
                if i == 1:
                    trophy = "🥇"
                elif i == 2:
                    trophy = "🥈"
                elif i == 3:
                    trophy = "🥉"
                else:
                    trophy = f"{i}."
                
                votes = voter['vote_count']
                leaderboard_text += f"{trophy} **{display_name}** - {votes} vote{'s' if votes != 1 else ''}\n"
            
            embed.add_field(
                name="🗳️ Top Voters",
                value=leaderboard_text,
                inline=False
            )
        
        embed.add_field(
            name="🎁 Prize Information",
            value="**Winner gets:** 1 Month Elite VIP\n**Requirement:** Must join support server to claim\n**How to vote:** [Click here](https://top.gg/bot/1381206034269339658/vote)",
            inline=False
        )
        
        embed.set_footer(text="Leaderboard updates in real-time • Vote daily for better chances!")
        
        return embed
    
    @tasks.loop(hours=24)
    async def monthly_leaderboard_task(self):
        """Daily task to post leaderboard and handle month transitions"""
        try:
            now = datetime.now(timezone.utc)
            
            # Check if it's the last day of the month
            tomorrow = now + timedelta(days=1)
            if tomorrow.month != now.month:
                # Last day of month - announce winner
                await self.announce_monthly_winner()
            
            # Post current leaderboard every Sunday
            if now.weekday() == 6:  # Sunday
                embed = await self.create_leaderboard_embed()
                await self.send_to_crosschat_channels(embed)
                
        except Exception as e:
            print(f"❌ Error in monthly_leaderboard_task: {e}")
    
    @monthly_leaderboard_task.before_loop
    async def before_monthly_leaderboard_task(self):
        """Wait for bot to be ready before starting task"""
        await self.bot.wait_until_ready()
    
    async def announce_monthly_winner(self):
        """Announce the monthly winner and provide claim instructions"""
        try:
            # Get previous month
            now = datetime.now(timezone.utc)
            if now.month == 1:
                prev_month = f"{now.year - 1}-12"
            else:
                prev_month = f"{now.year}-{now.month-1:02d}"
            
            leaderboard = await self.get_monthly_leaderboard(prev_month)
            
            if leaderboard:
                winner = leaderboard[0]
                year, month_num = prev_month.split('-')
                month_name = calendar.month_name[int(month_num)]
                
                # Get winner user object
                try:
                    user = self.bot.get_user(int(winner['_id']))
                    if user:
                        display_name = f"{user.mention}"
                        winner_name = f"{user.name}#{user.discriminator}"
                    else:
                        display_name = f"{winner.get('username', 'Unknown')}#{winner.get('discriminator', '0000')}"
                        winner_name = display_name
                except:
                    display_name = f"{winner.get('username', 'Unknown')}#{winner.get('discriminator', '0000')}"
                    winner_name = display_name
                
                embed = discord.Embed(
                    title=f"🎉 {month_name} {year} Voting Champion!",
                    description=f"Congratulations {display_name}!",
                    color=0xffd700,
                    timestamp=datetime.now(timezone.utc)
                )
                
                embed.add_field(
                    name="🏆 Winner Statistics",
                    value=f"**Champion:** {winner_name}\n**Total Votes:** {winner['vote_count']}\n**Prize:** 1 Month Elite VIP",
                    inline=False
                )
                
                embed.add_field(
                    name="🎁 How to Claim Your Prize",
                    value=f"1. Join our support server\n2. Contact staff with this message\n3. Staff will manually add your Elite VIP role\n\n**Prize expires in 7 days if not claimed!**",
                    inline=False
                )
                
                embed.add_field(
                    name="📊 New Month Started",
                    value="The leaderboard has reset! Start voting now for this month's Elite VIP prize!",
                    inline=False
                )
                
                embed.set_footer(text="Thank you for supporting SynapseChat!")
                
                await self.send_to_crosschat_channels(embed)
                
                print(f"🏆 Monthly winner announced: {winner_name} with {winner['vote_count']} votes")
                
        except Exception as e:
            print(f"❌ Error in announce_monthly_winner: {e}")
    
    async def get_user_vote_count(self, user_id: str, month: str = None) -> int:
        """Get vote count for a specific user in a specific month"""
        if not month:
            month = datetime.now(timezone.utc).strftime('%Y-%m')
        
        try:
            def get_count():
                try:
                    if hasattr(self.db_handler, 'mongodb_handler') and self.db_handler.mongodb_handler:
                        votes_collection = self.db_handler.mongodb_handler.db['votes']
                        return votes_collection.count_documents({
                            'user_id': str(user_id),
                            'month': month
                        })
                    else:
                        query = "SELECT COUNT(*) FROM votes WHERE user_id = %s AND month = %s"
                        result = self.db_handler.fetch_one(query, (str(user_id), month))
                        return result[0] if result else 0
                except Exception as e:
                    print(f"❌ Error getting user vote count: {e}")
                    return 0
            
            count = await asyncio.get_event_loop().run_in_executor(None, get_count)
            return count
            
        except Exception as e:
            print(f"❌ Error in get_user_vote_count: {e}")
            return 0
    
    async def update_leaderboard_immediately(self):
        """Update leaderboard immediately after a vote"""
        try:
            # Get the dedicated leaderboard channel
            channel = self.bot.get_channel(self.leaderboard_channel_id)
            if not channel:
                print(f"⚠️ Leaderboard channel {self.leaderboard_channel_id} not found")
                return
            
            # Create current leaderboard embed
            embed = await self.create_leaderboard_embed()
            embed.set_footer(text="🔄 Updated in real-time after vote • Use /leaderboard from anywhere!")
            
            # Try to edit existing message, or send new one
            if self.last_leaderboard_message_id:
                try:
                    # Try to fetch and edit the existing message
                    existing_message = await channel.fetch_message(self.last_leaderboard_message_id)
                    await existing_message.edit(embed=embed)
                    print("✅ Updated leaderboard message immediately")
                    return
                except discord.NotFound:
                    # Message was deleted, we'll send a new one
                    self.last_leaderboard_message_id = None
                except Exception as e:
                    print(f"⚠️ Failed to edit leaderboard message: {e}")
                    self.last_leaderboard_message_id = None
            
            # Send new leaderboard message
            message = await channel.send(embed=embed)
            self.last_leaderboard_message_id = message.id
            print(f"✅ Posted new immediate leaderboard message (ID: {message.id})")
            
        except Exception as e:
            print(f"❌ Error in update_leaderboard_immediately: {e}")
    
    @tasks.loop(hours=1)
    async def hourly_leaderboard_update(self):
        """Update leaderboard in dedicated channel every hour"""
        try:
            # Get the dedicated leaderboard channel
            channel = self.bot.get_channel(self.leaderboard_channel_id)
            if not channel:
                print(f"⚠️ Leaderboard channel {self.leaderboard_channel_id} not found")
                return
            
            # Create current leaderboard embed
            embed = await self.create_leaderboard_embed()
            embed.set_footer(text="🔄 Auto-updates every hour • Use /leaderboard from anywhere!")
            
            # Try to edit existing message, or send new one
            if self.last_leaderboard_message_id:
                try:
                    # Try to fetch and edit the existing message
                    existing_message = await channel.fetch_message(self.last_leaderboard_message_id)
                    await existing_message.edit(embed=embed)
                    print("✅ Updated existing leaderboard message")
                    return
                except discord.NotFound:
                    # Message was deleted, we'll send a new one
                    self.last_leaderboard_message_id = None
                except Exception as e:
                    print(f"⚠️ Failed to edit leaderboard message: {e}")
                    self.last_leaderboard_message_id = None
            
            # Send new leaderboard message
            message = await channel.send(embed=embed)
            self.last_leaderboard_message_id = message.id
            print(f"✅ Posted new leaderboard message (ID: {message.id})")
            
        except Exception as e:
            print(f"❌ Error in hourly_leaderboard_update: {e}")
    
    @hourly_leaderboard_update.before_loop
    async def before_hourly_leaderboard_update(self):
        """Wait for bot to be ready before starting hourly updates"""
        await self.bot.wait_until_ready()
        # Wait 5 minutes after bot startup before first update
        await asyncio.sleep(300)

def initialize_vote_tracker(bot, database_handler, topgg_updater=None):
    """Initialize the global vote tracker"""
    global vote_tracker
    vote_tracker = VoteTracker(bot, database_handler, topgg_updater)
    return vote_tracker
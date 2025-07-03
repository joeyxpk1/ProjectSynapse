"""
MongoDB Handler for SynapseChat Bot
Reliable NoSQL database with generous free tier
"""

import os
import pymongo
from pymongo import MongoClient
from datetime import datetime
from typing import Optional, Dict, Any, List
import threading

class MongoDBHandler:
    """MongoDB handler with graceful error handling"""
    
    def __init__(self):
        self.client = None
        self.db = None
        self._connection_lock = threading.Lock()
        self.connection_failed = False
        
    def _connect(self) -> bool:
        """Create MongoDB connection and initialize collections"""
        try:
            mongodb_url = os.environ.get('MONGODB_URL') or os.environ.get('MONGODB_URI')
            print(f"🔍 DEBUG: Environment check - MONGODB_URL exists: {bool(os.environ.get('MONGODB_URL'))}")
            print(f"🔍 DEBUG: Environment check - MONGODB_URI exists: {bool(os.environ.get('MONGODB_URI'))}")
            
            if not mongodb_url:
                print("❌ MONGODB_URL or MONGODB_URI not set - database logging disabled")
                print("❌ Available environment variables starting with MONGO:")
                for key in os.environ:
                    if 'MONGO' in key.upper():
                        print(f"   - {key}: {'SET' if os.environ[key] else 'EMPTY'}")
                self.connection_failed = True
                return False
                
            print(f"🔗 Connecting to MongoDB for database logging...")
            self.client = MongoClient(mongodb_url, serverSelectionTimeoutMS=15000)
            
            # Test connection with ping
            self.client.admin.command('ping')
            self.db = self.client.synapsechat
            
            # Initialize all required collections and indexes
            self._initialize_collections()
            
            print("✅ MongoDB connected - database logging ACTIVE")
            return True
            
        except Exception as e:
            print(f"❌ MongoDB connection failed: {e}")
            print("❌ Database logging will be DISABLED")
            self.connection_failed = True
            return False
    
    def _initialize_collections(self):
        """Initialize all required collections with proper indexes"""
        try:
            collections = [
                'crosschat_messages', 'crosschat_channels', 'banned_users', 
                'user_warnings', 'guild_info', 'bot_status', 'moderation_logs',
                'sent_messages', 'pending_alerts', 'automod_whitelist', 'partner_servers', 'votes'
            ]
            
            existing = self.db.list_collection_names()
            for collection_name in collections:
                if collection_name not in existing:
                    self.db.create_collection(collection_name)
                    print(f"📁 Created collection: {collection_name}")
            
            # Create indexes for performance
            self.db.crosschat_messages.create_index([("message_id", 1)], unique=True, background=True)
            self.db.crosschat_channels.create_index([("channel_id", 1)], unique=True, background=True)
            self.db.banned_users.create_index([("user_id", 1)], unique=True, background=True)
            self.db.automod_whitelist.create_index([("type", 1), ("identifier", 1)], unique=True, background=True)
            self.db.partner_servers.create_index([("server_id", 1)], unique=True, background=True)
            self.db.votes.create_index([("user_id", 1), ("month", 1)], background=True)
            self.db.votes.create_index([("timestamp", -1)], background=True)
            
        except Exception as e:
            print(f"❌ Error initializing collections: {e}")

    def get_crosschat_channels(self) -> List[Dict]:
        """Get list of crosschat channels with full information"""
        try:
            print(f"🔍 DEBUG: Getting crosschat channels from MongoDB...")
            if not self._ensure_connected():
                print(f"❌ DEBUG: Cannot get channels - no database connection")
                return []
            
            channels = list(self.db.crosschat_channels.find({}))
            print(f"✅ DEBUG: Found {len(channels)} crosschat channels")
            return channels
        except Exception as e:
            print(f"❌ CRITICAL: Error getting crosschat channels: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_crosschat_channel_ids(self) -> List[int]:
        """Get list of crosschat channel IDs only (for backward compatibility)"""
        try:
            channels = self.get_crosschat_channels()
            channel_ids = [int(ch["channel_id"]) for ch in channels if "channel_id" in ch]
            return channel_ids
        except Exception as e:
            print(f"❌ Error getting crosschat channel IDs: {e}")
            return []
    
    def add_crosschat_channel(self, channel_id: int, guild_id: int, channel_name: str = None, guild_name: str = None) -> bool:
        """Add crosschat channel"""
        try:
            print(f"🔍 DEBUG: FORCE ADDING crosschat channel {channel_id} to MongoDB...")
            if not self._ensure_connected():
                print(f"❌ CRITICAL: Cannot add channel - no database connection")
                return False
            
            channel_data = {
                "channel_id": str(channel_id),
                "guild_id": str(guild_id),
                "channel_name": channel_name or "Unknown",
                "guild_name": guild_name or "Unknown",
                "added_at": datetime.utcnow(),
                "active": True,
                "is_active": True
            }
            
            print(f"🔍 DEBUG: Channel data being inserted: {channel_data}")
            
            # Use upsert to avoid duplicates
            result = self.db.crosschat_channels.update_one(
                {"channel_id": str(channel_id)},
                {"$set": channel_data},
                upsert=True
            )
            
            if result.upserted_id or result.modified_count > 0:
                print(f"✅ FORCED SUCCESS: Channel {channel_id} added/updated in MongoDB")
                
                # VERIFY the channel was actually added
                verify = self.db.crosschat_channels.find_one({"channel_id": str(channel_id)})
                if verify:
                    print(f"✅ VERIFICATION: Channel {channel_id} confirmed in database")
                else:
                    print(f"❌ VERIFICATION FAILED: Channel {channel_id} not found after insertion")
                return True
            else:
                print(f"❌ FAILED: Channel {channel_id} was not added to database")
                return False
                
        except Exception as e:
            print(f"❌ CRITICAL: Error adding crosschat channel: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_crosschat_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get crosschat message by ID with debug logging"""
        try:
            if not self._ensure_connected():
                print(f"❌ DUPLICATE_CHECK: No database connection for message {message_id}")
                return None
            
            message = self.db.crosschat_messages.find_one({"message_id": message_id})
            if message:
                print(f"✅ DUPLICATE_FOUND: Message {message_id} already exists in database")
            else:
                print(f"🔍 DUPLICATE_CHECK: Message {message_id} not found - proceeding with processing")
            return message
        except Exception as e:
            print(f"❌ Error getting crosschat message: {e}")
            return None

    def update_crosschat_message(self, message_id: str, new_content: str) -> bool:
        """Update crosschat message content"""
        try:
            if not self._ensure_connected():
                return False
            
            result = self.db.crosschat_messages.update_one(
                {"message_id": message_id},
                {"$set": {"content": new_content, "updated_at": datetime.utcnow()}}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"❌ Error updating crosschat message: {e}")
            return False

    def get_pending_alerts(self) -> List[Dict[str, Any]]:
        """Get pending system alerts"""
        try:
            if not self._ensure_connected():
                return []
            
            alerts = list(self.db.pending_alerts.find({"processed": False}))
            return alerts
        except Exception as e:
            print(f"❌ Error getting pending alerts: {e}")
            return []

    def mark_alert_processed(self, alert_id) -> bool:
        """Mark alert as processed"""
        try:
            if not self._ensure_connected():
                return False
            
            result = self.db.pending_alerts.update_one(
                {"_id": alert_id},
                {"$set": {"processed": True, "processed_at": datetime.utcnow()}}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"❌ Error marking alert processed: {e}")
            return False

    def track_sent_message(self, cc_id: str, channel_id: str, sent_message_id: str, original_message_id: str = None) -> bool:
        """Track sent crosschat messages for editing/deletion, with optional original_message_id"""
        try:
            if not self._ensure_connected():
                return False

            doc = {
                "cc_id": cc_id,
                "channel_id": channel_id,
                "message_id": sent_message_id,
                "timestamp": datetime.utcnow()
            }
            if original_message_id is not None:
                doc["original_message_id"] = original_message_id

            self.db.sent_messages.insert_one(doc)
            return True
        except Exception as e:
            print(f"❌ Error tracking sent message: {e}")
            return False

    def get_sent_messages_by_cc_id(self, cc_id: str) -> List[Dict[str, Any]]:
        """Get all sent messages for a specific CC-ID for global editing/deletion"""
        try:
            if not self._ensure_connected():
                return []
            
            messages = list(self.db.sent_messages.find({"cc_id": cc_id}))
            print(f"🔍 LOOKUP: Found {len(messages)} sent messages for CC-ID {cc_id}")
            return messages
        except Exception as e:
            print(f"❌ Error getting sent messages by CC-ID: {e}")
            return []

    def mark_message_deleted(self, cc_id: str, deleted_by: str) -> bool:
        """Mark a crosschat message as deleted by staff"""
        try:
            if not self._ensure_connected():
                return False
            
            # Update crosschat_messages collection
            result = self.db.crosschat_messages.update_many(
                {"cc_id": cc_id},
                {
                    "$set": {
                        "is_deleted": True,
                        "deleted_at": datetime.utcnow(),
                        "deleted_by": deleted_by
                    }
                }
            )
            
            # Log the deletion action
            self.db.moderation_logs.insert_one({
                "action": "global_delete",
                "cc_id": cc_id,
                "moderator_id": deleted_by,
                "timestamp": datetime.utcnow(),
                "messages_affected": result.modified_count
            })
            
            print(f"✅ Marked {result.modified_count} messages as deleted for CC-ID {cc_id}")
            return True
        except Exception as e:
            print(f"❌ Error marking message deleted: {e}")
            return False

    def get_crosschat_message_by_cc_id(self, cc_id: str) -> Optional[Dict[str, Any]]:
        """Get original crosschat message by CC-ID"""
        try:
            if not self._ensure_connected():
                return None
            
            message = self.db.crosschat_messages.find_one({"cc_id": cc_id})
            return message
        except Exception as e:
            print(f"❌ Error getting message by CC-ID: {e}")
            return None

    def _ensure_connected(self) -> bool:
        """Ensure database connection is active"""
        print(f"🔍 DEBUG: Checking connection status - failed: {self.connection_failed}")
        
        if self.connection_failed:
            print(f"❌ DEBUG: Connection previously failed - not retrying")
            return False
            
        with self._connection_lock:
            if self.client is None or self.db is None:
                print(f"🔍 DEBUG: No active connection - attempting to connect...")
                return self._connect()
            
            # Test existing connection
            try:
                self.client.admin.command('ping')
                print(f"✅ DEBUG: Existing connection verified")
                return True
            except Exception as e:
                print(f"❌ DEBUG: Connection test failed: {e}")
                return self._connect()
    
    def is_available(self) -> bool:
        """Check if MongoDB connection is available and working"""
        return self._ensure_connected()

    def log_crosschat_message(self, message_data: Dict[str, Any]) -> bool:
        """Log crosschat message to database with duplicate handling"""
        try:
            print(f"🔍 DEBUG: Logging crosschat message: {message_data.get('message_id', 'unknown')}")
            
            if not self._ensure_connected():
                print(f"❌ CRITICAL: Database connection failed - LOGGING IMPOSSIBLE")
                return False
            
            # Add timestamp if not present
            if 'timestamp' not in message_data:
                message_data['timestamp'] = datetime.utcnow()
            
            # Ensure CC-ID is included in the log data
            if 'cc_id' not in message_data:
                print(f"⚠️ WARNING: No CC-ID provided in message data")
            
            # Use upsert to handle duplicates gracefully
            message_id = message_data.get('message_id')
            if message_id:
                print(f"🔍 DEBUG: Using upsert for message_id: {message_id} with CC-ID: {message_data.get('cc_id', 'N/A')}")
                result = self.db.crosschat_messages.update_one(
                    {"message_id": message_id},
                    {"$set": message_data},
                    upsert=True
                )
                
                if result.upserted_id:
                    print(f"✅ SUCCESS: New message logged with ID: {result.upserted_id}")
                elif result.modified_count > 0:
                    print(f"✅ SUCCESS: Updated existing message: {message_id}")
                else:
                    print(f"✅ SUCCESS: Message already exists (no changes): {message_id}")
            else:
                # Fallback for messages without message_id
                print(f"🔍 DEBUG: No message_id provided, using regular insert")
                result = self.db.crosschat_messages.insert_one(message_data)
                print(f"✅ SUCCESS: Message logged with ID: {result.inserted_id}")
            
            return True
        except Exception as e:
            print(f"❌ CRITICAL logging crosschat message ERROR: {e}")
            # Only show full traceback for non-duplicate errors
            if "E11000 duplicate key error" not in str(e):
                import traceback
                traceback.print_exc()
            return False

    def log_moderation_action(self, action_data: Dict[str, Any]) -> bool:
        """Log moderation action"""
        try:
            print(f"🔍 DEBUG: FORCE LOGGING moderation action: {action_data.get('action_type', 'unknown')}")
            if not self._ensure_connected():
                print(f"❌ CRITICAL: Cannot log moderation - no database connection")
                return False
            
            action_data['timestamp'] = datetime.utcnow()
            print(f"🔍 DEBUG: Moderation data being inserted: {action_data}")
            result = self.db.moderation_logs.insert_one(action_data)
            print(f"✅ FORCED SUCCESS: Moderation action logged with ID: {result.inserted_id}")
            
            # VERIFY insertion worked
            verify = self.db.moderation_logs.find_one({"_id": result.inserted_id})
            if verify:
                print(f"✅ VERIFICATION: Moderation action confirmed in database")
            else:
                print(f"❌ VERIFICATION FAILED: Moderation action not found after insertion")
            
            return True
        except Exception as e:
            print(f"❌ CRITICAL: Error logging moderation action: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def add_warning(self, user_id: str, moderator_id: str, reason: str, guild_id: str = None) -> bool:
        """Add warning to user"""
        try:
            print(f"🔍 DEBUG: FORCE ADDING warning for user {user_id}")
            if not self._ensure_connected():
                print(f"❌ CRITICAL: Cannot add warning - no database connection")
                return False
            
            warning_data = {
                "user_id": str(user_id),
                "moderator_id": str(moderator_id), 
                "reason": reason,
                "guild_id": str(guild_id) if guild_id else "global",
                "timestamp": datetime.utcnow(),
                "active": True
            }
            
            print(f"🔍 DEBUG: Warning data being inserted: {warning_data}")
            result = self.db.user_warnings.insert_one(warning_data)
            print(f"✅ FORCED SUCCESS: Warning added with ID: {result.inserted_id}")
            
            # Also log as moderation action
            mod_action = {
                "action_type": "warning",
                "target_user_id": str(user_id),
                "moderator_id": str(moderator_id),
                "reason": reason,
                "guild_id": str(guild_id) if guild_id else "global"
            }
            self.log_moderation_action(mod_action)
            
            return True
        except Exception as e:
            print(f"❌ CRITICAL: Error adding warning: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def ban_user(self, user_id: str, moderator_id: str, reason: str, duration: str = "permanent") -> bool:
        """Ban user from crosschat"""
        try:
            print(f"🔍 DEBUG: FORCE BANNING user {user_id}")
            if not self._ensure_connected():
                print(f"❌ CRITICAL: Cannot ban user - no database connection")
                return False
            
            ban_data = {
                "user_id": str(user_id),
                "moderator_id": str(moderator_id),
                "reason": reason,
                "duration": duration,
                "banned_at": datetime.utcnow(),
                "active": True
            }
            
            print(f"🔍 DEBUG: Ban data being inserted: {ban_data}")
            # Use upsert to update existing bans
            result = self.db.banned_users.update_one(
                {"user_id": str(user_id)},
                {"$set": ban_data},
                upsert=True
            )
            
            if result.upserted_id or result.modified_count > 0:
                print(f"✅ FORCED SUCCESS: User {user_id} banned")
                
                # Also log as moderation action
                mod_action = {
                    "action_type": "ban",
                    "target_user_id": str(user_id),
                    "moderator_id": str(moderator_id),
                    "reason": reason,
                    "duration": duration
                }
                self.log_moderation_action(mod_action)
                return True
            else:
                print(f"❌ FAILED: Could not ban user {user_id}")
                return False
                
        except Exception as e:
            print(f"❌ CRITICAL: Error banning user: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_user_warnings(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all warnings for a user"""
        try:
            if not self._ensure_connected():
                return []
            
            warnings = list(self.db.user_warnings.find(
                {"user_id": str(user_id), "active": True}
            ).sort("timestamp", -1))
            return warnings
        except Exception as e:
            print(f"❌ Error getting user warnings: {e}")
            return []
    
    def is_user_banned(self, user_id: str) -> bool:
        """Check if user is banned"""
        try:
            if not self._ensure_connected():
                return False
            
            ban = self.db.banned_users.find_one({"user_id": str(user_id), "active": True})
            return ban is not None
        except Exception as e:
            print(f"❌ Error checking user ban: {e}")
            return False

    def get_chatlog_count(self):
        """Get total number of crosschat messages logged"""
        try:
            if not self._ensure_connected():
                print(f"❌ MONGODB: Cannot get message count - no connection")
                return 0
                
            # Count documents in crosschat_messages collection
            count = self.db.crosschat_messages.count_documents({})
            print(f"✅ MONGODB: Retrieved crosschat message count: {count}")
            
            # Also verify collection exists and has data
            if count == 0:
                # Check if collection exists
                collections = self.db.list_collection_names()
                if 'crosschat_messages' in collections:
                    print(f"🔍 MONGODB: crosschat_messages collection exists but is empty")
                else:
                    print(f"❌ MONGODB: crosschat_messages collection does not exist")
                    
            return count
        except Exception as e:
            print(f"❌ MONGODB ERROR: Failed to get message count: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def get_message_count(self):
        """Alias for get_chatlog_count"""
        return self.get_chatlog_count()
    
    def remove_guild_data(self, guild_id: str) -> bool:
        """Remove all guild-related data from MongoDB when bot leaves a guild"""
        try:
            if not self._ensure_connected():
                print(f"❌ MONGODB: Cannot remove guild data - no connection")
                return False
            
            guild_id_str = str(guild_id)
            removed_count = 0
            
            # Remove crosschat channels for this guild
            result = self.db.crosschat_channels.delete_many({"guild_id": guild_id_str})
            removed_count += result.deleted_count
            print(f"✅ MONGODB: Removed {result.deleted_count} crosschat channels for guild {guild_id}")
            
            # Remove guild info
            result = self.db.guild_info.delete_many({"guild_id": guild_id_str})
            removed_count += result.deleted_count
            print(f"✅ MONGODB: Removed {result.deleted_count} guild info entries for guild {guild_id}")
            
            # Keep crosschat messages - they are part of the network history
            # Only remove guild-specific administrative data
            print(f"✅ MONGODB: Crosschat messages preserved - they are part of network history")
            
            # Keep user warnings - they are part of moderation history
            # Warnings should persist across the network for accountability
            print(f"✅ MONGODB: User warnings preserved - they are part of moderation history")
            
            # Remove guild-specific moderation logs
            result = self.db.moderation_logs.delete_many({"guild_id": guild_id_str})
            removed_count += result.deleted_count
            print(f"✅ MONGODB: Removed {result.deleted_count} moderation logs for guild {guild_id}")
            
            print(f"✅ MONGODB: Total cleanup complete - removed {removed_count} documents for guild {guild_id}")
            return True
            
        except Exception as e:
            print(f"❌ MONGODB ERROR: Failed to remove guild data for {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def cleanup_guild_data(self, guild_id: str) -> bool:
        """Clean up guild-specific data when bot leaves guild - preserves network history"""
        try:
            if not self._ensure_connected():
                print(f"❌ MONGODB: Cannot cleanup guild data - no connection")
                return False
            
            guild_id_str = str(guild_id)
            removed_count = 0
            
            print(f"🧹 GUILD_CLEANUP: Starting cleanup for guild {guild_id}")
            
            # Remove crosschat channels for this guild (guild-specific administrative data)
            result = self.db.crosschat_channels.delete_many({"guild_id": guild_id_str})
            removed_count += result.deleted_count
            print(f"✅ GUILD_CLEANUP: Removed {result.deleted_count} crosschat channels for guild {guild_id}")
            
            # Remove guild-specific moderation logs (administrative data)
            result = self.db.moderation_logs.delete_many({"guild_id": guild_id_str})
            removed_count += result.deleted_count
            print(f"✅ GUILD_CLEANUP: Removed {result.deleted_count} moderation logs for guild {guild_id}")
            
            # PRESERVE crosschat messages - they are network-wide history, not guild-specific
            print(f"✅ GUILD_CLEANUP: Crosschat messages preserved - network history maintained")
            
            # PRESERVE user warnings - they are network-wide moderation history for accountability
            print(f"✅ GUILD_CLEANUP: User warnings preserved - moderation accountability maintained")
            
            print(f"✅ GUILD_CLEANUP: Cleanup complete - removed {removed_count} guild-specific documents, preserved network history")
            return True
            
        except Exception as e:
            print(f"❌ GUILD_CLEANUP ERROR: Failed to cleanup guild data for {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            return False

# Global instance
mongo_handler = MongoDBHandler()

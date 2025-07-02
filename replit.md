# Project Overview

## Overview
This repository appears to be empty or the contents were not provided. This template serves as a foundation for documenting the system architecture and user preferences for any project that will be developed.

## System Architecture
To be determined based on project requirements. Common architectural patterns include:
- **Frontend**: Web application (React, Vue, or vanilla JavaScript)
- **Backend**: API server (Node.js, Python, or similar)
- **Database**: Relational or NoSQL database
- **Authentication**: Session-based or token-based authentication

## Key Components
The following components will likely be developed:
- **User Interface**: Frontend application for user interaction
- **API Layer**: Backend services for data processing and business logic
- **Data Layer**: Database for persistent storage
- **Authentication System**: User management and security

## Data Flow
1. User interacts with the frontend interface
2. Frontend sends requests to the backend API
3. Backend processes requests and interacts with the database
4. Results are returned to the frontend and displayed to the user

## External Dependencies
Dependencies will be determined based on the chosen technology stack. Common dependencies include:
- **Frontend Libraries**: UI frameworks and utility libraries
- **Backend Frameworks**: Server frameworks and middleware
- **Database Drivers**: Connection libraries for database interaction
- **Third-party APIs**: External service integrations as needed

## Deployment Strategy
Deployment approach to be determined. Options include:
- **Development**: Local development environment
- **Staging**: Testing environment for validation
- **Production**: Live environment for end users

Note: If using Drizzle ORM, PostgreSQL may be added as the database solution during development.

## Bot Information
- **Bot ID**: 1381206034269339658
- **Required Permissions**: 534724869184 (service-level only, no Discord server moderation)
- **Invite Link**: https://discord.com/oauth2/authorize?client_id=1381206034269339658&permissions=534724869184&scope=bot%20applications.commands

## Environment Variables Required
- **DISCORD_TOKEN**: Bot token for Discord API access
- **MONGODB_URL**: MongoDB connection string for data storage
- **MODERATION_WEBHOOK_URL**: Webhook URL for moderation action notifications (optional)
- **GUILD_WEBHOOK_URL**: Webhook URL for guild join/leave notifications (optional)
- **STAFF_ROLE_ID**: Discord role ID for staff members (optional)

## Command Permission Structure
- **Public Commands (7)**: `/ping`, `/status`, `/help`, `/invite`, `/serverinfo`, `/leaderboard`, `/votecount` - Available to all users
- **Server Administrator Commands (2)**: `/setup`, `/warn` - Available to Server Admins, Official Staff, and Bot Owner
- **Official Staff Commands (3)**: `/announce`, `/ban`, `/unban` - Available to Official Staff and Bot Owner only
- **Bot Owner Commands (5)**: `/crosschat`, `/serverban`, `/serverunban`, `/serverbans`, `/testtopgg` - Bot Owner only
- **Prefix Commands (12)**: 
  - `!sync` - Force sync all commands with Discord (Bot Owner only)
  - `!guilds` - List all servers with crosschat analysis (Restricted to User ID: 662655499811946536)
  - `!leave <guild_id> [reason]` - Force bot to leave specific server (Restricted to User ID: 662655499811946536)
  - `!eval <code>` - Execute Python code (Bot Owner only)
  - `!moderation <action>` - Manage auto-moderation settings (Bot Owner or Official Staff)
  - `!presence <status> <activity_type> <activity_text>` - Change bot presence (Bot Owner only)
  - `!shutdown` - Safely shutdown the bot (Bot Owner only)
  - `!restart` - Restart the bot (Bot Owner only)
  - `!stats` - Show detailed bot statistics (Bot Owner only)
  - `!announce <message>` - Send announcement to all crosschat channels with newline formatting support (Bot Owner or Official Staff)
  - `!whitelist <user_id>` - Add user to automod whitelist (User ID: 662655499811946536 or Role ID: 951234288228134942)
  - `!unwhitelist <user_id>` - Remove user from automod whitelist (User ID: 662655499811946536 or Role ID: 951234288228134942)
  - `!partner <server_id>` - Add server to partner network with message processing boost (Bot Owner only)
  - `!unpartner <server_id>` - Remove server from partner network (Bot Owner only)
  - `!partners-view` or `!partners` - List all partner servers with status and statistics (Available to all users)

## Changelog
- July 1, 2025: ADDED automatic leaderboard updates in dedicated channel ID 1389721837042143365 - implemented hourly automatic updates and real-time updates after each vote, leaderboard message editing to prevent spam, public /leaderboard command access from anywhere, comprehensive vote statistics display with trophy rankings, and smart message management with fallback to new messages if editing fails
- July 1, 2025: IMPLEMENTED comprehensive vote tracking system with MongoDB persistence - added VoteTracker class with real-time webhook processing for TopGG vote notifications, monthly leaderboards with Elite VIP rewards for top voters, Flask webhook server on port 8080 (/webhook/vote endpoint), vote announcements to crosschat channels with celebration embeds, vote database with proper indexing for efficient queries, /leaderboard and /votecount slash commands for user engagement, automatic monthly leaderboard postings with prize claim instructions, and support server requirement for Elite VIP role assignment
- July 1, 2025: FIXED TopGG integration completely - corrected import from topggpy to topgg module, used proper DBLClient class, fixed method calls to post_guild_count() and get_bot_info(), and added session cleanup with await client.close() to prevent unclosed aiohttp session warnings, TopGG stats posting now works cleanly with comprehensive debug logging
- July 1, 2025: Made !partners-view command public - removed bot owner restriction, allowing all users to view partner server network information for transparency
- July 1, 2025: Added !partners-view command - implemented comprehensive partner server listing with status indicators, member counts, boost delays, partnership dates, and active/inactive tracking for bot owner management
- July 1, 2025: Fixed partner command datetime import error - resolved "cannot access local variable 'datetime'" error in !partner command by adding proper local datetime import, enabling successful partner server registration
- July 1, 2025: Fixed TopGG stats posting - completed missing on_ready task creation for TopGG stats updater, resolved MongoDB handler attribute mismatch (mongodb_handler vs db_handler), and fixed UnboundLocalError with os module import scoping, ensuring automatic stats posting every 30 minutes and immediate posting on startup
- July 1, 2025: Corrected Elite VIP processing speed to 0.25s - Elite VIP users now get proper 0.25s processing delay instead of instant, maintaining correct speed hierarchy: Elite VIP (0.25s) > Architect VIP (0.5s) > Partner Servers (0.75s) > Regular Users (1.0s)
- July 1, 2025: Fixed VIP speed priority system - VIP users now get their VIP processing speeds regardless of whether they're in partner servers, ensuring Elite VIP and Architect VIP always override partner speed (0.75s), maintaining proper speed hierarchy while partner servers still get speed boost for non-VIP users
- July 1, 2025: Implemented unified tag hierarchy and processing system - VIP status now takes priority over partner status for tags, while partner servers maintain their 0.75s processing speed boost, creating proper hierarchy: Elite VIP (instant) > Architect VIP (0.5s) > Partner Servers (0.75s) > Regular Users (1.0s), with partnership tag only showing for non-VIP users in partner servers
- July 1, 2025: Enhanced TopGG integration with official topggpy library - replaced manual HTTP requests with proper topggpy.DBLClient for reliable stats posting and bot info retrieval, following official documentation for better error handling and API compatibility
- July 1, 2025: CRITICAL FIX - Fixed channel verification bug that completely broke crosschat message processing - SimpleCrossChat was calling get_crosschat_channels() which returns dictionaries but checking for integers, changed to use get_crosschat_channel_ids() which returns proper integer list, this was preventing ALL crosschat messages from being processed
- July 1, 2025: CRITICAL FIX - Fixed Elite VIP file attachment processing that was breaking all message processing - implemented pre-read attachment data with fresh Discord.File object creation for each channel to prevent "file object can only be used once" errors that were causing the entire crosschat system to stop working
- July 1, 2025: Fixed MongoDB partner_servers collection initialization - added missing 'partner_servers' collection to MongoDB handler initialization list and created unique index on server_id field, ensuring partner commands (!partner/!unpartner) work reliably with proper database backing
- July 1, 2025: Fixed VIP speed hierarchy - Elite VIP (VIP_ROLE_ID2) now processes faster than Architect VIP (VIP_ROLE_ID) with Ultra-Fast parallel processing, maintaining correct tier order: Elite VIP (fastest) > Architect VIP (fast) > Partner Servers (75ms) > Regular Users (100ms)
- July 1, 2025: Added partner server system with message processing optimization - implemented `!partner <server_id>` and `!unpartner <server_id>` commands for Bot Owner to manage partner network, partner servers get parallel message processing with 75ms delay instead of 100ms standard delay for faster crosschat distribution while maintaining quality slower than VIP users
- June 30, 2025: Fixed guilds command statistics accuracy - updated MongoDB handler to return complete channel data with guild_id information, enabling accurate crosschat setup detection and network statistics reporting
- June 30, 2025: Added generic community moderation notifications - all warning and ban actions now send anonymous community notices to all crosschat channels without user names, includes intelligent violation categorization and scope indication for community awareness while maintaining user privacy
- June 30, 2025: Converted automod whitelist to MongoDB persistence - automod whitelist system now stores data in MongoDB `automod_whitelist` collection for persistence across bot restarts, includes unique compound index on type+identifier for efficient queries, maintains backward compatibility with in-memory fallback
- June 30, 2025: Added prefix announce command - added `!announce <message>` prefix command for Bot Owner or Official Staff with enhanced formatting support, automatic newline conversion (\n to line breaks), delivery confirmation, failure tracking, and audit logging to make announcements easier without using web panel
- June 30, 2025: Added automod whitelist management commands - added `!whitelist <user_id>` and `!unwhitelist <user_id>` prefix commands for specific User ID (662655499811946536) or Role ID (951234288228134942) with global role checking across all servers to manage users who bypass automod checks, includes validation and detailed embed responses
- June 30, 2025: Fixed automod integration with command-issued warnings - automod now properly checks existing warnings from database before determining escalation actions, ensuring users with prior `/warn` command warnings receive appropriate consequences when automod violations occur
- June 30, 2025: Fixed Discord embed field length limit error in `!guilds` command - implemented intelligent batching system to split guild information across multiple embed fields instead of single field exceeding 1024 character limit
- June 30, 2025: Added missing `is_available` method to MongoDB handler - fixed "MongoDBHandler object has no attribute 'is_available'" error when using `!guilds` command
- June 30, 2025: Converted problematic slash commands to prefix commands - `/eval`, `/moderation`, `/presence`, `/shutdown`, `/restart`, and `/stats` removed as slash commands and added as prefix commands (`!eval`, `!moderation`, `!presence`, `!shutdown`, `!restart`, `!stats`) to resolve Discord sync conflicts and registration issues
- June 30, 2025: Fixed db_handler scope error in guild join process - resolved "name 'db_handler' is not defined" error when bot joins new servers
- June 30, 2025: Converted /guilds and /leaveguild commands to prefix commands - !guilds and !leave now restricted to specific user ID (662655499811946536) for enhanced security
- June 30, 2025: Enhanced TopGG integration debugging - added comprehensive logging to identify why TopGG stats posting wasn't working despite showing as "enabled"
- June 30, 2025: Fixed TopGG stats updater timing - now posts stats immediately on startup instead of waiting 30 minutes, then continues every 30 minutes
- June 30, 2025: Added /testtopgg slash command for bot owners to test TopGG API connection immediately with detailed feedback
- June 30, 2025: Fixed status command crosschat channel count - now properly queries MongoDB database instead of performance cache for accurate channel count
- June 30, 2025: Changed /sync to !sync prefix command - removed slash command and implemented as owner-only prefix command with visual feedback
- June 30, 2025: Fixed status command datetime error - resolved timezone-aware/naive datetime calculation issue preventing /status command from working
- June 30, 2025: Added TopGG API integration - bot now automatically posts server count every 30 minutes with comprehensive error logging and owner test command
- June 30, 2025: Fixed global delete functionality - updated `/delete` command to properly search Discord channel history for CC-IDs instead of relying on sent_messages collection
- June 30, 2025: Fixed crosschat embed duplication issue - removed problematic processing marker that was interfering with duplicate prevention
- June 30, 2025: Added `/delete` command for Official Staff and Bot Owner - allows global deletion of crosschat messages by CC-ID across all channels
- June 30, 2025: Enhanced MongoDB handler with global delete methods - added CC-ID logging and message deletion tracking
- June 30, 2025: Fixed announcement formatting issue - enhanced newline conversion to handle both \\n and \\\\n escape sequences properly in Discord embeds
- June 30, 2025: Fixed syntax error in auto_moderation.py preventing bot startup
- June 30, 2025: Corrected command permission structure - only /setup and /warn are available to Server Administrators (while maintaining Bot Owner/Official Staff access)
- June 30, 2025: Enhanced /guilds command for bot owners - shows detailed server analysis with CrossChat setup status, member counts, creation dates, and network statistics
- June 30, 2025: Added "Run /setup to get started" to revolving bot status messages for better user discovery
- June 30, 2025: Added bot onboarding system - when bot is added to new servers, it pings the person who added it with comprehensive setup instructions via DM or server channel
- June 29, 2025: Added MongoDB database cleanup when bot leaves guilds - removes guild administrative data (channels, guild info, logs) while preserving crosschat messages and warnings as network history
- June 29, 2025: Added comprehensive guild webhook notifications for server joins/leaves with detailed server information
- June 29, 2025: Added bot invite link with correct permissions for Client ID 1381206034269339658
- June 29, 2025: Fixed multiline formatting in announcements to properly convert \\n to line breaks and handle markdown edge cases
- June 29, 2025: Clarified bot permission requirements - only needs service-level permissions (534724869184), no Discord server moderation powers
- June 29, 2025: Enhanced announce command to support multiline formatting with \\n escape sequences for professional announcements
- June 29, 2025: Updated crosschat embeds to include user Discord IDs in footer for enhanced moderation tracking
- June 28, 2025: Initial setup

## User Preferences
Preferred communication style: Simple, everyday language.
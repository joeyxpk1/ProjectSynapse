"""
Top.gg Vote Webhook Receiver
Receives vote notifications and records them in the database
"""

from flask import Flask, request, jsonify
import json
import asyncio
import threading
import os
from datetime import datetime, timezone
import hmac
import hashlib

app = Flask(__name__)

# Global variables to store bot reference
bot_instance = None
vote_tracker_instance = None

def set_bot_instance(bot, vote_tracker):
    """Set bot and vote tracker instances for webhook use"""
    global bot_instance, vote_tracker_instance
    bot_instance = bot
    vote_tracker_instance = vote_tracker
    print("✅ Vote webhook: Bot instance registered")

def verify_webhook_signature(data: bytes, signature: str) -> bool:
    """Verify Top.gg webhook signature"""
    try:
        webhook_auth = os.environ.get('TOPGG_WEBHOOK_SECRET')
        if not webhook_auth:
            print("⚠️ Vote webhook: No TOPGG_WEBHOOK_SECRET found - skipping verification")
            return True  # Allow unverified webhooks for now
        
        # Create expected signature
        expected_signature = hmac.new(
            webhook_auth.encode('utf-8'),
            data,
            hashlib.sha256
        ).hexdigest()
        
        # Remove 'sha256=' prefix if present
        if signature.startswith('sha256='):
            signature = signature[7:]
        
        # Compare signatures
        return hmac.compare_digest(expected_signature, signature)
        
    except Exception as e:
        print(f"❌ Vote webhook: Signature verification error: {e}")
        return False

@app.route('/webhook/vote', methods=['POST'])
def handle_vote():
    """Handle Top.gg vote webhook"""
    try:
        # Get raw data for signature verification
        raw_data = request.get_data()
        
        # Verify signature if header is present
        signature = request.headers.get('Authorization', '')
        if signature and not verify_webhook_signature(raw_data, signature):
            print("❌ Vote webhook: Invalid signature")
            return jsonify({'error': 'Invalid signature'}), 401
        
        # Parse JSON data
        try:
            data = request.get_json()
        except Exception as e:
            print(f"❌ Vote webhook: JSON parse error: {e}")
            return jsonify({'error': 'Invalid JSON'}), 400
        
        if not data:
            print("❌ Vote webhook: No data received")
            return jsonify({'error': 'No data'}), 400
        
        print(f"🗳️ Vote webhook: Received data: {data}")
        
        # Extract vote information
        user_id = data.get('user')
        bot_id = data.get('bot')
        vote_type = data.get('type', 'vote')  # vote, test, etc.
        is_weekend = data.get('isWeekend', False)
        
        if not user_id:
            print("❌ Vote webhook: No user ID in vote data")
            return jsonify({'error': 'No user ID'}), 400
        
        if not bot_id:
            print("❌ Vote webhook: No bot ID in vote data")
            return jsonify({'error': 'No bot ID'}), 400
        
        # Verify this is for our bot
        expected_bot_id = "1381206034269339658"
        if str(bot_id) != expected_bot_id:
            print(f"❌ Vote webhook: Wrong bot ID. Expected {expected_bot_id}, got {bot_id}")
            return jsonify({'error': 'Wrong bot'}), 400
        
        print(f"✅ Vote webhook: Valid vote from user {user_id} (type: {vote_type}, weekend: {is_weekend})")
        
        # Process the vote asynchronously
        if bot_instance and vote_tracker_instance:
            # Get user data for better display
            user_data = {
                'user_id': str(user_id),
                'vote_type': vote_type,
                'is_weekend': is_weekend,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            # Try to get Discord user info
            try:
                user = bot_instance.get_user(int(user_id))
                if user:
                    user_data['username'] = user.name
                    user_data['discriminator'] = user.discriminator
            except:
                pass  # Continue without user info if not available
            
            # Schedule vote recording
            def run_async_vote_recording():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(vote_tracker_instance.record_vote(str(user_id), user_data))
                    loop.close()
                except Exception as e:
                    print(f"❌ Vote webhook: Error recording vote: {e}")
            
            # Run in background thread to avoid blocking webhook response
            threading.Thread(target=run_async_vote_recording, daemon=True).start()
            
            print(f"✅ Vote webhook: Vote recording scheduled for user {user_id}")
        else:
            print("⚠️ Vote webhook: Bot or vote tracker not available")
        
        return jsonify({'success': True, 'message': 'Vote recorded'}), 200
        
    except Exception as e:
        print(f"❌ Vote webhook: Error handling vote: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/webhook/vote', methods=['GET'])
def webhook_info():
    """Provide webhook information"""
    return jsonify({
        'message': 'Top.gg Vote Webhook Endpoint',
        'status': 'active',
        'bot_ready': bot_instance is not None,
        'tracker_ready': vote_tracker_instance is not None
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'bot_connected': bot_instance is not None,
        'vote_tracker_ready': vote_tracker_instance is not None
    })

def start_webhook_server(port=8080):
    """Start the webhook server"""
    try:
        print(f"🌐 Starting vote webhook server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except Exception as e:
        print(f"❌ Failed to start webhook server: {e}")

if __name__ == '__main__':
    # Start server if run directly
    start_webhook_server()
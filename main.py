import os
import logging
import asyncio
from datetime import datetime, timedelta, timezone
import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot

# --- LOGGING SETUP (Professional Standard) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- CONFIG ---
class Config:
    BITQUERY_ID = os.getenv("BITQUERY_ID")
    BITQUERY_SECRET = os.getenv("BITQUERY_SECRET")
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    CHAT_ID = os.getenv("CHAT_ID")
    # Scan interval in minutes
    INTERVAL_MINUTES = 10 

# --- THE RADAR CORE ---
class CryptoRadar:
    def __init__(self):
        self.token = None
        self.token_expiry = datetime.now(timezone.utc)
        self.bot = Bot(token=Config.TELEGRAM_TOKEN)

    def _refresh_token(self):
        """Fetches a new token only if the current one is expired or missing."""
        if self.token and datetime.now(timezone.utc) < self.token_expiry:
            return # Token is still valid

        logger.info("Refreshing Bitquery Token...")
        url = "https://oauth2.bitquery.io/oauth2/token"
        payload = {
            'grant_type': 'client_credentials',
            'client_id': Config.BITQUERY_ID,
            'client_secret': Config.BITQUERY_SECRET,
            'scope': 'api'
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        
        try:
            # Note: The payload should be data, not json for x-www-form-urlencoded
            response = requests.post(url, headers=headers, data=payload)
            response.raise_for_status()
            data = response.json()
            self.token = data.get('access_token')
            # Set expiry to 23 hours to be safe (usually 24h)
            self.token_expiry = datetime.now(timezone.utc) + timedelta(hours=23)
            logger.info("Token refreshed successfully.")
        except Exception as e:
            logger.error(f"Auth Critical Failure: {e}")
            self.token = None

    def _get_dynamic_query(self):
        """Generates GraphQL query with a DYNAMIC timestamp (Last X Mins)."""
        # Calculate time X minutes ago in ISO8601 format
        time_window = datetime.now(timezone.utc) - timedelta(minutes=Config.INTERVAL_MINUTES)
        time_str = time_window.strftime('%Y-%m-%dT%H:%M:%SZ')

        return f"""
        {{
          bitcoin {{
            inflow: transactions(
              options: {{desc: "value", limit: 1}}
              date: {{after: "{time_str}"}} 
              outputAddress: {{annotation: "Exchange"}}
            ) {{
              average: value(calculate: average)
              count
            }}
            old_coins: inputs(age: {{gt: 1095}}, date: {{after: "{time_str}"}}) {{
              volume: value(calculate: sum)
            }}
          }}
        }}
        """

    def scan(self):
        """Main Logic: Auth -> Query -> Analyze -> Alert"""
        self._refresh_token()
        if not self.token:
            logger.warning("Skipping scan due to missing token.")
            return

        query = self._get_dynamic_query()
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

        try:
            # Using V2 streaming endpoint (check your specific API docs if using V1)
            res = requests.post("https://streaming.bitquery.io/graphql", json={"query": query}, headers=headers)
            
            if res.status_code != 200:
                logger.error(f"Bitquery API Error: {res.text}")
                return

            json_data = res.json()
            if 'errors' in json_data:
                logger.error(f"GraphQL Error: {json_data['errors']}")
                return

            data = json_data['data']['bitcoin']
            
            # Safe parsing with defaults
            avg_inflow = data['inflow'][0]['average'] if data['inflow'] else 0.0
            old_vol = data['old_coins'][0]['volume'] if data['old_coins'] else 0.0

            logger.info(f"Scan Result - Inflow Avg: {avg_inflow:.2f} | Old Vol: {old_vol:.2f}")

            # --- INTELLIGENT TRIGGER ---
            # Using asyncio.run here is safe because APScheduler runs this in a thread
            if avg_inflow > 2.0 or old_vol > 100:
                asyncio.run(self._send_alert(avg_inflow, old_vol))

        except Exception as e:
            logger.error(f"Scan Runtime Error: {e}")

    async def _send_alert(self, inflow, old_vol):
        """Asynchronous Telegram Sender"""
        msg = f"📡 **RADAR DETECTED MOVEMENT**\n"
        msg += f"──────────────────────\n"
        msg += f"📊 **Exchange Inflow (Avg):** {inflow:.2f} BTC\n"
        
        if old_vol > 500:
            msg += f"💀 **WHALE ALERT:** {old_vol:.0f} BTC (3y+ old) moved!\n"
        elif old_vol > 0:
            msg += f"⏳ **Old Coins:** {old_vol:.0f} BTC moved.\n"
            
        msg += f"──────────────────────\n"
        
        if inflow > 5.0:
            msg += "🚨 **HIGH DUMP RISK** 🚨"
        
        try:
            await self.bot.send_message(chat_id=Config.CHAT_ID, text=msg)
            logger.info("Alert sent to Telegram.")
        except Exception as e:
            logger.error(f"Telegram Error: {e}")

# --- INIT ---
radar = CryptoRadar()
scheduler = BackgroundScheduler()
# Run immediately on startup to check health, then every interval
scheduler.add_job(func=radar.scan, trigger="interval", minutes=Config.INTERVAL_MINUTES)
scheduler.start()

@app.route('/')
def health():
    return "Radar 10000/10 is Active and Scanning... 📡"

if __name__ == "__main__":
    # Use PORT 10000 or whatever Render assigns
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

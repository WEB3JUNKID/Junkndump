import os
import logging
import asyncio
from datetime import datetime, timedelta, timezone
import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot

# --- LOGGING SETUP ---
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
    INTERVAL_MINUTES = 10 

# --- THE RADAR CORE ---
class CryptoRadar:
    def __init__(self):
        self.token = None
        self.token_expiry = datetime.now(timezone.utc)
        self.bot = Bot(token=Config.TELEGRAM_TOKEN)

    def _refresh_token(self):
        if self.token and datetime.now(timezone.utc) < self.token_expiry:
            return 
        
        url = "https://oauth2.bitquery.io/oauth2/token"
        payload = {
            'grant_type': 'client_credentials',
            'client_id': Config.BITQUERY_ID,
            'client_secret': Config.BITQUERY_SECRET,
            'scope': 'api'
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        
        try:
            response = requests.post(url, headers=headers, data=payload)
            response.raise_for_status()
            data = response.json()
            self.token = data.get('access_token')
            self.token_expiry = datetime.now(timezone.utc) + timedelta(hours=23)
            logger.info("Bitquery token refreshed.")
        except Exception as e:
            logger.error(f"Auth Critical Failure: {e}")

    def _get_dynamic_query(self):
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
            }}
            old_coins: inputs(age: {{gt: 1095}}, date: {{after: "{time_str}"}}) {{
              volume: value(calculate: sum)
            }}
          }}
        }}
        """

    def scan(self):
        self._refresh_token()
        if not self.token: return

        query = self._get_dynamic_query()
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

        try:
            res = requests.post("https://streaming.bitquery.io/graphql", json={"query": query}, headers=headers)
            data = res.json()['data']['bitcoin']
            
            avg_inflow = data['inflow'][0]['average'] if data['inflow'] else 0.0
            old_vol = data['old_coins'][0]['volume'] if data['old_coins'] else 0.0

            logger.info(f"Scan: Inflow {avg_inflow:.2f} | Old Vol {old_vol:.2f}")

            if avg_inflow > 2.0 or old_vol > 100:
                asyncio.run(self._send_alert(avg_inflow, old_vol))
        except Exception as e:
            logger.error(f"Scan Error: {e}")

    async def _send_alert(self, inflow, old_vol, is_test=False):
        prefix = "✅ **TEST MESSAGE**\n" if is_test else "📡 **RADAR ALERT**\n"
        msg = f"{prefix}──────────────────────\n"
        msg += f"📊 **Inflow Avg:** {inflow:.2f} BTC\n"
        msg += f"⏳ **Old Coins:** {old_vol:.2f} BTC\n"
        msg += f"──────────────────────"
        
        await self.bot.send_message(chat_id=Config.CHAT_ID, text=msg, parse_mode='Markdown')

# --- INITIALIZE ---
radar = CryptoRadar()

# --- ROUTES ---
@app.route('/')
def home():
    return """
    <div style="font-family:sans-serif; text-align:center; padding:50px;">
        <h1>Radar 10000/10 📡</h1>
        <p>Status: <b>Active and Scanning</b></p>
        <hr style="width:200px">
        <p>Confirm your Telegram credentials:</p>
        <a href="/test"><button style="padding:10px 20px; background:#0088cc; color:white; border:none; border-radius:5px; cursor:pointer;">Send Test Message</button></a>
    </div>
    """

@app.route('/test')
def test_route():
    try:
        asyncio.run(radar._send_alert(0.0, 0.0, is_test=True))
        return "<h3>Success! Check Telegram.</h3><a href='/'>Go Back</a>"
    except Exception as e:
        return f"<h3>Failed ❌</h3><p>{str(e)}</p><a href='/'>Go Back</a>"

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=radar.scan, trigger="interval", minutes=Config.INTERVAL_MINUTES)
scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
    

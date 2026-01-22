import os
import requests
import asyncio
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot

app = Flask(__name__)

# --- CONFIG (Set these in Render Environment Variables) ---
BITQUERY_ID = os.getenv("BITQUERY_ID")
BITQUERY_SECRET = os.getenv("BITQUERY_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def get_bitquery_token():
    """Uses ID and Secret to get a 24h Access Token."""
    url = "https://oauth2.bitquery.io/oauth2/token"
    payload = f'grant_type=client_credentials&client_id={BITQUERY_ID}&client_secret={BITQUERY_SECRET}&scope=api'
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    try:
        response = requests.post(url, headers=headers, data=payload)
        return response.json().get('access_token')
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def scan_bitcoin_radar():
    """The 10000/10 Radar Logic"""
    token = get_bitquery_token()
    if not token: return

    # GraphQL Query for Inflow Mean and Old Coin Movement
    query = """
    {
      bitcoin {
        inflow: transactions(
          options: {desc: "value", limit: 1}
          date: {after: "2026-01-20"} 
          outputAddress: {annotation: "Exchange"}
        ) {
          average: value(calculate: average)
        }
        old_coins: inputs(age: {gt: 1095}) {
          volume: value(calculate: sum)
        }
      }
    }
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    try:
        res = requests.post("https://streaming.bitquery.io/graphql", json={"query": query}, headers=headers)
        data = res.json()['data']['bitcoin']
        
        avg_inflow = data['inflow'][0]['average'] if data['inflow'] else 0
        old_vol = data['old_coins'][0]['volume'] if data['old_coins'] else 0

        # --- TRIGGER LOGIC ---
        if avg_inflow > 2.0:
            msg = f"🚨 **DUMP RADAR**\nMean Inflow: {avg_inflow:.2f} BTC\n"
            if old_vol > 500:
                msg += f"💀 **SMART MONEY EXIT**: {old_vol:.0f} BTC (3y+) moved!"
            
            asyncio.run(send_telegram(msg))
    except Exception as e:
        print(f"Scan Error: {e}")

async def send_telegram(msg):
    await Bot(token=TELEGRAM_TOKEN).send_message(chat_id=CHAT_ID, text=msg)

@app.route('/')
def health():
    return "Radar 10000/10 is Active and Scanning... 📡"

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=scan_bitcoin_radar, trigger="interval", minutes=10)
scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
    

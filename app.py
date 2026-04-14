import logging
import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import aiohttp
from bs4 import BeautifulSoup
import phonenumbers
from datetime import datetime
import json

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables (Render.com)
BOT_TOKEN = os.getenv('BOT_TOKEN')
NUMVERIFY_API_KEY = os.getenv('NUMVERIFY_API_KEY', '')

class PhoneOSINT:
    def __init__(self):
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]
    
    async def parse_number(self, number: str) -> dict:
        """Parse and validate phone number"""
        try:
            parsed = phonenumbers.parse(number)
            if phonenumbers.is_valid_number(parsed):
                return {
                    'e164': phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
                    'international': phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
                    'country': phonenumbers.region_code_for_number(parsed),
                    'carrier': phonenumbers.carrier.name_for_number(parsed, 'en') or 'Unknown'
                }
        except:
            pass
        return None
    
    async def numverify_lookup(self, number: str) -> dict:
        """NumVerify API lookup"""
        if not NUMVERIFY_API_KEY:
            return {}
        
        url = f"http://apilayer.net/api/validate?access_key={NUMVERIFY_API_KEY}&number={number}&format=1"
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={'User-Agent': self.user_agents[0]}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            'valid': data.get('valid', False),
                            'country_name': data.get('country_name', ''),
                            'location': data.get('location', ''),
                            'carrier': data.get('carrier', ''),
                            'line_type': data.get('line_type', '')
                        }
        except Exception as e:
            logger.error(f"Numverify error: {e}")
        return {}
    
    async def google_social(self, number: str) -> list:
        """Google dorks for social profiles"""
        queries = [
            f'"{number}" site:facebook.com OR site:instagram.com OR site:linkedin.com OR site:twitter.com OR site:t.me'
        ]
        
        results = []
        timeout = aiohttp.ClientTimeout(total=15)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for query in queries:
                try:
                    url = f"https://www.google.com/search?q={query}&num=10"
                    async with session.get(url, headers={'User-Agent': self.user_agents[0]}) as resp:
                        soup = BeautifulSoup(await resp.text(), 'html.parser')
                        for link in soup.find_all('a', href=True)[:5]:
                            href = link.get('href', '')
                            if any(site in href.lower() for site in ['facebook', 'instagram', 'linkedin', 'twitter', 't.me']):
                                platform = next((s for s in ['facebook', 'instagram', 'linkedin', 'twitter', 't.me'] if s in href.lower()), 'unknown')
                                results.append({'platform': platform, 'url': href[:100]})
                except:
                    continue
        return results[:10]
    
    async def full_scan(self, number: str) -> dict:
        """Complete OSINT reconnaissance"""
        parsed = await self.parse_number(number)
        if not parsed:
            return {'error': 'Invalid phone number format'}
        
        # Run parallel scans
        tasks = [
            self.numverify_lookup(number),
            self.google_social(number)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        report = {
            'number': parsed,
            'carrier_info': results[0] if isinstance(results[0], dict) else {},
            'social_profiles': results[1] if isinstance(results[1], list) else [],
            'scan_time': datetime.utcnow().isoformat()
        }
        return report

osint = PhoneOSINT()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot welcome message"""
    welcome = """
🔍 **Phone OSINT Bot**

Send any phone number for complete reconnaissance:

• 📍 Carrier + Location
• 🔗 Social Profiles  
• 🌐 Google Dorks
• 📊 Validation Status

**Example**: `+1-234-567-8900` or `+44 20 7946 0958`

*Deployed on Render.com - Production ready*
    """
    await update.message.reply_text(welcome, parse_mode='Markdown')

async def scan_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone number scans"""
    number = update.message.text.strip()
    status_msg = await update.message.reply_text("🔄 **Scanning...**\n\n⏳ This takes 20-45 seconds")
    
    try:
        report = await osint.full_scan(number)
        
        if 'error' in report:
            await status_msg.edit_text(f"❌ **Error**: {report['error']}")
            return
        
        # Build formatted response
        response = f"📱 **OSINT Report: {report['number']['international']}**\n\n"
        
        # Basic info
        response += f"🌍 **Country**: `{report['number']['country']}`\n"
        response += f"📡 **Carrier**: `{report['number']['carrier']}`\n\n"
        
        # Carrier validation
        carrier_info = report['carrier_info']
        if carrier_info:
            response += f"✅ **Validated**: {'✅ Yes' if carrier_info.get('valid') else '❌ No'}\n"
            if carrier_info.get('location'):
                response += f"📍 **Location**: `{carrier_info['location']}`\n"
            if carrier_info.get('carrier'):
                response += f"📶 **Network**: `{carrier_info['carrier']}`\n"
            response += "\n"
        
        # Social profiles
        socials = report['social_profiles']
        if socials:
            response += f"🔗 **Social Profiles** ({len(socials)} found):\n"
            for profile in socials[:8]:
                response += f"• `{profile['platform'].title()}`: {profile['url']}\n"
        else:
            response += "🔍 **No social profiles found**\n"
        
        response += f"\n⏰ **Scan completed**: {report['scan_time'][:19].replace('T', ' ')} UTC"
        
        await status_msg.edit_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Scan error: {e}")
        await status_msg.edit_text("❌ **Scan failed**. Try again or check number format.")

def main():
    """Render.com startup"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable required")
        return
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, scan_number))
    
    # Render.com logging
    logger.info("🚀 Phone OSINT Bot starting on Render.com...")
    logger.info(f"Bot token: {'✅ Set' if BOT_TOKEN else '❌ Missing'}")
    logger.info(f"NumVerify: {'✅ Set' if NUMVERIFY_API_KEY else 'ℹ️ Optional'}")
    
    # Polling with error handler
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

import asyncio
import json
import logging
from typing import List, Dict, Optional
from openai import OpenAI
# Import your Elementus code
# Make sure elementus.py is in the same directory or installed as a package
from elementus import ElementusClient, ElementusAPIError
from helper import *

# Load the environment variables
load_env()
################################################################################
# GLOBALS / CONFIG
################################################################################
THRESHOLD = 1
ELEMENTUS_API_KEY = get_elementus_api_key()
TELEGRAM_TOKEN = get_telegram_token()
TELEGRAM_CHANNEL_ID = get_telegram_channel_id()
OPENAI_API_KEY = get_openai_api_key()
OPENAI_PROMPT = """
You are an expert financial analyst specializing in Bitcoin blockchain analytics and market structure that receives a list of Bitcoin transactions from the most recent block with entity attribution added. 
Your task is to create a Telegram botmessage explaining the most important on-chain insights from those transactions, which may affect BTC/USD price. 
Be concise and provide just the message text, no additional comments or enclosing ```markdown tag.
Limit the text to 4000 characters. 
Exclude any Fastmoney_ transactions, miner block rewards and mining pool payouts, and outputs with less than 1 BTC value from analysis - do not mention what has been excluded. 
For every transaction hash you mention insert URL to Blockchain.com transaction page.

Step-by-Step Plan for Analyzing Transactions

1. Parse Incoming Transaction Data
	1.	Collect Raw JSON: Receive the latest batch of transactions in JSON format below.
	2.	Extract Key Fields: For each transaction, parse:
	•	hash (the transaction ID)
	•	inputs (if available) and associated input_entity
	•	outputs and associated receiving addresses, their values, and entity attributions
	•	The total BTC amounts transferred and any special flags (e.g., null outputs or inscriptions)

2. Classify Entities and Addresses
	1.	Identify Known Entities: Check if input_entity or outputs[...]entity is a recognized exchange, mining pool, OTC desk, etc.
	2.	Tag Unknown Addresses: Label new or untagged addresses as “wallet,” “unknown,” or “internal” if repeated often.

3. Calculate Net Entity Flow
	1.	Sum of Outputs to an Entity: If multiple outputs lead to the same recognized entity, combine them to see total inflow.
	2.	Compare vs. Previous Balances (if you maintain historical state):
	•	Has an entity’s overall BTC holdings changed significantly?
	•	Are we seeing large inflows/outflows from major exchanges (which often signal potential price movements)?

4. Identify Whale Movements or Large Transactions
	1.	Threshold Check: Flag transactions with values above a certain BTC threshold (e.g., 100 BTC, 500 BTC, etc.).
	2.	Look for Whale or Custodial Splits: Large transactions sometimes get split among multiple addresses—track if a single large input is distributed across many addresses.

5. Spot Potential Price-Impacting Activity
	1.	Exchange Deposits (inflows to known exchange deposit addresses) can signal potential selling.
	2.	Exchange Withdrawals (outflows from known exchange addresses to private wallets) can suggest HODLing or bullish sentiment.
	3.	Movements by High-Volume OTC Desks (e.g., cumberland.io, galaxy.com, wintermute.com) sometimes precede big trades.

6. Highlight Any Unusual or Repetitive Patterns
	1.	Repeated large movements from the same entity within a short time may indicate systematic accumulation or distribution.
	2.	Movement to aggregator/mixer addresses might hint at privacy moves or institutional reorganizations.

7. Summarize Insights and Potential Market Impact
	1.	Bullet or Short Paragraph explaining major inflows/outflows, top whales, major exchange net flows, and any relevant patterns.
	2.	Assess Sentiment: Is the net flow into exchanges (possible short-term selling pressure) or out of exchanges (possible bullish sign)?
	3.	Conclude with how these data points may affect BTC/USD price or general market structure.

JSON content

"""

import websockets
from telegram import Bot
from aiohttp import ClientSession, ClientTimeout

class WebSocketTelegramBridge:
    def __init__(self, telegram_token: str, telegram_channel_id: str, websocket_url: str):
        """Initialize the bridge with necessary credentials and configuration."""
        self.openai = OpenAI(api_key=OPENAI_API_KEY)
        self.telegram_token = telegram_token
        self.channel_id = telegram_channel_id
        self.websocket_url = websocket_url
        self.bot: Optional[Bot] = None
        # Configure logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    async def setup_elementus_client(self):
        """Initialize the Elementus client."""
        self.elementus_client = ElementusClient(api_key=ELEMENTUS_API_KEY)
        try:
            result = await self.elementus_client.check_health()
            if not result:
                raise Exception("Elementus client is not healthy!")
        except Exception as e:
            self.logger.error(f"Failed to initialize Elementus client: {str(e)}")    
        finally:
            await self.elementus_client.close()

    async def get_tx_attributions(self, transactions: List[Dict]):
        """Get address attributions from Elementus."""
        addresses = set()
        txs = []
        for tx in transactions:
            tx_stripped = {
                'hash': tx['hash'],
                'inputs': [inp.get('prev_out', {}).get('addr') for inp in tx.get('inputs', [])],
                'outputs': {out.get('addr'): {'value': out.get('value', 0) / 100_000_000} for out in tx.get('out', [])}
            }
            if any(out['value'] > THRESHOLD for out in tx_stripped['outputs'].values()):
                txs.append(tx_stripped)
                addresses.update(tx_stripped['inputs'])
                addresses.update(tx_stripped['outputs'].keys())

        addresses = list(filter(None, addresses))
        ret = {}
        try:
            result = await self.elementus_client.get_address_attributions(addresses)
            # Convert Pydantic model to dict for JSON serialization
            attributions = {addr: data.get('entity') for addr, data in result.model_dump()['data'].items()}

            for tx in txs:
                for addr in tx['inputs']:
                    if addr in attributions:
                        tx['input_entity'] = attributions[addr]
                        break
                for addr, output in tx['outputs'].items():
                    if output['value'] < THRESHOLD or addr in tx['inputs']:
                        continue
                    if addr in attributions:
                        if attributions[addr] == tx.get('input_entity', None):
                            continue
                        output['entity'] = attributions[addr]
                tx.pop('inputs')
            return txs

        except Exception as e:
            self.logger.error(f"Failed to get address attributions: {str(e)}")
            return None

    async def setup_telegram_bot(self):
        """Initialize the Telegram bot."""
        self.bot = Bot(token=self.telegram_token)

    async def send_to_telegram(self, message: str):
        """Send a message to the configured Telegram channel using Markdown formatting."""
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode='Markdown'
            )
            self.logger.info(f"Message sent to Telegram: {message[:50]}...")
        except Exception as e:
            self.logger.error(f"Failed to send message to Telegram: {str(e)}")

    async def process_websocket_message(self, message: str):
        """Process incoming WebSocket message and prepare it for Telegram using Markdown formatting."""
        try:
            attributions = []
            # Parse the message
            block_data = json.loads(message)
            # Retrieve full block data
            block_hash = block_data.get('x', {}).get('hash')
            if block_hash:
                async with ClientSession(timeout=ClientTimeout(total=10)) as session:
                    await asyncio.sleep(5)
                    async with session.get(f"https://blockchain.info/rawblock/{block_hash}") as response:
                        if response.status == 200:
                            full_block_data = await response.json()
                            # Process full_block_data as needed
                            attributions = await self.get_tx_attributions(full_block_data['tx'])
                            completion = self.openai.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": OPENAI_PROMPT + '\n' + json.dumps(attributions)},], temperature=0)
                        else:
                            raise Exception(f"Failed to process block data! Status: {response.status}")
            else:
                raise Exception("Block hash not found in the message!")
            
            # Format the message for Telegram using Markdown
            formatted_message = (   
                f"*Block Height:* {block_data.get('x', {}).get('height', 'N/A')}\n"
                f"*Number of Transactions:* {block_data.get('x', {}).get('nTx', 'N/A')}\n"
                f"\n{completion.choices[0].message.content}\n"
            )
            # Escape special characters for MarkdownV2
            #formatted_message = formatted_message.replace('.', '\\.').replace('-', '\\-').replace('_', '\\_').replace('!', '\\!').replace('(', '\\(').replace(')', '\\)').replace('[', '\\[').replace(']', '\\]')
            
            await self.send_to_telegram(formatted_message)
        except json.JSONDecodeError:
            self.logger.error("Failed to parse WebSocket message as JSON")
        except Exception as e:
            self.logger.error(f"Error processing message: {str(e)}")

    async def websocket_listener(self):
        """Main WebSocket connection handler."""
        while True:
            try:
                async with websockets.connect(self.websocket_url) as websocket:
                    self.logger.info(f"Connected to WebSocket at {self.websocket_url}")
                    
                    # Send subscription message
                    ping_message = {"op": "ping_block"}
                    await websocket.send(json.dumps(ping_message))
                    subscription_message = {"op": "blocks_sub"}
                    await websocket.send(json.dumps(subscription_message))
                    self.logger.info(f"Sent subscription message: {subscription_message}")
                    
                    while True:
                        message = await websocket.recv()
                        self.logger.debug(f"Received message: {message[:50]}...")
                        await self.process_websocket_message(message)
                        
            except websockets.exceptions.ConnectionClosed:
                self.logger.warning("WebSocket connection closed, attempting to reconnect...")
                await asyncio.sleep(5)  # Wait before reconnecting
            except Exception as e:
                self.logger.error(f"WebSocket error: {str(e)}")
                await asyncio.sleep(5)  # Wait before reconnecting

    async def run(self):
        """Start the bridge."""
        await self.setup_telegram_bot()
        await self.setup_elementus_client()
        await self.websocket_listener()

def main():
    # Configuration - replace with your actual values
    WEBSOCKET_URL = "wss://ws.blockchain.info/inv"

    # Create and run the bridge
    bridge = WebSocketTelegramBridge(
        telegram_token=TELEGRAM_TOKEN,
        telegram_channel_id=TELEGRAM_CHANNEL_ID,
        websocket_url=WEBSOCKET_URL
    )

    # Run the async event loop
    asyncio.run(bridge.run())

if __name__ == "__main__":
    main()
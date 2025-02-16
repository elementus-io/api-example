# Add your utilities or helper functions to this file.

import os
from dotenv import load_dotenv, find_dotenv

# these expect to find a .env file at the directory above the lesson.                                                                                                                     # the format for that file is (without the comment)                                                                                                                                       #API_KEYNAME=AStringThatIsTheLongAPIKeyFromSomeService                                                                                                                                     
def load_env():
    _ = load_dotenv(find_dotenv())

def get_gbq_uri():
    return os.getenv('GBQ_URI')

def get_elementus_api_key():
    return os.getenv('ELEMENTUS_API_KEY')

def get_blockchain_ws_url():
    return os.getenv('BLOCKCHAIN_WS_URL')

def get_xai_api_key():
    return os.getenv('XAI_API_KEY')

def get_twitter_access_token():
    return os.getenv('TWITTER_ACCESS_TOKEN')

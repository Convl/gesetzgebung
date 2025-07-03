import os
from openai import OpenAI

AI_API_KEY = os.environ.get("OPENROUTER_API_KEY")
AI_ENDPOINT = "https://openrouter.ai/api/v1"
client = OpenAI(base_url=AI_ENDPOINT, api_key=AI_API_KEY)

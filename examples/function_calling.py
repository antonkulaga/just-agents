#from just_agents.chat_agent import ChatAgent
import json
import pprint

from dotenv import load_dotenv

import just_agents.llm_options
from just_agents.llm_session import LLMSession

load_dotenv()

def get_current_weather(location):
    """Gets the current weather in a given location"""
    if "tokyo" in location.lower():
        return json.dumps({"location": "Tokyo", "temperature": "10", "unit": "celsius"})
    elif "san francisco" in location.lower():
        return json.dumps({"location": "San Francisco", "temperature": "72", "unit": "fahrenheit"})
    elif "paris" in location.lower():
        return json.dumps({"location": "Paris", "temperature": "22", "unit": "celsius"})
    else:
        return json.dumps({"location": location, "temperature": "unknown"})


session: LLMSession = LLMSession(
    llm_options=just_agents.llm_options.LLAMA3,
    functions=[get_current_weather]
)
session.memory.add_on_message(lambda m: pprint.pprint(m.content) if m.content is not None else None)
session.query("What's the weather like in San Francisco, Tokyo, and Paris?")
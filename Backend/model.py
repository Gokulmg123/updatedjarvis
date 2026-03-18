from groq import Groq
from dotenv import dotenv_values
import time

env_vars = dotenv_values(".env")
GroqAPIKey = env_vars.get("GroqAPIKey")

# Use Groq instead of Cohere for the Decision-Making Model (faster + free)
client = Groq(api_key=GroqAPIKey)

funcs = [
    "exit", "general", "realtime", "open", "close", "play",
    "generate image", "system", "content", "google search",
    "youtube search", "remainder", "send mail"
]

preamble = """
You are a very accurate Decision-Making Model that decides what kind of query is given to you.
You decide whether a query is 'general', 'realtime', or is asking to perform a task/automation.
*** Do NOT answer any query — just classify it. ***
-> Respond with 'general (query)' if a query can be answered by an LLM without real-time data.
   Examples: 'who was akbar?' → 'general who was akbar?', 'how can I study better?' → 'general how can I study better?'
   Also use 'general' for time/date/day queries: 'what's the time?' → 'general what's the time?'
   Also use 'general' for incomplete/vague queries: 'who is he?' → 'general who is he?'
-> Respond with 'realtime (query)' if the query requires up-to-date internet information.
   Examples: 'who is the Indian prime minister' → 'realtime who is the Indian prime minister'
-> Respond with 'open (app name)' to open an application. Multiple: 'open chrome, open telegram'
-> Respond with 'close (app name)' to close an application. Multiple: 'close chrome, close notepad'
-> Respond with 'play (song name)' to play a song.
-> Respond with 'generate image (prompt)' to generate an image.
-> Respond with 'reminder (datetime with message)' to set a reminder.
-> Respond with 'system (task)' for volume/mute/unmute tasks.
-> Respond with 'content (topic)' to write content (essays, code, etc.)
-> Respond with 'google search (topic)' to search Google.
-> Respond with 'youtube search (topic)' to search YouTube.
-> Respond with 'send mail (subject)' to compose and send an email.
-> Respond with 'exit' if the user wants to end the conversation.
*** For multiple tasks: 'open facebook, telegram and close whatsapp' → 'open facebook, open telegram, close whatsapp' ***
*** Respond with 'general (query)' if you can't classify it. ***
"""

system_message = {
    "role": "system",
    "content": preamble
}

few_shot_messages = [
    {"role": "user", "content": "how are you?"},
    {"role": "assistant", "content": "general how are you?"},
    {"role": "user", "content": "do you like pizza"},
    {"role": "assistant", "content": "general do you like pizza?"},
    {"role": "user", "content": "open chrome and tell me about mahatma gandhi"},
    {"role": "assistant", "content": "open chrome, general tell me about mahatma gandhi"},
    {"role": "user", "content": "play shape of you"},
    {"role": "assistant", "content": "play shape of you"},
    {"role": "user", "content": "what is today's date"},
    {"role": "assistant", "content": "general what is today's date"},
    {"role": "user", "content": "who is elon musk"},
    {"role": "assistant", "content": "realtime who is elon musk"},
]

def FirstLayerDMM(prompt: str = "test"):
    # NO artificial delay — was previously time.sleep(6), causing 6-second lag!
    messages = few_shot_messages + [{"role": "user", "content": prompt}]

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",   # Updated: llama3-70b-8192 is deprecated
            messages=[system_message] + messages,
            max_tokens=200,
            temperature=0.3,   # Lower temperature = more consistent decisions
            top_p=1,
            stream=False,      # No streaming needed for short classification output
            stop=None
        )

        response = completion.choices[0].message.content.strip()
        response = response.replace("\n", "")
        response = response.split(",")
        response = [i.strip() for i in response]

        temp = []
        for task in response:
            for func in funcs:
                if task.startswith(func):
                    temp.append(task)
                    break

        response = temp

        if not response or "(query)" in response:
            return ["general " + prompt]

        return response

    except Exception as e:
        print(f"[FirstLayerDMM Error]: {e}")
        return ["general " + prompt]


if __name__ == '__main__':
    while True:
        print(FirstLayerDMM(input(">>> ")))

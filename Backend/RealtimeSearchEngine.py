from duckduckgo_search import DDGS
from groq import Groq
from json import load, dump, JSONDecodeError
import datetime
from dotenv import dotenv_values

# =========================
# LOAD ENV VARIABLES
# =========================

env_vars = dotenv_values(".env")

Username = env_vars.get("Username")
Assistantname = env_vars.get("Assistantname")
GroqAPIKey = env_vars.get("GroqAPIKey")

# =========================
# GROQ CLIENT
# =========================

client = Groq(api_key=GroqAPIKey)

# =========================
# SYSTEM PROMPT
# =========================

System = f"""
Hello, I am {Username}.

You are a highly advanced AI assistant named {Assistantname} with access to real-time internet search results.

Provide answers professionally using proper grammar, punctuation, and formatting.

Use the provided real-time search data whenever necessary.

Do not mention that you are using search results unless asked.
"""

# =========================
# LOAD CHAT HISTORY
# =========================

try:
    with open(r"Data\ChatLog.json", "r") as f:
        messages = load(f)

except (FileNotFoundError, JSONDecodeError):

    with open(r"Data\ChatLog.json", "w") as f:
        dump([], f)

    messages = []

# =========================
# REALTIME SEARCH FUNCTION
# =========================

def DuckDuckGoSearch(query):

    try:

        Answer = f"Real-time search results for '{query}':\n[start]\n\n"

        with DDGS() as ddgs:

            results = list(ddgs.text(query, max_results=5))

            if not results:
                return "No real-time search results found."

            for index, result in enumerate(results, start=1):

                title = result.get("title", "No Title")
                body = result.get("body", "No Description")
                href = result.get("href", "No Link")

                Answer += (
                    f"Result {index}:\n"
                    f"Title: {title}\n"
                    f"Description: {body}\n"
                    f"Link: {href}\n\n"
                )

        Answer += "[end]"

        print("\n========== SEARCH RESULTS ==========\n")
        print(Answer)
        print("\n====================================\n")

        return Answer

    except Exception as e:

        print(f"[DuckDuckGoSearch Error]: {e}")

        return f"Could not retrieve search results for '{query}'."

# =========================
# CLEAN ANSWER
# =========================

def AnswerModifier(answer):

    lines = answer.split("\n")

    non_empty_lines = [line for line in lines if line.strip()]

    return "\n".join(non_empty_lines)

# =========================
# REALTIME DATE/TIME INFO
# =========================

def Information():

    current_datetime = datetime.datetime.now()

    day = current_datetime.strftime("%A")
    date = current_datetime.strftime("%d")
    month = current_datetime.strftime("%B")
    year = current_datetime.strftime("%Y")
    hour = current_datetime.strftime("%H")
    minute = current_datetime.strftime("%M")
    second = current_datetime.strftime("%S")

    data = (
        f"Current Date and Time Information:\n"
        f"Day: {day}\n"
        f"Date: {date}\n"
        f"Month: {month}\n"
        f"Year: {year}\n"
        f"Time: {hour}:{minute}:{second}\n"
    )

    return data

# =========================
# MAIN REALTIME ENGINE
# =========================

def RealtimeSearchEngine(prompt):

    global messages

    # =========================
    # LOAD CHAT HISTORY AGAIN
    # =========================

    try:

        with open(r"Data\ChatLog.json", "r") as f:
            messages = load(f)

    except (FileNotFoundError, JSONDecodeError):

        messages = []

    # =========================
    # ADD USER MESSAGE
    # =========================

    messages.append(
        {
            "role": "user",
            "content": prompt
        }
    )

    # =========================
    # GET REALTIME SEARCH DATA
    # =========================

    realtime_search = DuckDuckGoSearch(prompt)

    # =========================
    # PREPARE CONTEXT
    # =========================

    context_messages = [

        {
            "role": "system",
            "content": System
        },

        {
            "role": "system",
            "content": Information()
        },

        {
            "role": "system",
            "content": realtime_search
        }

    ] + messages

    # =========================
    # GENERATE AI RESPONSE
    # =========================

    try:

        completion = client.chat.completions.create(

            model="llama-3.1-8b-instant",

            messages=context_messages,

            temperature=0.7,

            max_tokens=2048,

            top_p=1,

            stream=False

        )

        Answer = completion.choices[0].message.content

        Answer = Answer.strip().replace("</s>", "")

        # =========================
        # SAVE ASSISTANT RESPONSE
        # =========================

        messages.append(
            {
                "role": "assistant",
                "content": Answer
            }
        )

        with open(r"Data\ChatLog.json", "w") as f:

            dump(messages, f, indent=4)

        return AnswerModifier(Answer)

    except Exception as e:

        print(f"[RealtimeSearchEngine Error]: {e}")

        return "I encountered an issue while processing your request."

# =========================
# MAIN LOOP
# =========================

if __name__ == "__main__":

    while True:

        prompt = input("\nEnter your query: ")

        if prompt.lower() == "exit":
            break

        response = RealtimeSearchEngine(prompt)

        print("\nAssistant:\n")
        print(response)
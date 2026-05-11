from Frontend.GUI import (
    ChatSection,
    GraphicalUserInterface,
    SetAssistantStatus,
    ShowTextToScreen,
    TempDirectoryPath,
    SetMicrophoneStatus,
    AnswerModifier,
    QueryModifier,
    GetMicrophoneStatus,
    GetAssistantStatus
)
from Backend.sendmail import sendmail
from Backend.model import FirstLayerDMM
from Backend.RealtimeSearchEngine import RealtimeSearchEngine
from Backend.Automation import Automation
from Backend.SpeechToText import SpeechRecognition
from Backend.Chatbot import ChatBot
from Backend.TextToSpeech import TextToSpeech
from dotenv import dotenv_values
from asyncio import run
from time import sleep
import subprocess
import threading
import json
import sys
import os

env_vars = dotenv_values(".env")
Username = env_vars.get("Username")
Assistantname = env_vars.get("Assistantname")
DefaultMessage = f'''{Username} : Hello {Assistantname}, How are you?
{Assistantname} : Welcome {Username}. I am doing well. How may I help you?'''
subprocesses = []
Functions = ["open", "close", "play", "system", "content", "google search", "youtube search", "send mail"]

def ResetChatLog():
    path = r'Data\ChatLog.json'

    try:
        # create file if missing
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump([], f)

        # reset content
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4)

        print("[INFO] ChatLog reset successfully.")

    except Exception as e:
        print(f"[ResetChatLog Error]: {e}")

def ShowDefaultChatIfNoChats():
    try:
        with open(r'Data\ChatLog.json', "r", encoding='utf-8') as File:
            if len(File.read()) < 5:
                with open(TempDirectoryPath('Database.data'), 'w', encoding='utf-8') as file:
                    file.write("")
                with open(TempDirectoryPath('Responses.data'), 'w', encoding='utf-8') as file:
                    file.write(DefaultMessage)
    except Exception as e:
        print(f"[ShowDefaultChatIfNoChats Error]: {e}")


def ReadChatLogJson():
    try:
        with open(r'Data\ChatLog.json', 'r', encoding='utf-8') as file:
            Chatlog_data = json.load(file)
        return Chatlog_data
    except Exception:
        return []


def ChatLogIntegration():
    json_data = ReadChatLogJson()
    formatted_chatlog = ""
    for entry in json_data:
        if entry["role"] == "user":
            formatted_chatlog += f"User: {entry['content']}\n"
        elif entry["role"] == "assistant":
            formatted_chatlog += f"Assistant: {entry['content']}\n"
    formatted_chatlog = formatted_chatlog.replace("User", Username + " ")
    formatted_chatlog = formatted_chatlog.replace("Assistant", Assistantname + " ")

    with open(TempDirectoryPath('Database.data'), 'w', encoding='utf-8') as file:
        file.write(AnswerModifier(formatted_chatlog))


def ShowChatsOnGUI():
    try:
        with open(TempDirectoryPath('Database.data'), "r", encoding='utf-8') as File:
            Data = File.read()
        if len(str(Data)) > 0:
            lines = Data.split('\n')
            result = '\n'.join(lines)
            with open(TempDirectoryPath('Responses.data'), "w", encoding='utf-8') as File:
                File.write(result)
    except Exception as e:
        print(f"[ShowChatsOnGUI Error]: {e}")


def InitialExecution():
    ResetChatLog() 
    SetMicrophoneStatus("False")
    ShowTextToScreen("")
    ShowDefaultChatIfNoChats()
    ChatLogIntegration()
    ShowChatsOnGUI()


InitialExecution()


def GetTextQuery():
    """Read text query from file (written by GUI when user submits text input)."""
    try:
        query_file = TempDirectoryPath('UserQuery.data')
        with open(query_file, "r", encoding='utf-8') as file:
            query = file.read().strip()
        if query:
            with open(query_file, "w", encoding='utf-8') as file:
                file.write("")
            return query
    except Exception:
        pass
    return ""


# Phrases the user can say to confirm a pending email send.
_EMAIL_CONFIRM_PHRASES = {
    "yes", "yes send it", "yes send", "send it", "send now",
    "confirm email", "confirm", "ok send it", "okay send it", "sure send it",
}


def MainExecution():
    TaskExecution = False
    ImageExecution = False
    ImageGenerationQuery = ""

    # Check for text input first (non-blocking), then fall back to speech
    TextQuery = GetTextQuery()

    if TextQuery:
        Query = QueryModifier(TextQuery)
        ShowTextToScreen(f"{Username} : {TextQuery}")

    else:
        SetAssistantStatus("Listening ... ")
        Query = SpeechRecognition()

        if not Query or not Query.strip():
            SetAssistantStatus("Available ... ")
            return False

        ShowTextToScreen(f"{Username} : {Query}")

    SetMicrophoneStatus("False")

    # ── EMAIL CONFIRMATION INTERCEPT ────────────────────────────────────────
    # Must happen BEFORE FirstLayerDMM, because the AI will classify
    # "yes send it" as "general yes send it" and the send mail branch
    # is never reached. We check here directly.
    import Backend.sendmail as _sm
    raw_lower = Query.lower().strip().rstrip(".?!")
    if raw_lower in _EMAIL_CONFIRM_PHRASES and _sm._pending_email:
        SetAssistantStatus("Sending email...")
        result = sendmail("", confirm=True)
        ShowTextToScreen(f"{Assistantname} : {result}")
        TextToSpeech(result)
        SetAssistantStatus("Available ... ")
        return True

    # ── ABORT / CANCEL PENDING EMAIL ────────────────────────────────────────
    cancel_phrases = {"cancel email", "cancel", "no", "abort", "don't send", "dont send"}
    if raw_lower in cancel_phrases and _sm._pending_email:
        _sm._pending_email.clear()
        msg = "Okay, email cancelled."
        ShowTextToScreen(f"{Assistantname} : {msg}")
        TextToSpeech(msg)
        SetAssistantStatus("Available ... ")
        return True
    # ────────────────────────────────────────────────────────────────────────

    SetAssistantStatus("Thinking... ")
    Decision = FirstLayerDMM(Query)

    print(f"\nDecision : {Decision}\n")

    G = any([i for i in Decision if i.startswith("general")])
    R = any([i for i in Decision if i.startswith("realtime")])

    Mearged_query = " and ".join(
        [" ".join(i.split()[1:]) for i in Decision if i.startswith("general") or i.startswith("realtime")]
    )

    for queries in Decision:
        if "generate " in queries:
            ImageGenerationQuery = str(queries)
            ImageExecution = True

    # ── Step 1: Run automation tasks (open/close/play/system/content/google search/youtube search) ──
    # We do this ONCE (not inside a per-query loop) so Automation() receives the full
    # decision list and only fires a single time.
    if not TaskExecution:
        if any(any(q.startswith(func) for func in Functions) for q in Decision):
            run(Automation(list(Decision)))
            TaskExecution = True

    # ── Step 2: Launch image generation in a background thread ──────────────
    if ImageExecution:
        from Backend.ImageGeneration import GenerateImages as _GenImages

        # Strip the "generate image " prefix that the decision model adds
        img_prompt = ImageGenerationQuery.replace("generate image ", "").strip()

        data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "Frontend", "Files", "ImageGeneration.data")

        def _run_image_gen(prompt, df):
            try:
                _GenImages(prompt)
            except Exception as e:
                print(f"[ImageGen Error]: {e}")
            finally:
                # Always mark done — even on failure — so the flag doesn't stay True
                try:
                    with open(df, "w", encoding="utf-8") as f:
                        f.write("False,False")
                except Exception:
                    pass

        # Mark as in-progress
        with open(data_file, "w", encoding="utf-8") as file:
            file.write(f"{img_prompt},True")

        t = threading.Thread(target=_run_image_gen,
                             args=(img_prompt, data_file),
                             daemon=True)
        t.start()
        print(f"[ImageGen] Generation thread started for: '{img_prompt}'")

    # ── Step 3: If there were no general/realtime queries, we're done ─────────
    # Pure automation commands (open/close/play etc.) should return here.
    if not G and not R:
        if TaskExecution or ImageExecution:
            SetAssistantStatus("Available ... ")
            return True

    # ── Step 4: Handle realtime or general queries ────────────────────────────
    if G and R or R:
        SetAssistantStatus("Searching ...")
        Answer = RealtimeSearchEngine(QueryModifier(Mearged_query))
        ShowTextToScreen(f"{Assistantname} : {Answer}")
        SetAssistantStatus("Answering ... ")
        TextToSpeech(Answer)
        return True

    else:
        for Queries in Decision:

            if "general" in Queries:
                SetAssistantStatus("Thinking ... ")
                QueryFinal = Queries.replace("general ", "")
                Answer = ChatBot(QueryModifier(QueryFinal))
                ShowTextToScreen(f"{Assistantname} : {Answer}")
                SetAssistantStatus("Answering ... ")
                TextToSpeech(Answer)
                return True

            elif "realtime" in Queries:
                SetAssistantStatus("Searching ... ")
                QueryFinal = Queries.replace("realtime ", "")
                Answer = RealtimeSearchEngine(QueryModifier(QueryFinal))
                ShowTextToScreen(f"{Assistantname} : {Answer}")
                SetAssistantStatus("Answering ... ")
                TextToSpeech(Answer)
                return True

            elif "send mail" in Queries:
                SetAssistantStatus("Composing email...")
                QueryFinal = Queries.replace("send mail", "").strip()
                # First call only — returns a preview asking for confirmation.
                # The actual send is handled by the intercept block above
                # BEFORE FirstLayerDMM so the AI never swallows "yes send it".
                result = sendmail(QueryFinal)
                ShowTextToScreen(f"{Assistantname} : {result}")
                TextToSpeech(result)
                SetAssistantStatus("Available ... ")

            elif "exit" in Queries:
                QueryFinal = "Okay, Bye!"
                Answer = ChatBot(QueryModifier(QueryFinal))
                ShowTextToScreen(f"{Assistantname} : {Answer}")
                SetAssistantStatus("Answering ... ")
                TextToSpeech(Answer)
                sys.exit(0)  # FIXED: was os._exit(1) which skips all cleanup


def FirstThread():
    while True:
        CurrentStatus = GetMicrophoneStatus()

        if CurrentStatus == "True":
            MainExecution()
            # FIX: Only reset mic here if MainExecution didn't already reset it
            # (text input path doesn't reset it inside MainExecution).
            # Safe to call again — writing "False" when already "False" is harmless.
            SetMicrophoneStatus("False")

        else:
            AIStatus = GetAssistantStatus()
            if "Available ... " in AIStatus:
                sleep(0.1)
            else:
                SetAssistantStatus("Available ... ")


def SecondThread():
    GraphicalUserInterface()


if __name__ == "__main__":
    thread2 = threading.Thread(target=FirstThread, daemon=True)
    thread2.start()
    SecondThread()
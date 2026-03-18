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
import os

env_vars = dotenv_values(".env")
Username = env_vars.get("Username")
Assistantname = env_vars.get("Assistantname")
DefaultMessage = f'''{Username} : Hello {Assistantname}, How are you?
{Assistantname} : Welcome {Username}. I am doing well. How may I help you?'''
subprocesses = []
Functions = ["open", "close", "play", "system", "content", "google search", "youtube search", "send mail"]


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
        # FIX: Set status so user knows assistant is listening
        SetAssistantStatus("Listening ... ")
        Query = SpeechRecognition()

        # FIX: If mic was turned off mid-capture or nothing was heard, bail
        # out cleanly without processing an empty/partial query.
        if not Query or not Query.strip():
            SetAssistantStatus("Available ... ")
            return False

        ShowTextToScreen(f"{Username} : {Query}")

    # FIX: Immediately turn off mic AFTER we have a confirmed, non-empty query.
    # In the old code this happened in FirstThread AFTER MainExecution returned,
    # which meant a second trigger could fire before the first finished.
    SetMicrophoneStatus("False")

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

    for queries in Decision:
        if TaskExecution == False:
            if any(queries.startswith(func) for func in Functions):
                run(Automation(list(Decision)))
                TaskExecution = True

        if ImageExecution == True:
            with open(r"Frontend\Files\ImageGeneration.data", "w") as file:
                file.write(f"{ImageGenerationQuery},True")

            try:
                p1 = subprocess.Popen(['python', r'Backend\ImageGeneration.py'],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      stdin=subprocess.PIPE, shell=False)
                subprocesses.append(p1)
            except Exception as e:
                print(f"Error starting ImageGeneration.py: {e}")

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
                    SetAssistantStatus("Sending email...")
                    QueryFinal = Queries.replace("send mail", "").strip()
                    sendmail(QueryFinal)
                    SetAssistantStatus("Email sent successfully.")

                elif "exit" in Queries:
                    QueryFinal = "Okay, Bye!"
                    Answer = ChatBot(QueryModifier(QueryFinal))
                    ShowTextToScreen(f"{Assistantname} : {Answer}")
                    SetAssistantStatus("Answering ... ")
                    TextToSpeech(Answer)
                    os._exit(1)


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
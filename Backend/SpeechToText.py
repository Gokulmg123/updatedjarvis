from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import dotenv_values
import os
import mtranslate as mt

env_Vars = dotenv_values(".env")
InputLanguage = env_Vars.get("InputLanguage")

HtmlCode = '''<!DOCTYPE html>
<html lang="en">
<head>
    <title>Speech Recognition</title>
</head>
<body>
    <button id="start" onclick="startRecognition()">Start Recognition</button>
    <button id="end" onclick="stopRecognition()">Stop Recognition</button>
    <p id="output"></p>
    <script>
        const output = document.getElementById('output');
        let recognition;

        function startRecognition() {
            output.textContent = "";
            recognition = new webkitSpeechRecognition() || new SpeechRecognition();
            recognition.lang = '';
            recognition.continuous = true;

            recognition.onresult = function(event) {
                const transcript = event.results[event.results.length - 1][0].transcript;
                output.textContent += transcript;
            };

            recognition.onend = function() {
                recognition.start();
            };
            recognition.start();
        }

        function stopRecognition() {
            recognition.stop();
            output.innerHTML = "";
        }
    </script>
</body>
</html>'''

HtmlCode = str(HtmlCode).replace("recognition.lang = '';", f"recognition.lang = '{InputLanguage}';")

with open(r"Data\Voice.html", "w") as f:
    f.write(HtmlCode)

current_dir = os.getcwd()
Link = f"{current_dir}/Data/Voice.html"

chrome_options = Options()
user_agent = "Mozilla/5.0(Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.142.86 Safari/537.36"
chrome_options.add_argument(f"user-agent={user_agent}")   # FIX: was "user=agent=" (typo)
chrome_options.add_argument("--use-fake-ui-for-media-stream")
chrome_options.add_argument("--use-fake-device-for-media-stream")
chrome_options.add_argument("--headless=new")             # FIX: "now" is deprecated, use "new"

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)

TempDirPath = rf"{current_dir}/Frontend/Files"


def SetAssistantStatus(Status):
    with open(rf'{TempDirPath}/Status.data', "w", encoding='utf-8') as file:
        file.write(Status)


def GetMicrophoneStatus():
    try:
        with open(rf'{TempDirPath}/Mic.data', "r", encoding='utf-8') as file:
            return file.read().strip()
    except Exception:
        return "False"


def QueryModifier(Query):
    new_query = Query.lower().strip()
    query_words = new_query.split()
    if not query_words:
        return ""
    question_words = ["how", "what", "who", "where", "when", "why", "which",
                      "whose", "whom", "can you", "what's", "where's", "how's"]

    if any(word + " " in new_query for word in question_words):
        if query_words[-1][-1] in ['.', '?', '!']:
            new_query = new_query[:-1] + "?"
        else:
            new_query += "?"
    else:
        if query_words[-1][-1] in ['.', '?', '!']:
            new_query = new_query[:-1] + "."
        else:
            new_query += "."
    return new_query.capitalize()


def UniversalTranslator(Text):
    english_translation = mt.translate(Text, "en", "auto")
    return english_translation.capitalize()


def SpeechRecognition():
    # FIX 1: Always reload the page fresh so there is no leftover text
    # from the previous recognition session. Without this, stale text
    # could be returned instantly or the output element holds old data.
    driver.get("file:///" + Link)

    # FIX 2: Clear the output element explicitly before starting,
    # as a safety net in case the page cached previous content.
    try:
        driver.execute_script("document.getElementById('output').textContent = '';")
    except Exception:
        pass

    driver.find_element(by=By.ID, value="start").click()

    while True:
        try:
            # FIX 3: Check mic status inside the loop. If the mic has been
            # turned off externally (e.g. assistant starts answering),
            # stop recognition immediately and return nothing so the caller
            # doesn't process a half-captured or empty query.
            if GetMicrophoneStatus() != "True":
                try:
                    driver.find_element(By.ID, value="end").click()
                except Exception:
                    pass
                return ""

            Text = driver.find_element(by=By.ID, value="output").text.strip()

            if Text:
                driver.find_element(By.ID, value="end").click()

                if InputLanguage.lower() == "en" or "en" in InputLanguage.lower():
                    return QueryModifier(Text)
                else:
                    SetAssistantStatus("Translating ... ")
                    return QueryModifier(UniversalTranslator(Text))

        except Exception:
            pass


if __name__ == "__main__":
    while True:
        Text = SpeechRecognition()
        if Text:
            print(Text)
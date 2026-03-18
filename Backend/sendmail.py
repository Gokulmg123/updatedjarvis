"""
sendmail.py — AI-generated email composition and sending.
Uses Groq (llama-3.3-70b-versatile) to generate email content.
Credentials are read from the .env file.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import subprocess
import os
from groq import Groq
from dotenv import dotenv_values

env_vars = dotenv_values(".env")
GroqAPIKey  = env_vars.get("GroqAPIKey")
SenderEmail = env_vars.get("SenderEmail", "")
SenderPass  = env_vars.get("SenderPassword", "")

client = Groq(api_key=GroqAPIKey)


def generate_email_body(subject: str) -> str:
    """Generate a professional email body using Groq."""
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional email writer. "
                        "Write concise, polished emails based on the given subject. "
                        "Include a greeting, body, and a proper closing statement."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Write a professional email about: {subject}",
                },
            ],
            max_tokens=512,
            temperature=0.7,
            stream=False,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"[sendmail] AI generation error: {e}")
        return f"Dear Recipient,\n\nThis email is regarding: {subject}.\n\nBest regards."


def open_in_notepad(file_path: str):
    try:
        subprocess.Popen(["notepad.exe", file_path])
    except Exception as e:
        print(f"[sendmail] Notepad open error: {e}")


def compose_email(subject: str) -> str:
    """Generate and save email to a .txt file, then open in Notepad."""
    body = generate_email_body(subject)
    safe_name = subject.lower().replace(" ", "")[:50]
    file_path = rf"Data\{safe_name}.txt"

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(body)
        open_in_notepad(file_path)
    except Exception as e:
        print(f"[sendmail] File write error: {e}")

    return body


def sendmail(subject: str):
    """Compose and send an AI-generated email. Prompts for recipient email."""
    body = compose_email(subject)
    print(f"\n[Generated Email]\n{body}\n")

    if not SenderEmail or not SenderPass:
        print(
            "❌ Missing email credentials.\n"
            "   Add SenderEmail and SenderPassword to your .env file."
        )
        return

    receiver_email = input("Enter recipient email address: ").strip()
    if not receiver_email:
        print("❌ No recipient provided. Aborting.")
        return

    msg = MIMEMultipart()
    msg["From"]    = SenderEmail
    msg["To"]      = receiver_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SenderEmail, SenderPass)
        server.sendmail(SenderEmail, receiver_email, msg.as_string())
        server.quit()
        print(f"✅ Email sent successfully to {receiver_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


if __name__ == "__main__":
    topic = input("Enter email subject/topic: ").strip()
    sendmail(topic)

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
        "You are a professional email writer.\n"
        "Write concise, natural, and realistic emails.\n\n"

        "STRICT RULES:\n"
        "- NEVER use placeholders like [Name], [Your Name], [Company], etc.\n"
        "- NEVER write 'Dear Sir/Madam'. Use a natural greeting like 'Hello' or omit if unknown.\n"
        "- NEVER include bracketed text.\n"
        "- Do NOT leave blanks for the user to fill.\n"
        "- Use a real-world tone, as if the sender is writing directly.\n"
        "- End with a simple closing like 'Best regards' or 'Thanks'.\n"
        "- Keep it human-like, not robotic or templated.\n\n"

        "Write complete, ready-to-send emails only."
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


def parse_mail_query(query: str):
    """
    Parse a query of the form '<subject> to <recipient@email.com>'.
    Returns (subject, recipient_email).
    If no email is found, recipient_email is None.

    Examples:
        'job to gokul@gmail.com'          -> ('job', 'gokul@gmail.com')
        'interview invitation to hr@x.com' -> ('interview invitation', 'hr@x.com')
        'project update'                  -> ('project update', None)
    """
    import re
    # Match " to <email>" pattern — email regex keeps original case
    match = re.search(
        r'\bto\s+([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
        query, re.IGNORECASE
    )
    if match:
        receiver_email = match.group(1)          # original case preserved
        subject = query[:match.start()].strip()  # everything before ' to <email>'
        if not subject:
            subject = "Important Update"
        return subject, receiver_email
    # No email found in query
    return query.strip(), None


def sendmail(query: str) -> str:
    """
    Compose and send an AI-generated email.
    'query' is a natural-language string like 'job to gokul@gmail.com'.
    Returns a status message string.
    """
    subject, receiver_email = parse_mail_query(query)

    if not receiver_email:
        msg = (
            "\u274c Could not find a recipient email in your request.\n"
            "   Please say something like:\n"
            "   'Send an email about job to gokul@gmail.com'"
        )
        print(msg)
        return msg

    print(f"[sendmail] Subject   : {subject}")
    print(f"[sendmail] Recipient : {receiver_email}")

    body = compose_email(subject)
    print(f"\n[Generated Email]\n{body}\n")

    if not SenderEmail or not SenderPass:
        msg = (
            "\u274c Missing email credentials.\n"
            "   Add SenderEmail and SenderPassword to your .env file."
        )
        print(msg)
        return msg

    email_msg = MIMEMultipart()
    email_msg["From"]    = SenderEmail
    email_msg["To"]      = receiver_email
    email_msg["Subject"] = subject
    email_msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SenderEmail, SenderPass)
        server.sendmail(SenderEmail, receiver_email, email_msg.as_string())
        server.quit()
        status = f"\u2705 Email sent successfully to {receiver_email}"
        print(status)
        return status
    except Exception as e:
        status = f"\u274c Failed to send email: {e}"
        print(status)
        return status


if __name__ == "__main__":
    # CLI test: python sendmail.py
    # Example input: job to gokul@gmail.com
    raw = input("Enter query (e.g. 'job to gokul@gmail.com'): ").strip()
    result = sendmail(raw)
    print(result)

"""
sendmail.py — AI-generated email composition and sending.
Uses Groq (llama-3.3-70b-versatile) to generate email content.
Includes sender name and clean success response.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import subprocess
import re
import os
from groq import Groq
from dotenv import dotenv_values

# Load environment variables
env_vars = dotenv_values(".env")
GroqAPIKey  = env_vars.get("GroqAPIKey")
SenderEmail = env_vars.get("SenderEmail", "")
SenderPass  = env_vars.get("SenderPassword", "")
SenderName  = env_vars.get("SenderName", "Sender")

client = Groq(api_key=GroqAPIKey)


def generate_email_body(subject: str) -> str:
    """Generate a professional email body using Groq."""
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional email writer.\n"
                        "Write concise, natural, and realistic emails.\n\n"

                        "STRICT RULES:\n"
                        "- NEVER use placeholders like [Name], [Your Name], etc.\n"
                        "- write 'Dear Sir/Madam'.\n"
                        "- Do NOT leave blanks.\n"
                        "- Use a real-world tone.\n"
                        "- End with a closing and sender name.\n"
                        f"- Sender name: {SenderName}\n\n"

                        "Write complete emails only."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Write a professional email about: {subject}. Include the sender name at the end.",
                },
            ],
            max_tokens=512,
            temperature=0.7,
        )

        body = completion.choices[0].message.content.strip()

        # Ensure sender name exists
        if SenderName.lower() not in body.lower():
            body += f"\n\nBest regards,\n{SenderName}"

        return body

    except Exception as e:
        print(f"[sendmail] AI error: {e}")
        return f"Hello,\n\nThis email is regarding: {subject}.\n\nBest regards,\n{SenderName}"


def open_in_notepad(file_path: str):
    try:
        subprocess.Popen(["notepad.exe", file_path])
    except Exception as e:
        print(f"[sendmail] Notepad error: {e}")


def compose_email(subject: str) -> str:
    """Generate and save email to file."""
    body = generate_email_body(subject)

    os.makedirs("Data", exist_ok=True)
    # SECURITY FIX: strip path separators and special chars to prevent traversal
    safe_name = re.sub(r'[^\w\-]', '', subject.lower().replace(" ", ""))[:50]
    if not safe_name:
        safe_name = "email_draft"
    file_path = rf"Data\{safe_name}.txt"

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(body)
        open_in_notepad(file_path)
    except Exception as e:
        print(f"[sendmail] File error: {e}")

    return body


def parse_mail_query(query: str):
    """Extract subject and email from query."""
    import re

    match = re.search(
        r'\bto\s+([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
        query,
        re.IGNORECASE,
    )

    if match:
        receiver_email = match.group(1)
        subject = query[:match.start()].strip()
        if not subject:
            subject = "Important Update"
        return subject, receiver_email

    return query.strip(), None


# SECURITY: pending confirmation cache — keyed by recipient so the caller
# can match preview → confirm without ambiguity.
_pending_email: dict = {}


def sendmail(query: str, confirm: bool = False) -> str:
    """
    Two-step email send with mandatory human confirmation.

    First call  (confirm=False):
        - Parses + generates the email body.
        - Caches it in _pending_email.
        - Returns a preview string asking the user to confirm.

    Second call (confirm=True):
        - Retrieves the cached email.
        - Actually sends it via SMTP.
        - Clears the cache.

    This prevents the AI from sending emails without user approval.
    """
    global _pending_email

    # ── STEP 2: User confirmed — send the cached email ────────────────────────
    if confirm:
        if not _pending_email:
            return "❌ No pending email found. Please make the email request first."

        subject        = _pending_email.get("subject", "")
        receiver_email = _pending_email.get("receiver_email", "")
        body           = _pending_email.get("body", "")
        _pending_email.clear()  # in-place clear keeps the module-level reference valid

        if not SenderEmail or not SenderPass:
            return "❌ Missing email credentials in .env"

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
            return "✅ Done! Email sent successfully."
        except Exception as e:
            print(f"[sendmail] SMTP error: {e}")
            return "❌ Failed to send email. Check credentials or internet."

    # ── STEP 1: Preview — parse, generate and ask for confirmation ────────────
    subject, receiver_email = parse_mail_query(query)

    if not receiver_email:
        return "❌ No recipient found. Try: 'send a mail about job to email@gmail.com'"

    print(f"[sendmail] Subject   : {subject}")
    print(f"[sendmail] Recipient : {receiver_email}")

    body = compose_email(subject)
    print(f"\n[Generated Email]\n{body}\n")

    # Cache for the confirmation step (in-place update keeps external ref valid)
    _pending_email.clear()
    _pending_email.update({
        "subject":        subject,
        "receiver_email": receiver_email,
        "body":           body,
    })

    preview = (
        f"📧 Email Preview\n"
        f"To      : {receiver_email}\n"
        f"Subject : {subject}\n"
        f"───────────────────────\n"
        f"{body[:300]}{'...' if len(body) > 300 else ''}\n"
        f"───────────────────────\n"
        f"Say 'yes send it' to confirm, or 'cancel email' to abort."
    )
    return preview


# CLI Testing
if __name__ == "__main__":
    raw = input("Enter query (e.g. 'job to gokul@gmail.com'): ").strip()
    preview = sendmail(raw)          # Step 1 — preview
    print("\n" + preview + "\n")
    answer = input("Send? (yes/no): ").strip().lower()
    if answer in ("yes", "y"):
        result = sendmail(raw, confirm=True)  # Step 2 — send
        print("\n" + result)
    else:
        print("Email cancelled.")
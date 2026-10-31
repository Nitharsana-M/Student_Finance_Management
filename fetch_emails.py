import os
import re
import time
import email
from email.header import decode_header
import imaplib
from dotenv import load_dotenv

# 1. Load credentials from .env
load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

print("Email loaded:", GMAIL_USER)
print("Password loaded:", bool(GMAIL_APP_PASSWORD))

if not GMAIL_USER or not GMAIL_APP_PASSWORD:
    raise ValueError("Missing GMAIL_USER or GMAIL_APP_PASSWORD in your .env file!")

# 2. Configure Django Environment (pointing to your SFT settings)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SFT.settings')
import django
django.setup()

# 3. Import models and user model
from django.contrib.auth.models import User
from finance.models import Transaction, Category

# Fetch the active user account to satisfy foreign key constraints
DEFAULT_USER = User.objects.first()
if not DEFAULT_USER:
    raise ValueError("No user found in the database. Please register/create a user first.")

# Bank sender verification keyword
CANARA_KEYWORD = "canarabank"

# Category classification rules for expenses
EXPENSE_KEYWORDS = {
    "Food": ["swiggy", "zomato", "canteen", "cafe", "restaurant", "bakery", "hotel", "tea", "bites"],
    "Travel": ["uber", "ola", "rapido", "metro", "irctc", "fuel", "petrol"],
    "Book": ["amazon", "flipkart", "book", "stationery", "xerox", "print"],
}

def detect_transaction_type(text):
    text_lower = text.lower()
    # Credit keywords take precedence for incoming money
    if any(k in text_lower for k in ["credited", "received", "deposited", "credit to", "credit of"]):
        return "income"
    return "expense"

def auto_categorize(text, tx_type):
    text_lower = text.lower()

    if tx_type == "income":
        if any(k in text_lower for k in ["refund", "cashback", "reversal"]):
            return "Refund / Cashback"
        elif any(k in text_lower for k in ["goog", "salary", "stipend"]):
            return "Salary / Stipend"
        return "Income"

    # Expense categorization
    for cat, keywords in EXPENSE_KEYWORDS.items():
        if any(k in text_lower for k in keywords):
            return cat
    return "Other"

def extract_canara_details(body, subject):
    combined_text = f"{subject} {body}"

    # Extract Amount: matches "INR 39.00", "INR 20.00", "Rs. 50", "₹1.0"
    amt_match = re.search(r'(?:INR|Rs\.?|₹)\s*([\d,]+\.?\d*)', combined_text, re.IGNORECASE)
    amount = float(amt_match.group(1).replace(',', '')) if amt_match else None

    # Extract Merchant / Payee / VPA / Account source
    merch_match = re.search(r'(?:to\s+(?:VPA\s+)?|at\s+|from\s+|info\s*[:\-]\s*)([A-Za-z0-9.\-_@ ]{2,30})', combined_text, re.IGNORECASE)
    merchant = merch_match.group(1).strip() if merch_match else "Canara Bank Transaction"
    merchant = re.sub(r'\s+(?:on|ref|avl|bal|date|has|is).*$', '', merchant, flags=re.IGNORECASE).strip()

    return amount, merchant

def check_canara_alerts():
    try:
        # Connect to Gmail securely via IMAP
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        # Search specifically for unread transaction alert emails
        status, messages = mail.search(None, '(UNSEEN SUBJECT "Transaction Alert")')
        email_ids = messages[0].split()

        if email_ids:
            print(f"Found {len(email_ids)} unread transaction alert(s). Processing the latest one...")

            # Take only the most recent unread email
            for eid in email_ids[-1:]:
                _, msg_data = mail.fetch(eid, '(RFC822)')
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        sender = msg.get("From", "").lower()

                        # Decode subject safely
                        raw_subject, encoding = decode_header(msg.get("Subject", ""))[0]
                        if isinstance(raw_subject, bytes):
                            subject = raw_subject.decode(encoding or "utf-8", errors="ignore")
                        else:
                            subject = raw_subject

                        # Strict check: only process emails from Canara Bank
                        if CANARA_KEYWORD not in sender:
                            continue

                        # Extract body text
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                if content_type in ["text/plain", "text/html"]:
                                    raw_payload = part.get_payload(decode=True)
                                    if raw_payload:
                                        body += raw_payload.decode(errors="ignore")
                        else:
                            raw_payload = msg.get_payload(decode=True)
                            if raw_payload:
                                body = raw_payload.decode(errors="ignore")

                        amount, merchant = extract_canara_details(body, subject)

                        if amount:
                            # 1. Detect whether money came in or went out
                            tx_type = detect_transaction_type(f"{subject} {body}")

                            # 2. Categorize based on transaction type and text content
                            cat_name = auto_categorize(f"{body} {merchant}", tx_type)

                            # 3. Create/fetch Category assigned to user
                            category, _ = Category.objects.get_or_create(
                                name=cat_name,
                                user=DEFAULT_USER
                            )

                            # 4. Save transaction with correct type ('income' or 'expense')
                            tx = Transaction.objects.create(
                                user=DEFAULT_USER,
                                amount=amount,
                                merchant=merchant,
                                category=category,
                                transaction_type=tx_type
                            )
                            print(f"Recorded Canara Bank {tx_type.upper()}: ₹{amount} | Merchant: {merchant} | Category: {cat_name} | User: {DEFAULT_USER.username}")

        mail.logout()
    except Exception as e:
        print("Polling error:", e)

if __name__ == "__main__":
    print("\nSmartFinance Polling Engine Started")
    print(f"Default user assigned: {DEFAULT_USER.username}")
    print("Listening for Canara Bank transaction emails every 30 seconds... (Press Ctrl+C to stop)\n")
    while True:
        check_canara_alerts()
        time.sleep(30)
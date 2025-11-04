#!/usr/bin/env python3
"""Generate a Fernet encryption key for AGENTBOT_SESSION_KEY."""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    key = Fernet.generate_key().decode()
    print(f"\nAGENTBOT_SESSION_KEY={key}\n")
    print("Bu key'i .env dosyanıza ekleyin:\n")
    print(f"AGENTBOT_SESSION_KEY={key}")


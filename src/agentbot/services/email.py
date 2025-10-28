"""Email inbox integration for OTP / verification code retrieval."""

from __future__ import annotations

import asyncio
import imaplib
import re
from contextlib import contextmanager
from email.message import Message
from typing import Optional


class EmailInboxService:
    """IMAP email reader to extract verification codes with simple filtering."""

    CODE_REGEX = re.compile(r"\b(\d{4,8})\b")

    def __init__(
        self,
        host: str,
        *,
        port: int = 993,
        username: str,
        password: str,
        folder: str = "INBOX",
        use_ssl: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.folder = folder
        self.use_ssl = use_ssl

    @contextmanager
    def _client(self) -> imaplib.IMAP4:
        client = imaplib.IMAP4_SSL(self.host, self.port) if self.use_ssl else imaplib.IMAP4(self.host, self.port)
        try:
            client.login(self.username, self.password)
            yield client
        finally:
            try:
                client.logout()
            except Exception:
                pass

    async def fetch_latest_code(
        self,
        *,
        timeout: float = 30.0,
        subject_filters: Optional[list[str]] = None,
        unseen_only: bool = True,
        lookback: int = 50,
    ) -> Optional[str]:
        """Fetch the latest numeric code in the mailbox.

        Parameters
        - subject_filters: list of substrings to match in the Subject (any matches)
        - unseen_only: if True, restrict search to unseen; otherwise search all
        - lookback: number of most recent message ids to scan
        """
        return await asyncio.wait_for(
            asyncio.to_thread(self._fetch_latest_code_sync, subject_filters, unseen_only, lookback),
            timeout=timeout,
        )

    def _fetch_latest_code_sync(
        self,
        subject_filters: Optional[list[str]] = None,
        unseen_only: bool = True,
        lookback: int = 50,
    ) -> Optional[str]:
        with self._client() as client:
            status, _ = client.select(self.folder)
            if status != "OK":
                raise RuntimeError("Unable to select email folder")

            criteria = "UNSEEN" if unseen_only else "ALL"
            status, data = client.search(None, criteria)
            if status != "OK" or not data or not data[0]:
                return None

            ids = data[0].split()[-lookback:]
            subject_filters = [s.lower() for s in (subject_filters or [])]

            for msg_id in reversed(ids):
                status, message_data = client.fetch(msg_id, "(RFC822.HEADER RFC822.TEXT)")
                if status != "OK" or not message_data or not message_data[0]:
                    continue
                raw_email_bytes = message_data[0][1]
                text = raw_email_bytes.decode("utf-8", errors="ignore")
                if subject_filters:
                    subj_match = any(sf in text.lower() for sf in subject_filters)
                    if not subj_match:
                        continue
                match = self.CODE_REGEX.search(text)
                if match:
                    return match.group(1)
            return None


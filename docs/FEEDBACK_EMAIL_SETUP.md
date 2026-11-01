# Feedback email setup

The feedback form sends a message from the server through an SMTP provider. The message includes the sender's name and email, feedback category, how they heard about ARIA, and their message. Replies go to the submitted address using the email's Reply-To header. The From address must be permitted by the SMTP provider.

Set these values in the server's `.env` (see `.env.example`):

```dotenv
ARIA_SMTP_HOST=smtp.example.com
ARIA_SMTP_PORT=587
ARIA_SMTP_SECURITY=starttls
ARIA_SMTP_USERNAME=your-smtp-username
ARIA_SMTP_PASSWORD=your-smtp-password
ARIA_SMTP_FROM=permitted-sender@example.com
ARIA_FEEDBACK_TO=first-recipient@example.com,second-recipient@example.com
```

List up to 10 recipient addresses separated by commas. For implicit TLS, use `ARIA_SMTP_SECURITY=ssl` and the provider's port (commonly 465). If your SMTP relay does not require authentication, leave both username and password blank. Both must be supplied when either is used. Use the SMTP credentials or app password supplied by your provider, keep `.env` private, and restart the backend after changing it.

Until host, sender and destination are configured, the service reports that feedback email is unavailable. A successful API response means the SMTP server accepted the message; it does not guarantee delivery to the final inbox. Failed delivery returns an error and no success message. The endpoint applies a per-process limit of five attempts per client address per ten minutes; deployment-wide limits should also be enforced by the hosting proxy.

Run `python -m pytest tests/test_feedback.py -q` to check validation, sender headers, TLS mode and failure handling using a fake SMTP provider. The tests do not send real email. Once a destination is configured, the operator can submit a test message through the form and check that mailbox.

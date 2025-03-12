# Instagram Automation Script

This Python script automates posting random images to an Instagram business account using Facebook's Graph API. It uploads images to ImgBB temporarily, then publishes them on Instagram. It also logs actions and sends email notifications in case of errors.

## Features
- Automatically uploads images to ImgBB.
- Posts images to Instagram via Facebook Graph API.
- Logs operations with timestamps.
- Sends email alerts for critical issues.

## Requirements
- Python 3
- Facebook Developer account and Instagram Business Account
- ImgBB API key
- SMTP server for email notifications

## Installation
1. Clone this repository:
```bash
git clone <repository-url>
cd <repository-folder>
```

2. Set up a virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Create a `.env` file in the root folder and populate it with the required environment variables (listed below).

## Environment Variables
Add these variables to your `.env` file:

```env
ACCESS_TOKEN=
ACCESS_TOKEN_EXPIRY=
IG_BUSINESS_USER_ID=
IMGBB_API_KEY=
LOG_FILE=
SMTP_SERVER=
SMTP_PORT=
SENDER_EMAIL=
SENDER_PASSWORD=
RECIPIENT_EMAIL=
```

### Explanation of Environment Variables
- **ACCESS_TOKEN**: Facebook Graph API access token.
- **ACCESS_TOKEN_EXPIRY**: Expiry datetime of the access token (`YYYY-MM-DD HH:MM:SS.%f`).
- **IG_BUSINESS_USER_ID**: Instagram Business account ID (auto-fetched if empty).
- **IMGBB_API_KEY**: ImgBB API key for temporary image uploads.
- **LOG_FILE**: Path to store the log file (e.g., `/var/log/insta_bot/log.txt`).
- **SMTP_SERVER**: SMTP server address for sending email alerts.
- **SMTP_PORT**: SMTP server port.
- **SENDER_EMAIL**: Sender's email address.
- **SENDER_PASSWORD**: Sender's email password.
- **RECIPIENT_EMAIL**: Recipient's email address for alerts.

## Usage
Import and use the `post_random_photo` function in your Python script:

```python
from your_script import post_random_photo

post_random_photo('path/to/image.jpg', 'Your Instagram caption here')
```

## Logging
Logs are saved at the path specified by the `LOG_FILE` environment variable. Logs include timestamps and statuses of script operations.

## Troubleshooting
- Ensure the Facebook Graph API token is valid and not expired.
- Confirm SMTP details are accurate for email alerts.
- Check the ImgBB API key if image uploads fail.

## License
This project is licensed under the MIT License.
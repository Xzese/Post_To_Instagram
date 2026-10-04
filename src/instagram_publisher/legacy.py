"""Legacy low-level helpers; callers own their checkpointing and coordination."""

from email.message import EmailMessage
import logging
import smtplib
import ssl
from uuid import uuid4

from .config import graph_config, required, storage_config
from .graph import GraphClient, REQUEST_TIMEOUT as REQUEST_TIMEOUT
from .media import validate_media
from .service import publish_image
from .storage import S3Storage

LOGGER = logging.getLogger(__name__)


def _required(name):
    return required(name)


def _graph_base():
    return graph_config().base


def _account():
    return graph_config().account_id


def _token():
    return graph_config().token


def business_id_check():
    _account()
    return True


def add_to_log(message):
    LOGGER.info(message)


def _best_effort_log(message):
    try:
        add_to_log(message)
    except Exception:
        pass


def upload_image(image_path):
    media = validate_media(image_path, "")
    config = storage_config()
    return S3Storage(config).upload(
        media.content, f"{config.prefix}/images/{uuid4().hex}.jpg"
    )


def create_media_container(image_url, caption):
    return GraphClient(graph_config()).create(image_url, caption)


def publish_media_container(creation_id):
    media_id = GraphClient(graph_config()).publish(creation_id)
    _best_effort_log("Publication confirmed.")
    return {"id": media_id}


def post_random_photo(file_path, caption, **kwargs):
    return publish_image(file_path, caption, **kwargs)


def send_email_alert(subject, body):
    """Optional notification; never invoked automatically by publishing."""
    try:
        sender, recipient = required("SENDER_EMAIL"), required("RECIPIENT_EMAIL")
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = sender, recipient, subject
        message.set_content(body)
        with smtplib.SMTP(
            required("SMTP_SERVER"), int(required("SMTP_PORT")), timeout=10
        ) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(sender, required("SENDER_PASSWORD"))
            server.send_message(message)
        return True
    except Exception:
        _best_effort_log("Email notification failed.")
        return False

"""Compatibility imports for installed projects and the existing Git submodule."""

from importlib import import_module

if __package__:
    # Always select this submodule checkout, even if another version is installed.
    _package = import_module(".src.instagram_publisher", __package__)
else:
    try:
        _package = import_module("instagram_publisher")
    except ModuleNotFoundError as error:
        if error.name != "instagram_publisher":
            raise
        _package = import_module("src.instagram_publisher")
_legacy = import_module(_package.__name__ + ".legacy")
_legacy_names = [
    "REQUEST_TIMEOUT",
    "_account",
    "_best_effort_log",
    "_graph_base",
    "_required",
    "_token",
    "add_to_log",
    "business_id_check",
    "create_media_container",
    "post_random_photo",
    "publish_media_container",
    "send_email_alert",
    "upload_image",
]
__all__ = list(_package.__all__) + _legacy_names
for _name in __all__:
    globals()[_name] = (
        getattr(_legacy, _name) if hasattr(_legacy, _name) else getattr(_package, _name)
    )

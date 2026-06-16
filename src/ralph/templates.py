"""Template rendering seam."""

from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape


def environment() -> Environment:
    return Environment(
        loader=PackageLoader("ralph", "templates"),
        autoescape=select_autoescape(default_for_string=False, default=False),
        keep_trailing_newline=True,
    )


def render_template(name: str, **context: object) -> str:
    return environment().get_template(name).render(**context)


def template_dir() -> Path:
    return Path(__file__).parent / "templates"


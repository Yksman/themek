"""E5 결과를 Jinja 템플릿으로 자연어 답으로 변환."""
from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from themek.query.e5 import E5Result


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def synthesize_e5_answer(result: E5Result) -> str:
    template = _env.get_template("e5_answer.txt.j2")
    return template.render(result=result)

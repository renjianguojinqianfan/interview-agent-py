import os

from langchain_core.prompts import PromptTemplate

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "prompts")
_cache: dict[str, PromptTemplate] = {}


def load_prompt(name: str) -> PromptTemplate:
    if name in _cache:
        return _cache[name]

    file_path = os.path.join(_PROMPTS_DIR, f"{name}.st")
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    template = PromptTemplate.from_template(content)
    _cache[name] = template
    return template

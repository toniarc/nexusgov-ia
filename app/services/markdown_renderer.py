import markdown as md_lib
import nh3

_md = md_lib.Markdown(extensions=["tables", "fenced_code", "nl2br"])

_ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "strong", "em", "code", "pre", "blockquote",
    "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "img", "span", "div",
}
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "code": {"class"},
    "span": {"class"},
    "div": {"class"},
}


def render(text: str) -> str:
    """Markdown → HTML sanitizado. _md é stateful — reset() obrigatório."""
    _md.reset()
    html = _md.convert(text.replace("\\n", "\n"))
    safe = nh3.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS)
    return safe.replace("\n", "")

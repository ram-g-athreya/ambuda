from flask import Blueprint, abort, render_template
from vidyut.lipi import transliterate, Scheme

import ambuda.queries as q

bp = Blueprint("authors", __name__)


@bp.route("/<slug>")
def author(slug):
    author = q.author(slug)
    if author is None:
        abort(404)

    texts = sorted(
        [t for t in author.texts if t.parent_id is None],
        key=lambda t: transliterate(t.title, Scheme.HarvardKyoto, Scheme.Devanagari),
    )
    return render_template("authors/author.html", author=author, texts=texts)

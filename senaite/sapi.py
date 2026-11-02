"""Tiny SENAITE JSON API client (stdlib only)."""
import base64
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("SENAITE_URL", "http://127.0.0.1:8088/senaite") + "/@@API/senaite/v1/"
_pw = os.environ["SENAITE_PASSWORD"]
AUTH = "Basic " + base64.b64encode((os.environ.get("SENAITE_USER", "admin") + ":" + _pw).encode()).decode()


def call(route, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + route, body, {
        "Authorization": AUTH, "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s: %s" % (route, e.code, e.read().decode(errors="replace")))


def find(portal_type, title):
    items = call("search?portal_type=%s&limit=500&complete=no" % portal_type)["items"]
    return next((i for i in items if i.get("title") == title), None)


def ensure(portal_type, parent_path, title, **fields):
    """Create once; re-running the seed is a no-op for existing titles."""
    hit = find(portal_type, title)
    if hit:
        return hit["uid"]
    data = dict(portal_type=portal_type, parent_path=parent_path, title=title, **fields)
    res = call("create", data)
    if "items" in res:
        return res["items"][0]["uid"]
    # Numeric AnalysisService: object is stored, then a post-create hook fails on a
    # missing REQUEST ("'NoneType' object has no attribute 'form'"). Treat as created.
    if "attribute 'form'" in str(res.get("message")):
        hit = find(portal_type, title)
        if hit:
            return hit["uid"]
    raise RuntimeError("create %s %r failed: %s" % (portal_type, title, res.get("message")))


def _empty_err_fields(err):
    """Field names whose validation message is "" (spurious DX UIDReference error)."""
    msg = str(err)
    try:
        inner = json.loads(json.loads(msg[msg.index("{"):])["message"])
    except Exception:
        return []
    return [k for k, v in inner.items() if v == ""] if isinstance(inner, dict) else []


def set_refs(uid, refs):
    """Set reference fields one by one; the API stores them but still answers 400 ""."""
    for k, v in refs.items():
        try:
            call("update", {"uid": uid, k: v})
        except RuntimeError as e:
            if not _empty_err_fields(e) or "\": \"[^\"]" in str(e):
                raise


_ensure_plain = ensure


def ensure(portal_type, parent_path, title, **fields):  # noqa: F811
    try:
        return _ensure_plain(portal_type, parent_path, title, **fields)
    except RuntimeError as e:
        bad = _empty_err_fields(e)
        if not bad:
            raise
        refs = {k: fields.pop(k) for k in bad}
        uid = _ensure_plain(portal_type, parent_path, title,
                            **dict(fields, **{k: None for k in refs}))
        set_refs(uid, refs)
        return uid

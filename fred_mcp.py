"""FRED MCP server.

The same shape as northwind-mcp: a data service that publishes a catalog, describes
what is in it, and answers queries. Nothing here knows about an LLM -- it is an HTTP
server exposing tools, and anything that speaks MCP can call it.

The FRED API key lives in this server's environment, not in the client. Callers get
the data; they never get the key.

That is exactly why the server itself needs a door. Anyone who can reach /mcp can
spend this server's API key and read whatever it can read, so /mcp requires an API key
of its own: set MCP_API_KEYS (comma separated, so keys can be added and revoked one at
a time) and clients send either

    Authorization: Bearer <key>
    X-API-Key: <key>

A ?key=<key> query parameter is also accepted, for clients that cannot set a header
(the claude.ai custom-connector form is one). It is the weaker path -- a key in a URL
ends up in server logs and browser history -- so prefer a header where you can set one.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from hmac import compare_digest

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

FRED_BASE = "https://api.stlouisfed.org/fred"
API_KEY = os.environ.get("FRED_API_KEY", "")

# The keys clients must present. Comma separated so one can be revoked without
# disturbing the others. Empty means the server runs open, which is fine on localhost
# and wrong anywhere else.
API_KEYS = [k.strip() for k in os.environ.get("MCP_API_KEYS", "").split(",") if k.strip()]

# Caps that keep a tool result small enough for a model to read.
MAX_SEARCH_RESULTS = 30
MAX_SERIES_PER_CALL = 8
MAX_POINTS_PER_SERIES = 800
NOTES_CHARS = 700

# The tracked series: the finance side's standard set. An agent can go outside this
# with fred_search_series; the dashboard's menus are built from it.
CATALOG = [
    # series_id,        label,                          group,     units
    ("DGS10",           "10-year Treasury yield",       "rates",   "%"),
    ("DGS2",            "2-year Treasury yield",        "rates",   "%"),
    ("T10Y2Y",          "10-year minus 2-year spread",  "rates",   "pp"),
    ("BAMLH0A0HYM2",    "High-yield credit spread",     "rates",   "pp"),
    ("MORTGAGE30US",    "30-year fixed mortgage",       "rates",   "%"),
    ("FEDFUNDS",        "Federal funds rate",           "rates",   "%"),
    ("CPIAUCSL",        "CPI, all items",               "prices",  "index"),
    ("CPILFESL",        "Core CPI",                     "prices",  "index"),
    ("PPIACO",          "PPI, all commodities",         "prices",  "index"),
    ("PCU325325",       "PPI, chemical manufacturing",  "prices",  "index"),
    ("WPU0571",         "PPI, gasoline",                "prices",  "index"),
    ("PCU221210221210114", "PPI, industrial natural gas", "prices", "index"),
    ("INDPRO",          "Industrial production",        "activity", "index"),
    ("IPG325S",         "Industrial production, chemicals (NAICS 325)", "activity", "index"),
    ("RSAFS",           "Retail sales",                 "activity", "$mn"),
    ("HOUST",           "Housing starts",               "activity", "thousands"),
    ("UMCSENT",         "Consumer sentiment",           "activity", "index"),
    ("GDPC1",           "Real GDP",                     "activity", "$bn"),
    ("PAYEMS",          "Nonfarm payrolls",             "labor",   "thousands"),
    ("UNRATE",          "Unemployment rate",            "labor",   "%"),
    ("ICSA",            "Initial jobless claims",       "labor",   "claims"),
    ("SP500",           "S&P 500",                      "markets", "index"),
    ("DTWEXBGS",        "Broad dollar index",           "markets", "index"),
    ("DCOILWTICO",      "WTI crude oil",                "markets", "$/bbl"),
    ("DHHNGSP",         "Henry Hub natural gas spot",   "markets", "$/mmbtu"),
    ("GASREGW",         "Regular gasoline price",       "markets", "$/gal"),
]

CATALOG_IDS = {row[0] for row in CATALOG}

mcp = FastMCP("FRED", host="0.0.0.0")


def _get(path: str, params: dict) -> dict:
    """One GET against the FRED API. The key is added here and never returned."""
    if not API_KEY:
        raise ValueError("FRED_API_KEY is not set on the server.")
    query = {k: v for k, v in params.items() if v not in (None, "")}
    query.update({"api_key": API_KEY, "file_type": "json"})
    url = f"{FRED_BASE}/{path}?" + urllib.parse.urlencode(query)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Surface FRED's own message without the URL, which carries the API key.
        try:
            msg = json.loads(e.read()).get("error_message", "")
        except Exception:
            msg = ""
        raise ValueError(f"FRED API error {e.code}: {msg or 'request rejected'}")


@mcp.tool()
def fred_list_catalog() -> str:
    """List the tracked FRED series: series ID, label, group, and units.

    Pipe delimited, because the labels contain commas. These are the series this
    service publishes as its standard set. Start here; use fred_search_series only
    when the question needs something outside the catalog.
    """
    lines = ["series_id|label|group|units"]
    for sid, label, group, units in CATALOG:
        lines.append(f"{sid}|{label}|{group}|{units}")
    return "\n".join(lines)


@mcp.tool()
def fred_search_series(query: str, limit: int = 10) -> str:
    """Search all of FRED for series matching a text query.

    Returns candidate series IDs with title, frequency, units, seasonal adjustment,
    and date coverage. Use when the series you need is not in fred_list_catalog.
    """
    limit = max(1, min(int(limit or 10), MAX_SEARCH_RESULTS))
    data = _get(
        "series/search",
        {"search_text": query, "limit": limit, "order_by": "popularity", "sort_order": "desc"},
    )
    hits = data.get("seriess", [])
    if not hits:
        return f"No series found for '{query}'."
    lines = [f"{data.get('count', len(hits))} matches; showing {len(hits)} most popular.", ""]
    for s in hits:
        lines.append(
            f"{s['id']} | {s['title']} | {s['frequency_short']} | {s['units_short']} | "
            f"{s['seasonal_adjustment_short']} | {s['observation_start']} to {s['observation_end']}"
        )
    return "\n".join(lines)


@mcp.tool()
def fred_series_info(series_id: str) -> str:
    """Metadata for one series: title, units, frequency, seasonal adjustment, coverage,
    last update, and the source's notes.

    Use it to confirm what a series measures before charting or interpreting it.
    """
    sid = series_id.strip().upper()
    rows = _get("series", {"series_id": sid}).get("seriess", [])
    if not rows:
        return f"No series with ID {sid}."
    s = rows[0]
    notes = (s.get("notes") or "").strip().replace("\r\n", " ")
    if len(notes) > NOTES_CHARS:
        notes = notes[:NOTES_CHARS] + " ..."
    in_catalog = "yes" if sid in CATALOG_IDS else "no"
    return (
        f"id: {s['id']}\n"
        f"title: {s['title']}\n"
        f"units: {s['units']}\n"
        f"frequency: {s['frequency']}\n"
        f"seasonal adjustment: {s['seasonal_adjustment']}\n"
        f"coverage: {s['observation_start']} to {s['observation_end']}\n"
        f"last updated: {s['last_updated']}\n"
        f"in catalog: {in_catalog}\n"
        f"notes: {notes or '(none)'}"
    )


def _observations(sid, start, end, units, freq, vintage=None):
    params = {
        "series_id": sid,
        "observation_start": start,
        "observation_end": end,
        "units": units,
        "frequency": freq,
        "aggregation_method": "avg" if freq else None,
    }
    if vintage:
        # Same observation dates, but the values as they stood on the vintage date.
        params["realtime_start"] = vintage
        params["realtime_end"] = vintage
    data = _get("series/observations", params)
    return [o for o in data.get("observations", []) if o["value"] != "."]


@mcp.tool()
def fred_get_observations(
    series_ids: str,
    start_date: str = "",
    end_date: str = "",
    units: str = "lin",
    frequency: str = "",
) -> str:
    """Fetch observations for one or more series over a date range, as date,value CSV.

    series_ids is comma separated, at most 8. units transforms the data server-side:
    lin (levels, default), pc1 (percent change from a year ago), pch (percent change
    from the previous period), chg (change). frequency downsamples to m, q, or a.
    """
    ids = [s.strip().upper() for s in series_ids.split(",") if s.strip()]
    if not ids:
        return "No series IDs given."
    if len(ids) > MAX_SERIES_PER_CALL:
        return f"Too many series; ask for at most {MAX_SERIES_PER_CALL} at a time."
    units = (units or "lin").strip().lower()
    freq = (frequency or "").strip().lower()

    blocks = []
    for sid in ids:
        try:
            obs = _observations(sid, start_date, end_date, units, freq)
        except ValueError as e:
            blocks.append(f"### {sid}\nERROR: {e}")
            continue
        if not obs:
            blocks.append(f"### {sid}\n(no observations in that range)")
            continue
        note = ""
        if len(obs) > MAX_POINTS_PER_SERIES:
            note = (
                f" (truncated to the last {MAX_POINTS_PER_SERIES} of {len(obs)}; "
                f"use frequency=q or a, or a later start_date, for full coverage)"
            )
            obs = obs[-MAX_POINTS_PER_SERIES:]
        rows = "\n".join(f"{o['date']},{o['value']}" for o in obs)
        blocks.append(
            f"### {sid} | units={units} | {len(obs)} obs | "
            f"{obs[0]['date']} to {obs[-1]['date']} | latest {obs[-1]['value']}{note}\n"
            f"date,value\n{rows}"
        )
    return "\n\n".join(blocks)


@mcp.tool()
def fred_get_vintage(series_id: str, vintage_date: str, start_date: str = "") -> str:
    """Fetch a series as it stood on a past date, as date,value CSV.

    FRED revises. This returns the vintage -- the numbers that were published as of
    vintage_date (YYYY-MM-DD) -- so the same observation date can carry a different
    value than fred_get_observations returns today. That difference is the revision.
    """
    sid = series_id.strip().upper()
    obs = _observations(sid, start_date, "", "lin", "", vintage=vintage_date.strip())
    if not obs:
        return f"### {sid}\n(no observations published as of {vintage_date})"
    if len(obs) > MAX_POINTS_PER_SERIES:
        obs = obs[-MAX_POINTS_PER_SERIES:]
    rows = "\n".join(f"{o['date']},{o['value']}" for o in obs)
    return (
        f"### {sid} | vintage={vintage_date} | {len(obs)} obs | "
        f"{obs[0]['date']} to {obs[-1]['date']} | latest {obs[-1]['value']}\n"
        f"date,value\n{rows}"
    )


def presented_key(request) -> str:
    """The key the caller sent, by header or, failing that, query parameter."""
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    from_header = request.headers.get("x-api-key", "").strip()
    if from_header:
        return from_header
    return request.query_params.get("key", "").strip()


class ApiKeyAuth(BaseHTTPMiddleware):
    """Require a valid API key on the MCP endpoint.

    The root page stays open so the platform health check still gets a 200. Only the
    tools are behind the key.
    """

    async def dispatch(self, request, call_next):
        if API_KEYS and request.url.path.startswith("/mcp"):
            given = presented_key(request)
            # compare_digest against each key, so a wrong key cannot be timed out.
            if not any(compare_digest(given, k) for k in API_KEYS):
                return JSONResponse(
                    {"error": "unauthorized: send Authorization: Bearer <key>, "
                              "X-API-Key: <key>, or ?key=<key>"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)


def build_app():
    """The MCP app, plus a root page so a plain health check gets a 200."""
    app = mcp.streamable_http_app()
    app.add_middleware(ApiKeyAuth)

    async def root(request):
        return PlainTextResponse(
            "FRED MCP server\n\n"
            "MCP endpoint: /mcp\n"
            "Tools: fred_list_catalog, fred_search_series, fred_series_info, "
            "fred_get_observations, fred_get_vintage\n"
            f"Catalog: {len(CATALOG)} tracked series\n"
            f"API key configured: {'yes' if API_KEY else 'no'}\n"
            f"Authentication: {'API key required' if API_KEYS else 'OPEN'}\n"
        )

    app.router.routes.append(Route("/", root))
    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

"""Bharat Vistaar weather (Mausamgram): the reply shapes behind "I couldn't
retrieve the weather forecast for your area".

The weather mock in test_vistaar_location.py is "always available" — every
point gets one forecast block — which is exactly the permissive-mock trap that
file warns about for mandi. These tests feed the tool the shapes the seeker
really hands back when the provider is down, and the item shape bharat-oan-api's
production weather tool parses from the same BPP, and pin what the model sees.
"""
import importlib.util
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "vistaar_weather_mod", ROOT / "agents" / "tools" / "vistaar.py"
)
vistaar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vistaar)

from agents.deps import FarmerContext  # noqa: E402
from agents.tools.districts import DISTRICTS  # noqa: E402

LEG = vistaar.VISTAAR_LEG
UNAVAILABLE = "temporarily unavailable"

# One forecast day as the Mausamgram BPP returns it: dated descriptor, values in
# a Beckn TagGroup (the shape bharat-oan-api's WeatherResponse model requires).
FORECAST_DAY = {
    "id": "wfc-2026-10-21",
    "descriptor": {"name": "21-10-2026"},
    "matched": True,
    "recommended": True,
    "tags": [{
        "descriptor": {"code": "forecast", "name": "Forecast"},
        "list": [
            {"descriptor": {"code": "max_temp", "name": "Max Temperature"}, "value": "34.2"},
            {"descriptor": {"code": "min_temp", "name": "Min Temperature"}, "value": "21.5"},
            {"descriptor": {"code": "rainfall", "name": "Rainfall"}, "value": "0"},
        ],
    }],
}
ERROR_CALLBACK = {
    "context": {"action": "on_search"},
    "error": {"code": "SOURCE_UNAVAILABLE", "message": "Mausamgram did not respond"},
}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        self.calls.append((url, json))
        return _FakeResponse(self._payload)


class _SequencedClient(_FakeAsyncClient):
    """One payload per POST, in order — for the candidate walk."""

    def __init__(self, payloads):
        super().__init__(None)
        self._payloads = list(payloads)

    async def post(self, url, json=None):
        self.calls.append((url, json))
        return _FakeResponse(self._payloads.pop(0))


def _seeker(on_search, errors=None):
    body = {"results": {LEG: on_search}}
    if errors:
        body["errors"] = errors
    return body


def _catalog(items):
    return {"message": {"catalog": {"providers": [{"id": "mausamgram", "items": items}]}}}


def _ctx(district="anand"):
    # session_id=None keeps the sticky-location cache out of these tests.
    return SimpleNamespace(deps=FarmerContext(
        query="weather for the next 5 days", session_id=None, farmer_district=district,
    ))


async def _weather(payload, **kw):
    fake = _FakeAsyncClient(payload)
    with patch.object(vistaar.httpx, "AsyncClient", return_value=fake):
        out = await vistaar.get_vistaar_weather(kw.pop("ctx", _ctx()), **kw)
    return out, fake


# ── The request ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_intent_matches_the_reference_mausamgram_request():
    _, fake = await _weather(_seeker(_catalog([FORECAST_DAY])))
    (url, body), = fake.calls
    anand = DISTRICTS["anand"].primary
    assert url.endswith("/search")
    assert body["legs"] == [LEG]
    assert body["intent"] == {
        "category": {"descriptor": {"name": "Weather-Forecast-Mausamgram", "code": "WFC"}},
        "fulfillment": {"stops": [{"location": {"lat": anand.lat, "lon": anand.lon}}]},
    }


# ── Provider down: never "no forecast", never a bare header ─────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    pytest.param(_seeker(None, errors={LEG: "timeout"}), id="leg-error"),
    pytest.param(_seeker(None), id="null-leg"),
    pytest.param(_seeker(ERROR_CALLBACK), id="error-callback"),
    pytest.param(_seeker({"context": {}, "responses": []}), id="empty-bap-wrapper"),
    pytest.param(_seeker({"responses": [ERROR_CALLBACK]}), id="wrapper-of-errors"),
])
async def test_a_dead_provider_reads_as_unavailable_not_as_no_forecast(payload):
    out, _ = await _weather(payload)
    assert UNAVAILABLE in out.lower()
    assert "No weather forecast" not in out


@pytest.mark.asyncio
async def test_the_failure_reason_is_logged(caplog):
    with caplog.at_level(logging.WARNING):
        await _weather(_seeker(ERROR_CALLBACK))
    assert "Mausamgram did not respond" in caplog.text


@pytest.mark.asyncio
async def test_rows_that_render_to_nothing_are_not_returned_as_an_empty_forecast(caplog):
    with caplog.at_level(logging.WARNING):
        out, _ = await _weather(_seeker(_catalog([{"id": "x", "tags": []}])))
    assert UNAVAILABLE in out.lower()
    assert "Weather forecast for" not in out
    assert "rendered empty" in caplog.text


@pytest.mark.asyncio
async def test_a_healthy_but_empty_catalogue_is_still_a_genuine_miss():
    out, _ = await _weather(_seeker(_catalog([])))
    assert out == "No weather forecast was returned for Anand."


# ── Provider up: the forecast reaches the model ──────────────────────────────


@pytest.mark.asyncio
async def test_a_mausamgram_forecast_day_is_rendered_with_its_values():
    out, _ = await _weather(_seeker(_catalog([FORECAST_DAY])))
    assert out.startswith("Weather forecast for Anand:")
    assert "21-10-2026" in out
    assert "max_temp: 34.2" in out
    assert "min_temp: 21.5" in out


@pytest.mark.asyncio
async def test_one_error_reply_does_not_hide_another_providers_forecast():
    out, _ = await _weather(_seeker({"responses": [ERROR_CALLBACK, _catalog([FORECAST_DAY])]}))
    assert "max_temp: 34.2" in out


@pytest.mark.asyncio
async def test_a_reply_with_rows_and_an_error_still_shows_the_forecast():
    reply = {**_catalog([FORECAST_DAY]), "error": {"code": "40002", "message": "partial"}}
    out, _ = await _weather(_seeker(reply))
    assert "max_temp: 34.2" in out


@pytest.mark.asyncio
async def test_an_error_at_one_town_still_walks_to_the_next():
    """Kutch walks Bhuj -> Bhachau. An error reply at Bhuj used to read as zero
    rows and the walk went on; it must still reach Bhachau's forecast."""
    fake = _SequencedClient([_seeker(ERROR_CALLBACK), _seeker(_catalog([FORECAST_DAY]))])
    with patch.object(vistaar.httpx, "AsyncClient", return_value=fake):
        out = await vistaar.get_vistaar_weather(_ctx(district="kutch"))
    assert len(fake.calls) == 2
    assert "Bhachau" in out and "max_temp: 34.2" in out


@pytest.mark.asyncio
async def test_when_every_town_fails_it_says_unavailable_not_no_forecast():
    fake = _SequencedClient([_seeker(ERROR_CALLBACK), _seeker({"responses": []})])
    with patch.object(vistaar.httpx, "AsyncClient", return_value=fake):
        out = await vistaar.get_vistaar_weather(_ctx(district="kutch"))
    assert len(fake.calls) == 2
    assert UNAVAILABLE in out.lower()
    assert "No weather forecast" not in out


@pytest.mark.asyncio
async def test_an_assumed_area_is_described_as_a_forecast_not_as_prices():
    out, _ = await _weather(_seeker(_catalog([FORECAST_DAY])), ctx=_ctx(district=None))
    assert "Anand-area forecast" in out
    assert "do not have your district on file" in out
    assert "prices" not in out


# ── Scope: only weather is strict ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_strict_handling_is_opt_in_so_mandi_and_schemes_are_unchanged():
    """Mandi walks to the next candidate on zero rows; reclassifying an error
    callback there changes which market a farmer is quoted, so it stays
    weather-only until it is checked against mandi live."""
    intent = vistaar._weather_intent(DISTRICTS["anand"].primary)
    fake = _FakeAsyncClient(_seeker(ERROR_CALLBACK))
    with patch.object(vistaar.httpx, "AsyncClient", return_value=fake):
        assert await vistaar._vistaar_search(intent) == []
        with pytest.raises(vistaar.VistaarLegUnavailable, match="SOURCE_UNAVAILABLE"):
            await vistaar._vistaar_search(intent, strict=True)


@pytest.mark.asyncio
async def test_strict_direct_bap_error_callbacks_are_a_failure():
    fake = _FakeAsyncClient({"responses": [ERROR_CALLBACK]})
    with patch.object(vistaar, "VISTAAR_SEEKER_URL", ""):
        with patch.object(vistaar.httpx, "AsyncClient", return_value=fake):
            with pytest.raises(vistaar.VistaarLegUnavailable, match="SOURCE_UNAVAILABLE"):
                await vistaar._vistaar_search(
                    vistaar._weather_intent(DISTRICTS["anand"].primary), strict=True
                )

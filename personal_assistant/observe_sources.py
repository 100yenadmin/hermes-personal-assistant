"""Bounded Open-Meteo reads; no provider actions, proxies or redirects."""
import ipaddress
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

SEVERITIES = ("clear", "gusts", "heavy rain", "freezing", "snow", "thunderstorm")


class ProviderError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def bases(settings):
    if settings.get("weather_provider", "open_meteo") == "open_meteo":
        return "https://geocoding-api.open-meteo.com/v1/search", "https://api.open-meteo.com/v1/forecast"
    if settings.get("weather_provider") != "local":
        raise ProviderError("refused")
    p = urllib.parse.urlsplit(settings.get("local_base_url", ""))
    host = p.hostname
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback or p.scheme not in {"http", "https"} or p.username or p.password or p.query or p.fragment or p.path not in {"", "/"}:
        raise ProviderError("refused")
    # Do not resolve even a nominally local hostname through DNS.
    authority = p.netloc.replace("localhost", "127.0.0.1")
    base = f"{p.scheme}://{authority}/open-meteo/v1/"
    return base + "search", base + "forecast"


def fetch(url, params, timeout, deadline, usage, provider):
    remaining = deadline - time.monotonic()
    if remaining < 0.15:
        raise ProviderError("timeout")
    usage[provider] = usage.get(provider, 0) + 1
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                             urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(url + "?" + urllib.parse.urlencode(params), timeout=min(timeout, remaining + 0.25)) as response:
            body = response.read(256 * 1024 + 1)
        if len(body) > 256 * 1024:
            raise ProviderError("size")
        return json.loads(body)
    except ProviderError:
        raise
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise ProviderError("timeout" if isinstance(exc, TimeoutError) else "provider") from None


def weather(settings, origin, coords, start, end, deadline, usage):
    """Return cached coordinates and the highest severity in the travel window."""
    try:
        search, forecast = bases(settings)
        provider = settings.get("weather_provider", "open_meteo")
        place = origin.get("iata") or origin.get("label")
        if not coords or coords.get("place") != place:  # Re-geocode when the trip's origin changes.
            data = fetch(search, {"name": origin.get("label") or origin["iata"], "count": 1}, 4, deadline, usage, provider)
            item = data["results"][0]
            coords.clear()
            coords.update({"lat": float(item["latitude"]), "lon": float(item["longitude"]), "label": str(item.get("name", ""))[:80], "place": place})
        data = fetch(forecast, {"latitude": coords["lat"], "longitude": coords["lon"],
                     "hourly": "precipitation,precipitation_probability,weather_code,wind_gusts_10m,snowfall",
                     "timezone": "UTC", "timeformat": "unixtime", "forecast_days": 3}, 6, deadline, usage, provider)
        hourly = data["hourly"]
        levels = []
        for i, stamp in enumerate(hourly["time"]):
            if not start <= float(stamp) <= end:
                continue
            code, rain, probability, gust, snow = (float(hourly[k][i]) for k in
                ("weather_code", "precipitation", "precipitation_probability", "wind_gusts_10m", "snowfall"))
            level = (5 if code in {95, 96, 99} else 4 if 71 <= code <= 77 or code in {85, 86} or snow >= .5
                     else 3 if code in {56, 57, 66, 67} else 2 if code in {65, 82} or rain >= 7.6 and probability >= 50
                     else 1 if gust >= 60 else 0)
            levels.append(level)
        if not levels:
            raise ProviderError("coverage")
        return coords, SEVERITIES[max(levels)]
    except ProviderError:
        raise
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProviderError("parse") from None

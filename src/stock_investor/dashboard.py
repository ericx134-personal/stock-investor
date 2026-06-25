from __future__ import annotations

import html
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .data import Price, load_prices
from .diagnostics import analyze_alert_burden, load_monitor_records
from .io import atomic_write_text
from .kline import classify_kline
from .wave import (
    classify_wave_directional_evidence,
    classify_wave_walk_forward_evidence,
    shrink_direction_probability,
    wave_age_bucket,
    wave_magnitude_bucket,
)


ACTION_RANK = {
    "TRIM_REVIEW": 0,
    "REVIEW": 1,
    "BUY_CANDIDATE": 2,
    "ADD_CANDIDATE": 2,
    "DATA_REVIEW": 3,
    "HOLD": 4,
}

DEFAULT_CHART_MODE = "line"


def _load_jsonl(path: str | Path | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    return load_monitor_records(path)


def _latest_by_symbol(records: list[dict]) -> list[dict]:
    latest = {}
    for record in records:
        symbol = str(record.get("symbol", "")).strip().upper()
        if symbol:
            latest[symbol] = record
    return sorted(
        latest.values(),
        key=lambda item: (
            ACTION_RANK.get(item.get("alert", {}).get("action", ""), 9),
            -float(item.get("portfolio_weight", 0)),
            item.get("symbol", ""),
        ),
    )


def _percent(value: object) -> str:
    return f"{float(value or 0):.1%}"


def _optional_percent(value: object) -> str:
    return "pending" if value is None else f"{float(value):.1%}"


def _optional_signed_percent(value: object) -> str:
    return "pending" if value is None else f"{float(value):+.1%}"


def _optional_ratio(value: object) -> str:
    return "pending" if value is None else f"{float(value):.2f}×"


def _optional_number(value: object) -> str:
    if value is None:
        return "pending"
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.3f}".rstrip("0").rstrip(".")


def _optional_money(value: object) -> str:
    return "pending" if value is None else f"${float(value):,.2f}"


def _mini_sparkline(
    points: list[object],
    fallback_history: list[Price],
    css_class: str,
) -> str:
    values = []
    for point in points or []:
        if isinstance(point, dict):
            value = point.get("price")
        else:
            value = point
        if value is not None and float(value) > 0:
            values.append(float(value))
    if len(values) < 2:
        values = [
            float(item.close)
            for item in fallback_history[-20:]
            if item.close is not None and float(item.close) > 0
        ]
    if len(values) < 2:
        return '<svg class="mini-sparkline empty" viewBox="0 0 70 22" aria-hidden="true"></svg>'
    width, height, pad = 70, 22, 2
    previous_close = None
    for item in reversed(fallback_history[:-1]):
        if item.close is not None and float(item.close) > 0:
            previous_close = float(item.close)
            break
    scale_values = values + ([previous_close] if previous_close is not None else [])
    low, high = min(scale_values), max(scale_values)
    span = high - low or max(high * 0.01, 1)
    step = (width - pad * 2) / (len(values) - 1)
    coords = []
    for index, value in enumerate(values):
        x = pad + index * step
        y = pad + (high - value) / span * (height - pad * 2)
        coords.append(f"{x:.1f},{y:.1f}")
    baseline = ""
    if previous_close is not None:
        baseline_y = pad + (high - previous_close) / span * (height - pad * 2)
        baseline = (
            f'<line class="mini-sparkline-baseline" x1="{pad:.1f}" y1="{baseline_y:.1f}" '
            f'x2="{width - pad:.1f}" y2="{baseline_y:.1f}"/>'
        )
    return (
        f'<svg class="mini-sparkline {html.escape(css_class)}" viewBox="0 0 {width} {height}" '
        f'aria-hidden="true">{baseline}<polyline points="'
        + " ".join(coords)
        + '"/></svg>'
    )


def _sparkline_points(quote: dict) -> list[dict]:
    points = [point for point in quote.get("intraday_path") or [] if isinstance(point, dict)]
    latest_price = _safe_float(quote.get("price"))
    latest_time = quote.get("regular_market_time")
    if latest_price is None or latest_price <= 0:
        return points
    if latest_time is None:
        if not points or _safe_float(points[-1].get("price")) != latest_price:
            points.append({"price": latest_price})
        return points
    latest_timestamp = _quote_time_to_timestamp(latest_time)
    if latest_timestamp is None:
        if not points or _safe_float(points[-1].get("price")) != latest_price:
            points.append({"price": latest_price})
        return points
    if not points or (_quote_time_to_timestamp(points[-1].get("time")) or 0) < latest_timestamp:
        points.append({"time": latest_timestamp, "price": latest_price})
    elif _safe_float(points[-1].get("price")) != latest_price:
        points[-1] = {**points[-1], "price": latest_price}
    return points


def _quote_time_to_timestamp(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _load_account_summary(path: str | Path | None) -> dict:
    if not path or not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text())
    cash = _safe_float(payload.get("cash"))
    buying_power = _safe_float(payload.get("buying_power"))
    return {
        "account_value": _safe_float(payload.get("account_value"))
        or _safe_float(payload.get("total_value")),
        "holdings_value": _safe_float(payload.get("holdings_value"))
        or _safe_float(payload.get("equity_value")),
        "margin_used": _safe_float(payload.get("margin_used")),
        "total_cash": (
            cash
            if cash is not None
            else (_safe_float(payload.get("total_cash")) or 0.0)
        ),
        "total_buying_power": (
            buying_power
            if buying_power is not None
            else (_safe_float(payload.get("total_buying_power")) or 0.0)
        ),
        "account_count": int(payload.get("account_count") or 0),
        "imported_at": str(payload.get("imported_at") or ""),
        "requires_auth": bool(payload.get("requires_auth") or False),
    }


def _load_snaptrade_accounts(path: str | Path | None) -> dict:
    if not path or not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text())
    return payload if isinstance(payload, dict) else {}


def _money_amount(value: object) -> float | None:
    if isinstance(value, dict):
        return _safe_float(value.get("amount"))
    return _safe_float(value)


def _snaptrade_account_total(account_snapshot: dict) -> float:
    account = account_snapshot.get("account") or {}
    balance = account.get("balance") or {}
    total = _money_amount((balance.get("total") if isinstance(balance, dict) else None))
    if total is not None:
        return total
    positions_total = sum(
        _snaptrade_position_value(position)
        for position in account_snapshot.get("positions", [])
        if isinstance(position, dict)
    )
    cash_total = sum(
        _safe_float(balance.get("cash")) or 0.0
        for balance in account_snapshot.get("balances", [])
        if isinstance(balance, dict)
    )
    return positions_total + cash_total


def _snaptrade_position_value(position: dict) -> float:
    market_value = _safe_float(position.get("market_value"))
    if market_value is not None:
        return market_value
    units = _safe_float(position.get("units")) or 0.0
    price = _safe_float(position.get("price")) or 0.0
    return units * price


def _snaptrade_cash(account_snapshot: dict) -> float:
    return sum(
        _safe_float(balance.get("cash")) or 0.0
        for balance in account_snapshot.get("balances", [])
        if isinstance(balance, dict)
    )


def _snaptrade_buying_power(account_snapshot: dict) -> float:
    return sum(
        _safe_float(balance.get("buying_power")) or 0.0
        for balance in account_snapshot.get("balances", [])
        if isinstance(balance, dict)
    )


def _snaptrade_margin_used(account_snapshot: dict) -> float:
    return max(0.0, -_snaptrade_cash(account_snapshot))


def _snaptrade_account_is_visible(account_snapshot: dict) -> bool:
    return (
        abs(_snaptrade_account_total(account_snapshot)) >= 0.01
        or abs(_snaptrade_cash(account_snapshot)) >= 0.01
        or abs(_snaptrade_buying_power(account_snapshot)) >= 0.01
        or bool(account_snapshot.get("positions") or [])
    )


def _visible_snaptrade_accounts(snapshot: dict | None) -> list[dict]:
    if not snapshot:
        return []
    return [
        row
        for row in snapshot.get("accounts", [])
        if isinstance(row, dict) and _snaptrade_account_is_visible(row)
    ]


def _snaptrade_balance_history(
    snapshot: dict | None,
    institution_name: str | None = None,
) -> list[Price]:
    institution_filter = institution_name.lower() if institution_name else None
    selected_accounts = [
        account
        for account in _visible_snaptrade_accounts(snapshot)
        if not institution_filter
        or _snaptrade_institution(account).lower() == institution_filter
    ]
    if not selected_accounts:
        return []
    account_histories: list[dict[date, float]] = []
    for account in selected_accounts:
        prices = _snaptrade_account_balance_history(account)
        if len(prices) < 2:
            return []
        account_points = {price.date: price.close for price in prices}
        if len(account_points) < 2:
            return []
        account_histories.append(account_points)
    common_dates = set(account_histories[0])
    for account_points in account_histories[1:]:
        common_dates &= set(account_points)
    if len(common_dates) < 2:
        return []
    return [
        Price(
            date=day,
            open=sum(account_points[day] for account_points in account_histories),
            high=sum(account_points[day] for account_points in account_histories),
            low=sum(account_points[day] for account_points in account_histories),
            close=sum(account_points[day] for account_points in account_histories),
            volume=0,
        )
        for day in sorted(common_dates)
    ]


def _snaptrade_account_balance_history(account_snapshot: dict) -> list[Price]:
    history = account_snapshot.get("balance_history")
    if not isinstance(history, dict):
        return []
    points = history.get("history", [])
    if not isinstance(points, list):
        return []
    account_points: dict[date, float] = {}
    for point in points:
        parsed = _snaptrade_balance_history_point(point)
        if parsed is None:
            continue
        day, value = parsed
        account_points[day] = value
    return [
        Price(
            date=day,
            open=value,
            high=value,
            low=value,
            close=value,
            volume=0,
        )
        for day, value in sorted(account_points.items())
    ]


def _snaptrade_balance_history_point(point: object) -> tuple[date, float] | None:
    if not isinstance(point, dict):
        return None
    raw_date = point.get("date")
    value = _safe_float(
        point.get("total_value")
        if point.get("total_value") is not None
        else point.get("value")
    )
    if not raw_date or value is None or value <= 0:
        return None
    try:
        day = date.fromisoformat(str(raw_date)[:10])
    except ValueError:
        return None
    return day, value


def _snaptrade_balance_history_status(
    snapshot: dict | None,
    institution_name: str | None = None,
) -> str:
    institution_filter = institution_name.lower() if institution_name else None
    selected_accounts = [
        account
        for account in _visible_snaptrade_accounts(snapshot)
        if not institution_filter
        or _snaptrade_institution(account).lower() == institution_filter
    ]
    if not selected_accounts:
        return "No funded broker accounts are available for account history."
    missing = [
        account
        for account in selected_accounts
        if not isinstance(account.get("balance_history"), dict)
    ]
    if missing:
        return "Exact broker account history is not available for every account yet."
    sparse = [
        account
        for account in selected_accounts
        if len(
            [
                point
                for point in (account.get("balance_history") or {}).get("history", [])
                if _snaptrade_balance_history_point(point) is not None
            ]
        )
        < 2
    ]
    if sparse:
        return "Exact broker account history does not have enough points yet."
    return "Exact broker account history is not available yet."


def _snaptrade_institution(account_snapshot: dict) -> str:
    account = account_snapshot.get("account") or {}
    return str(
        account.get("institution_name")
        or account.get("brokerage")
        or account.get("broker")
        or "Broker"
    )


def _slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "broker"


def _broker_logo(institution: str) -> tuple[str, str, str | None]:
    normalized = institution.lower()
    if "robinhood" in normalized:
        return "broker-logo-robinhood", "R", "https://robinhood.com/favicon.ico"
    if "fidelity" in normalized:
        return "broker-logo-fidelity", "F", "https://www.fidelity.com/favicon.ico"
    if "moomoo" in normalized:
        return "broker-logo-moomoo", "M", "https://www.moomoo.com/favicon.ico"
    return "broker-logo-generic", institution[:1].upper() or "B", None


def _broker_logo_html(institution: str, size_class: str) -> str:
    logo_class, fallback, icon_url = _broker_logo(institution)
    if icon_url:
        return (
            f'<span class="{html.escape(size_class)} {html.escape(logo_class)}">'
            f'<img src="{html.escape(icon_url)}" alt="{html.escape(institution)} icon" loading="lazy" referrerpolicy="no-referrer">'
            f"<b>{html.escape(fallback)}</b></span>"
        )
    return (
        f'<span class="{html.escape(size_class)} {html.escape(logo_class)}">'
        f"{html.escape(fallback)}</span>"
    )


def _snaptrade_last_sync(account_snapshot: dict) -> str:
    sync = (account_snapshot.get("account") or {}).get("sync_status") or {}
    holdings = sync.get("holdings") if isinstance(sync, dict) else {}
    value = holdings.get("last_successful_sync") if isinstance(holdings, dict) else None
    return str(value or "pending")


def _account_position_rows(account_snapshot: dict) -> str:
    rows = []
    for position in account_snapshot.get("positions", []):
        if not isinstance(position, dict):
            continue
        symbol = str(position.get("symbol") or "").upper()
        if not symbol:
            continue
        description = str(position.get("description") or "")
        units = _safe_float(position.get("units")) or 0.0
        price = _safe_float(position.get("price"))
        market_value = _snaptrade_position_value(position)
        average_cost = _safe_float(position.get("average_purchase_price"))
        rows.append(
            (
                -market_value,
                symbol,
                f"""<tr>
                  <td><b>{html.escape(symbol)}</b><span>{html.escape(description[:72])}</span></td>
                  <td>{_optional_number(units)}</td>
                  <td>{_optional_money(price)}</td>
                  <td>{_optional_money(market_value)}</td>
                  <td>{_optional_money(average_cost)}</td>
                </tr>""",
            )
        )
    return "".join(row for _, _, row in sorted(rows)) or (
        '<tr><td colspan="5">No positions are available for this account yet.</td></tr>'
    )


def _broker_account_section(
    account_snapshot: dict,
    payload_registry: dict | None = None,
) -> str:
    account = account_snapshot.get("account") or {}
    account_name = str(account.get("name") or "Broker account")
    account_number = str(account.get("number") or "masked")
    institution = _snaptrade_institution(account_snapshot)
    logo = _broker_logo_html(institution, "broker-icon-mini")
    total = _snaptrade_account_total(account_snapshot)
    margin_used = _snaptrade_margin_used(account_snapshot)
    buying_power = _snaptrade_buying_power(account_snapshot)
    positions = len(account_snapshot.get("positions", []) or [])
    sync_status = "synced" if "pending" not in _snaptrade_last_sync(account_snapshot) else "pending"
    account_history = _snaptrade_account_balance_history(account_snapshot)
    account_history_status = (
        "Exact broker account history is not available for this account yet."
        if len(account_history) < 2
        else ""
    )
    today_return = None
    if len(account_history) >= 2 and account_history[-2].close:
        today_return = (account_history[-1].close - account_history[-2].close) / account_history[-2].close
    chart_key = f"__ACCOUNT__-{_slug(institution)}-{_slug(account_number)}"
    account_chart = _account_kline_card(
        account_history,
        total,
        today_return,
        payload_registry,
        account_history_status,
        chart_key,
        account_name,
        compact=True,
    )
    return f"""
      <article class="broker-account-panel">
        <div class="broker-card-title">
          {logo}
          <div><b>{html.escape(account_name)}</b><small>{html.escape(account_number)}</small></div>
        </div>
        <div class="broker-card-grid">
          <span><small>Value</small><b>{_optional_money(total)}</b></span>
          <span><small>Margin used</small><b>{_optional_money(margin_used)}</b></span>
          <span><small>Buying power</small><b>{_optional_money(buying_power)}</b></span>
          <span><small>Positions</small><b>{positions}</b></span>
        </div>
        <small class="broker-sync {html.escape(sync_status)}">Holdings sync: {html.escape(_snaptrade_last_sync(account_snapshot))}</small>
        <div class="broker-account-chart">{account_chart}</div>
        <div class="broker-table-wrap">
          <table class="broker-positions-table"><thead><tr><th>Symbol</th><th>Shares</th><th>Price</th><th>Value</th><th>Avg cost</th></tr></thead><tbody>{_account_position_rows(account_snapshot)}</tbody></table>
        </div>
      </article>"""


def _broker_institution_view(
    institution: str,
    accounts: list[dict],
    captured_at: str,
    payload_registry: dict | None = None,
) -> str:
    if not accounts:
        return """
        <section class="broker-board empty-state">
          Broker data is not connected yet. Use the SnapTrade read-only import, then refresh this dashboard.
        </section>"""
    total_value = sum(_snaptrade_account_total(account) for account in accounts)
    total_margin_used = sum(_snaptrade_margin_used(account) for account in accounts)
    total_buying_power = sum(_snaptrade_buying_power(account) for account in accounts)
    position_count = sum(len(account.get("positions", []) or []) for account in accounts)
    unique_symbols = sorted(
        {
            str(position.get("symbol") or "").upper()
            for account in accounts
            for position in account.get("positions", [])
            if isinstance(position, dict) and position.get("symbol")
        }
    )
    logo = _broker_logo_html(institution, "broker-icon")
    return f"""
    <section class="broker-board" aria-label="{html.escape(institution)} accounts">
      <section class="broker-hero">
        <div class="broker-brand">
          {logo}
          <div><small>{html.escape(institution)} via SnapTrade · read only</small><h2>{_optional_money(total_value)}</h2><p>{len(accounts)} funded accounts · {position_count} positions · {len(unique_symbols)} symbols</p></div>
        </div>
        <div class="broker-totals">
          <span><small>Margin used</small><b>{_optional_money(total_margin_used)}</b></span>
          <span><small>Buying power</small><b>{_optional_money(total_buying_power)}</b></span>
          <span><small>Last import</small><b>{html.escape(captured_at[:10])}</b></span>
        </div>
      </section>
      <section class="broker-accounts-grid">
        {"".join(_broker_account_section(account, payload_registry) for account in accounts)}
      </section>
      <p class="note">Each account is shown separately. 401k funds, cash sweeps, and non-stock instruments stay visible here but are not promoted into stock prediction signals until the broker-neutral merger can classify them safely.</p>
    </section>"""


def _broker_tab_fragments(
    snapshot: dict,
    payload_registry: dict | None = None,
) -> tuple[str, str]:
    accounts = _visible_snaptrade_accounts(snapshot)
    if not accounts:
        return "", ""
    grouped: dict[str, list[dict]] = {}
    for account in accounts:
        grouped.setdefault(_snaptrade_institution(account), []).append(account)
    buttons = []
    panels = []
    captured_at = str(snapshot.get("captured_at") or "unknown")
    for institution in sorted(grouped, key=lambda item: (item != "Robinhood", item)):
        target = f"broker-{_slug(institution)}"
        logo = _broker_logo_html(institution, "broker-tab-mark")
        buttons.append(
            f'<button type="button" class="tab-button" data-tab-target="{html.escape(target)}" role="tab" aria-selected="false">{logo}{html.escape(institution)}</button>'
        )
        panels.append(
            f'<section id="tab-{html.escape(target)}" class="tab-view" role="tabpanel" hidden>{_broker_institution_view(institution, grouped[institution], captured_at, payload_registry)}</section>'
        )
    return "\n".join(buttons), "\n".join(panels)


def _asset_home(snapshot: dict, account_summary: dict, portfolio_totals: dict) -> str:
    accounts = _visible_snaptrade_accounts(snapshot)
    broker_cards = ""
    if accounts:
        total_value = sum(_snaptrade_account_total(account) for account in accounts)
        position_count = sum(len(account.get("positions", []) or []) for account in accounts)
        institutions = {_snaptrade_institution(account) for account in accounts}
        subtitle = f"{len(institutions)} brokers · {len(accounts)} funded accounts · {position_count} positions"
        captured = str(snapshot.get("captured_at") or "unknown")[:10]
        grouped: dict[str, list[dict]] = {}
        for account in accounts:
            grouped.setdefault(_snaptrade_institution(account), []).append(account)
        broker_cards = "".join(
            _asset_home_broker_card(institution, grouped[institution])
            for institution in sorted(grouped, key=lambda item: (item != "Robinhood", item))
        )
    else:
        cash = float(account_summary.get("total_cash", 0.0) or 0.0)
        total_value = (
            account_summary.get("account_value")
            if account_summary.get("account_value") is not None
            else float(portfolio_totals.get("market_value", 0.0) or 0.0) + cash
        )
        subtitle = "Local portfolio file only"
        captured = str(account_summary.get("imported_at") or "unknown")[:10]
    action_cards = broker_cards + """
        <button type="button" class="asset-nav-card" data-jump-tab="signals">
          <small>Signals</small><b>Holdings board</b><span>Prices, P/L, and model status</span>
        </button>
        <button type="button" class="asset-nav-card" data-jump-tab="opportunities">
          <small>Opportunities</small><b>Action lanes</b><span>Only valid BUY/SELL candidates</span>
        </button>"""
    return f"""
    <section class="asset-home" aria-label="Total asset value">
      <div class="asset-home-main">
        <small>Total assets</small>
        <h2>{_optional_money(total_value)}</h2>
        <p>{html.escape(subtitle)} · updated {html.escape(captured)}</p>
      </div>
      <div class="asset-home-actions">
        {action_cards}
      </div>
    </section>"""


def _asset_home_broker_card(institution: str, accounts: list[dict]) -> str:
    total_value = sum(_snaptrade_account_total(account) for account in accounts)
    position_count = sum(len(account.get("positions", []) or []) for account in accounts)
    target = f"broker-{_slug(institution)}"
    logo = _broker_logo_html(institution, "broker-icon-mini")
    return f"""
        <button type="button" class="asset-broker-card" data-jump-tab="{html.escape(target)}">
          {logo}
          <span><small>{html.escape(institution)}</small><b>{_optional_money(total_value)}</b><em>{len(accounts)} accounts · {position_count} positions</em></span>
        </button>"""


def _load_moomoo_watchlists(path: str | Path | None) -> dict:
    if not path or not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text())


def _moomoo_watchlist_view(payload: dict) -> str:
    groups = [row for row in payload.get("groups", []) if isinstance(row, dict)]
    items = [row for row in payload.get("items", []) if isinstance(row, dict)]
    if not groups and not items:
        return """
        <section class="moomoo-board empty-state">
          Moomoo watchlists are not imported yet. Keep Moomoo OpenD online and run the refresh.
        </section>"""
    names_by_symbol = {
        str(item.get("symbol") or "").upper(): str(item.get("name") or "")
        for item in items
        if item.get("symbol")
    }
    group_cards = []
    for group in groups:
        group_name = str(group.get("group_name") or "Watchlist")
        symbols = [
            str(symbol).upper()
            for symbol in group.get("symbols", [])
            if str(symbol).strip()
        ]
        chips = "".join(
            f"<span><b>{html.escape(symbol)}</b><small>{html.escape(names_by_symbol.get(symbol, ''))}</small></span>"
            for symbol in symbols
        )
        group_cards.append(
            f"""<article class="moomoo-watchlist-card">
              <header><small>Watchlist</small><h3>{html.escape(group_name)}</h3><b>{len(symbols)}</b></header>
              <div class="moomoo-symbol-grid">{chips or '<p class="empty-state">No symbols in this group.</p>'}</div>
            </article>"""
        )
    return f"""
    <section class="moomoo-board" aria-label="Moomoo watchlists">
      <section class="moomoo-hero">
        {_broker_logo_html("Moomoo", "broker-icon")}
        <div><small>Moomoo OpenD · read only</small><h2>{int(payload.get("symbol_count") or len(names_by_symbol))} symbols</h2><p>{int(payload.get("group_count") or len(groups))} watchlists · imported {html.escape(str(payload.get("captured_at") or "unknown")[:10])}</p></div>
      </section>
      <section class="moomoo-watchlists-grid">
        {''.join(group_cards)}
      </section>
    </section>"""


def _parse_utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _account_connection_state(
    path: str | Path | None,
    summary: dict,
    *,
    max_age_hours: int = 36,
) -> dict:
    if not path:
        return {"requires_auth": False, "status": "not_configured", "detail": ""}
    source = Path(path)
    if not source.exists() or not summary:
        return {
            "requires_auth": True,
            "status": "missing",
            "detail": "No fresh broker account summary was found.",
            "imported_at": "",
            "path": str(source),
        }
    imported_at = summary.get("imported_at") or ""
    imported_dt = _parse_utc_datetime(imported_at)
    if summary.get("requires_auth"):
        return {
            "requires_auth": True,
            "status": "oauth_required",
            "detail": "The broker import reported that authorization is required.",
            "imported_at": imported_at,
            "path": str(source),
        }
    if imported_dt is not None:
        age = datetime.now(timezone.utc) - imported_dt
        if age > timedelta(hours=max_age_hours):
            hours = max(1, round(age.total_seconds() / 3600))
            return {
                "requires_auth": True,
                "status": "stale",
                "detail": f"Broker account data is {hours} hours old.",
                "imported_at": imported_at,
                "path": str(source),
            }
    return {
        "requires_auth": False,
        "status": "connected",
        "detail": "Broker account summary is fresh enough for account-level totals.",
        "imported_at": imported_at,
        "path": str(source),
    }


def _account_connection_notice(state: dict) -> str:
    if not state.get("requires_auth"):
        return ""
    imported = state.get("imported_at") or "never"
    detail = state.get("detail") or "Broker account authorization is required."
    return f"""
    <section class="account-connection-notice" data-account-data-stale="true" aria-label="Account data stale">
      <b>Account data needs refresh</b>
      <span>{html.escape(detail)} Showing the last imported read-only portfolio for now. Login/connect work is shelved.</span>
      <small>Last account import: {html.escape(str(imported))}. Use broker aggregators or local providers; this app will not ask for your brokerage password.</small>
    </section>"""


def _file_update_label(path: str | Path | None, fallback: str = "unknown") -> str:
    if not path or not Path(path).exists():
        return fallback
    modified = datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).astimezone()
    return modified.strftime("%b %d %I:%M %p").replace(" 0", " ").lower()


def _refresh_control(latest_quotes_path: str | Path | None, fallback: str) -> str:
    last_updated = _file_update_label(latest_quotes_path, fallback)
    return f"""
    <section class="refresh-strip" aria-label="Market data refresh">
      <span>Updated {html.escape(last_updated)}</span>
      <button type="button" data-refresh-button>Update</button>
      <span class="refresh-progress" data-refresh-progress role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" hidden><i></i></span>
      <small data-refresh-message></small>
    </section>"""


def _account_chart_payload(
    history: list[Price],
    account_value: float,
    today_return: float | None,
    payload_registry: dict | None,
    symbol_key: str = "__ACCOUNT__",
    display_name: str = "Account",
) -> dict | None:
    clean_history = [
        item
        for item in history
        if item.open is not None and item.high is not None and item.low is not None
    ]
    if len(clean_history) < 2:
        return None
    payload = _kline_chart_payload(
        clean_history,
        {},
        "ACCOUNT",
        "wait",
        None,
        None,
        None,
        symbol_key,
        account_value,
        today_return,
        [],
    )
    payload["symbol"] = symbol_key
    payload["display_name"] = display_name
    payload["signal"] = {"label": "ACCOUNT", "class": "wait", "probability": None}
    payload["quality"]["source"] = "snaptrade_balance_history"
    if payload_registry is not None:
        payload_registry[payload["symbol"]] = payload
    return payload


def _range_buttons(payload: dict) -> str:
    range_order = ("1D", "1W", "1M", "3M", "YTD", "1Y", "5Y", "MAX")
    active_range = (
        payload["default_range"]
        if payload["ranges"].get(payload["default_range"], {}).get("available")
        else "1M"
    )
    buttons = []
    for label in range_order:
        range_payload = payload["ranges"].get(label, {})
        disabled = "" if range_payload.get("available") else " disabled"
        active_class = ' class="active"' if label == active_range and not disabled else ""
        button_label = html.escape(str(range_payload.get("label") or _chart_range_label(label)))
        buttons.append(
            f'<button type="button" data-chart-range="{label}" data-chart-bars="{int(range_payload.get("bar_count", 0))}"'
            f'{active_class}{disabled}>{button_label}</button>'
        )
    return "".join(buttons)


def _chart_mode_buttons(active: str = DEFAULT_CHART_MODE) -> str:
    active_mode = active if active in {"line", "candles"} else DEFAULT_CHART_MODE
    buttons = []
    for mode, label in (("line", "Line"), ("candles", "Candle")):
        active_class = ' class="active"' if mode == active_mode else ""
        buttons.append(
            f'<button type="button" data-chart-mode="{mode}"{active_class}>{label}</button>'
        )
    return "".join(buttons)


def _account_kline_card(
    history: list[Price],
    account_value: float,
    today_return: float | None,
    payload_registry: dict | None,
    unavailable_message: str = "Exact broker account history is not available yet.",
    symbol_key: str = "__ACCOUNT__",
    display_name: str = "Account",
    compact: bool = False,
) -> str:
    payload = _account_chart_payload(
        history,
        account_value,
        today_return,
        payload_registry,
        symbol_key,
        display_name,
    )
    if not payload:
        return (
            f'<div class="account-chart-empty">{html.escape(unavailable_message)}</div>'
        )
    active_range = (
        payload["default_range"]
        if payload["ranges"].get(payload["default_range"], {}).get("available")
        else "1M"
    )
    compact_class = " compact-account-chart" if compact else ""
    return f"""<section class="kline-chart-card account-kline-card{compact_class}" data-chart-symbol="{html.escape(symbol_key)}" data-active-chart-range="{html.escape(active_range)}" data-chart-mode="line">
      <div class="interactive-kline" data-chart-root role="img" aria-label="{html.escape(display_name)} broker-reported account value history"></div>
      <div class="chart-overlay" data-chart-overlay aria-hidden="true"></div>
      <div class="chart-tooltip" aria-live="polite" hidden></div>
      <div class="chart-status" data-chart-status>Loading local chart runtime…</div>
      <div class="chart-fallback" data-chart-fallback hidden>Interactive account chart unavailable; chart data is still recorded in the payload.</div>
      <div class="chart-controls">
        <div class="chart-range-tabs" aria-label="Account chart time range">
          {_range_buttons(payload)}
        </div>
      </div>
      <div class="chart-legend account-chart-legend"><span>Broker-reported account value</span></div>
    </section>"""


def _portfolio_account_overview(
    totals: dict[str, float],
    history: list[Price],
    account_summary: dict,
    payload_registry: dict | None,
    account_history_status: str | None = None,
) -> str:
    holdings_value = (
        _safe_float(account_summary.get("holdings_value"))
        or totals.get("market_value", 0.0)
    )
    cash_balance = float(account_summary.get("total_cash", 0.0) or 0.0)
    buying_power = float(account_summary.get("total_buying_power", 0.0) or 0.0)
    margin_used = (
        _safe_float(account_summary.get("margin_used"))
        if _safe_float(account_summary.get("margin_used")) is not None
        else max(0.0, -cash_balance)
    )
    account_value = (
        _safe_float(account_summary.get("account_value"))
        or holdings_value + cash_balance
    )
    today_dollars = totals.get("today_dollars", 0.0)
    gain_dollars = totals.get("gain_dollars", 0.0)
    prior_value = account_value - today_dollars
    today_pct = today_dollars / prior_value if prior_value > 0 else None
    today_class = "positive" if today_dollars >= 0 else "negative"
    gain_class = "positive" if gain_dollars >= 0 else "negative"
    margin_class = "negative" if margin_used > 0 else "positive"
    chart = _account_kline_card(
        history,
        account_value,
        today_pct,
        payload_registry,
        account_history_status or "Exact broker account history is not available yet.",
    )
    return f"""
    <section class="account-overview" aria-label="Account overview">
      <div class="account-copy">
        <small>Individual</small>
        <h2>${account_value:,.2f}</h2>
        <p class="{today_class}"><b>{_signed_money(today_dollars)}</b> ({_optional_signed_percent(today_pct)}) today</p>
      </div>
      <div class="account-chart-wrap">{chart}</div>
      <div class="account-stats" aria-label="Account summary">
        <div><small>Account value</small><b>{_optional_money(account_value)}</b></div>
        <div><small>Margin used</small><b class="{margin_class}">{_optional_money(margin_used)}</b></div>
        <div><small>Gain/Loss</small><b class="{gain_class}">{_signed_money(gain_dollars)}</b></div>
        <div><small>Buying power</small><b>{_optional_money(buying_power)}</b></div>
      </div>
    </section>"""


def _health_value(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and 0 <= value <= 1:
        return f"{value:.0%}"
    if isinstance(value, dict):
        return " · ".join(f"{key} {item}" for key, item in sorted(value.items()))
    return str(value)


def _rate_interval(rate: object, low: object, high: object) -> str:
    if rate is None or low is None or high is None:
        return "pending"
    return f"{float(rate):.0%} ({float(low):.0%}–{float(high):.0%})"


def _clamped_rate(value: object) -> float:
    return max(0.0, min(1.0, float(value or 0)))


def _directional_rate(row: dict | None, signal_label: str, key: str) -> float | None:
    if not row or row.get(key) is None:
        return None
    rate = float(row[key])
    return 1 - rate if signal_label == "SELL" else rate


def _evidence_bar(label: str, rate: float | None, detail: str, css_class: str) -> str:
    if rate is None:
        return f"""<div class="evidence-bar {css_class}">
          <div><span>{html.escape(label)}</span><b>pending</b></div>
          <div class="bar-track"><i style="width:0%"></i></div>
          <small>{html.escape(detail)}</small>
        </div>"""
    return f"""<div class="evidence-bar {css_class}">
      <div><span>{html.escape(label)}</span><b>{rate:.0%}</b></div>
      <div class="bar-track"><i style="width:{_clamped_rate(rate):.0%}"></i></div>
      <small>{html.escape(detail)}</small>
    </div>"""


def _position_summary(record: dict) -> str:
    shares = record.get("shares")
    average_cost = record.get("average_cost")
    cost_basis = record.get("cost_basis")
    market_value = float(record.get("market_value") or 0)
    unrealized_return = record.get("unrealized_return")
    unrealized_dollars = None
    if cost_basis is not None:
        unrealized_dollars = market_value - float(cost_basis)
    elif unrealized_return is not None and float(unrealized_return) != -1:
        inferred_cost = market_value / (1 + float(unrealized_return))
        unrealized_dollars = market_value - inferred_cost
    gain_class = (
        "positive"
        if unrealized_dollars is not None and unrealized_dollars >= 0
        else "negative"
    )
    total_gain = "pending"
    if unrealized_dollars is not None:
        sign = "+" if unrealized_dollars >= 0 else "-"
        total_gain = f"{sign}${abs(unrealized_dollars):,.2f}"
    return f"""<section class="position-hero">
      <div class="position-main {gain_class}">
        <small>Your position</small>
        <b>${market_value:,.2f}</b>
        <span>{total_gain} · {_optional_percent(unrealized_return)}</span>
      </div>
      <div><small>Shares</small><b>{_optional_number(shares)}</b></div>
      <div><small>Average cost</small><b>{_optional_money(average_cost)}</b></div>
      <div><small>Cost basis</small><b>{_optional_money(cost_basis)}</b></div>
      <div><small>Portfolio weight</small><b>{_percent(record.get("portfolio_weight"))}</b></div>
      <div><small>Latest close</small><b>${float(record.get("latest_close") or 0):,.2f}</b></div>
    </section>"""


def _unrealized_dollars(record: dict) -> float | None:
    market_value = float(record.get("market_value") or 0)
    cost_basis = record.get("cost_basis")
    unrealized_return = record.get("unrealized_return")
    if cost_basis is not None:
        return market_value - float(cost_basis)
    if unrealized_return is not None and float(unrealized_return) != -1:
        inferred_cost = market_value / (1 + float(unrealized_return))
        return market_value - inferred_cost
    return None


def _signed_money(value: float | None) -> str:
    if value is None:
        return "pending"
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.2f}"


def _signed_compact_money(value: float | None) -> str:
    if value is None:
        return "pending"
    sign = "+" if value >= 0 else "-"
    absolute = abs(float(value))
    if absolute >= 1_000_000:
        return f"{sign}${absolute / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{sign}${absolute / 1_000:.1f}K"
    return f"{sign}${absolute:.0f}"


def _latest_daily_return(history: list[Price]) -> float | None:
    closes = [float(item.close) for item in history if item.close is not None]
    if len(closes) < 2 or closes[-2] <= 0:
        return None
    return closes[-1] / closes[-2] - 1


def _holding_stage(record: dict) -> tuple[str, str]:
    shares = float(record.get("shares") or 0)
    unrealized = record.get("unrealized_return")
    risk = record.get("risk") or {}
    suggested_weight = risk.get("suggested_max_weight")
    portfolio_weight = float(record.get("portfolio_weight") or 0)
    if shares <= 0:
        return "Watchlist candidate", "No live position; judge entry quality first."
    if suggested_weight is not None and portfolio_weight > float(suggested_weight):
        return "Oversized holding", "Position size deserves attention before adding."
    if unrealized is not None and float(unrealized) >= 0.5:
        return "Profit-protection mode", "Large winner; protect gains without assuming the trend is over."
    if unrealized is not None and float(unrealized) >= 0.15:
        return "Winner management", "Positive cushion; trims and trailing stops are different decisions."
    if unrealized is not None and float(unrealized) <= -0.15:
        return "Underwater review", "Loss context matters; separate thesis failure from normal volatility."
    return "Active holding", "Manage around cost, weight, support, resistance, and thesis quality."


def _professional_plan(
    signal_label: str,
    record: dict,
    wave: dict,
    price_plan: dict | None,
) -> dict:
    action = str((record.get("alert") or {}).get("action", ""))
    reasons = " ".join((record.get("alert") or {}).get("reasons", []))
    unrealized = record.get("unrealized_return")
    stage, stage_detail = _holding_stage(record)
    close = record.get("latest_close") or wave.get("latest_close")
    support_low = wave.get("support_zone_low")
    support_high = wave.get("support_zone_high")
    resistance_low = wave.get("resistance_zone_low")
    resistance_high = wave.get("resistance_zone_high")
    if signal_label == "BUY":
        label = "STARTER BUY" if float(record.get("shares") or 0) <= 0 else "ADD REVIEW"
        invalidation = (
            f"Invalid below {_optional_money(support_low)}"
            if support_low is not None
            else "Invalidation pending support evidence"
        )
        return {
            "label": label,
            "class": "buy",
            "stage": stage,
            "stage_detail": stage_detail,
            "primary": (
                "Use the buy zone as a review range, not a market order. "
                "Require thesis and risk-room confirmation before adding."
            ),
            "risk_line": invalidation,
            "management": "Scale only if price holds support and market context is not hostile.",
        }
    if signal_label == "SELL":
        if price_plan and price_plan.get("plan_class") == "breakout":
            label = "BREAKOUT RETEST"
            primary = (
                "Old resistance was exceeded, so the old sell zone is no longer a clean exit. "
                "Watch whether it becomes support."
            )
            risk_line = (
                f"Failure back below {_optional_money(resistance_low)} reopens trim risk"
                if resistance_low is not None
                else "Retest level pending resistance evidence"
            )
            management = "Prefer trailing-profit logic over a fixed sell cap while breakout holds."
            css_class = "breakout"
        elif unrealized is not None and float(unrealized) >= 0.2:
            label = "TRAIL PROFIT"
            primary = "Winner with sell pressure: protect profit without assuming the whole trend is finished."
            risk_line = (
                f"First structural support: {_optional_money(support_low)}–{_optional_money(support_high)}"
                if support_low is not None and support_high is not None
                else "Trailing support pending"
            )
            management = "Consider staged trim near resistance and trailing stop below support."
            css_class = "sell"
        elif action == "TRIM_REVIEW":
            label = "TRIM REVIEW"
            primary = "Portfolio or deterioration pressure suggests reducing exposure, not automatically exiting."
            risk_line = (
                f"Resistance review: {_optional_money(resistance_low)}–{_optional_money(resistance_high)}"
                if resistance_low is not None and resistance_high is not None
                else "Resistance review pending"
            )
            management = "Size decision should consider weight, conviction, and tax context."
            css_class = "sell"
        elif "thesis" in reasons.lower() or "severe" in reasons.lower():
            label = "EXIT REVIEW"
            primary = "The issue may be thesis or severe risk, so this is different from a normal profit trim."
            risk_line = "Recheck thesis before using chart support as an excuse to hold."
            management = "If the thesis is broken, technical bounce zones should not override the exit review."
            css_class = "sell"
        else:
            label = "SELL REVIEW"
            primary = "Historical wave evidence leans down; wait for price behavior around resistance/support."
            risk_line = (
                f"Latest close: {_optional_money(close)}"
                if close is not None
                else "Latest close unavailable"
            )
            management = "Do not treat this as a forced liquidation signal."
            css_class = "sell"
        return {
            "label": label,
            "class": css_class,
            "stage": stage,
            "stage_detail": stage_detail,
            "primary": primary,
            "risk_line": risk_line,
            "management": management,
        }
    return {
        "label": "WAIT",
        "class": "wait",
        "stage": stage,
        "stage_detail": stage_detail,
        "primary": "No robust directional edge. Manage the existing holding by thesis, weight, and risk.",
        "risk_line": "No new buy/sell price plan.",
        "management": "Wait is an active decision when evidence is thin.",
    }


def _professional_plan_card(plan: dict) -> str:
    return f"""<section class="professional-plan {html.escape(plan["class"])}">
      <div><small>PROFESSIONAL PLAN</small><h3>{html.escape(plan["label"])}</h3></div>
      <div><small>Position stage</small><b>{html.escape(plan["stage"])}</b><span>{html.escape(plan["stage_detail"])}</span></div>
      <p>{html.escape(plan["primary"])}</p>
      <div class="plan-grid">
        <span><small>Risk line</small><b>{html.escape(plan["risk_line"])}</b></span>
        <span><small>Management</small><b>{html.escape(plan["management"])}</b></span>
      </div>
    </section>"""


def _evidence_graphics(
    historical: dict | None,
    wave: dict,
    signal_label: str,
    signal_class: str,
) -> str:
    if not historical:
        return """<section class="evidence-graphics wait">
          <div class="probability-ring" style="--probability:0%"><b>--</b><span>direction</span></div>
          <div class="why-copy"><small>WHY WAIT</small><h3>No comparable wave sample</h3>
          <p>The system refuses directional confidence until a matching historical sample exists.</p></div>
        </section>"""
    raw_direction_rate = _directional_rate(historical, signal_label, "positive_rate")
    direction_rate = shrink_direction_probability(
        raw_direction_rate, int(historical.get("observations", 0))
    )
    breadth_rate = _directional_rate(
        historical, signal_label, "symbol_positive_return_rate"
    )
    beat_spy = historical.get("beat_benchmark_rate")
    probability = direction_rate if signal_label in {"BUY", "SELL"} else None
    direction_word = (
        "rose" if signal_label == "BUY" else "fell" if signal_label == "SELL" else "agreed"
    )
    horizon = str(historical.get("horizon", "selected horizon"))
    observations = int(historical.get("observations", 0))
    symbols = int(historical.get("directional_symbols", historical.get("symbols", 0)))
    headline = (
        f"{direction_rate:.0%} shrunk confidence; raw analog rate {raw_direction_rate:.0%}"
        if direction_rate is not None and signal_label in {"BUY", "SELL"}
        else "Historical direction is not proven"
    )
    relative_detail = (
        f"{_historical_stance(historical)} versus SPY"
        if beat_spy is not None
        else "SPY comparison unavailable"
    )
    return f"""<section class="evidence-graphics {signal_class}">
      <div class="evidence-hero">
        <div class="probability-ring" style="--probability:{_clamped_rate(probability):.0%}">
          <b>{"--" if probability is None else f"{probability:.0%}"}</b><span>{html.escape(signal_label)} direction</span>
        </div>
        <div class="why-copy"><small>WHY {html.escape(signal_label)}</small><h3>{html.escape(headline)}</h3>
        <p>{observations} non-overlapping analogs across {symbols} stocks. BUY/SELL appears only when pooled and cross-stock 95% intervals agree.</p></div>
      </div>
      <div class="evidence-bars">
        {_evidence_bar("Matching waves", direction_rate, f"{observations} historical analogs over {horizon}", signal_class)}
        {_evidence_bar("Cross-stock agreement", breadth_rate, f"{symbols} independently contributing stocks", signal_class)}
        {_evidence_bar("Beat SPY", float(beat_spy) if beat_spy is not None else None, relative_detail, "relative")}
      </div>
    </section>"""


def _kline_chart(
    history: list[Price],
    wave: dict,
    signal_label: str,
    signal_class: str,
    probability: float | None,
    price_plan: dict | None = None,
    data_quality_status: str | None = None,
    average_cost: object = None,
    symbol: object = None,
    latest_price: object = None,
    today_return: object = None,
    forecast_markers: list[dict] | None = None,
    payload_registry: dict | None = None,
) -> str:
    if data_quality_status == "POOR":
        return '<div class="chart-unavailable">K-line chart blocked by the data-quality gate.</div>'
    clean_history = [
        item
        for item in history
        if item.open is not None and item.high is not None and item.low is not None
    ]
    if len(clean_history) < 20:
        return '<div class="chart-unavailable">Daily OHLCV chart unavailable.</div>'
    payload = _kline_chart_payload(
        clean_history,
        wave,
        signal_label,
        signal_class,
        probability,
        price_plan,
        average_cost,
        symbol,
        latest_price,
        today_return,
        forecast_markers,
    )
    symbol_key = payload["symbol"] or "UNKNOWN"
    if payload_registry is not None:
        payload_registry[symbol_key] = payload
        local_payload = ""
    else:
        local_payload = (
            '<script type="application/json" class="kline-local-payload">'
            f"{_json_script(payload)}</script>"
        )
    signal_probability = "--" if probability is None else f"{probability:.0%}"
    active_range = (
        payload["default_range"]
        if payload["ranges"].get(payload["default_range"], {}).get("available")
        else "1M"
    )
    price_context = ""
    if symbol_key != "UNKNOWN":
        price_class = (
            "positive"
            if today_return is not None and float(today_return) >= 0
            else "negative"
        )
        price_context = (
            f'<h3><span>{html.escape(str(symbol).upper())}</span> '
            f'<b>{_optional_money(latest_price)}</b> '
            f'<em class="{price_class}">({_optional_signed_percent(today_return)})</em></h3>'
        )
    else:
        price_context = "<h3>Price wave in context</h3>"
    return f"""<section class="kline-chart-card" data-chart-symbol="{html.escape(symbol_key)}" data-active-chart-range="{html.escape(active_range)}" data-chart-mode="{DEFAULT_CHART_MODE}">
      <div class="chart-heading"><div><small>Interactive K-line · switched by candle interval</small>{price_context}</div>
      <span class="chart-signal {signal_class}">{html.escape(signal_label)} {signal_probability}</span></div>
      <div class="interactive-kline" data-chart-root role="img" aria-label="{html.escape(symbol_key)} interactive candlestick chart"></div>
      <div class="chart-overlay" data-chart-overlay aria-hidden="true"></div>
      <div class="chart-tooltip" aria-live="polite" hidden></div>
      <div class="chart-status" data-chart-status>Loading local chart runtime…</div>
      <div class="chart-fallback" data-chart-fallback hidden>Interactive chart unavailable; chart data is still recorded in the payload.</div>
      <div class="chart-controls">
        <div class="chart-range-tabs" aria-label="Chart time range">
          {_range_buttons(payload)}
        </div>
        <div class="chart-mode-tabs" aria-label="Chart display type">
          {_chart_mode_buttons()}
        </div>
      </div>
      <div class="chart-legend"><span class="support-key">Support zone</span><span class="resistance-key">Resistance zone</span><span class="cost-key">Average cost</span><span class="wave-key">Forecast / pivot</span><span>Volume</span></div>
      {local_payload}
    </section>"""


def _sample_tier(observations: int) -> str:
    if observations >= 20:
        return "developing"
    if observations >= 10:
        return "early"
    return "very small"


def _select_historical_wave(wave: dict, evidence: dict[tuple[object, object], dict]) -> dict | None:
    if not wave:
        return None
    candidates = [
        evidence.get((wave.get("regime"), horizon))
        for horizon in ("63d", "126d", "21d")
    ]
    return next(
        (
            row
            for row in candidates
            if row and int(row.get("observations", 0)) >= 10
        ),
        None,
    ) or next((row for row in candidates if row), None)


def _select_conditional_wave(
    wave: dict,
    evidence: dict[tuple[object, object, object, object], dict],
    horizon: object,
) -> dict | None:
    _, magnitude_bucket = wave_magnitude_bucket(
        wave.get("active_wave_return"), wave.get("reversal_threshold")
    )
    return evidence.get(
        (
            wave.get("regime"),
            horizon,
            wave_age_bucket(wave.get("wave_age_sessions")),
            magnitude_bucket,
        )
    )


def _effective_historical_wave(broad: dict | None, conditional: dict | None) -> dict | None:
    if conditional and (
        _historical_stance(conditional) != "Inconclusive"
        or _directional_stance(conditional) != "WAIT"
    ):
        return conditional
    return broad


def _outcome_summary(row: dict | None) -> str:
    if not row or not row.get("observations"):
        return "No matured outcomes"
    if row.get("directional_success_rate") is not None:
        return (
            f"{float(row['directional_success_rate']):.0%} win rate "
            f"across {row['observations']} matured outcomes"
        )
    if row.get("positive_rate") is not None:
        return (
            f"{float(row['positive_rate']):.0%} positive-return rate "
            f"across {row['observations']} matured outcomes"
        )
    return f"{row['observations']} matured outcomes"


def _board_signal(historical: dict | None) -> tuple[str, str, str, str]:
    if not historical:
        return "WAIT", "wait", "--", "no wave analog"
    classification = historical.get("directional_evidence_classification")
    if classification not in {"BUY", "SELL", "WAIT"}:
        classification = classify_wave_directional_evidence(historical)
    positive_rate = historical.get("positive_rate")
    if classification == "BUY" and positive_rate is not None:
        probability = shrink_direction_probability(
            float(positive_rate), int(historical.get("observations", 0))
        )
        return "BUY", "buy", f"{float(probability):.0%}", "shrunk robust evidence"
    if classification == "SELL" and positive_rate is not None:
        probability = shrink_direction_probability(
            1 - float(positive_rate), int(historical.get("observations", 0))
        )
        return "SELL", "sell", f"{float(probability):.0%}", "shrunk robust evidence"
    return "WAIT", "wait", "--", "direction not proven"


def _price_plan(signal_label: str, wave: dict, current_price: object) -> dict | None:
    """Return a structural review zone without inventing an exact execution price."""
    plan_class = signal_label.lower()
    if signal_label == "BUY":
        label, low_key, high_key = (
            "Buy zone",
            "support_zone_low",
            "support_zone_high",
        )
        source = "confirmed structural support"
        interpretation = "Review add/buy only if price action still supports the thesis."
    elif signal_label == "SELL":
        label, low_key, high_key = (
            "Sell zone",
            "resistance_zone_low",
            "resistance_zone_high",
        )
        source = "confirmed structural resistance"
        interpretation = "Review trim/sell only if price stalls or rejects in this area."
    else:
        return None
    if wave.get(low_key) is None or wave.get(high_key) is None:
        return None
    low, high = sorted((float(wave[low_key]), float(wave[high_key])))
    if low <= 0 or high <= 0:
        return None
    current = float(current_price or wave.get("latest_close") or 0)
    if (
        signal_label == "SELL"
        and current > high
        and wave.get("next_resistance_zone_low") is not None
        and wave.get("next_resistance_zone_high") is not None
    ):
        low, high = sorted(
            (
                float(wave["next_resistance_zone_low"]),
                float(wave["next_resistance_zone_high"]),
            )
        )
        label = "Upper sell zone"
        source = str(wave.get("next_resistance_source") or "next overhead resistance")
        plan_class = "sell"
        interpretation = (
            "Price cleared the old resistance; the next review area is the nearest "
            "overhead pressure cluster, not the invalidated lower zone."
        )
    midpoint = (low + high) / 2
    if (
        signal_label == "SELL"
        and current > high
        and wave.get("next_resistance_zone_low") is None
    ):
        label = "Breakout retest zone"
        source = "former structural resistance"
        plan_class = "breakout"
        interpretation = (
            "The old sell zone has been invalidated by a close above resistance; "
            "treat it as a retest/support area before making a trim decision."
        )
    if current <= 0:
        proximity = "Current-price distance unavailable."
    elif low <= current <= high:
        proximity = "Current price is inside this review zone."
    elif current < low:
        proximity = (
            f"Zone is {low / current - 1:.1%} to {high / current - 1:.1%} "
            "above the current price."
        )
    else:
        proximity = (
            f"Zone is {1 - high / current:.1%} to {1 - low / current:.1%} "
            "below the current price."
        )
    return {
        "label": label,
        "low": low,
        "high": high,
        "midpoint": midpoint,
        "source": source,
        "plan_class": plan_class,
        "interpretation": interpretation,
        "proximity": proximity,
    }


def _next_resistance_zone(
    history: list[Price], current_price: object, existing_high: object = None
) -> dict:
    current = float(current_price or 0)
    if current <= 0:
        return {}
    floor = max(current * 1.005, float(existing_high or 0) * 1.005)
    candidates = sorted(
        {
            round(float(value), 4)
            for item in history[-252:]
            for value in (item.high, item.close)
            if value is not None and float(value) > floor
        }
    )
    if len(candidates) >= 3:
        nearest = candidates[0]
        band_limit = max(nearest * 1.045, nearest + current * 0.025)
        cluster = [value for value in candidates if value <= band_limit][:10]
        if len(cluster) >= 3:
            return {
                "next_resistance_zone_low": min(cluster),
                "next_resistance_zone_high": max(cluster),
                "next_resistance_source": "nearest historical overhead cluster",
            }
    recent_ranges = [
        float(item.high) - float(item.low)
        for item in history[-20:]
        if item.high is not None and item.low is not None and float(item.high) >= float(item.low)
    ]
    if recent_ranges:
        average_range = sum(recent_ranges) / len(recent_ranges)
        low = current + max(average_range, current * 0.025)
        high = low + max(average_range * 1.5, current * 0.035)
        return {
            "next_resistance_zone_low": low,
            "next_resistance_zone_high": high,
            "next_resistance_source": "projected volatility extension",
        }
    return {}


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_json_records(path: str | Path | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("records", "outcomes", "forecasts", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def _forecast_horizon(record: dict) -> str:
    horizon = str(record.get("horizon") or "21d")
    return horizon if horizon.endswith("d") else f"{horizon}d"


def _forecast_return(record: dict, key: str, horizon: str) -> float | None:
    values = record.get(key)
    if not isinstance(values, dict):
        return None
    return _safe_float(values.get(horizon))


def _forecast_marker_key(record: dict) -> str:
    forecast_id = str(record.get("forecast_id") or "").strip()
    if forecast_id:
        return forecast_id
    return "|".join(
        str(record.get(key) or "")
        for key in ("symbol", "signal_date", "direction", "horizon")
    )


def _forecast_marker(record: dict) -> dict | None:
    symbol = str(record.get("symbol") or "").strip().upper()
    signal_date = str(record.get("signal_date") or "").strip()
    direction = str(record.get("direction") or "").strip().upper()
    entry_close = _safe_float(record.get("entry_close"))
    if not symbol or direction not in {"BUY", "SELL", "WAIT"}:
        return None
    if not signal_date or entry_close is None or entry_close <= 0:
        return None
    try:
        date.fromisoformat(signal_date)
    except ValueError:
        return None
    horizon = _forecast_horizon(record)
    directional_return = _forecast_return(record, "directional_returns", horizon)
    status = str(record.get("status") or "RECORDED").upper()
    outcome = "pending"
    if status == "MATURED" and directional_return is not None:
        outcome = "hit" if directional_return > 0 else "miss"
    label = direction
    if outcome == "hit":
        label = f"{direction} HIT"
    elif outcome == "miss":
        label = f"{direction} MISS"
    marker = {
        "time": signal_date,
        "price": entry_close,
        "label": label,
        "type": "forecast",
        "signal": direction.lower(),
        "status": status,
        "outcome": outcome,
        "horizon": horizon,
        "probability": _safe_float(record.get("probability")),
        "return": _forecast_return(record, "returns", horizon),
        "directional_return": directional_return,
        "excess_return": _forecast_return(record, "excess_returns", horizon),
        "max_favorable_excursion": _safe_float(
            record.get("max_favorable_excursion")
        ),
        "max_adverse_excursion": _safe_float(record.get("max_adverse_excursion")),
    }
    for key in ("forecast_id", "forecast_version", "regime"):
        if record.get(key) is not None:
            marker[key] = str(record.get(key))
    return marker


def _forecast_markers_by_symbol(
    forecasts: list[dict],
    outcomes: list[dict],
    *,
    limit_per_symbol: int = 80,
) -> dict[str, list[dict]]:
    latest_by_key: dict[str, dict] = {}
    for record in forecasts:
        latest_by_key[_forecast_marker_key(record)] = record
    for record in outcomes:
        latest_by_key[_forecast_marker_key(record)] = record
    markers_by_symbol: dict[str, list[dict]] = {}
    for record in latest_by_key.values():
        marker = _forecast_marker(record)
        if not marker:
            continue
        symbol = str(record.get("symbol") or "").strip().upper()
        markers_by_symbol.setdefault(symbol, []).append(marker)
    for symbol, markers in markers_by_symbol.items():
        markers.sort(key=lambda marker: (marker["time"], marker.get("forecast_id", "")))
        if len(markers) > limit_per_symbol:
            markers_by_symbol[symbol] = markers[-limit_per_symbol:]
    return markers_by_symbol


def _chart_bar(item: Price) -> dict:
    return {
        "time": item.date.isoformat(),
        "open": float(item.open),
        "high": float(item.high),
        "low": float(item.low),
        "close": float(item.close),
        "volume": float(item.volume or 0),
        "source": "daily",
    }


def _chart_range_label(range_key: str) -> str:
    return {
        "1D": "Daily",
        "1W": "Weekly",
        "1M": "Monthly",
        "3M": "Quarterly",
        "YTD": "YTD",
        "1Y": "Yearly",
        "5Y": "5 years",
        "MAX": "All",
    }.get(range_key, range_key)


def _aggregate_chart_bars(bars: list[dict], bucket: str) -> list[dict]:
    grouped: dict[date, list[dict]] = {}
    for bar in bars:
        bar_date = date.fromisoformat(str(bar["time"]))
        if bucket == "monthly":
            key = date(bar_date.year, bar_date.month, 1)
        elif bucket == "quarterly":
            quarter_month = ((bar_date.month - 1) // 3) * 3 + 1
            key = date(bar_date.year, quarter_month, 1)
        elif bucket == "yearly":
            key = date(bar_date.year, 1, 1)
        else:
            key = bar_date - timedelta(days=bar_date.weekday())
        grouped.setdefault(key, []).append(bar)
    aggregated = []
    for key, items in sorted(grouped.items()):
        aggregated.append(
            {
                "time": key.isoformat(),
                "open": float(items[0]["open"]),
                "high": max(float(item["high"]) for item in items),
                "low": min(float(item["low"]) for item in items),
                "close": float(items[-1]["close"]),
                "volume": sum(float(item.get("volume") or 0) for item in items),
                "source": f"{bucket}_aggregate",
            }
        )
    return aggregated


def _chart_range(
    label: str,
    bars: list[dict],
    fallback_reason: str | None = None,
    aggregation: str | None = None,
    initial_bar_count: int | None = None,
) -> dict:
    if not bars:
        return {
            "label": label,
            "available": False,
            "bar_count": 0,
            "raw_bar_count": 0,
            "aggregation": "none",
            "initial_bar_count": 0,
            "fallback_reason": fallback_reason,
        }
    selected_aggregation = aggregation or "none"
    visible_bars = bars
    if selected_aggregation != "none":
        visible_bars = _aggregate_chart_bars(bars, selected_aggregation)
    return {
        "label": label,
        "available": True,
        "bar_count": len(visible_bars),
        "raw_bar_count": len(bars),
        "aggregation": selected_aggregation,
        "initial_bar_count": min(
            len(visible_bars),
            max(1, int(initial_bar_count or len(visible_bars))),
        ),
        "fallback_reason": fallback_reason,
        "start": bars[0]["time"],
        "end": bars[-1]["time"],
    }


def _chart_ranges(history: list[Price]) -> dict[str, dict]:
    daily_bars = [_chart_bar(item) for item in history]
    latest = history[-1].date
    ytd_bars = [
        bar for bar in daily_bars if date.fromisoformat(bar["time"]).year == latest.year
    ]
    return {
        "1D": _chart_range(
            _chart_range_label("1D"),
            daily_bars,
            initial_bar_count=160,
        ),
        "1W": _chart_range(
            _chart_range_label("1W"),
            daily_bars,
            aggregation="weekly",
            initial_bar_count=130,
        ),
        "1M": _chart_range(
            _chart_range_label("1M"),
            daily_bars,
            aggregation="monthly",
            initial_bar_count=96,
        ),
        "3M": _chart_range(
            _chart_range_label("3M"),
            daily_bars,
            aggregation="quarterly",
            initial_bar_count=56,
        ),
        "YTD": _chart_range(
            _chart_range_label("YTD"),
            ytd_bars or daily_bars[-min(126, len(daily_bars)) :],
            initial_bar_count=len(ytd_bars) if ytd_bars else 126,
        ),
        "1Y": _chart_range(
            _chart_range_label("1Y"),
            daily_bars,
            aggregation="yearly",
            initial_bar_count=40,
        ),
        "5Y": _chart_range(
            _chart_range_label("5Y"),
            daily_bars[-min(1260, len(daily_bars)) :] if len(daily_bars) > 252 else [],
            "Need more than one year of daily bars before showing 5Y.",
            aggregation="monthly",
            initial_bar_count=80,
        ),
        "MAX": _chart_range(_chart_range_label("MAX"), daily_bars, initial_bar_count=260),
    }


def _zone_payload(
    zone_id: str,
    label: str,
    low: object,
    high: object,
    zone_type: str,
) -> dict | None:
    low_value = _safe_float(low)
    high_value = _safe_float(high)
    if low_value is None or high_value is None or low_value <= 0 or high_value <= 0:
        return None
    low_value, high_value = sorted((low_value, high_value))
    return {
        "id": zone_id,
        "label": label,
        "low": low_value,
        "high": high_value,
        "midpoint": (low_value + high_value) / 2,
        "type": zone_type,
    }


def _kline_chart_payload(
    history: list[Price],
    wave: dict,
    signal_label: str,
    signal_class: str,
    probability: float | None,
    price_plan: dict | None,
    average_cost: object,
    symbol: object,
    latest_price: object,
    today_return: object,
    forecast_markers: list[dict] | None = None,
) -> dict:
    clean_history = [
        item
        for item in history
        if item.open is not None and item.high is not None and item.low is not None
    ]
    zones = [
        zone
        for zone in (
            _zone_payload(
                "support",
                "Support",
                wave.get("support_zone_low"),
                wave.get("support_zone_high"),
                "support",
            ),
            _zone_payload(
                "resistance",
                "Pressure",
                wave.get("resistance_zone_low"),
                wave.get("resistance_zone_high"),
                "resistance",
            ),
            _zone_payload(
                "upper_resistance",
                "Upper pressure",
                wave.get("next_resistance_zone_low"),
                wave.get("next_resistance_zone_high"),
                "resistance",
            ),
            _zone_payload(
                "target",
                str((price_plan or {}).get("label") or signal_label),
                (price_plan or {}).get("low"),
                (price_plan or {}).get("high"),
                str((price_plan or {}).get("plan_class") or signal_class),
            )
            if price_plan
            else None,
        )
        if zone
    ]
    lines = []
    average_cost_value = _safe_float(average_cost)
    latest_price_value = _safe_float(latest_price or wave.get("latest_close"))
    if average_cost_value is not None and average_cost_value > 0:
        lines.append(
            {
                "id": "average_cost",
                "label": "Avg cost",
                "price": average_cost_value,
                "type": "cost",
            }
        )
    if latest_price_value is not None and latest_price_value > 0:
        lines.append(
            {
                "id": "current_price",
                "label": "Current",
                "price": latest_price_value,
                "type": "current",
            }
        )
    markers = []
    for marker in forecast_markers or []:
        if not isinstance(marker, dict):
            continue
        marker_time = marker.get("time")
        marker_price = _safe_float(marker.get("price"))
        if marker_time and marker_price is not None:
            markers.append({**marker, "time": str(marker_time), "price": marker_price})
    pivot_date = wave.get("last_pivot_date")
    pivot_price = _safe_float(wave.get("last_pivot_price"))
    if pivot_date and pivot_price is not None:
        markers.append(
            {
                "time": str(pivot_date),
                "price": pivot_price,
                "label": "Pivot",
                "type": "pivot",
                "signal": signal_class,
            }
        )
    latest_bar_date = clean_history[-1].date.isoformat() if clean_history else None
    return {
        "symbol": str(symbol or "").upper(),
        "display_name": str(symbol or "").upper(),
        "quote": {
            "price": latest_price_value,
            "today_return": _safe_float(today_return),
            "latest_bar_date": latest_bar_date,
        },
        "position": {"average_cost": average_cost_value},
        "bars_daily": [_chart_bar(item) for item in clean_history],
        "bars_intraday": [],
        "ranges": _chart_ranges(clean_history) if clean_history else {},
        "default_range": "1D",
        "signal": {
            "label": signal_label,
            "class": signal_class,
            "probability": probability,
        },
        "zones": zones,
        "lines": lines,
        "markers": markers,
        "quality": {
            "ohlcv_bars": len(clean_history),
            "intraday_available": False,
            "fallback_reasons": [],
        },
    }


def _json_script(data: dict) -> str:
    return (
        json.dumps(data, sort_keys=True, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _price_plan_card(plan: dict | None, signal_class: str) -> str:
    if not plan:
        return """<section class="price-plan unavailable">
          <div><small>PRICE PLAN</small><h3>Structural price zone unavailable</h3></div>
          <p>The system refuses to invent a buy or sell price without a confirmed structural zone.</p>
        </section>"""
    tooltip = (
        f'{plan["proximity"]} Based on {plan["source"]}. '
        "Review area only; no automatic order."
    )
    plan_class = html.escape(str(plan.get("plan_class") or signal_class))
    return f"""<section class="price-plan {plan_class}">
      <div><small>{html.escape(plan["label"])}</small>
      <h3>{_optional_money(plan["low"])}–{_optional_money(plan["high"])}</h3></div>
      <div class="price-plan-mid"><small>Mid</small><b>{_optional_money(plan["midpoint"])}</b></div>
      <span class="info-tip" tabindex="0" data-tip="{html.escape(tooltip)}" aria-label="{html.escape(tooltip)}">i</span>
      <p>{html.escape(str(plan.get("interpretation", "")))}</p>
    </section>"""


def _historical_stance(row: dict) -> str:
    classification = row.get("evidence_classification")
    if classification not in {"FAVORABLE", "CAUTION", "INCONCLUSIVE"}:
        classification = classify_wave_walk_forward_evidence(row)
    if classification == "FAVORABLE":
        return "Historically favorable"
    if classification == "CAUTION":
        return "Historical caution"
    return "Inconclusive"


def _directional_stance(row: dict) -> str:
    classification = row.get("directional_evidence_classification")
    if classification not in {"BUY", "SELL", "WAIT"}:
        classification = classify_wave_directional_evidence(row)
    return classification


def _view(action: str, score: float) -> str:
    if action in {"BUY_CANDIDATE", "ADD_CANDIDATE"}:
        return "Bullish candidate"
    if action == "TRIM_REVIEW":
        return "Bearish / trim review"
    if action == "REVIEW" and score <= -0.25:
        return "Bearish review"
    if action == "REVIEW":
        return "Caution / thesis review"
    if action == "DATA_REVIEW":
        return "Insufficient evidence"
    return "Neutral"


def build_dashboard(
    alerts_path: str | Path,
    risk_path: str | Path | None = None,
    scorecard_path: str | Path | None = None,
    title: str = "Stock Investor",
    decision_scorecard_path: str | Path | None = None,
    comparison_path: str | Path | None = None,
    fundamental_coverage_path: str | Path | None = None,
    kline_scorecard_path: str | Path | None = None,
    wave_snapshot_path: str | Path | None = None,
    wave_scorecard_path: str | Path | None = None,
    wave_experiment_scorecard_path: str | Path | None = None,
    wave_conditional_scorecard_path: str | Path | None = None,
    wave_time_decay_scorecard_path: str | Path | None = None,
    direction_rate_comparison_path: str | Path | None = None,
    direction_forecasts_path: str | Path | None = None,
    direction_forecast_outcomes_path: str | Path | None = None,
    direction_forecast_scorecard_path: str | Path | None = None,
    forecast_calibration_curves_path: str | Path | None = None,
    direction_classification_metrics_path: str | Path | None = None,
    direction_error_cohorts_path: str | Path | None = None,
    first_observed_forecasts_path: str | Path | None = None,
    forecast_action_segments_path: str | Path | None = None,
    portfolio_learning_review_path: str | Path | None = None,
    multiple_testing_ledger_path: str | Path | None = None,
    false_discovery_warnings_path: str | Path | None = None,
    model_health_path: str | Path | None = None,
    price_health_path: str | Path | None = None,
    prices_path: str | Path | None = None,
    latest_quotes_path: str | Path | None = None,
    account_summary_path: str | Path | None = None,
    snaptrade_accounts_path: str | Path | None = None,
    moomoo_watchlists_path: str | Path | None = None,
) -> str:
    records = _latest_by_symbol(_load_jsonl(alerts_path))
    diagnostic = analyze_alert_burden(records)
    actions = Counter(record.get("alert", {}).get("action", "UNKNOWN") for record in records)
    kline_ready = sum(
        bool((record.get("technicals") or {}).get("ohlcv_available"))
        for record in records
    )
    model_versions = sorted(
        {record.get("model_version") for record in records if record.get("model_version")}
    )
    risk_records = _load_jsonl(risk_path)
    latest_risk = {}
    for record in risk_records:
        latest_risk[record.get("key", record.get("event_key", "risk"))] = record
    scorecard = (
        json.loads(Path(scorecard_path).read_text())
        if scorecard_path and Path(scorecard_path).exists()
        else []
    )
    decision_scorecard = (
        json.loads(Path(decision_scorecard_path).read_text())
        if decision_scorecard_path and Path(decision_scorecard_path).exists()
        else []
    )
    comparison = (
        json.loads(Path(comparison_path).read_text())
        if comparison_path and Path(comparison_path).exists()
        else None
    )
    fundamental_coverage = (
        json.loads(Path(fundamental_coverage_path).read_text())
        if fundamental_coverage_path and Path(fundamental_coverage_path).exists()
        else None
    )
    kline_scorecard = (
        json.loads(Path(kline_scorecard_path).read_text())
        if kline_scorecard_path and Path(kline_scorecard_path).exists()
        else []
    )
    wave_snapshot = (
        json.loads(Path(wave_snapshot_path).read_text()).get("waves", {})
        if wave_snapshot_path and Path(wave_snapshot_path).exists()
        else {}
    )
    chart_prices = (
        load_prices(prices_path)
        if prices_path and Path(prices_path).exists()
        else {}
    )
    latest_quotes = (
        json.loads(Path(latest_quotes_path).read_text())
        if latest_quotes_path and Path(latest_quotes_path).exists()
        else {}
    )
    account_summary = _load_account_summary(account_summary_path)
    account_connection = _account_connection_state(account_summary_path, account_summary)
    snaptrade_accounts = _load_snaptrade_accounts(snaptrade_accounts_path)
    moomoo_watchlists = _load_moomoo_watchlists(moomoo_watchlists_path)
    wave_scorecard = (
        json.loads(Path(wave_scorecard_path).read_text())
        if wave_scorecard_path and Path(wave_scorecard_path).exists()
        else []
    )
    wave_experiment_scorecard = (
        json.loads(Path(wave_experiment_scorecard_path).read_text())
        if wave_experiment_scorecard_path
        and Path(wave_experiment_scorecard_path).exists()
        else []
    )
    historical_wave_evidence = {
        (row.get("regime"), row.get("horizon")): row
        for row in wave_experiment_scorecard
    }
    wave_conditional_scorecard = (
        json.loads(Path(wave_conditional_scorecard_path).read_text())
        if wave_conditional_scorecard_path
        and Path(wave_conditional_scorecard_path).exists()
        else []
    )
    wave_time_decay_scorecard = (
        json.loads(Path(wave_time_decay_scorecard_path).read_text())
        if wave_time_decay_scorecard_path
        and Path(wave_time_decay_scorecard_path).exists()
        else []
    )
    direction_rate_comparison = (
        json.loads(Path(direction_rate_comparison_path).read_text())
        if direction_rate_comparison_path
        and Path(direction_rate_comparison_path).exists()
        else []
    )
    direction_forecast_markers = _forecast_markers_by_symbol(
        _load_jsonl(direction_forecasts_path),
        _load_json_records(direction_forecast_outcomes_path),
    )
    direction_forecast_scorecard = (
        json.loads(Path(direction_forecast_scorecard_path).read_text())
        if direction_forecast_scorecard_path
        and Path(direction_forecast_scorecard_path).exists()
        else []
    )
    forecast_calibration_curves = (
        json.loads(Path(forecast_calibration_curves_path).read_text())
        if forecast_calibration_curves_path
        and Path(forecast_calibration_curves_path).exists()
        else []
    )
    direction_classification_metrics = (
        json.loads(Path(direction_classification_metrics_path).read_text())
        if direction_classification_metrics_path
        and Path(direction_classification_metrics_path).exists()
        else []
    )
    direction_error_cohorts = (
        json.loads(Path(direction_error_cohorts_path).read_text())
        if direction_error_cohorts_path
        and Path(direction_error_cohorts_path).exists()
        else []
    )
    first_observed_forecasts = (
        json.loads(Path(first_observed_forecasts_path).read_text())
        if first_observed_forecasts_path
        and Path(first_observed_forecasts_path).exists()
        else {"holdings": []}
    )
    forecast_action_segments = (
        json.loads(Path(forecast_action_segments_path).read_text())
        if forecast_action_segments_path
        and Path(forecast_action_segments_path).exists()
        else {"scorecard": []}
    )
    portfolio_learning_review_link = (
        '<p><a href="portfolio-learning-review.md">Open monthly portfolio-learning review</a></p>'
        if portfolio_learning_review_path
        and Path(portfolio_learning_review_path).exists()
        else ""
    )
    multiple_testing_ledger = (
        json.loads(Path(multiple_testing_ledger_path).read_text())
        if multiple_testing_ledger_path
        and Path(multiple_testing_ledger_path).exists()
        else None
    )
    false_discovery_warnings = (
        json.loads(Path(false_discovery_warnings_path).read_text())
        if false_discovery_warnings_path
        and Path(false_discovery_warnings_path).exists()
        else []
    )
    model_health = (
        json.loads(Path(model_health_path).read_text())
        if model_health_path and Path(model_health_path).exists()
        else None
    )
    price_health = (
        json.loads(Path(price_health_path).read_text())
        if price_health_path and Path(price_health_path).exists()
        else None
    )
    price_health_by_symbol = {
        row.get("symbol"): row for row in (price_health or {}).get("symbols", [])
    }
    conditional_wave_evidence = {
        (
            row.get("regime"),
            row.get("horizon"),
            row.get("wave_age_bucket"),
            row.get("wave_magnitude_bucket"),
        ): row
        for row in wave_conditional_scorecard
    }
    relevant_scorecard = [
        row
        for row in scorecard
        if not model_versions or row.get("model_version") in model_versions
    ]
    evidence = {
        (row.get("action"), row.get("horizon")): row for row in relevant_scorecard
    }
    relevant_decision_scorecard = [
        row
        for row in decision_scorecard
        if not model_versions or row.get("model_version") in model_versions
    ]
    decision_evidence = {
        (row.get("action"), row.get("horizon")): row
        for row in relevant_decision_scorecard
    }
    health_gate_rows = "".join(
        f"""<tr><td><span class="health-status {str(gate.get("status", "")).lower()}">{html.escape(str(gate.get("status", "")))}</span></td>
        <td>{html.escape(str(gate.get("id", "")).replace("_", " ").title())}</td>
        <td>{html.escape(_health_value(gate.get("actual", "")))}</td>
        <td>{html.escape(_health_value(gate.get("threshold", "")))}</td>
        <td>{html.escape(str(gate.get("detail", "")))}</td></tr>"""
        for gate in (model_health or {}).get("gates", [])
    )
    model_health_panel = (
        f"""<section class="panel"><h2>Explicit Model-Health Gates</h2>
        <p class="health-summary"><span class="health-status {str(model_health.get("overall_status", "")).lower()}">{html.escape(str(model_health.get("overall_status", "")))}</span>
        {len(model_health.get("failed_gates", []))} failed · {len(model_health.get("pending_gates", []))} pending · {len(model_health.get("blocking_failures", []))} blocking</p>
        <table><thead><tr><th>Status</th><th>Gate</th><th>Actual</th><th>Threshold</th><th>Meaning</th></tr></thead>
        <tbody>{health_gate_rows}</tbody></table>
        <p class="note">PENDING means evidence has not matured; it is not treated as a pass or a failed prediction. BLOCKED means a safety or required-data gate failed.</p></section>"""
        if model_health
        else ""
    )
    price_health_rows = "".join(
        f"""<tr><td><b>{html.escape(str(row.get("symbol", "")))}</b></td>
        <td><span class="health-status {str(row.get("data_quality_status", "")).lower()}">{html.escape(str(row.get("data_quality_status", "")))}</span> {_percent(row.get("data_quality_score"))}</td>
        <td><span class="health-status {str(row.get("status", "")).lower()}">{html.escape(str(row.get("status", "")))}</span></td>
        <td>{html.escape(str(row.get("latest_date") or "missing"))}</td>
        <td>{html.escape(str(row.get("age_calendar_days") if row.get("age_calendar_days") is not None else "missing"))}</td>
        <td>{_percent(row.get("session_coverage_rate")) if row.get("session_coverage_rate") is not None else "pending"}</td>
        <td>{html.escape(str(row.get("missing_session_count", 0)))}</td>
        <td>{_percent(row.get("ohlcv_coverage_rate"))}</td>
        <td>{html.escape(str(row.get("suspicious_intraday_range_count", 0)))}</td>
        <td>{html.escape(str(row.get("suspicious_close_gap_count", 0)))}</td>
        <td>{"Review" if row.get("cost_basis_reconciliation_warning") else "—"}</td>
        <td><span class="health-status {str(row.get("symbol_lifecycle_status", "")).lower()}">{html.escape(str(row.get("symbol_lifecycle_status", "OK")))}</span>
        {html.escape("; ".join(row.get("symbol_lifecycle_reasons", [])) or "—")}</td>
        <td>{html.escape(str(row.get("adjustment_type", "unknown")))} · {html.escape(str(row.get("adjustment_confidence", "unknown")).lower())}</td>
        <td>{html.escape(str(row.get("source", "")))} · {html.escape(str(row.get("source_confidence", "")).lower())}</td></tr>"""
        for row in (price_health or {}).get("symbols", [])
    )
    price_health_panel = (
        f"""<section class="panel"><h2>Per-Symbol Price Freshness</h2>
        <table><thead><tr><th>Symbol</th><th>Data quality</th><th>Status</th><th>Latest</th><th>Age days</th><th>Session coverage</th><th>Missing</th><th>OHLCV coverage</th><th>Extreme ranges</th><th>Close gaps</th><th>Cost basis</th><th>Symbol lifecycle</th><th>Adjustment</th><th>Source</th></tr></thead>
        <tbody>{price_health_rows}</tbody></table>
        <p class="note">Expected sessions use the latest 252 observed {html.escape(str(price_health.get("expected_session_source") or "benchmark"))} market dates, avoiding an invented holiday calendar. Source confidence distinguishes declared provenance from conservative filename inference.</p></section>"""
        if price_health
        else ""
    )

    board_rows: dict[str, list[tuple[float, float, str, str]]] = {
        "BUY": [],
        "SELL": [],
        "WAIT": [],
    }
    chart_payloads = {"version": 1, "source": "dashboard-v3", "symbols": {}}
    portfolio_rows = []
    detail_panels = []
    portfolio_totals = {
        "market_value": 0.0,
        "cost_basis": 0.0,
        "gain_dollars": 0.0,
        "today_dollars": 0.0,
    }
    for index, record in enumerate(records):
        alert = record.get("alert", {})
        action = alert.get("action", "UNKNOWN")
        score = float(alert.get("score", 0))
        action_evidence = (
            decision_evidence.get((action, "63d"))
            or decision_evidence.get((action, "21d"))
            or evidence.get((action, "63d"))
            or evidence.get((action, "21d"))
        )
        wins = _outcome_summary(action_evidence)
        reasons = "".join(
            f"<li>{html.escape(reason)}</li>" for reason in alert.get("reasons", [])
        )
        technicals = record.get("technicals") or {}
        symbol = str(record.get("symbol", "")).upper()
        quote = latest_quotes.get(symbol, {})
        display_price = float(quote.get("price") or record.get("latest_close") or 0)
        shares = float(record.get("shares") or 0)
        market_value = shares * display_price if shares > 0 else float(record.get("market_value") or 0)
        gain_dollars = (
            market_value - float(record.get("cost_basis"))
            if record.get("cost_basis") is not None
            else _unrealized_dollars(record)
        )
        unrealized_return = record.get("unrealized_return")
        display_unrealized_return = (
            gain_dollars / float(record.get("cost_basis"))
            if gain_dollars is not None
            and record.get("cost_basis") is not None
            and float(record.get("cost_basis")) > 0
            else unrealized_return
        )
        display_return_class = (
            "positive"
            if display_unrealized_return is not None
            and float(display_unrealized_return) >= 0
            else "negative"
        )
        symbol_history = chart_prices.get(record.get("symbol", ""), [])
        today_return = quote.get("today_return")
        if today_return is None:
            today_return = _latest_daily_return(symbol_history)
        today_return_class = (
            "positive"
            if today_return is not None and float(today_return) >= 0
            else "negative"
        )
        previous_close = quote.get("previous_close")
        if previous_close is None:
            daily_closes = [
                float(item.close)
                for item in symbol_history
                if item.close is not None and float(item.close) > 0
            ]
            previous_close = daily_closes[-2] if len(daily_closes) >= 2 else None
        today_dollars = (
            shares * (display_price - float(previous_close))
            if previous_close is not None and shares > 0
            else None
        )
        portfolio_totals["market_value"] += market_value
        if record.get("cost_basis") is not None:
            portfolio_totals["cost_basis"] += float(record.get("cost_basis") or 0)
        if gain_dollars is not None:
            portfolio_totals["gain_dollars"] += float(gain_dollars)
        if today_dollars is not None:
            portfolio_totals["today_dollars"] += float(today_dollars)
        wave = {
            **wave_snapshot.get(record.get("symbol", ""), {}),
            **_next_resistance_zone(
                symbol_history,
                display_price or record.get("latest_close"),
                (wave_snapshot.get(record.get("symbol", ""), {}) or {}).get(
                    "resistance_zone_high"
                ),
            ),
        }
        broad_historical_wave = _select_historical_wave(wave, historical_wave_evidence)
        conditional_wave = _select_conditional_wave(
            wave,
            conditional_wave_evidence,
            broad_historical_wave.get("horizon") if broad_historical_wave else None,
        )
        historical_wave = _effective_historical_wave(
            broad_historical_wave, conditional_wave
        )
        signal_label, signal_class, signal_percent, signal_evidence = _board_signal(
            historical_wave
        )
        signal_probability = (
            shrink_direction_probability(
                float(historical_wave.get("positive_rate", 0)),
                int(historical_wave.get("observations", 0)),
            )
            if signal_label == "BUY" and historical_wave
            else (
                shrink_direction_probability(
                    1 - float(historical_wave.get("positive_rate", 1)),
                    int(historical_wave.get("observations", 0)),
                )
                if signal_label == "SELL" and historical_wave
                else None
            )
        )
        price_plan = _price_plan(
            signal_label,
            wave,
            display_price or record.get("latest_close") or wave.get("latest_close"),
        )
        professional_plan = _professional_plan(
            signal_label,
            record,
            wave,
            price_plan,
        )
        evidence_graphics = _evidence_graphics(
            historical_wave, wave, signal_label, signal_class
        )
        kline_chart = _kline_chart(
            symbol_history,
            wave,
            signal_label,
            signal_class,
            signal_probability,
            price_plan,
            (price_health_by_symbol.get(record.get("symbol", "")) or {}).get(
                "data_quality_status"
            ),
            record.get("average_cost"),
            record.get("symbol", ""),
            display_price,
            today_return,
            forecast_markers=direction_forecast_markers.get(symbol, []),
            payload_registry=chart_payloads["symbols"],
        )
        return_class = (
            "positive"
            if unrealized_return is not None and float(unrealized_return) >= 0
            else "negative"
        )
        wave_view = (
            f"""<div class="wave">
              <b>{html.escape(wave.get("regime", "Wave unavailable"))}</b> ·
              active move <b>{_optional_percent(wave.get("active_wave_return"))}</b> ·
              wave age <b>{wave.get("wave_age_sessions", "pending")} sessions</b> ·
              support zone <b>{_optional_money(wave.get("support_zone_low"))}–{_optional_money(wave.get("support_zone_high"))}</b> ·
              resistance zone <b>{_optional_money(wave.get("resistance_zone_low"))}–{_optional_money(wave.get("resistance_zone_high"))}</b> ·
              structural position <b>{_optional_percent(wave.get("structural_range_position"))}</b>
            </div>"""
            if wave
            else '<div class="wave">Structural wave evidence unavailable.</div>'
        )
        wave_history_view = (
            f"""<div class="wave-history">
              Exploratory historical {html.escape(historical_wave["horizon"])} analogs:
              <b>{html.escape(_historical_stance(historical_wave))}</b> ·
              direction gate <b>{html.escape(_directional_stance(historical_wave))}</b> ·
              <b>{_percent(historical_wave.get("positive_rate"))} positive</b> ·
              <b>{_rate_interval(historical_wave.get("beat_benchmark_rate"), historical_wave.get("beat_benchmark_ci_low"), historical_wave.get("beat_benchmark_ci_high"))} beat SPY</b> ·
              cross-stock breadth <b>{_rate_interval(historical_wave.get("symbol_positive_excess_rate"), historical_wave.get("symbol_positive_excess_ci_low"), historical_wave.get("symbol_positive_excess_ci_high"))}</b>
              across <b>{int(historical_wave.get("benchmark_symbols", 0))} symbols</b> ·
              median return <b>{_percent(historical_wave.get("median_return"))}</b> ·
              mean path <b>{_percent(historical_wave.get("mean_max_gain"))} upside /
              {_percent(historical_wave.get("mean_max_loss"))} downside</b> ·
              {_sample_tier(int(historical_wave.get("observations", 0)))} sample,
              n={int(historical_wave.get("observations", 0))}
            </div>"""
            if historical_wave
            else '<div class="wave-history">No exploratory historical analog sample for this wave regime.</div>'
        )
        conditional_wave_view = (
            f"""<div class="wave-history">
              Conditional age/magnitude evidence used:
              <b>{html.escape(conditional_wave.get("wave_age_bucket", ""))} · {html.escape(conditional_wave.get("wave_magnitude_bucket", ""))}</b> ·
              direction gate <b>{html.escape(_directional_stance(conditional_wave))}</b> ·
              relative evidence <b>{html.escape(_historical_stance(conditional_wave))}</b> ·
              n={int(conditional_wave.get("observations", 0))} across {int(conditional_wave.get("benchmark_symbols", 0))} symbols.
            </div>"""
            if conditional_wave
            and (
                _historical_stance(conditional_wave) != "Inconclusive"
                or _directional_stance(conditional_wave) != "WAIT"
            )
            else (
                f"""<div class="wave-history">
                  Conditional precision refused:
                  <b>{html.escape(conditional_wave.get("wave_age_bucket", ""))} · {html.escape(conditional_wave.get("wave_magnitude_bucket", ""))}</b>
                  remains inconclusive at n={int(conditional_wave.get("observations", 0))} across {int(conditional_wave.get("benchmark_symbols", 0))} symbols.
                </div>"""
                if conditional_wave
                else '<div class="wave-history">Conditional precision refused: no matching age/magnitude cell at the selected horizon.</div>'
            )
        )
        kline = (
            f"""<div class="kline">
              <b>{html.escape(classify_kline(technicals))}</b> ·
              K-line: ATR20 <b>{_percent(technicals.get("atr_20_percent"))}</b> ·
              volume <b>{_optional_ratio(technicals.get("volume_ratio_20"))}</b> ·
              20d breakout <b>{_percent(technicals.get("breakout_20"))}</b> ·
              range position <b>{_percent(technicals.get("close_position_20"))}</b> ·
              latest gap <b>{_optional_percent(technicals.get("latest_gap"))}</b>
            </div>"""
            if technicals.get("ohlcv_available")
            else '<div class="kline">Full K-line OHLCV evidence unavailable.</div>'
        )
        detail_id = f"holding-detail-{index}"
        recent_momentum = technicals.get("return_12_to_1")
        confidence_sort = float(signal_probability or 0)
        signal_rank = {"BUY": 3, "SELL": 2, "WAIT": 1}.get(signal_label, 0)
        signal_source = "no promoted analog"
        if (
            signal_label in {"BUY", "SELL"}
            and historical_wave
            and historical_wave.get("positive_rate") is not None
        ):
            raw_direction_rate = _directional_rate(
                historical_wave, signal_label, "positive_rate"
            )
            signal_source = (
                f"{wave.get('regime', 'wave')} · n={int(historical_wave.get('observations', 0))}"
                f" · raw {signal_label} {_optional_percent(raw_direction_rate)}"
            )
        pressure_summary = (
            f"{_optional_money(wave.get('resistance_zone_low'))}–{_optional_money(wave.get('resistance_zone_high'))}"
            if wave.get("resistance_zone_low") is not None
            and wave.get("resistance_zone_high") is not None
            else "pending"
        )
        support_summary = (
            f"{_optional_money(wave.get('support_zone_low'))}–{_optional_money(wave.get('support_zone_high'))}"
            if wave.get("support_zone_low") is not None
            and wave.get("support_zone_high") is not None
            else "pending"
        )
        more_summary = (
            f"Value ${market_value:,.2f} · Avg cost {_optional_money(record.get('average_cost'))} · "
            f"Shares {_optional_number(record.get('shares'))} · Gain {_signed_money(gain_dollars)} · "
            f"12-1 mom {_optional_percent(recent_momentum)} · Pressure {pressure_summary} · Support {support_summary}"
        )
        mini_sparkline = _mini_sparkline(
            _sparkline_points(quote),
            symbol_history,
            today_return_class,
        )
        portfolio_rows.append(
            f"""
            <button type="button" class="portfolio-holding-card signal-{signal_class}" data-detail-target="{detail_id}" title="{html.escape(more_summary)}"
              aria-label="{html.escape(str(record.get("symbol", "")))} holding, {signal_label} signal"
              data-sort-symbol="{html.escape(str(record.get("symbol", "")))}"
              data-sort-value="{market_value:.6f}"
              data-sort-gain="{float(display_unrealized_return or 0):.6f}"
              data-sort-gain-dollars="{float(gain_dollars or 0):.6f}"
              data-sort-today="{float(today_return or 0):.6f}"
              data-sort-today-dollars="{float(today_dollars or 0):.6f}"
              data-sort-weight="{float(record.get("portfolio_weight") or 0):.6f}"
              data-sort-recent="{float(recent_momentum or 0):.6f}"
              data-sort-confidence="{confidence_sort:.6f}"
              data-sort-signal="{signal_rank}">
              <span class="holding-identity" title="{html.escape(action.replace("_", " "))}"><strong>{html.escape(str(record.get("symbol", "")))}</strong><small>{_optional_number(record.get("shares"))} shares</small></span>
              <span class="holding-spark" data-label="Trend">{mini_sparkline}</span>
              <span class="today-pill {today_return_class}" data-label="Today return %"><b>{_optional_signed_percent(today_return)}</b></span>
              <span class="holding-today-cash {today_return_class}" data-label="Today $"><b>{_signed_compact_money(today_dollars)}</b></span>
              <span class="holding-market-value" data-label="Market Value"><small>Market Value</small><b>${market_value:,.2f}</b></span>
              <span class="holding-weight" data-label="Weight"><small>Weight</small><b>{_percent(record.get("portfolio_weight"))}</b></span>
              <span class="{display_return_class} holding-gain-loss" data-label="Gain/Loss"><small>Gain/Loss</small><b>{_optional_signed_percent(display_unrealized_return)}</b></span>
              <span class="holding-current {today_return_class}" data-label="Price"><small>Price</small><b>${display_price:,.2f}</b></span>
            </button>"""
        )
        board_rows[signal_label].append(
            (
                signal_probability or 0,
                float(record.get("portfolio_weight") or 0),
                str(record.get("symbol", "")),
                f"""
            <button type="button" class="holding-row {action.lower()} signal-{signal_class}" data-detail-target="{detail_id}">
                <span class="ticker"><strong>{html.escape(record.get("symbol", ""))}</strong></span>
                <span class="decision-signal {signal_class}">
                  <strong>{signal_label}</strong><b>{signal_percent}</b>
                  <small>{signal_evidence}</small>
                  {f'<small class="price-target">{_optional_money(price_plan["low"])}–{_optional_money(price_plan["high"])}</small>' if price_plan else ''}
                </span>
                <span class="board-basics">
                  <span><small>Close</small><b>${float(record.get("latest_close") or 0):,.2f}</b></span>
                  <span class="{return_class}"><small>Gain / loss</small><b>{_optional_percent(unrealized_return)}</b></span>
                  <span><small>Weight</small><b>{_percent(record.get("portfolio_weight"))}</b></span>
                </span>
            </button>""",
            )
        )
        detail_panels.append(
            f"""
            <section id="{detail_id}" class="holding-detail" hidden>
              <div class="drawer-heading">
                <div><h2>{html.escape(record.get("symbol", ""))}</h2><span class="decision-signal {signal_class}"><strong>{signal_label}</strong><b>{signal_percent}</b></span></div>
                <span class="board-action">{html.escape(action.replace("_", " "))}</span>
              </div>
                {kline_chart}
                {_position_summary(record)}
                {_professional_plan_card(professional_plan)}
                {evidence_graphics}
                {_price_plan_card(price_plan, signal_class) if signal_label in {"BUY", "SELL"} else ""}
                <details class="advanced-details">
                  <summary>Advanced details</summary>
                <div class="detail-title">
                  <div><b>{html.escape(_view(action, score))}</b><span>Portfolio action view</span></div>
                  <div><b>{html.escape(wins)}</b><span>Live outcome validation</span></div>
                </div>
                <div class="metrics">
                  <span>Market value <b>${float(record.get("market_value") or 0):,.2f}</b></span>
                  <span>Drawdown <b>{_percent(technicals.get("drawdown_from_high"))}</b></span>
                  <span>12-1 momentum <b>{_percent(technicals.get("return_12_to_1"))}</b></span>
                  <span>Suggested max weight <b>{_optional_percent((record.get("risk") or {}).get("suggested_max_weight"))}</b></span>
                </div>
                {wave_view}
                {wave_history_view}
                {conditional_wave_view}
                {kline}
                <ul>{reasons}</ul>
                </details>
            </section>"""
        )

    sorted_board_rows = {
        signal: [
            row[3]
            for row in sorted(
                signal_rows,
                key=lambda row: (-row[0], -row[1], row[2]),
            )
        ]
        for signal, signal_rows in board_rows.items()
    }
    sorted_signal_tuples = {
        signal: sorted(signal_rows, key=lambda row: (-row[0], -row[1], row[2]))
        for signal, signal_rows in board_rows.items()
    }
    top_buy = sorted_signal_tuples["BUY"][0][2] if sorted_signal_tuples["BUY"] else "none"
    top_sell = (
        sorted_signal_tuples["SELL"][0][2] if sorted_signal_tuples["SELL"] else "none"
    )
    portfolio_account_overview = ""
    if not _visible_snaptrade_accounts(snaptrade_accounts):
        account_history_institution = (
            str(account_summary.get("institution_name") or "")
            if account_summary.get("institution_name")
            else None
        )
        account_history = _snaptrade_balance_history(
            snaptrade_accounts,
            account_history_institution,
        )
        account_history_status = _snaptrade_balance_history_status(
            snaptrade_accounts,
            account_history_institution,
        )
        portfolio_account_overview = (
            _account_connection_notice(account_connection)
            + _portfolio_account_overview(
                portfolio_totals,
                account_history,
                account_summary,
                chart_payloads["symbols"],
                account_history_status,
            )
        )
    portfolio_holdings = f"""
    <section class="portfolio-holdings-panel" aria-label="All portfolio holdings">
      <div class="holdings-toolbar">
        <div><small>Your holdings</small><h3>Portfolio</h3></div>
        <label>Sort
          <select id="portfolio-sort" aria-label="Sort portfolio holdings">
            <option value="today-desc" selected>Today Return %</option>
            <option value="today-dollars-desc">Today Return $</option>
            <option value="value-desc">Market value</option>
            <option value="gain-desc">Gain/Loss %</option>
            <option value="gain-dollars-desc">Gain/Loss $</option>
            <option value="recent-desc">12-1 momentum</option>
            <option value="weight-desc">Portfolio weight</option>
            <option value="confidence-desc">Signal confidence</option>
            <option value="signal-desc">Signal type</option>
            <option value="symbol-asc">Symbol A-Z</option>
          </select>
        </label>
      </div>
      <div class="portfolio-holdings-list" data-portfolio-holdings>
        {''.join(portfolio_rows) or '<p class="empty-state">No current holdings loaded.</p>'}
      </div>
    </section>"""
    asset_home = _asset_home(snaptrade_accounts, account_summary, portfolio_totals)
    broker_tab_buttons, broker_tab_panels = _broker_tab_fragments(
        snaptrade_accounts,
        chart_payloads["symbols"],
    )
    moomoo_view = _moomoo_watchlist_view(moomoo_watchlists) if moomoo_watchlists else ""
    moomoo_logo = _broker_logo_html("Moomoo", "broker-tab-mark")
    moomoo_tab_button = (
        f'<button type="button" class="tab-button" data-tab-target="moomoo" role="tab" aria-selected="false">{moomoo_logo}Moomoo</button>'
        if moomoo_view
        else ""
    )
    moomoo_tab_panel = (
        f'<section id="tab-moomoo" class="tab-view" role="tabpanel" hidden>{moomoo_view}</section>'
        if moomoo_view
        else ""
    )
    prioritized_board = f"""
    <section class="priority-board-panel" id="opportunities-board">
      <div class="priority-board-heading"><div><small>JIRA-style BUY / SELL / WAIT lanes</small><h2>Opportunities</h2></div><p>{len(sorted_board_rows["BUY"])} buy · {len(sorted_board_rows["SELL"])} sell · top buy {html.escape(top_buy)} · top sell {html.escape(top_sell)}</p></div>
    <section class="decision-board" aria-label="Prioritized directional signals">
      <section class="signal-column buy-column">
        <header><div><small>Highest confidence first</small><h3>BUY</h3></div><b>{len(sorted_board_rows["BUY"])}</b></header>
        <div class="signal-stack">{''.join(sorted_board_rows["BUY"]) or '<p class="empty-state">No robust buy direction today.</p>'}</div>
      </section>
      <section class="signal-column sell-column">
        <header><div><small>Highest confidence first</small><h3>SELL</h3></div><b>{len(sorted_board_rows["SELL"])}</b></header>
        <div class="signal-stack">{''.join(sorted_board_rows["SELL"]) or '<p class="empty-state">No robust sell direction today.</p>'}</div>
      </section>
      <details class="signal-column wait-column">
        <summary><div><small>Direction not proven</small><h3>WAIT</h3></div><b>{len(sorted_board_rows["WAIT"])}</b></summary>
        <div class="signal-stack">{''.join(sorted_board_rows["WAIT"]) or '<p class="empty-state">No holdings are waiting.</p>'}</div>
      </details>
    </section></section>"""
    current_analogs = []
    for record in records:
        wave = wave_snapshot.get(record.get("symbol", ""), {})
        broad_historical = _select_historical_wave(wave, historical_wave_evidence)
        conditional = _select_conditional_wave(
            wave,
            conditional_wave_evidence,
            broad_historical.get("horizon") if broad_historical else None,
        )
        historical = _effective_historical_wave(broad_historical, conditional)
        if historical:
            current_analogs.append((record, wave, historical))
    current_wave_rows = "".join(
        f"<tr><td><b>{html.escape(record.get('symbol', ''))}</b></td>"
        f"<td>{html.escape(_directional_stance(historical))}</td>"
        f"<td>{html.escape(_historical_stance(historical))}</td>"
        f"<td>{html.escape(wave.get('regime', ''))}</td>"
        f"<td>{html.escape(historical['horizon'])}</td>"
        f"<td>{_rate_interval(historical.get('beat_benchmark_rate'), historical.get('beat_benchmark_ci_low'), historical.get('beat_benchmark_ci_high'))}</td>"
        f"<td>{_rate_interval(historical.get('symbol_positive_excess_rate'), historical.get('symbol_positive_excess_ci_low'), historical.get('symbol_positive_excess_ci_high'))}</td>"
        f"<td>{_percent(historical.get('median_return'))}</td>"
        f"<td>{_percent(historical.get('mean_max_gain'))} / {_percent(historical.get('mean_max_loss'))}</td>"
        f"<td>{_optional_percent(historical.get('directional_leave_one_out_rate'))}</td>"
        f"<td>{int(historical.get('benchmark_symbols', 0))} symbols · {int(historical['observations'])} observations</td></tr>"
        for record, wave, historical in sorted(
            current_analogs,
            key=lambda item: (
                -float(item[2].get("beat_benchmark_ci_low") or 0),
                -int(item[2].get("observations", 0)),
                item[0].get("symbol", ""),
            ),
        )
    ) or '<tr><td colspan="11">No current holdings have historical wave analog evidence.</td></tr>'

    risk_items = "".join(
        f"<li><b>{html.escape(record.get('severity', ''))}</b> "
        f"{html.escape(record.get('message', ''))}</li>"
        for record in latest_risk.values()
    ) or "<li>No persisted portfolio-risk alerts.</li>"
    ranked_evidence = sorted(
        (
            row
            for row in relevant_scorecard
            if row.get("directional_success_rate") is not None
            and row.get("observations", 0) > 0
        ),
        key=lambda row: (
            -float(row["directional_success_rate"]),
            -int(row["observations"]),
        ),
    )
    evidence_rows = "".join(
        f"<tr><td>{html.escape(row['action'].replace('_', ' '))}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{float(row['directional_success_rate']):.0%}</td>"
        f"<td>{int(row['observations'])}</td>"
        f"<td>{_percent(row.get('mean_directional_return'))}</td></tr>"
        for row in ranked_evidence
    ) or '<tr><td colspan="5">No matured forward outcomes yet. Win rates will appear after 21+ sessions.</td></tr>'
    decision_evidence_rows = "".join(
        f"<tr><td>{html.escape(row['action'].replace('_', ' '))}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{int(row['observations'])}</td>"
        f"<td>{_optional_percent(row.get('positive_rate'))}</td>"
        f"<td>{_optional_percent(row.get('mean_excess_return'))}</td>"
        f"<td>{_optional_percent(row.get('directional_success_rate'))}</td></tr>"
        for row in sorted(
            relevant_decision_scorecard,
            key=lambda row: (
                row.get("action", ""),
                int(str(row.get("horizon", "0d")).removesuffix("d")),
            ),
        )
    ) or '<tr><td colspan="6">No all-decision observations have been recorded yet.</td></tr>'
    generated = max(
        (record.get("observed_at") or "unknown" for record in records),
        default="unknown",
    )
    chart_payloads["generated_at"] = generated
    chart_payload_json = _json_script(chart_payloads)
    model_label = ", ".join(model_versions) or "model version unavailable"
    refresh_control = _refresh_control(latest_quotes_path, generated)
    comparison_html = ""
    if comparison:
        baseline = comparison["baseline"]
        candidate = comparison["candidate"]
        changed = ", ".join(sorted(comparison.get("changed_symbols", {}))) or "none"
        comparison_html = f"""
<section class="panel"><h2>Model Experiment</h2>
<div class="experiment">
  <div><b>{baseline["actionable_rate"]:.0%}</b><span>Baseline action-review rate</span></div>
  <div><b>{candidate["actionable_rate"]:.0%}</b><span>Candidate action-review rate</span></div>
  <div><b>{int(comparison["actionable_count_change"]):+d}</b><span>Action-review count change</span></div>
</div>
<p class="note">Changed symbols: {html.escape(changed)}. Selectivity improvement alone does not promote a model; forward outcomes must mature.</p>
</section>"""
    coverage_html = ""
    if fundamental_coverage:
        coverage_html = f"""
<section class="panel"><h2>Fundamental Coverage</h2>
<div class="experiment">
  <div><b>{fundamental_coverage["quality_coverage_rate"]:.0%}</b><span>Quality coverage</span></div>
  <div><b>{fundamental_coverage["valuation_coverage_rate"]:.0%}</b><span>Valuation coverage</span></div>
  <div><b>{len(fundamental_coverage["v3_buy_ready_symbols"])}</b><span>V3 buy-ready names</span></div>
</div>
<p class="note">Revisions coverage: {fundamental_coverage["revisions_coverage_rate"]:.0%}. V3 treats unavailable revisions as neutral; quality and valuation remain required.</p>
</section>"""
    kline_evidence_rows = "".join(
        f"<tr><td>{html.escape(row['regime'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{_percent(row['positive_rate'])}</td>"
        f"<td>{int(row['observations'])}</td>"
        f"<td>{_percent(row['mean_return'])}</td></tr>"
        for row in sorted(
            kline_scorecard,
            key=lambda row: (-float(row["mean_return"]), -int(row["observations"])),
        )
    ) or '<tr><td colspan="5">No matured K-line regime outcomes yet.</td></tr>'
    wave_evidence_rows = "".join(
        f"<tr><td>{html.escape(row['regime'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{_percent(row['positive_rate'])}</td>"
        f"<td>{int(row['observations'])}</td>"
        f"<td>{_percent(row['mean_return'])}</td></tr>"
        for row in sorted(
            wave_scorecard,
            key=lambda row: (-float(row["mean_return"]), -int(row["observations"])),
        )
    ) or '<tr><td colspan="5">No matured structural-wave outcomes yet.</td></tr>'
    wave_experiment_rows = "".join(
        f"<tr><td>{html.escape(row['regime'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{html.escape(_directional_stance(row))}</td>"
        f"<td>{_percent(row['positive_rate'])}</td>"
        f"<td>{_rate_interval(row.get('symbol_positive_return_rate'), row.get('symbol_positive_return_ci_low'), row.get('symbol_positive_return_ci_high'))}</td>"
        f"<td>{_rate_interval(row.get('beat_benchmark_rate'), row.get('beat_benchmark_ci_low'), row.get('beat_benchmark_ci_high'))}</td>"
        f"<td>{_rate_interval(row.get('symbol_positive_excess_rate'), row.get('symbol_positive_excess_ci_low'), row.get('symbol_positive_excess_ci_high'))}</td>"
        f"<td>{_percent(row['median_return'])}</td>"
        f"<td>{_percent(row['mean_max_gain'])}</td>"
        f"<td>{_percent(row['mean_max_loss'])}</td>"
        f"<td>{_optional_percent(row.get('directional_leave_one_out_rate'))}</td>"
        f"<td>{int(row.get('benchmark_symbols', 0))} symbols · {int(row['observations'])} observations · top share {_optional_percent(row.get('top_symbol_observation_share'))}</td></tr>"
        for row in sorted(
            wave_experiment_scorecard,
            key=lambda row: (
                -(
                    float(row["beat_benchmark_ci_low"])
                    if row.get("beat_benchmark_ci_low") is not None
                    else -1
                ),
                -int(row["observations"]),
                -float(row["positive_rate"]),
            ),
        )
    ) or '<tr><td colspan="12">No historical wave experiment outcomes available.</td></tr>'
    conditional_wave_rows = "".join(
        f"<tr><td>{html.escape(_historical_stance(row))}</td>"
        f"<td>{html.escape(_directional_stance(row))}</td>"
        f"<td>{html.escape(row['regime'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{html.escape(row['wave_age_bucket'])}</td>"
        f"<td>{html.escape(row['wave_magnitude_bucket'])}</td>"
        f"<td>{_rate_interval(row.get('beat_benchmark_rate'), row.get('beat_benchmark_ci_low'), row.get('beat_benchmark_ci_high'))}</td>"
        f"<td>{_rate_interval(row.get('symbol_positive_excess_rate'), row.get('symbol_positive_excess_ci_low'), row.get('symbol_positive_excess_ci_high'))}</td>"
        f"<td>{_optional_percent(row.get('directional_leave_one_out_rate'))}</td>"
        f"<td>{int(row.get('benchmark_symbols', 0))} symbols · {int(row['observations'])} observations</td></tr>"
        for row in sorted(
            wave_conditional_scorecard,
            key=lambda row: (
                {"FAVORABLE": 0, "CAUTION": 1, "INCONCLUSIVE": 2}.get(
                    row.get("evidence_classification"), 3
                ),
                -int(row.get("observations", 0)),
                row.get("regime", ""),
            ),
        )
    ) or '<tr><td colspan="10">No conditional wave evidence available.</td></tr>'
    direction_rate_rows = "".join(
        f"<tr><td>{html.escape(row['source'])}</td>"
        f"<td>{html.escape(row['direction'])}</td>"
        f"<td>{html.escape(str(row.get('horizon') or ''))}</td>"
        f"<td>{html.escape(str(row.get('regime') or ''))}</td>"
        f"<td>{html.escape(str(row.get('wave_age_bucket') or '—'))}</td>"
        f"<td>{html.escape(str(row.get('wave_magnitude_bucket') or '—'))}</td>"
        f"<td>{_optional_percent(row.get('raw_probability'))}</td>"
        f"<td>{_optional_percent(row.get('shrunk_probability'))}</td>"
        f"<td>{_optional_percent(row.get('wilson_lower_probability'))}</td>"
        f"<td>{int(row.get('directional_symbols', 0))} symbols · {int(row.get('observations', 0))} observations</td></tr>"
        for row in sorted(
            direction_rate_comparison,
            key=lambda row: (
                row.get("direction", ""),
                -float(row.get("shrunk_probability") or 0),
                -int(row.get("observations", 0)),
                row.get("source", ""),
            ),
        )
    ) or '<tr><td colspan="10">No robust BUY/SELL directional-rate comparisons yet.</td></tr>'
    time_decay_rows = "".join(
        f"<tr><td>{html.escape(row['regime'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{_optional_percent(row.get('weighted_positive_rate'))}</td>"
        f"<td>{_optional_percent(row.get('weighted_mean_return'))}</td>"
        f"<td>{_optional_percent(row.get('weighted_mean_excess_return'))}</td>"
        f"<td>{_optional_number(row.get('weighted_observations'))}</td>"
        f"<td>{int(row.get('symbols', 0))} symbols · {int(row.get('observations', 0))} raw observations</td>"
        f"<td>{_optional_percent(row.get('top_symbol_weight_share'))}</td></tr>"
        for row in sorted(
            wave_time_decay_scorecard,
            key=lambda row: (
                -float(row.get("weighted_mean_return") or -1),
                -float(row.get("weighted_observations") or 0),
                row.get("regime", ""),
            ),
        )
    ) or '<tr><td colspan="8">No time-decayed wave experiment rows available.</td></tr>'
    direction_validation_rows = "".join(
        f"<tr><td>{html.escape(row['forecast_version'])}</td>"
        f"<td>{html.escape(row['direction'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{int(row['forecast_episodes'])}</td>"
        f"<td>{int(row['observations'])}</td>"
        f"<td>{int(row['pending'])}</td>"
        f"<td>{_optional_percent(row.get('mean_probability'))}</td>"
        f"<td>{_rate_interval(row.get('directional_success_rate'), row.get('directional_success_ci_low'), row.get('directional_success_ci_high'))}</td>"
        f"<td>{_optional_number(row.get('brier_score'))}</td></tr>"
        for row in direction_forecast_scorecard
    ) or '<tr><td colspan="9">Displayed forecasts are now recorded; no scorecard rows yet.</td></tr>'
    calibration_curve_rows = "".join(
        f"<tr><td>{html.escape(curve['forecast_version'])}</td>"
        f"<td>{html.escape(curve['direction'])}</td>"
        f"<td>{html.escape(curve['horizon'])}</td>"
        f"<td>{html.escape(point['probability_bucket'])}</td>"
        f"<td>{_optional_percent(point.get('mean_probability'))}</td>"
        f"<td>{_optional_percent(point.get('directional_success_rate'))}</td>"
        f"<td>{int(point.get('observations', 0))}</td>"
        f"<td>{int(point.get('symbols', 0))}</td>"
        f"<td>{html.escape(point.get('status', curve.get('status', 'PENDING')))}</td></tr>"
        for curve in forecast_calibration_curves
        for point in curve.get("points", [])
    ) or '<tr><td colspan="9">Calibration curve points are pending forecast observations.</td></tr>'
    classification_metric_rows = "".join(
        f"<tr><td>{html.escape(row['forecast_version'])}</td>"
        f"<td>{html.escape(row['direction'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{int(row['population'])}</td>"
        f"<td>{int(row['predicted'])}</td>"
        f"<td>{int(row['actual'])}</td>"
        f"<td>{_rate_interval(row.get('precision'), row.get('precision_ci_low'), row.get('precision_ci_high'))}</td>"
        f"<td>{_rate_interval(row.get('recall'), row.get('recall_ci_low'), row.get('recall_ci_high'))}</td>"
        f"<td>{_rate_interval(row.get('false_positive_rate'), row.get('false_positive_rate_ci_low'), row.get('false_positive_rate_ci_high'))}</td>"
        f"<td>{_optional_percent(row.get('coverage'))}</td>"
        f"<td>{html.escape(row.get('status', 'PENDING'))}</td></tr>"
        for row in direction_classification_metrics
    ) or '<tr><td colspan="11">Directional classification metrics are pending matured forecasts.</td></tr>'
    error_cohort_rows = "".join(
        f"<tr><td>{html.escape(row['forecast_version'])}</td>"
        f"<td>{html.escape(row['direction'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{int(row['rank'])}</td>"
        f"<td>{html.escape(row['symbol'])}</td>"
        f"<td>{html.escape(row['signal_date'])}</td>"
        f"<td>{_optional_percent(row.get('probability'))}</td>"
        f"<td>{_optional_percent(row.get('directional_return'))}</td>"
        f"<td>{_optional_percent(row.get('max_adverse_excursion'))}</td>"
        f"<td>{html.escape(str(row.get('evidence_source') or ''))}</td></tr>"
        for row in direction_error_cohorts
    ) or '<tr><td colspan="10">No matured false BUY or SELL episodes yet.</td></tr>'
    first_observed_rows = "".join(
        f"<tr><td><b>{html.escape(row.get('symbol', ''))}</b></td>"
        f"<td>{html.escape((row.get('first_forecast') or {}).get('signal_date') or 'missing')}</td>"
        f"<td>{html.escape((row.get('first_forecast') or {}).get('forecast_version') or 'missing')}</td>"
        f"<td>{html.escape((row.get('first_forecast') or {}).get('direction') or 'missing')}</td>"
        f"<td>{_optional_percent((row.get('first_forecast') or {}).get('probability'))}</td>"
        f"<td>{_optional_money((row.get('first_forecast') or {}).get('entry_close'))}</td>"
        f"<td>{html.escape((row.get('current_forecast') or {}).get('direction') or 'missing')}</td>"
        f"<td>{'Yes' if row.get('changed_since_first') else 'No'}</td>"
        f"<td>{html.escape((row.get('first_outcome') or {}).get('status') or 'PENDING')}</td></tr>"
        for row in sorted(
            first_observed_forecasts.get("holdings", []),
            key=lambda item: (
                item.get("status") != "TRACKED",
                (item.get("first_forecast") or {}).get("signal_date", "9999-99-99"),
                item.get("symbol", ""),
            ),
        )
    ) or '<tr><td colspan="9">No first-observed forecast tracking artifact is available yet.</td></tr>'
    segment_rank = {
        "ACTED_ON_PROXY": 0,
        "WATCHED_PROXY": 1,
        "IGNORED_OR_EXITED_PROXY": 2,
    }
    forecast_action_segment_rows = "".join(
        f"<tr><td><b>{html.escape(row.get('segment_label') or row.get('segment') or '')}</b></td>"
        f"<td>{html.escape(row.get('direction') or '')}</td>"
        f"<td>{html.escape(row.get('horizon') or '')}</td>"
        f"<td>{int(row.get('forecast_episodes') or 0)}</td>"
        f"<td>{int(row.get('matured_observations') or 0)}</td>"
        f"<td>{int(row.get('pending') or 0)}</td>"
        f"<td>{_optional_percent(row.get('directional_success_rate'))}</td>"
        f"<td>{_optional_percent(row.get('mean_directional_return'))}</td>"
        f"<td>{_optional_percent(row.get('mean_excess_return'))}</td>"
        f"<td>{html.escape(', '.join((row.get('symbols') or [])[:8]))}</td></tr>"
        for row in sorted(
            forecast_action_segments.get("scorecard", []),
            key=lambda item: (
                segment_rank.get(item.get("segment"), 9),
                item.get("direction", ""),
                item.get("horizon", ""),
            ),
        )
    ) or '<tr><td colspan="10">No forecast action-segment comparison is available yet.</td></tr>'
    multiple_testing_rows = "".join(
        f"<tr><td>{html.escape(row['family'])}</td>"
        f"<td>{html.escape(row['id'])}</td>"
        f"<td>{int(row.get('hypothesis_count', 0))}</td>"
        f"<td>{html.escape(row.get('multiple_testing_risk', ''))}</td>"
        f"<td>{int(row.get('family_hypothesis_count', 0))}</td>"
        f"<td>{html.escape(row.get('family_multiple_testing_risk', ''))}</td>"
        f"<td>{'Yes' if row.get('predeclared') else 'No'}</td>"
        f"<td>{html.escape(row.get('promotion_status', ''))}</td></tr>"
        for row in (multiple_testing_ledger or {}).get("rows", [])
    ) or '<tr><td colspan="8">No multiple-testing ledger has been generated yet.</td></tr>'
    multiple_testing_panel = (
        f"""<section class="panel"><h2>Multiple-Testing Ledger</h2>
<div class="experiment">
  <div><b>{int(multiple_testing_ledger.get("total_hypothesis_count", 0))}</b><span>Total tested rows</span></div>
  <div><b>{len(multiple_testing_ledger.get("family_hypothesis_counts", {}))}</b><span>Experiment families</span></div>
  <div><b>0</b><span>Promoted from ledger alone</span></div>
</div>
<table><thead><tr><th>Family</th><th>Experiment</th><th>Rows</th><th>Risk</th><th>Family rows</th><th>Family risk</th><th>Predeclared</th><th>Status</th></tr></thead>
<tbody>{multiple_testing_rows}</tbody></table>
<p class="note">This ledger makes repeated testing visible. A high-looking result from any one row is not enough for promotion; family-level false-discovery controls or sealed holdout replication are required first.</p></section>"""
        if multiple_testing_ledger
        else ""
    )
    false_discovery_rows = "".join(
        f"<tr><td>{html.escape(row['family'])}</td>"
        f"<td>{int(row.get('family_hypothesis_count', 0))}</td>"
        f"<td><span class=\"health-status {html.escape(str(row.get('risk', '')).lower())}\">{html.escape(row.get('risk', ''))}</span></td>"
        f"<td>{html.escape(row.get('status', ''))}</td>"
        f"<td>{html.escape(row.get('message', ''))}</td></tr>"
        for row in false_discovery_warnings
    ) or '<tr><td colspan="5">No false-discovery warnings at the current testing volume.</td></tr>'
    false_discovery_panel = f"""<section class="panel"><h2>False-Discovery Warnings</h2>
<table><thead><tr><th>Family</th><th>Tested rows</th><th>Risk</th><th>Status</th><th>Meaning</th></tr></thead>
<tbody>{false_discovery_rows}</tbody></table>
<p class="note">Warnings block model promotion from attractive in-sample rows. They do not hide research rows; they force replication or correction before promotion.</p></section>"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%23000000'/%3E%3Cpath d='M13 43 25 31l8 8 18-24' fill='none' stroke='%2300c805' stroke-width='7' stroke-linecap='round' stroke-linejoin='round'/%3E%3Ccircle cx='51' cy='15' r='5' fill='%2300c805'/%3E%3C/svg%3E">
<style>
:root {{ --bg:#000; --panel:#0b0b0b; --panel-raised:#121212; --muted:#8c8c8c; --text:#f5f5f5;
--line:#252525; --red:#ff5a5f; --amber:#f5b642; --blue:#a6a6a6; --green:#00c805; --green-dim:#003b12; }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--bg);
color:var(--text); font:15px/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display",Inter,ui-sans-serif,system-ui,sans-serif; font-variant-numeric:tabular-nums }}
main {{ max-width:1480px; margin:auto; padding:24px 18px 70px }}
h1 {{ margin:0; font-size:40px; font-weight:750; letter-spacing:-2px }} h1::after {{ color:var(--green); content:"."; }}
.sub {{ color:var(--muted); margin:5px 0 28px }}
.refresh-strip {{ align-items:center; color:var(--muted); display:flex; gap:9px; min-height:24px; margin:-14px 0 14px }}
.refresh-strip span:first-child,.refresh-strip small {{ font-size:11px }} .refresh-strip button {{ background:#101010; border:1px solid #333; border-radius:999px; color:var(--green); cursor:pointer; font:inherit; font-size:11px; font-weight:800; padding:4px 9px }}
.refresh-strip button:disabled {{ color:#555; cursor:progress }} .refresh-progress {{ background:#1b1b1b; border-radius:999px; display:inline-block; height:4px; overflow:hidden; width:96px }}
.refresh-progress i {{ background:var(--green); border-radius:999px; display:block; height:100%; transform-origin:left center; transition:width .2s ease; width:0% }}
.grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:24px }}
.stat,.panel,.holding-row {{ background:var(--panel); border:1px solid var(--line); border-radius:10px }}
.stat {{ padding:18px }} .stat b {{ display:block; font-size:28px }} .stat span {{ color:var(--muted) }}
.warning {{ color:var(--amber) }} .panel {{ padding:20px; margin:18px 0 }} h2 {{ margin:0 0 12px; font-size:19px }}
.tabs {{ border-bottom:1px solid var(--line); display:flex; gap:24px; margin:22px 0 22px; max-width:100%; min-width:0; overflow-x:auto; overscroll-behavior-x:contain; scrollbar-width:none }} .tabs::-webkit-scrollbar {{ display:none }} .tab-button {{ align-items:center; background:transparent; border:0; border-bottom:2px solid transparent; color:var(--muted); cursor:pointer; display:inline-flex; flex:0 0 auto; font:inherit; font-weight:650; gap:7px; margin-bottom:-1px; padding:10px 1px }}
.tab-button:hover {{ color:var(--text) }} .tab-button.active {{ border-bottom-color:var(--green); color:var(--green) }} .tab-view {{ display:none }} .tab-view.active {{ display:block }}
.broker-tab-mark,.broker-icon-mini,.broker-icon {{ align-items:center; background:#00a83b; border-radius:50%; color:#001b0a; display:inline-flex; font-weight:900; justify-content:center }}
.broker-tab-mark {{ font-size:10px; height:17px; width:17px }}
.broker-icon img,.broker-icon-mini img,.broker-tab-mark img {{ border-radius:inherit; display:block; height:100%; object-fit:cover; width:100% }}
.broker-icon b,.broker-icon-mini b,.broker-tab-mark b {{ display:none }}
.broker-logo-robinhood {{ background:#00c805; color:#001f08 }}
.broker-logo-fidelity {{ background:#167b3a; color:#fff }}
.broker-logo-moomoo {{ background:#ff6900; color:#050505 }}
.broker-logo-generic {{ background:#2a2a2a; color:#f5f5f5 }}
.portfolio-board {{ margin:12px 0 24px }}
.board-intro {{ display:flex; align-items:end; justify-content:space-between; gap:18px; margin-top:12px }}
.board-intro h2 {{ margin:0; font-size:25px }} .board-intro p {{ color:var(--muted); margin:0 }}
.account-connection-notice {{ background:#211604; border:1px solid #5d3d09; border-radius:12px; color:#f6d49a; display:grid; gap:4px; margin:10px 0 12px; padding:13px 16px }}
.account-connection-notice b {{ color:#ffb84d; font-size:15px }} .account-connection-notice span {{ color:#f0d8b2 }} .account-connection-notice small {{ color:#c2a984 }}
.account-overview {{ background:#050505; border:1px solid var(--line); border-radius:14px; margin:14px 0 18px; max-width:1120px; overflow:hidden; padding:18px 22px 12px }}
.account-copy small {{ color:var(--muted); display:block; font-size:15px; font-weight:650; margin-bottom:2px }} .account-copy h2 {{ font-size:38px; letter-spacing:-1.5px; line-height:1; margin:0 }}
.account-copy p {{ color:var(--muted); margin:9px 0 0 }} .account-copy p.positive b,.account-stats .positive {{ color:var(--green) }} .account-copy p.negative b,.account-stats .negative {{ color:var(--red) }}
.account-chart-wrap {{ margin:10px 0 8px; min-height:280px; width:100% }}
.account-kline-card {{ background:transparent; border:0; border-radius:0; margin:0; padding:0 }}
.account-kline-card .interactive-kline {{ height:280px; margin-top:0 }}
.account-kline-card .chart-controls {{ align-items:center; border-top:1px solid var(--line); display:flex; gap:14px; justify-content:space-between; margin:8px 0 0; padding-top:8px }}
.account-kline-card .chart-range-tabs {{ justify-content:flex-start; margin:0; padding-top:0 }}
.chart-mode-tabs {{ align-items:center; background:#101010; border:1px solid #333; border-radius:999px; display:inline-flex; gap:0; padding:2px }}
.chart-mode-tabs button {{ background:transparent; border:0; border-radius:999px; color:var(--muted); cursor:pointer; font:inherit; font-size:12px; font-weight:800; min-width:58px; padding:5px 10px }}
.chart-mode-tabs button.active {{ background:var(--green); color:#001f08 }}
.account-chart-legend {{ display:none }}
.account-grid line {{ stroke:#252525; stroke-width:1 }} .account-line {{ fill:none; stroke:currentColor; stroke-linecap:round; stroke-linejoin:round; stroke-width:3 }}
.account-chart-empty {{ align-items:center; background:#0b0b0b; border-radius:10px; color:var(--muted); display:flex; min-height:230px; justify-content:center }}
.account-stats {{ border-top:1px solid var(--line); display:grid; gap:0; grid-template-columns:repeat(4,1fr); margin-top:8px }}
.account-stats div {{ border-right:1px solid var(--line); padding:11px 14px }} .account-stats div:first-child {{ padding-left:0 }} .account-stats div:last-child {{ border-right:0 }}
.account-stats small {{ color:var(--muted); display:block; font-size:11px; font-weight:700 }} .account-stats b {{ display:block; font-size:18px; margin-top:2px }}
.asset-home {{ background:#050505; border:1px solid var(--line); border-radius:16px; display:grid; gap:22px; grid-template-columns:minmax(320px,.95fr) minmax(360px,1.2fr); margin:14px 0 22px; max-width:1120px; padding:26px }}
.asset-home small,.moomoo-hero small {{ color:var(--green); display:block; font-size:11px; font-weight:850; letter-spacing:.6px; text-transform:uppercase }}
.asset-home h2 {{ font-size:52px; letter-spacing:-2.2px; line-height:1; margin:4px 0 }}
.asset-home p {{ color:var(--muted); margin:8px 0 0 }}
.asset-home-actions {{ align-content:start; display:grid; gap:10px; grid-template-columns:repeat(2,minmax(0,1fr)) }}
.asset-broker-card,.asset-nav-card {{ background:#101010; border:1px solid var(--line); border-radius:12px; color:var(--text); cursor:pointer; min-width:0; padding:12px; text-align:left }}
.asset-broker-card {{ align-items:center; display:flex; gap:10px }}
.asset-nav-card {{ align-items:start; display:grid; gap:3px; min-height:72px }}
.asset-broker-card:hover,.asset-nav-card:hover,.asset-broker-card:focus-visible,.asset-nav-card:focus-visible {{ background:#151515; border-color:#3d3d3d; outline:none }}
.asset-broker-card span,.asset-nav-card span {{ min-width:0 }} .asset-broker-card b,.asset-nav-card b {{ display:block; font-size:17px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }}
.asset-broker-card em,.asset-nav-card span {{ color:var(--muted); display:block; font-size:12px; font-style:normal; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }}
.broker-board {{ display:grid; gap:14px; margin:12px 0 24px }}
.broker-hero {{ background:#050505; border:1px solid var(--line); border-radius:14px; display:grid; gap:18px; grid-template-columns:minmax(260px,1.5fr) minmax(260px,1fr); min-width:0; padding:20px 22px }}
.broker-brand {{ align-items:center; display:flex; gap:15px; min-width:0 }} .broker-icon {{ flex:0 0 auto; font-size:30px; height:58px; width:58px }}
.broker-brand small,.broker-section-heading small {{ color:#00a83b; display:block; font-size:10px; font-weight:850; letter-spacing:.6px; text-transform:uppercase }}
.broker-brand h2 {{ font-size:38px; letter-spacing:-1.5px; line-height:1; margin:2px 0 0; overflow-wrap:anywhere }} .broker-brand p {{ color:var(--muted); margin:8px 0 0 }}
.broker-totals {{ display:grid; gap:8px; grid-template-columns:repeat(3,minmax(0,1fr)) }} .broker-totals span,.broker-card-grid span {{ background:#101010; border:1px solid var(--line); border-radius:10px; min-width:0; padding:12px }}
.broker-totals small,.broker-card-grid small {{ color:var(--muted); display:block; font-size:10px; font-weight:750; letter-spacing:.3px; text-transform:uppercase }} .broker-totals b,.broker-card-grid b {{ display:block; font-size:18px; margin-top:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }}
.broker-accounts-grid {{ display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr)) }}
.broker-account-panel {{ background:#050505; border:1px solid var(--line); border-radius:14px; display:grid; gap:12px; overflow:hidden; padding:15px }}
.broker-card-title {{ align-items:center; display:flex; gap:10px }} .broker-icon-mini {{ height:28px; width:28px }} .broker-card-title b {{ display:block; font-size:17px }} .broker-card-title small,.broker-sync {{ color:var(--muted); display:block; font-size:12px }}
.broker-card-grid {{ display:grid; gap:8px; grid-template-columns:repeat(2,minmax(0,1fr)) }} .broker-sync.synced {{ color:var(--green) }}
.broker-positions-panel {{ background:#050505; border:1px solid var(--line); border-radius:14px; overflow:hidden }}
.broker-section-heading {{ padding:16px 18px 8px }} .broker-section-heading h3 {{ font-size:22px; margin:1px 0 0 }}
.broker-table-wrap {{ overflow:auto }} .broker-positions-table td:first-child span {{ color:var(--muted); display:block; font-size:12px; margin-top:2px; max-width:360px }}
.broker-positions-table th {{ color:#00a83b }} .broker-positions-panel .note {{ padding:0 18px 16px }}
.moomoo-board {{ display:grid; gap:14px; margin:12px 0 24px }}
.moomoo-hero,.moomoo-watchlist-card {{ background:#050505; border:1px solid var(--line); border-radius:14px; padding:18px }}
.moomoo-hero {{ align-items:center; display:flex; gap:15px }}
.moomoo-hero h2 {{ font-size:38px; letter-spacing:-1.5px; line-height:1; margin:3px 0 }} .moomoo-hero p {{ color:var(--muted); margin:8px 0 0 }}
.moomoo-watchlists-grid {{ display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr)) }}
.moomoo-watchlist-card header {{ align-items:end; display:flex; justify-content:space-between; gap:12px; margin-bottom:12px }} .moomoo-watchlist-card h3 {{ font-size:22px; margin:0 }} .moomoo-watchlist-card header small {{ color:var(--green); display:block; font-size:10px; font-weight:850; letter-spacing:.6px; text-transform:uppercase }} .moomoo-watchlist-card header b {{ color:var(--muted) }}
.moomoo-symbol-grid {{ display:grid; gap:8px; grid-template-columns:repeat(auto-fill,minmax(110px,1fr)) }} .moomoo-symbol-grid span {{ background:#101010; border:1px solid var(--line); border-radius:10px; min-width:0; padding:9px }} .moomoo-symbol-grid b {{ display:block; font-size:15px }} .moomoo-symbol-grid small {{ color:var(--muted); display:block; font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }}
.portfolio-holdings-panel {{ background:#050505; border:1px solid var(--line); border-radius:14px; margin:10px 0 16px; overflow:hidden }}
.holdings-toolbar {{ align-items:center; display:flex; justify-content:space-between; padding:15px 16px; border-bottom:1px solid var(--line) }}
.holdings-toolbar small {{ color:var(--green); display:block; font-size:10px; font-weight:800; letter-spacing:.6px; text-transform:uppercase }} .holdings-toolbar h3 {{ font-size:22px; margin:1px 0 0 }}
.holdings-toolbar label {{ color:var(--muted); font-size:12px; font-weight:750 }} .holdings-toolbar select {{ background:#101010; border:1px solid #333; border-radius:999px; color:var(--text); font:inherit; margin-left:8px; padding:7px 12px }}
.inline-info {{ align-items:center; border:1px solid #555; border-radius:50%; color:var(--green); display:inline-flex; font-size:8px; height:13px; justify-content:center; margin-left:3px; text-decoration:none; text-transform:none; width:13px }}
.portfolio-holdings-list {{ container-type:inline-size; display:grid; grid-template-columns:1fr; position:relative }}
.portfolio-holding-card {{ align-items:center; background:transparent; border:0; border-bottom:1px solid var(--line); border-left:3px solid transparent; color:var(--text); cursor:pointer; display:grid; font:inherit; gap:8px; grid-template-columns:minmax(86px,1fr) 82px 84px 80px 100px 66px 86px 92px; min-height:60px; min-width:0; overflow:hidden; padding:9px 12px 9px 10px; text-align:left; width:100% }}
.portfolio-holding-card.signal-buy {{ background:linear-gradient(90deg,rgba(0,200,5,.12),rgba(0,200,5,.025) 38%,transparent 72%); border-left-color:var(--green) }}
.portfolio-holding-card.signal-sell {{ background:linear-gradient(90deg,rgba(255,90,95,.14),rgba(255,90,95,.03) 38%,transparent 72%); border-left-color:var(--red) }}
.portfolio-holding-card.signal-wait {{ border-left-color:transparent }}
.portfolio-holding-card:last-child {{ border-bottom:0 }} .portfolio-holding-card:hover,.portfolio-holding-card:focus-visible {{ background:#101010; outline:none }}
.portfolio-holding-card strong {{ font-size:17px; letter-spacing:-.25px }} .portfolio-holding-card small {{ color:#9aa0a6; display:block; font-size:10px; font-weight:700; letter-spacing:.15px; line-height:1.1; margin-bottom:2px }} .holding-identity small {{ font-size:12px; font-weight:500; letter-spacing:0; margin:1px 0 0 }} .portfolio-holding-card b {{ display:block; font-size:14px; letter-spacing:-.1px; white-space:nowrap }}
.portfolio-holding-card>span {{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }}
.portfolio-holding-card>span::before {{ color:var(--muted); content:attr(data-label); display:none; font-size:9px; font-weight:700; letter-spacing:.18px; margin-bottom:2px }}
.portfolio-holding-card .holding-market-value,.portfolio-holding-card .holding-weight,.portfolio-holding-card .holding-gain-loss,.portfolio-holding-card .holding-current,.portfolio-holding-card .holding-today-cash {{ text-align:right }}
.holding-current {{ justify-self:end }} .holding-current b {{ font-size:18px; font-weight:850; letter-spacing:-.35px }} .holding-current.positive b {{ color:var(--green) }} .holding-current.negative b {{ color:var(--red) }}
.holding-return.positive b,.positive b {{ color:var(--green) }} .holding-return.negative b,.negative b {{ color:var(--red) }}
.holding-spark {{ align-items:center; color:#79818a; display:flex; justify-content:flex-start }}
.holding-spark::after {{ content:none }}
.holding-today-cash.positive b {{ color:var(--green) }} .holding-today-cash.negative b {{ color:var(--red) }}
.today-pill {{ align-items:center; border:1px solid currentColor; border-radius:9px; display:flex; justify-content:center; min-height:34px; padding:3px 7px }}
.today-pill.positive {{ background:var(--green); border-color:var(--green); color:#001f08 }} .today-pill.negative {{ background:#ff5000; border-color:#ff5000; color:#050505 }}
.today-pill b {{ color:inherit; font-size:16px; font-weight:700; text-align:center }}
.mini-sparkline {{ display:block; height:26px; width:84px }} .mini-sparkline.positive {{ color:var(--green) }} .mini-sparkline.negative {{ color:#ff5000 }} .mini-sparkline polyline {{ fill:none; stroke:currentColor; stroke-linecap:round; stroke-linejoin:round; stroke-width:1.15 }} .mini-sparkline-baseline {{ stroke:#666; stroke-dasharray:2 3; stroke-linecap:round; stroke-width:.75 }}
.holding-mini {{ min-width:0 }} .holding-mini b {{ font-size:12px }}
.pressure-mini b {{ color:var(--red) }}
.priority-board-panel {{ margin-top:16px }} .priority-board-heading {{ align-items:end; display:flex; justify-content:space-between; gap:16px; margin:8px 0 14px }}
.priority-board-heading small {{ color:var(--green); display:block; font-size:10px; font-weight:800; letter-spacing:.6px; text-transform:uppercase }} .priority-board-heading h2 {{ font-size:28px; margin:2px 0 0 }} .priority-board-heading p {{ color:var(--muted); margin:0 }}
.decision-board {{ align-items:start; display:grid; gap:12px; grid-template-columns:repeat(3,minmax(0,1fr)); margin-top:16px }}
.signal-column {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; min-width:0; overflow:hidden }}
.signal-column header,.signal-column summary {{ align-items:center; display:flex; justify-content:space-between; list-style:none; padding:14px 15px }}
.signal-column summary {{ cursor:pointer }} .signal-column summary::-webkit-details-marker {{ display:none }}
.signal-column header small,.signal-column summary small {{ color:var(--muted); display:block; font-size:10px; letter-spacing:.4px; text-transform:uppercase }}
.signal-column h3 {{ font-size:20px; margin:1px 0 0 }} .signal-column header>b,.signal-column summary>b {{ align-items:center; border-radius:999px; display:flex; font-size:13px; height:28px; justify-content:center; min-width:28px; padding:0 8px }}
.buy-column header {{ border-bottom:1px solid #064b19 }} .buy-column h3,.buy-column header>b {{ color:var(--green) }} .buy-column header>b {{ background:var(--green-dim) }}
.sell-column header {{ border-bottom:1px solid #562125 }} .sell-column h3,.sell-column header>b {{ color:var(--red) }} .sell-column header>b {{ background:#321214 }}
.wait-column summary {{ border-bottom:1px solid transparent }} .wait-column[open] summary {{ border-bottom-color:#55481b }} .wait-column h3,.wait-column summary>b {{ color:var(--amber) }} .wait-column summary>b {{ background:#2b240f }}
.signal-stack {{ display:grid; gap:7px; padding:8px }} .empty-state {{ color:var(--muted); margin:0; padding:14px 8px }}
.holding-row {{ border-left:3px solid var(--line); color:var(--text); cursor:pointer; display:grid; font:inherit; grid-template-columns:90px minmax(180px,1.5fr) minmax(260px,1.6fr); gap:14px; align-items:center; padding:13px 16px; text-align:left; transition:background .15s,border-color .15s,transform .15s; width:100% }}
.holding-row.signal-sell {{ border-left-color:var(--red) }} .holding-row.signal-buy {{ border-left-color:var(--green) }} .holding-row.signal-wait {{ border-left-color:var(--amber) }}
.holding-row:hover,.holding-row:focus-visible {{ background:var(--panel-raised); border-color:#3b3b3b; outline:none; transform:translateY(-1px) }} .holding-row span {{ min-width:0 }} .holding-row small {{ color:var(--muted); display:block; font-size:11px; letter-spacing:.3px }}
.holding-row b {{ display:block; white-space:nowrap }} .ticker strong {{ display:block; font-size:21px }} .ticker small {{ margin-top:1px }}
.board-basics {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px }}
.signal-column .holding-row {{ grid-template-columns:56px 1fr; padding:11px }}
.signal-column .ticker strong {{ font-size:17px }} .signal-column .decision-signal {{ padding:7px 9px }}
.signal-column .decision-signal strong {{ font-size:13px }} .signal-column .decision-signal b {{ font-size:18px }}
.signal-column .board-basics {{ grid-column:1 / -1; gap:6px }} .signal-column .board-basics small {{ font-size:9px }} .signal-column .board-basics b {{ font-size:12px }}
.decision-signal {{ align-items:baseline; border:1px solid transparent; border-radius:7px; display:grid; grid-template-columns:auto 1fr; gap:0 10px; padding:9px 12px }}
.decision-signal strong {{ font-size:16px; letter-spacing:.8px }} .decision-signal b {{ font-size:22px; text-align:right }}
.decision-signal small {{ grid-column:1 / -1; opacity:.72 }} .decision-signal.buy {{ background:var(--green-dim); border-color:#007a26; color:var(--green) }}
.decision-signal.sell {{ background:#321214; border-color:#702a2e; color:var(--red) }} .decision-signal.hold {{ background:#202020; border-color:#3b3b3b; color:#c8c8c8 }}
.decision-signal.wait {{ background:#2b240f; border-color:#65551e; color:var(--amber) }}
.decision-signal .price-target {{ border-top:1px solid currentColor; font-weight:750; margin-top:5px; opacity:1; padding-top:5px }}
.outlook,.board-action {{ border-radius:999px; display:inline-block; font-size:11px; font-weight:800; letter-spacing:.5px; padding:6px 9px; text-align:center }}
.outlook.positive,.outlook.favorable {{ background:var(--green-dim); color:var(--green) }} .outlook.caution {{ background:#321214; color:var(--red) }}
.outlook.watch {{ background:#2b240f; color:var(--amber) }} .outlook.unknown {{ background:#202020; color:#c8c8c8 }}
.health-summary {{ align-items:center; display:flex; gap:10px }} .health-status {{ border-radius:999px; display:inline-block; font-size:10px; font-weight:800; letter-spacing:.4px; padding:5px 8px }}
.health-status.pass,.health-status.ready {{ background:var(--green-dim); color:var(--green) }} .health-status.fail,.health-status.blocked {{ background:#321214; color:var(--red) }} .health-status.pending {{ background:#2b240f; color:var(--amber) }} .health-status.degraded {{ background:#35240c; color:#ffb84d }}
.health-status.fresh {{ background:var(--green-dim); color:var(--green) }} .health-status.stale,.health-status.missing {{ background:#321214; color:var(--red) }}
.health-status.good {{ background:var(--green-dim); color:var(--green) }} .health-status.review {{ background:#2b240f; color:var(--amber) }} .health-status.poor {{ background:#321214; color:var(--red) }}
.health-status.low {{ background:var(--green-dim); color:var(--green) }} .health-status.medium {{ background:#2b240f; color:var(--amber) }} .health-status.high {{ background:#321214; color:var(--red) }}
.board-action {{ background:#1b1b1b; color:var(--muted) }} .positive b {{ color:var(--green) }} .negative b {{ color:var(--red) }} .today-pill.positive b,.today-pill.negative b {{ color:inherit }}
.drawer-backdrop {{ background:rgba(0,0,0,.78); display:none; inset:0; position:fixed; z-index:20 }} .drawer-backdrop.open {{ display:block }}
.drawer {{ background:#050505; border-left:1px solid var(--line); bottom:0; box-shadow:-24px 0 60px rgba(0,0,0,.75); display:none; max-width:1040px; overflow:auto; padding:24px; position:fixed; right:0; top:0; width:min(96vw,1040px); z-index:30 }}
.drawer.open {{ display:block }} .drawer-close {{ background:#171717; border:1px solid var(--line); border-radius:999px; color:var(--text); cursor:pointer; display:block; font:inherit; margin-left:auto; padding:7px 12px; position:sticky; top:0; z-index:2 }}
.drawer-heading {{ align-items:center; display:flex; justify-content:space-between; gap:12px; margin:34px 0 18px }} .drawer-heading h2 {{ display:inline; font-size:32px; margin:0 10px 0 0 }}
.holding-detail {{ overflow-wrap:anywhere; padding:0 }} .detail-title {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px }}
.position-hero {{ background:#050505; border:1px solid var(--line); border-radius:14px; display:grid; gap:1px; grid-template-columns:1.4fr repeat(5,1fr); margin:0 0 14px; overflow:hidden }}
.position-hero>div {{ background:#101010; min-width:0; padding:15px }} .position-hero small {{ color:var(--muted); display:block; font-size:10px; font-weight:750; letter-spacing:.5px; text-transform:uppercase }}
.position-hero b {{ display:block; font-size:18px; margin-top:4px }} .position-main b {{ font-size:30px; letter-spacing:-.8px }} .position-main span {{ color:var(--muted); display:block; margin-top:2px }}
.professional-plan {{ background:#0b0b0b; border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:12px; display:grid; gap:10px; grid-template-columns:1fr 1.2fr; margin:0 0 12px; padding:14px 16px }}
.professional-plan.buy {{ border-left-color:var(--green) }} .professional-plan.sell {{ border-left-color:var(--red) }} .professional-plan.breakout {{ border-left-color:var(--green); background:#071008 }}
.professional-plan small {{ color:var(--muted); display:block; font-size:10px; font-weight:800; letter-spacing:.5px; text-transform:uppercase }}
.professional-plan h3 {{ font-size:23px; margin:2px 0 0 }} .professional-plan b {{ display:block; font-size:14px; margin-top:3px }} .professional-plan span {{ color:var(--muted); display:block; font-size:12px; margin-top:2px }}
.professional-plan p {{ color:#d8d8d8; grid-column:1 / -1; margin:0 }} .plan-grid {{ display:grid; gap:8px; grid-column:1 / -1; grid-template-columns:1fr 1fr }}
.plan-grid span {{ background:#111; border-radius:8px; padding:10px }} .plan-grid b {{ color:var(--text); font-size:13px; font-weight:650 }}
.evidence-graphics {{ --tone:var(--amber); background:#0b0b0b; border:1px solid var(--line); border-radius:10px; margin:0 0 12px; padding:14px }}
.evidence-graphics.buy {{ --tone:var(--green) }} .evidence-graphics.sell {{ --tone:var(--red) }}
.evidence-hero {{ align-items:center; display:grid; gap:16px; grid-template-columns:118px 1fr }}
.probability-ring {{ align-items:center; background:radial-gradient(circle,#0b0b0b 57%,transparent 59%),conic-gradient(var(--tone) var(--probability),#262626 0); border-radius:50%; display:flex; flex-direction:column; height:112px; justify-content:center; width:112px }}
.probability-ring b {{ color:var(--tone); font-size:27px }} .probability-ring span {{ color:var(--muted); font-size:10px; text-transform:uppercase }}
.why-copy small {{ color:var(--tone); font-size:10px; font-weight:750; letter-spacing:.6px }} .why-copy h3 {{ font-size:19px; line-height:1.2; margin:4px 0 7px }} .why-copy p {{ color:var(--muted); font-size:12px; margin:0 }}
.evidence-bars {{ display:grid; gap:10px; margin-top:15px }} .evidence-bar>div:first-child {{ display:flex; justify-content:space-between }}
.evidence-bar span,.evidence-bar small {{ color:var(--muted); font-size:11px }} .evidence-bar b {{ color:var(--text); font-size:12px }}
.bar-track {{ background:#242424; border-radius:999px; height:7px; margin:4px 0; overflow:hidden }} .bar-track i {{ background:var(--tone); border-radius:999px; display:block; height:100% }}
.evidence-bar.relative .bar-track i {{ background:#aaa }} .evidence-bar.relative b {{ color:#ddd }}
.price-plan {{ align-items:center; background:#0b0b0b; border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:10px; display:grid; gap:8px 16px; grid-template-columns:1fr auto auto; margin:0 0 12px; padding:13px 15px }}
.price-plan.buy {{ border-left-color:var(--green) }} .price-plan.sell {{ border-left-color:var(--red) }} .price-plan.breakout {{ border-left-color:var(--green); background:#071008 }}
.price-plan small {{ color:var(--muted); display:block; font-size:10px; font-weight:750; letter-spacing:.5px; text-transform:uppercase }}
.price-plan h3 {{ font-size:25px; margin:2px 0 0 }} .price-plan-mid {{ text-align:right }} .price-plan-mid b {{ display:block; font-size:18px }}
.price-plan p {{ color:var(--muted); grid-column:1 / -1; margin:0 }}
.price-plan.unavailable {{ display:block }} .info-tip {{ align-items:center; border:1px solid #555; border-radius:50%; color:var(--muted); cursor:help; display:flex; font-size:11px; font-weight:800; height:20px; justify-content:center; position:relative; width:20px }}
.info-tip::after {{ background:#222; border:1px solid #555; border-radius:6px; bottom:29px; color:#ddd; content:attr(data-tip); display:none; font-size:11px; font-weight:500; line-height:1.35; padding:8px; position:absolute; right:-6px; text-transform:none; width:240px; z-index:5 }}
.info-tip:hover::after,.info-tip:focus::after {{ display:block }} .info-tip:focus {{ border-color:#aaa; outline:none }}
.kline-chart-card {{ background:#050505; border:1px solid var(--line); border-radius:14px; margin:0 0 12px; padding:16px; position:relative }}
.chart-heading {{ align-items:center; display:flex; justify-content:space-between; margin-bottom:7px }} .chart-heading small {{ color:var(--muted); font-size:10px; text-transform:uppercase }} .chart-heading h3 {{ align-items:baseline; display:flex; flex-wrap:wrap; gap:7px; font-size:17px; margin:1px 0 0 }} .chart-heading h3 b {{ font-size:21px }} .chart-heading h3 em {{ font-style:normal }} .chart-heading h3 em.positive {{ color:var(--green) }} .chart-heading h3 em.negative {{ color:var(--red) }}
.chart-signal {{ border-radius:999px; font-size:12px; font-weight:750; padding:6px 9px }} .chart-signal.buy {{ background:var(--green-dim); color:var(--green) }} .chart-signal.sell {{ background:#321214; color:var(--red) }} .chart-signal.wait {{ background:#2b240f; color:var(--amber) }}
.interactive-kline {{ height:520px; margin-top:8px; position:relative; touch-action:none; width:100% }}
.chart-overlay {{ inset:0; pointer-events:none; position:absolute; z-index:2 }}
.kline-zone {{ border:1px solid currentColor; border-radius:3px; left:0; opacity:.36; position:absolute; right:0 }}
.kline-zone.support {{ background:rgba(0,200,5,.18); color:var(--green) }} .kline-zone.resistance,.kline-zone.sell {{ background:rgba(255,90,95,.20); color:var(--red) }} .kline-zone.buy {{ background:rgba(0,200,5,.22); color:var(--green) }} .kline-zone.breakout {{ background:rgba(0,200,5,.13); border-style:dashed; color:var(--green) }}
.kline-zone-label {{ background:#050505; border:1px solid currentColor; border-radius:999px; color:inherit; font-size:10px; font-weight:800; padding:3px 8px; position:absolute; right:10px; top:4px; white-space:nowrap }}
.chart-tooltip {{ background:#050505; border:1px solid #555; border-radius:8px; box-shadow:0 10px 28px rgba(0,0,0,.45); color:var(--text); font-size:11px; left:12px; min-width:210px; padding:8px 10px; pointer-events:none; position:absolute; top:72px; z-index:4 }}
.chart-tooltip b,.chart-tooltip span {{ display:block }} .chart-tooltip span {{ color:var(--muted); margin-top:2px }}
.chart-status,.chart-fallback {{ background:rgba(17,17,17,.92); border:1px solid rgba(255,255,255,.08); border-radius:999px; color:var(--muted); font-size:11px; left:18px; max-width:min(620px,calc(100% - 36px)); padding:6px 10px; position:absolute; top:10px; z-index:3 }}
.chart-controls {{ align-items:center; border-top:1px solid var(--line); display:flex; gap:14px; justify-content:space-between; margin:8px 0 0; min-width:0; padding-top:8px }}
.chart-controls > * {{ min-width:0 }}
.chart-range-tabs {{ align-items:center; display:flex; flex:1 1 auto; flex-wrap:nowrap; gap:22px; justify-content:flex-start; margin:0; max-width:100%; min-width:0; overflow-x:auto; padding-top:0; scrollbar-width:none }} .chart-range-tabs::-webkit-scrollbar {{ display:none }} .chart-range-tabs button {{ background:transparent; border:0; border-radius:8px; color:var(--green); cursor:pointer; flex:0 0 auto; font:inherit; font-size:13px; font-weight:800; padding:7px 10px; white-space:nowrap }} .chart-range-tabs button.active {{ background:var(--green); color:#001f08 }} .chart-range-tabs button:disabled {{ color:#474747; cursor:not-allowed }} .chart-legend {{ color:var(--muted); display:flex; flex-wrap:wrap; font-size:10px; gap:12px; margin-top:3px }} .chart-legend span::before {{ background:#777; border-radius:2px; content:""; display:inline-block; height:7px; margin-right:4px; width:7px }}
.chart-legend .support-key::before {{ background:var(--green) }} .chart-legend .resistance-key::before {{ background:var(--red) }} .chart-legend .wave-key::before {{ background:var(--amber) }} .chart-legend .cost-key::before {{ background:#e6e6e6 }}
.chart-unavailable {{ background:#111; border-radius:7px; color:var(--muted); margin-bottom:12px; padding:18px }}
.advanced-details {{ border-top:1px solid var(--line); margin-top:12px; padding-top:8px }} .advanced-details summary {{ color:var(--muted); cursor:pointer; font-weight:650; padding:8px 0 }} .advanced-details[open] summary {{ color:var(--text) }}
.detail-title div {{ background:#111; border-radius:7px; padding:10px }} .detail-title span {{ color:var(--muted); display:block; font-size:11px; margin-top:3px }}
.metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:7px; margin:14px 0; color:var(--muted) }}
.drawer .detail-title {{ grid-template-columns:1fr }} .drawer .metrics {{ grid-template-columns:repeat(2,1fr) }}
.metrics b {{ color:var(--text) }} ul {{ margin:8px 0 0; padding-left:20px; color:#d0d0d0 }}
.kline {{ color:var(--muted); font-size:13px; margin:8px 0 }} .kline b {{ color:var(--text) }}
.wave {{ background:#111; border-radius:7px; color:var(--muted); font-size:13px; margin:10px 0; padding:10px }} .wave b {{ color:var(--text) }}
.wave-history {{ color:var(--muted); font-size:12px; margin:7px 0 }} .wave-history b {{ color:var(--text) }}
.view {{ margin-top:8px; font-weight:700 }} .evidence {{ color:var(--muted); font-size:13px }}
.experiment {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px }}
.experiment div {{ background:#111; border-radius:7px; padding:14px }} .experiment b {{ display:block; font-size:24px }}
.experiment span {{ color:var(--muted); font-size:13px }}
table {{ width:100%; border-collapse:collapse }} th,td {{ text-align:left; padding:9px; border-bottom:1px solid var(--line) }} th {{ color:var(--green); font-size:12px; letter-spacing:.25px }}
.note {{ color:var(--muted); font-size:13px }} @media(min-width:900px) {{
  .portfolio-holdings-list {{ background:transparent; column-gap:22px; grid-template-columns:repeat(2,minmax(0,1fr)); position:relative; row-gap:0 }}
  .portfolio-holdings-list::before {{ background:#3a3a3a; bottom:0; box-shadow:0 0 0 1px rgba(255,255,255,.04); content:""; left:50%; position:absolute; top:0; width:2px; z-index:1 }}
  .portfolio-holding-card {{ background:#050505; gap:7px; grid-template-columns:minmax(92px,1fr) 72px 78px 84px; min-height:60px; padding:9px 12px }}
  .holding-today-cash,.holding-market-value,.holding-weight,.holding-gain-loss {{ display:none }}
  .holding-spark .mini-sparkline {{ width:72px }}
  .portfolio-holding-card.signal-buy {{ background:linear-gradient(90deg,rgba(0,200,5,.13),rgba(0,200,5,.03) 40%,#050505 78%) }}
  .portfolio-holding-card.signal-sell {{ background:linear-gradient(90deg,rgba(255,90,95,.15),rgba(255,90,95,.035) 40%,#050505 78%) }}
  .portfolio-holding-card.signal-wait {{ background:#050505 }}
}} @media(min-width:1360px) {{
  .portfolio-holding-card {{ grid-template-columns:minmax(108px,1.05fr) 80px 84px 96px 60px 76px 88px }}
  .holding-market-value,.holding-weight,.holding-gain-loss {{ display:block }}
  .holding-spark .mini-sparkline {{ width:80px }}
}} @media(max-width:1299px) and (min-width:1100px) {{
  .portfolio-holding-card {{ gap:7px; grid-template-columns:minmax(76px,1fr) 58px 70px 70px; min-height:58px; padding-left:10px; padding-right:10px }}
  .holding-spark .mini-sparkline {{ width:58px }}
  .holding-today-cash,.holding-market-value,.holding-weight,.holding-gain-loss {{ display:none }}
  .today-pill {{ min-height:34px; padding:4px 6px }} .today-pill b {{ font-size:14px }} .holding-current b {{ font-size:16px }}
}} @media(max-width:1099px) and (min-width:900px) {{
  .portfolio-holding-card {{ gap:7px; grid-template-columns:minmax(74px,1fr) 54px 68px 68px; min-height:58px; padding-left:9px; padding-right:9px }}
  .holding-spark .mini-sparkline {{ width:54px }}
  .holding-today-cash,.holding-market-value,.holding-weight,.holding-gain-loss {{ display:none }}
  .today-pill {{ min-height:34px; padding:4px 6px }} .today-pill b {{ font-size:13px }} .holding-current b {{ font-size:15px }}
}} @media(max-width:1080px) {{
  .portfolio-holding-card {{ min-height:58px }}
}} @media(max-width:899px) {{
  .grid,.experiment,.detail-title,.metrics {{ grid-template-columns:1fr 1fr }}
  .tabs {{ gap:10px }}
  .decision-board {{ grid-template-columns:1fr 1fr }} .wait-column {{ grid-column:1 / -1 }}
  .asset-home {{ grid-template-columns:1fr; max-width:none }}
  .broker-hero {{ grid-template-columns:1fr }}
  .broker-totals {{ grid-template-columns:repeat(3,minmax(0,1fr)) }}
  .account-stats {{ grid-template-columns:repeat(2,1fr) }} .account-stats div:nth-child(2n) {{ border-right:0 }}
  .portfolio-holding-card {{ grid-template-columns:minmax(92px,1fr) 90px 88px 86px 92px 58px 78px; min-height:64px; padding:11px 12px }}
  .holding-today-cash {{ display:none }}
  .portfolio-holding-card>span::before {{ display:none }}
  .today-pill {{ justify-self:start; min-width:84px }}
  .holding-row {{ grid-template-columns:80px 1fr; gap:10px }}
  .board-action {{ display:none }} .board-basics {{ grid-column:1 / -1; margin-top:3px }}
}} @media(max-width:700px) {{
  .portfolio-holding-card {{ grid-template-columns:minmax(88px,1fr) 90px 86px 88px 92px }}
  .holding-market-value,.holding-weight {{ display:none }}
  .holding-spark .mini-sparkline {{ height:38px; width:92px }}
}} @media(max-width:620px) {{
  .portfolio-holding-card {{ grid-template-columns:minmax(88px,1fr) 90px 86px 92px }}
  .holding-weight,.holding-gain-loss {{ display:none }}
}} @media(max-width:600px) {{
  main {{ padding:24px 12px 60px }} .grid,.experiment,.detail-title,.metrics {{ grid-template-columns:1fr }}
  .decision-board {{ grid-template-columns:1fr }} .wait-column {{ grid-column:auto }}
  .board-intro {{ align-items:start; flex-direction:column }} .holding-row {{ grid-template-columns:70px 1fr }}
  .holdings-toolbar {{ align-items:start; flex-direction:column; gap:10px }}
  .asset-home {{ padding:20px }} .asset-home h2 {{ font-size:38px; letter-spacing:-1.5px }} .asset-home-actions,.broker-totals,.broker-card-grid {{ grid-template-columns:1fr }}
  .broker-hero {{ padding:16px }} .broker-brand {{ align-items:flex-start }} .broker-brand h2,.moomoo-hero h2 {{ font-size:32px }}
  .moomoo-hero {{ align-items:flex-start; padding:16px }}
  .account-overview {{ padding:16px 16px 12px }} .account-copy h2 {{ font-size:34px }} .account-chart-wrap {{ min-height:260px }} .account-stats {{ grid-template-columns:1fr 1fr }} .account-kline-card .interactive-kline {{ height:260px }} .board-intro p {{ display:none }}
  .interactive-kline {{ height:380px }}
  .chart-controls {{ align-items:stretch; flex-direction:column; gap:8px }}
  .chart-mode-tabs {{ justify-content:flex-start }}
  .chart-range-tabs {{ gap:9px; justify-content:flex-start; width:100% }} .chart-range-tabs button {{ font-size:12px; padding:6px 7px }}
  .board-basics {{ gap:8px }} .drawer {{ max-width:none; padding:14px; width:100vw }} .position-hero {{ grid-template-columns:1fr 1fr }} .position-main {{ grid-column:1 / -1 }} .professional-plan,.plan-grid {{ grid-template-columns:1fr }} .evidence-hero {{ grid-template-columns:92px 1fr }} .probability-ring {{ height:88px; width:88px }} .probability-ring b {{ font-size:22px }}
}} @media(max-width:460px) {{
  .portfolio-holding-card {{ gap:7px; grid-template-columns:minmax(78px,1fr) 64px 78px 82px; padding-left:9px; padding-right:9px }}
  .holding-spark .mini-sparkline {{ height:30px; width:64px }}
  .today-pill b {{ font-size:14px }} .holding-current b {{ font-size:16px }}
}}
</style>
</head>
<body><main>
<h1>{html.escape(title)}</h1>
<p class="sub">Read-only decision support · {html.escape(model_label)} · generated {html.escape(generated)}</p>
{refresh_control}
<nav class="tabs" role="tablist" aria-label="Dashboard sections">
  <button type="button" class="tab-button active" data-tab-target="home" role="tab" aria-selected="true">Home</button>
  {broker_tab_buttons}
  {moomoo_tab_button}
  <button type="button" class="tab-button" data-tab-target="signals" role="tab" aria-selected="false">Signals</button>
  <button type="button" class="tab-button" data-tab-target="opportunities" role="tab" aria-selected="false">Opportunities</button>
  <button type="button" class="tab-button" data-tab-target="research" role="tab" aria-selected="false">Research</button>
  <button type="button" class="tab-button" data-tab-target="health" role="tab" aria-selected="false">Health &amp; Risk</button>
</nav>
<section id="tab-home" class="tab-view active" role="tabpanel">
<section class="portfolio-board">{asset_home}</section>
</section>
{broker_tab_panels}
{moomoo_tab_panel}
<section id="tab-signals" class="tab-view" role="tabpanel" hidden>
<section class="portfolio-board">{portfolio_account_overview}{portfolio_holdings}</section>
</section>
<section id="tab-opportunities" class="tab-view" role="tabpanel" hidden>
{prioritized_board}
</section>
<section id="tab-research" class="tab-view" role="tabpanel" hidden>
{portfolio_learning_review_link}
<section class="panel"><h2>Displayed Direction Forecast Validation</h2>
<table><thead><tr><th>Version</th><th>Direction</th><th>Horizon</th><th>Episodes</th><th>Matured</th><th>Pending</th><th>Displayed rate</th><th>Directional success</th><th>Brier score</th></tr></thead>
<tbody>{direction_validation_rows}</tbody></table>
<p class="note">Every displayed BUY, SELL, and WAIT is retained in an immutable ledger. Daily repeats are de-duplicated into episodes. WAIT is audited for coverage but has no invented directional success or Brier score.</p></section>
<section class="panel"><h2>First Observed Forecast Tracking</h2>
<div class="experiment">
  <div><b>{int(first_observed_forecasts.get("tracked_count", 0))}</b><span>Tracked holdings</span></div>
  <div><b>{int(first_observed_forecasts.get("changed_since_first_count", 0))}</b><span>Changed since first seen</span></div>
  <div><b>{int(first_observed_forecasts.get("missing_count", 0))}</b><span>Missing first forecast</span></div>
</div>
<table><thead><tr><th>Symbol</th><th>First date</th><th>Version</th><th>First direction</th><th>Displayed</th><th>Entry</th><th>Current</th><th>Changed</th><th>Outcome</th></tr></thead>
<tbody>{first_observed_rows}</tbody></table>
<p class="note">This is the M078 accountability view: each current holding is anchored to the first persisted direction forecast available in the immutable ledger. It is observational and does not rewrite old forecasts when the current model changes.</p></section>
<section class="panel"><h2>Forecast Action Segment Comparison</h2>
<div class="experiment">
  <div><b>{int((forecast_action_segments.get("episode_segment_counts") or {}).get("ACTED_ON_PROXY", 0))}</b><span>Acted-on proxy episodes</span></div>
  <div><b>{int((forecast_action_segments.get("episode_segment_counts") or {}).get("WATCHED_PROXY", 0))}</b><span>Watched proxy episodes</span></div>
  <div><b>{int((forecast_action_segments.get("episode_segment_counts") or {}).get("IGNORED_OR_EXITED_PROXY", 0))}</b><span>Ignored/exited proxy episodes</span></div>
</div>
<table><thead><tr><th>Segment</th><th>Direction</th><th>Horizon</th><th>Episodes</th><th>Matured</th><th>Pending</th><th>Directional success</th><th>Avg directional</th><th>Avg excess</th><th>Symbols</th></tr></thead>
<tbody>{forecast_action_segment_rows}</tbody></table>
<p class="note">This is the M079 observational comparison. Segments are current-state proxies: currently held, zero-share watchlist, or no longer listed. They do not prove that a forecast caused a trade, watchlist decision, or ignored opportunity.</p></section>
<section class="panel"><h2>BUY/SELL Calibration Curves</h2>
<table><thead><tr><th>Version</th><th>Direction</th><th>Horizon</th><th>Bucket</th><th>Displayed</th><th>Actual success</th><th>Matured</th><th>Symbols</th><th>Status</th></tr></thead>
<tbody>{calibration_curve_rows}</tbody></table>
<p class="note">Curve buckets are fixed before outcome review. A point stays PENDING until it has at least 20 matured episodes across five symbols, then passes only if actual directional success is within 10 percentage points of the displayed rate.</p></section>
<section class="panel"><h2>Directional Classification Metrics</h2>
<table><thead><tr><th>Version</th><th>Direction</th><th>Horizon</th><th>Matured universe</th><th>Predicted</th><th>Actual</th><th>Precision</th><th>Recall</th><th>False-positive rate</th><th>Coverage</th><th>Status</th></tr></thead>
<tbody>{classification_metric_rows}</tbody></table>
<p class="note">BUY actuals are positive forward returns; SELL actuals are negative forward returns. WAIT forecasts remain in the recall universe so missed waves are visible. Rows stay PENDING until at least 20 matured episodes across five symbols exist.</p></section>
<section class="panel"><h2>Largest False Direction Episodes</h2>
<table><thead><tr><th>Version</th><th>Direction</th><th>Horizon</th><th>Rank</th><th>Symbol</th><th>Date</th><th>Displayed</th><th>Directional return</th><th>Max adverse</th><th>Evidence</th></tr></thead>
<tbody>{error_cohort_rows}</tbody></table>
<p class="note">False BUY means the forward return was flat or negative; false SELL means the stock was flat or up. Rows are ranked by worst direction-aware return and preserve the original forecast version.</p></section>
{multiple_testing_panel}
{false_discovery_panel}
<section class="panel"><h2>All-Decision Forward Evidence</h2>
<table><thead><tr><th>Decision</th><th>Horizon</th><th>Matured sample</th><th>Positive return</th><th>Mean excess return</th><th>Directional success</th></tr></thead>
<tbody>{decision_evidence_rows}</tbody></table>
<p class="note">Includes HOLD and ordinary REVIEW decisions from the append-only daily ledger. HOLD is evaluated as remaining long; REVIEW preserves raw and excess outcomes without inventing directional success; DATA REVIEW is excluded from investment-performance claims.</p></section>
<section class="panel"><h2>Current Wave Analog Ranking</h2>
<table><thead><tr><th>Symbol</th><th>Direction gate</th><th>Relative evidence</th><th>Current wave</th><th>Horizon</th><th>Beat SPY (95% CI)</th><th>Cross-stock breadth (95% CI)</th><th>Median return</th><th>Mean upside / downside</th><th>Leave-one-symbol-out</th><th>Evidence · sample</th></tr></thead>
<tbody>{current_wave_rows}</tbody></table>
<p class="note">Ranks current holdings by the conservative lower bound of the best-supported historical wave analog. “Favorable” or “caution” requires pooled and per-symbol breadth intervals to agree, at least 10 observations across eight symbols, and no symbol above 25% of the sample. This is a research-priority view, not a buy/sell instruction.</p></section>
<section class="panel"><h2>Historical Wave Experiment</h2>
<table><thead><tr><th>Wave regime</th><th>Horizon</th><th>Direction gate</th><th>Positive</th><th>Absolute breadth (95% CI)</th><th>Beat SPY (95% CI)</th><th>Relative breadth (95% CI)</th><th>Median return</th><th>Mean max upside</th><th>Mean max downside</th><th>Leave-one-symbol-out</th><th>Evidence · sample</th></tr></thead>
<tbody>{wave_experiment_rows}</tbody></table>
<p class="note">Cross-stock breadth is the share of contributing symbols with positive mean excess return. Each symbol uses causal snapshots and non-overlapping windows within each horizon. Small samples remain visible. This is exploratory in-sample evidence, not a promoted prediction model.</p></section>
<section class="panel"><h2>Conditional Wave Precision Audit</h2>
<table><thead><tr><th>Relative evidence</th><th>Direction gate</th><th>Wave regime</th><th>Horizon</th><th>Wave age</th><th>Move magnitude</th><th>Beat SPY (95% CI)</th><th>Cross-stock breadth (95% CI)</th><th>Leave-one-symbol-out</th><th>Evidence · sample</th></tr></thead>
<tbody>{conditional_wave_rows}</tbody></table>
<p class="note">Age buckets are predeclared as early (≤10 sessions), mature (11–25), and extended (&gt;25). Move magnitude is normalized by each signal's reversal threshold: developing (&lt;1.5×), established (1.5–3×), and extended (&gt;3×). A conditional view can replace its broad regime analog only when the same strict pooled, cross-stock, and concentration gates pass; otherwise the dashboard explicitly refuses the extra precision.</p></section>
<section class="panel"><h2>Raw vs Shrunk vs Wilson Direction Rates</h2>
<table><thead><tr><th>Source</th><th>Direction</th><th>Horizon</th><th>Wave regime</th><th>Wave age</th><th>Move magnitude</th><th>Raw rate</th><th>Displayed</th><th>Wilson floor</th><th>Evidence · sample</th></tr></thead>
<tbody>{direction_rate_rows}</tbody></table>
<p class="note">Displayed confidence uses the shrunk rate, pulled toward 50% by a neutral 20-observation prior. The Wilson floor is stricter and stays visible as the audit floor; raw rates are not promoted directly.</p></section>
<section class="panel"><h2>Time-Decayed Wave Experiment</h2>
<table><thead><tr><th>Wave regime</th><th>Horizon</th><th>Weighted positive</th><th>Weighted return</th><th>Weighted excess</th><th>Weighted n</th><th>Evidence · sample</th><th>Top symbol weight</th></tr></thead>
<tbody>{time_decay_rows}</tbody></table>
<p class="note">Experimental view only: older analogs decay with a one-year half-life. It helps detect stale regimes but does not replace equal-weight evidence until sealed forward outcomes improve calibration.</p></section>
<section class="panel"><h2>Live Structural Wave Evidence</h2>
<table><thead><tr><th>Wave regime</th><th>Horizon</th><th>Positive rate</th><th>Matured sample</th><th>Mean return</th></tr></thead>
<tbody>{wave_evidence_rows}</tbody></table>
<p class="note">Wave regimes use confirmed pivots and are evaluated over 21/63/126 sessions. Exact tops and bottoms cannot be known in advance.</p></section>
<section class="panel"><h2>Supporting K-line Evidence</h2>
<table><thead><tr><th>Regime</th><th>Horizon</th><th>Positive rate</th><th>Matured sample</th><th>Mean return</th></tr></thead>
<tbody>{kline_evidence_rows}</tbody></table>
<p class="note">Daily K-line regimes are supporting observations, not day-trading instructions.</p></section>
<section class="panel"><h2>Signal Evidence Ranked by Win Rate</h2>
<table><thead><tr><th>Signal</th><th>Horizon</th><th>Directional win rate</th><th>Matured sample</th><th>Mean directional return</th></tr></thead>
<tbody>{evidence_rows}</tbody></table>
<p class="note">Win rate is ranked only from matured forward outcomes. Small samples are shown, never hidden.</p></section>
</section>
<section id="tab-health" class="tab-view" role="tabpanel" hidden>
{model_health_panel}
{price_health_panel}
<section class="grid">
  <div class="stat"><b>{diagnostic["symbols"]}</b><span>Holdings monitored</span></div>
  <div class="stat"><b>{actions.get("TRIM_REVIEW", 0)}</b><span>Trim reviews</span></div>
  <div class="stat"><b>{actions.get("REVIEW", 0)}</b><span>Reviews</span></div>
  <div class="stat"><b>{actions.get("DATA_REVIEW", 0)}</b><span>Data reviews</span></div>
  <div class="stat"><b class="warning">{diagnostic["actionable_rate"]:.0%}</b><span>Action-review rate</span></div>
</section>
<section class="panel"><h2>Model Health</h2>
<p>The current model flags <b>{diagnostic["actionable_rate"]:.0%}</b> of monitored holdings for action review.
{"This remains an alert-fatigue warning and requires outcome validation before promotion." if diagnostic["alert_fatigue_risk"] else "Current alert burden is within the configured diagnostic threshold."}</p>
<p><b>{diagnostic["data_review_rate"]:.0%}</b> of holdings require data review.
{"Missing data is a major confidence bottleneck for buy/add decisions." if diagnostic["data_quality_burden"] else "Current data-review burden is within the diagnostic threshold."}</p>
<p>Structural wave evidence targets multi-week to multi-month decisions. Daily K-line evidence is supporting context only and is available for <b>{kline_ready} of {diagnostic["symbols"]}</b> monitored holdings.</p>
<p class="note">Signals are prompts for research, not predictions or trade instructions. No orders are placed.</p></section>
{comparison_html}
{coverage_html}
<section class="panel"><h2>Portfolio Risk Alerts</h2><ul>{risk_items}</ul></section>
</section>
</main>
<div class="drawer-backdrop" data-close-drawer></div>
<aside id="holding-drawer" class="drawer" aria-hidden="true" aria-label="Holding details">
  <button type="button" class="drawer-close" data-close-drawer>Close</button>
  {''.join(detail_panels)}
</aside>
<script type="application/json" id="chart-payloads-v1">{chart_payload_json}</script>
<script src="/assets/lightweight-charts.standalone.production.js?v=20260620"></script>
<script>if(!window.LightweightCharts)document.write('<script src="/web/assets/lightweight-charts.standalone.production.js?v=20260620"><\\/script>');</script>
<script src="/assets/kline-chart.js?v=20260623-scratch-ui"></script>
<script>if(!window.StockInvestorKline)document.write('<script src="/web/assets/kline-chart.js?v=20260623-scratch-ui"><\\/script>');</script>
<script>
const tabButtons = [...document.querySelectorAll("[data-tab-target]")];
const tabViews = [...document.querySelectorAll(".tab-view")];
const activateDashboardTab = (target) => {{
  const activeButton = tabButtons.find((button) => button.dataset.tabTarget === target);
  if (!activeButton) return;
  tabButtons.forEach((item) => {{
    const active = item === activeButton;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  }});
  tabViews.forEach((view) => {{
    const active = view.id === `tab-${{target}}`;
    view.classList.toggle("active", active);
    view.hidden = !active;
  }});
  activeButton.scrollIntoView({{ block: "nearest", inline: "nearest" }});
  window.requestAnimationFrame(() => window.StockInvestorKline?.initVisibleCharts());
}};
tabButtons.forEach((button) => button.addEventListener("click", () => activateDashboardTab(button.dataset.tabTarget)));
document.querySelectorAll("[data-jump-tab]").forEach((button) => button.addEventListener("click", () => activateDashboardTab(button.dataset.jumpTab)));

const portfolioSort = document.getElementById("portfolio-sort");
const portfolioList = document.querySelector("[data-portfolio-holdings]");
const arrangePortfolioRows = (rows) => {{
  rows.forEach((row) => {{
    row.style.gridColumn = "";
    row.style.gridRow = "";
  }});
  if (!portfolioList) return;
  const twoColumn = window.matchMedia("(min-width: 900px)").matches;
  if (!twoColumn) {{
    rows.forEach((row) => portfolioList.appendChild(row));
    return;
  }}
  const gainers = rows.filter((row) => Number(row.dataset.sortToday || 0) >= 0);
  const losers = rows.filter((row) => Number(row.dataset.sortToday || 0) < 0);
  let leftRows = [];
  let rightRows = [];
  if (gainers.length && losers.length) {{
    leftRows = gainers;
    rightRows = losers;
  }} else {{
    const split = Math.ceil(rows.length / 2);
    leftRows = rows.slice(0, split);
    rightRows = rows.slice(split);
  }}
  [...leftRows, ...rightRows].forEach((row) => portfolioList.appendChild(row));
  leftRows.forEach((row, index) => {{
    row.style.gridColumn = "1";
    row.style.gridRow = String(index + 1);
  }});
  rightRows.forEach((row, index) => {{
    row.style.gridColumn = "2";
    row.style.gridRow = String(index + 1);
  }});
}};
const sortHoldings = () => {{
  if (!portfolioSort || !portfolioList) return;
  const [field, direction] = portfolioSort.value.split("-");
  const datasetKey = {{
    value: "sortValue",
    today: "sortToday",
    "today-dollars": "sortTodayDollars",
    gain: "sortGain",
    "gain-dollars": "sortGainDollars",
    recent: "sortRecent",
    weight: "sortWeight",
    confidence: "sortConfidence",
    signal: "sortSignal",
    symbol: "sortSymbol",
  }}[field];
  const rows = [...portfolioList.querySelectorAll(".portfolio-holding-card")];
  rows.sort((left, right) => {{
    if (field === "symbol") {{
      return (left.dataset[datasetKey] || "").localeCompare(right.dataset[datasetKey] || "");
    }}
    const leftValue = Number(left.dataset[datasetKey] || 0);
    const rightValue = Number(right.dataset[datasetKey] || 0);
    return direction === "asc" ? leftValue - rightValue : rightValue - leftValue;
  }});
  arrangePortfolioRows(rows);
}};
portfolioSort?.addEventListener("change", sortHoldings);
sortHoldings();
window.StockInvestorKline?.initVisibleCharts();

const refreshButton = document.querySelector("[data-refresh-button]");
const refreshProgress = document.querySelector("[data-refresh-progress]");
const refreshMessage = document.querySelector("[data-refresh-message]");
const refreshProgressFill = refreshProgress?.querySelector("i");
const setRefreshState = (message, running = false, progress = 0) => {{
  if (refreshButton) refreshButton.disabled = running;
  const boundedProgress = Math.max(0, Math.min(100, Number(progress || 0)));
  if (refreshProgress) {{
    refreshProgress.hidden = !running && boundedProgress <= 0;
    refreshProgress.setAttribute("aria-valuenow", String(Math.round(boundedProgress)));
  }}
  if (refreshProgressFill) refreshProgressFill.style.width = `${{boundedProgress}}%`;
  if (refreshMessage) refreshMessage.textContent = message || "";
}};
const pollRefreshStatus = async () => {{
  const response = await fetch(`/api/refresh-status?ts=${{Date.now()}}`, {{ cache: "no-store" }});
  if (!response.ok) throw new Error(`refresh status ${{response.status}}`);
  const payload = await response.json();
  if (payload.status === "running") {{
    setRefreshState(payload.message || "updating...", true, payload.progress || 0);
    window.setTimeout(() => pollRefreshStatus().catch(() => setRefreshState("refresh status unavailable")), 1800);
    return;
  }}
  if (payload.status === "succeeded") {{
    setRefreshState("updated, reloading...", false, 100);
    window.setTimeout(() => window.location.reload(), 700);
    return;
  }}
  if (payload.status === "failed") {{
    setRefreshState(payload.message || "refresh failed", false, 100);
    return;
  }}
  setRefreshState(payload.message || "", false, payload.progress || 0);
}};
refreshButton?.addEventListener("click", async () => {{
  try {{
    setRefreshState("starting...", true, 1);
    const response = await fetch("/api/refresh", {{ method: "POST" }});
    if (!response.ok) throw new Error(`refresh ${{response.status}}`);
    await pollRefreshStatus();
  }} catch (_error) {{
    setRefreshState("manual refresh endpoint unavailable", false);
  }}
}});

let portfolioResizeFrame = null;
window.addEventListener("resize", () => {{
  if (portfolioResizeFrame) return;
  portfolioResizeFrame = window.requestAnimationFrame(() => {{
    portfolioResizeFrame = null;
    sortHoldings();
    window.StockInvestorKline?.initVisibleCharts();
  }});
}});

const drawer = document.getElementById("holding-drawer");
const backdrop = document.querySelector(".drawer-backdrop");
const detailPanels = [...document.querySelectorAll(".holding-detail")];
const closeDrawer = () => {{
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  backdrop.classList.remove("open");
  detailPanels.forEach((panel) => panel.hidden = true);
}};
document.querySelectorAll("[data-detail-target]").forEach((button) => button.addEventListener("click", () => {{
  detailPanels.forEach((panel) => panel.hidden = panel.id !== button.dataset.detailTarget);
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  backdrop.classList.add("open");
  drawer.scrollTop = 0;
  window.StockInvestorKline?.initVisibleCharts();
}}));
document.querySelectorAll("[data-close-drawer]").forEach((button) => button.addEventListener("click", closeDrawer));
document.addEventListener("keydown", (event) => {{
  if (event.key === "Escape") closeDrawer();
}});
</script>
</body></html>"""


def _extract_chart_payload(content: str) -> dict | None:
    marker = '<script type="application/json" id="chart-payloads-v1">'
    start = content.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = content.find("</script>", start)
    if end == -1:
        return None
    return json.loads(content[start:end])


def _slim_chart_payload_script(content: str) -> str:
    marker = '<script type="application/json" id="chart-payloads-v1">'
    start = content.find(marker)
    if start == -1:
        return content
    payload_start = start + len(marker)
    end = content.find("</script>", payload_start)
    if end == -1:
        return content
    slim = (
        '<script type="application/json" id="chart-payloads-v1" '
        'data-src="chart-payloads-v1.json">{"version":1,"source":"dashboard-v3","symbols":{}}</script>'
    )
    return content[:start] + slim + content[end + len("</script>") :]


def write_dashboard(content: str, path: str | Path) -> None:
    output_path = Path(path)
    payload = _extract_chart_payload(content)
    dashboard_content = (
        _slim_chart_payload_script(content) if payload is not None else content
    )
    atomic_write_text(dashboard_content, output_path)
    sidecar_content = None
    if payload is not None:
        sidecar_content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        atomic_write_text(sidecar_content, output_path.with_name("chart-payloads-v1.json"))
    _mirror_dashboard_to_runtime(output_path, dashboard_content, sidecar_content)


def _path_relative_to(path: Path, root: Path) -> Path | None:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def _mirror_dashboard_to_runtime(
    output_path: Path,
    dashboard_content: str,
    sidecar_content: str | None,
) -> None:
    if os.environ.get("STOCK_INVESTOR_DISABLE_RUNTIME_MIRROR"):
        return
    runtime_root = Path(
        os.environ.get(
            "STOCK_INVESTOR_RUNTIME_ROOT",
            str(Path.home() / "Library" / "Application Support" / "stock-investor"),
        )
    )
    source_root_file = runtime_root / ".source-root"
    if not source_root_file.exists():
        return
    source_root = Path(source_root_file.read_text().strip())
    relative = _path_relative_to(output_path, source_root)
    if relative is None:
        return
    mirror_path = runtime_root / relative
    if mirror_path.resolve() == output_path.resolve():
        return
    atomic_write_text(dashboard_content, mirror_path)
    if sidecar_content is not None:
        atomic_write_text(sidecar_content, mirror_path.with_name("chart-payloads-v1.json"))

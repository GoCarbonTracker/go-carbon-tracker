"""The one way to call a model: transfer approval, then spend approval, then send. Refusals are GctError and send nothing."""
import math

from gct.models import adapters
from gct.models.adapters import Adapter, Request, Response
from gct.workspace import store
from gct.workspace.layout import REFUSED, USAGE, GctError

SET_CAP = "Set an estimated spending limit with: gct approve spend AMOUNT"


def money(x: float) -> str:
    """$0.00 for zero, two decimals from one cent up, below that the first two significant digits ($0.0012)."""
    if x == 0 or abs(x) >= 0.01:
        return f"${x:.2f}"
    return f"${x:.{1 - math.floor(math.log10(abs(x)))}f}"


def _newest(conn, column: str, where: str, args: tuple):
    row = conn.execute(f"SELECT {column} FROM approval WHERE {where} ORDER BY id DESC LIMIT 1", args).fetchone()
    return None if row is None else row[0]


def transfer_state(conn, adapter: Adapter) -> str:
    """'granted', 'not granted', or 'elsewhere' when the newest grant was for another base_url or model."""
    row = conn.execute("SELECT granted, destination FROM approval WHERE kind = 'transfer' AND provider = ?"
                       " ORDER BY id DESC LIMIT 1", (adapter.name,)).fetchone()
    if row is None or not row[0]:
        return "not granted"
    return "granted" if row[1] == adapters.destination(adapter) else "elsewhere"


def cap(conn) -> float | None:
    return _newest(conn, "amount", "kind = 'spend_cap'", ())


def allowance(conn, run_id: int) -> float | None:
    return _newest(conn, "amount", "kind = 'run_allowance' AND run_id = ?", (run_id,))


def transfer_granted(conn, adapter: Adapter) -> bool:
    return transfer_state(conn, adapter) == "granted"


def spent(conn, run_id: int | None = None) -> float:
    """Estimated or, when the provider confirmed it, confirmed cost of every attempt, failures included."""
    sql = "SELECT COALESCE(SUM(COALESCE(cost_confirmed, cost_estimated)), 0.0) FROM attempt"
    if run_id is None:
        return conn.execute(sql).fetchone()[0]
    return conn.execute(sql + " WHERE run_id = ?", (run_id,)).fetchone()[0]


def _insert(conn, kind, provider=None, destination=None, run_id=None, amount=None, granted=1) -> None:
    if amount is not None and not adapters._finite(amount):
        raise GctError(USAGE, f"{amount} is not an amount in USD of 0 or more.", "Give a number such as 5 or 2.50.")
    conn.execute(
        "INSERT INTO approval (kind, provider, destination, run_id, amount, granted, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, provider, destination, run_id, amount, int(granted), store.now()),
    )


def set_cap(conn, amount: float) -> None:
    _insert(conn, "spend_cap", amount=amount)


def set_transfer(conn, adapter: Adapter, granted: bool) -> None:
    _insert(conn, "transfer", provider=adapter.name, destination=adapters.destination(adapter), granted=granted)


def _cap_or_refuse(conn) -> float:
    c = cap(conn)
    if c is None:
        raise GctError(REFUSED, "No estimated spending limit is set, so no paid work is allowed.", SET_CAP)
    if c == 0:
        raise GctError(REFUSED, "The estimated spending limit is $0.00, so no paid work is allowed.", SET_CAP)
    return c


def allow_run(conn, run_id: int, amount: float) -> None:
    """Approve paid work for this run up to amount (FR10). Refused above the cap minus what is spent."""
    if not adapters._finite(amount):
        raise GctError(USAGE, f"{amount} is not an amount in USD of 0 or more.", "Give a number such as 5 or 2.50.")
    c = _cap_or_refuse(conn)
    left = c - spent(conn)
    if amount > left:
        raise GctError(REFUSED, f"An allowance of {money(amount)} is more than the {money(left)} left under the estimated"
                                f" spending limit of {money(c)}.",
                       "Use a smaller allowance, or raise the limit with: gct approve spend AMOUNT")
    _insert(conn, "run_allowance", run_id=run_id, amount=amount)


def call(conn, run_id: int, adapter: Adapter, request: Request, *, private: bool) -> Response:
    if adapter.external and private and (state := transfer_state(conn, adapter)) != "granted":
        command = f"gct approve transfer {adapter.name}"
        if state == "elsewhere":
            raise GctError(REFUSED, f"{adapter.name} was approved for a different endpoint or model. "
                                    f"Approve it again with: {command}", command)
        raise GctError(REFUSED, f"{adapter.name} is an external service and this document is private. "
                                f"Approve the transfer with: {command}", command)
    # The cap holds across processes: every paid command holds the workspace lock, so no two reach this check at once.
    if adapter.paid:
        c = _cap_or_refuse(conn)
        a = allowance(conn, run_id)
        if a is None:
            raise GctError(REFUSED, "This run has no allowance for paid work.",
                           "Run the command again with an allowance for paid work.")
        cost = adapters.estimate(adapter, request)
        run_spent, all_spent = spent(conn, run_id), spent(conn)
        if run_spent + cost > a:
            raise GctError(REFUSED, f"This run's allowance of {money(a)} is used up (estimated spend {money(run_spent)},"
                                    f" the next call is about {money(cost)}).", "Run the command again with a larger allowance.")
        if all_spent + cost > c:
            raise GctError(REFUSED, f"The estimated spending limit of {money(c)} would be passed (estimated spend"
                                    f" {money(all_spent)}, the next call is about {money(cost)}).",
                           "Raise the limit with: gct approve spend AMOUNT")
    return adapters.send(adapter, request)

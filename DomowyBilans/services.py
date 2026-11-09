"""Logika finansowa: salda, prognozy, limity, cele i symulacje."""
import calendar
import math
from datetime import date

from sqlalchemy import func

from extensions import db
from models import Budget, Member, Planned, SavingsGoal, Transaction

CATEGORIES = ["Mieszkanie", "Żywność", "Transport", "Edukacja", "Zdrowie",
              "Rozrywka", "Wynagrodzenie", "Inne"]
EXPENSE_CATEGORIES = [c for c in CATEGORIES if c != "Wynagrodzenie"]
FIXED_CATEGORIES = {"Mieszkanie"}  # tu nie podpowiadamy cięć
MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


# ---------- pomocnicze ----------
def r2(x):
    return round(float(x or 0), 2)


def pln(value):
    if value is None:
        return "–"
    return f"{value:,.2f}".replace(",", " ").replace(".", ",").replace("-", "−") + " zł"


def fmt(d):
    return d.strftime("%d.%m.%Y")


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def clamp_day(y, m, day):
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def month_label(d):
    return f"{MONTHS[d.month - 1]} {d.year % 100:02d}"


def parse_amount(raw):
    try:
        v = round(float(str(raw).strip().replace(",", ".").replace(" ", "")), 2)
    except (ValueError, TypeError):
        return None
    return v if 0 < v < 1_000_000 else None


def parse_date(raw):
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _sum(kind, start=None, end=None):
    q = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(Transaction.kind == kind)
    if start:
        q = q.filter(Transaction.date >= start)
    if end:
        q = q.filter(Transaction.date < end)
    return r2(q.scalar())


# ---------- salda i podsumowania ----------
def savings_total():
    return r2(db.session.query(func.coalesce(func.sum(SavingsGoal.saved), 0)).scalar())


def balance():
    """Środki do dyspozycji: dochody - wydatki - kwoty odłożone na cele."""
    return r2(_sum("income") - _sum("expense") - savings_total())


def summary():
    start = date.today().replace(day=1)
    end = add_months(start, 1)
    return {"income": _sum("income", start, end), "expense": _sum("expense", start, end),
            "balance": balance(), "savings": savings_total()}


def monthly_series(n=6):
    first = add_months(date.today().replace(day=1), -(n - 1))
    out = {"labels": [], "income": [], "expense": []}
    for i in range(n):
        s = add_months(first, i)
        e = add_months(s, 1)
        out["labels"].append(month_label(s))
        out["income"].append(_sum("income", s, e))
        out["expense"].append(_sum("expense", s, e))
    return out


def averages(n=3):
    """Średnie miesięczne z ostatnich n pełnych miesięcy."""
    cur = date.today().replace(day=1)
    s = add_months(cur, -n)
    inc, exp = _sum("income", s, cur) / n, _sum("expense", s, cur) / n
    return {"income": r2(inc), "expense": r2(exp), "surplus": r2(inc - exp)}


def row(t):
    return {"id": t.id, "iso_date": t.date.isoformat(), "date": fmt(t.date), "description": t.description or t.category,
            "category": t.category, "member": t.member.name if t.member else "–",
            "nature": t.nature, "kind": t.kind, "amount": r2(t.amount)}


def recent_transactions(n=6):
    q = Transaction.query.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(n)
    return [row(t) for t in q]


def filter_transactions(args):
    q = Transaction.query
    if parse_date(args.get("from")):
        q = q.filter(Transaction.date >= parse_date(args["from"]))
    if parse_date(args.get("to")):
        q = q.filter(Transaction.date <= parse_date(args["to"]))
    if parse_amount(args.get("min")):
        q = q.filter(Transaction.amount >= parse_amount(args["min"]))
    if parse_amount(args.get("max")):
        q = q.filter(Transaction.amount <= parse_amount(args["max"]))
    if args.get("category"):
        q = q.filter(Transaction.category == args["category"])
    if args.get("kind") in ("income", "expense"):
        q = q.filter(Transaction.kind == args["kind"])
    if args.get("member"):
        q = q.join(Member).filter(Member.name == args["member"])
    return q.order_by(Transaction.date.desc(), Transaction.id.desc())


# ---------- kalendarz i prognoza ----------
def next_date(day, today=None):
    today = today or date.today()
    d = clamp_day(today.year, today.month, day)
    if d < today:
        n = add_months(today.replace(day=1), 1)
        d = clamp_day(n.year, n.month, day)
    return d


def upcoming_events(days=30):
    today, out = date.today(), []
    for p in Planned.query.all():
        d = next_date(p.day, today)
        if (d - today).days <= days:
            out.append({"sort": d, "date": d.strftime("%d.%m"), "name": p.name,
                        "kind": p.kind, "amount": r2(p.amount)})
    out.sort(key=lambda e: e["sort"])
    for e in out:
        del e["sort"]
    return out


def regular_items():
    """Stałe miesięczne dochody i wydatki wyświetlane w zestawieniu."""
    items = Planned.query.filter_by(regular=True).all()
    result = [{"id": p.id, "kind": p.kind, "name": p.name, "member": p.member.name if p.member else "Wspólne",
               "day": p.day, "amount": r2(p.amount), "category": p.category} for p in items]
    return sorted(result, key=lambda p: (p["kind"] != "income", p["day"], p["name"].casefold()))


def forecast():
    """Prognozowane saldo na koniec miesiąca."""
    if not Transaction.query.count() and not Planned.query.count():
        return None
    today = date.today()
    last = calendar.monthrange(today.year, today.month)[1]
    inc_left = bills_left = bills_total = 0
    for p in Planned.query.all():
        if p.kind == "expense":
            bills_total += p.amount
        if clamp_day(today.year, today.month, p.day) > today:
            if p.kind == "income":
                inc_left += p.amount
            else:
                bills_left += p.amount
    variable = max(averages()["expense"] - bills_total, 0)
    var_left = variable / last * (last - today.day)
    end = balance() + inc_left - bills_left - var_left
    return {"end_balance": r2(end), "available": r2(end), "safe": end >= 0, "income_left": r2(inc_left),
            "bills_left": r2(bills_left), "variable_left": r2(var_left)}


# ---------- limity ----------
def budget_overview():
    today = date.today()
    start = today.replace(day=1)
    days = calendar.monthrange(today.year, today.month)[1]

    def by_cat(s, e):
        q = (db.session.query(Transaction.category, func.sum(Transaction.amount))
             .filter(Transaction.kind == "expense", Transaction.date >= s, Transaction.date < e)
             .group_by(Transaction.category))
        return {c: r2(v) for c, v in q}

    spent = by_cat(start, add_months(start, 1))
    avg = {c: r2(v / 3) for c, v in by_cat(add_months(start, -3), start).items()}
    limits = {b.category: b for b in Budget.query.all()}

    rows = []
    for c in sorted(set(spent) | set(avg) | set(limits)):
        s, a = spent.get(c, 0), avg.get(c, 0)
        lim = r2(limits[c].limit) if c in limits else None
        projected = r2(s / today.day * days)
        pct = round(s / lim * 100) if lim else None
        left = r2(lim - s) if lim else None
        suggested = saving = None
        if a >= 20 and c not in FIXED_CATEGORIES:
            suggested = float(round(a * 0.9 / 10) * 10)   # 10% mniej niż średnia
            saving = r2(a - suggested)
        if lim is None:
            status = "none"
        elif s > lim:
            status = "over"
        elif projected > lim or pct >= 80:
            status = "warn"
        else:
            status = "ok"
        rows.append({"id": limits[c].id if c in limits else None, "category": c, "spent": s, "avg": a, "limit": lim, "pct": pct, "left": left,
                     "daily": r2(left / (days - today.day + 1)) if lim and left > 0 else None,
                     "projected": projected, "suggested": suggested, "saving": saving or 0,
                     "status": status})
    rows.sort(key=lambda r: (r["limit"] is None, -r["spent"]))
    return {"rows": rows, "potential": r2(sum(r["saving"] for r in rows))}


# ---------- cele ----------
STATUS_LABELS = {"done": "Osiągnięty", "late": "Po terminie", "tight": "Zagrożony", "ok": "Na dobrej drodze"}


def goals_overview():
    today = date.today()
    surplus = max(averages()["surplus"], 0)
    goals, need_total = [], 0
    q = SavingsGoal.query.order_by(SavingsGoal.deadline.is_(None), SavingsGoal.deadline)
    for g in q:
        target, saved = r2(g.target), r2(g.saved)
        remaining = max(r2(target - saved), 0)
        months_left = need = None
        late = False
        if remaining > 0 and g.deadline:
            late = g.deadline <= today
            months_left = 1 if late else max(1, math.ceil((g.deadline - today).days / 30.4))
            need = r2(remaining / months_left)
            need_total += need
        eta = fmt(add_months(today, math.ceil(remaining / surplus))) if remaining > 0 and surplus > 0 else None
        goals.append({"id": g.id, "name": g.name, "target": target, "saved": saved,
                      "remaining": remaining, "pct": min(round(saved / target * 100), 100) if target else 0,
                      "deadline": fmt(g.deadline) if g.deadline else None, "months_left": months_left,
                      "need": need, "eta": eta, "late": late})

    shortfall = need_total - surplus
    for g in goals:
        g["status"] = ("done" if g["remaining"] == 0 else "late" if g["late"]
                       else "tight" if shortfall > 0 and g["need"] else "ok")
        g["status_label"] = STATUS_LABELS[g["status"]]

    tips = []
    if need_total > 0:
        if shortfall > 0:
            tips.append(f"Żeby zdążyć ze wszystkimi celami, trzeba odkładać ok. {pln(need_total)} miesięcznie, "
                        f"a Wasza średnia nadwyżka to {pln(surplus)}. Brakuje ok. {pln(shortfall)} miesięcznie.")
            cuts = sorted((r for r in budget_overview()["rows"] if r["saving"] > 0),
                          key=lambda r: -r["saving"])[:3]
            if cuts:
                total_cut = sum(r["saving"] for r in cuts)
                tips.append("Zacznijcie od ograniczenia wydatków: "
                            + ", ".join(f"{r['category']} o {pln(r['saving'])}" for r in cuts)
                            + f". Razem ok. {pln(total_cut)} miesięcznie.")
                if total_cut < shortfall:
                    tips.append("To nie pokryje całej różnicy. Rozważcie przesunięcie terminu jednego z celów "
                                "albo dodatkowe źródło dochodu.")
        else:
            tips.append(f"Wasza średnia nadwyżka ({pln(surplus)}) pokrywa wszystkie cele. "
                        f"Po odłożeniu {pln(need_total)} zostanie ok. {pln(-shortfall)} miesięcznie zapasu.")
    elif goals and surplus > 0 and any(g["remaining"] > 0 for g in goals):
        tips.append(f"Ustawcie terminy celów, a podpowiem, ile odkładać miesięcznie. Średnia nadwyżka: {pln(surplus)}.")
    return {"goals": goals, "tips": tips, "surplus": surplus, "need_total": r2(need_total)}


def deposit(goal_id, amount):
    g = db.session.get(SavingsGoal, goal_id)
    if not g:
        return "Nie znaleziono celu."
    if amount > balance():
        return f"Na koncie jest tylko {pln(balance())} wolnych środków."
    g.saved = r2(g.saved) + amount
    db.session.commit()
    return None


# ---------- symulacje ----------
def irregular_monthly_averages():
    """Średnie nieregularnych transakcji z maksymalnie 12 pełnych miesięcy."""
    current_month = date.today().replace(day=1)
    window_start = add_months(current_month, -12)
    earliest = db.session.query(func.min(Transaction.date)).scalar()
    if earliest is None:
        return {"income": 0, "expense": 0, "months": 0, "by_source": {}}

    start = max(window_start, earliest.replace(day=1))
    months = (current_month.year - start.year) * 12 + current_month.month - start.month
    if months <= 0:
        return {"income": 0, "expense": 0, "months": 0, "by_source": {}}

    # History entries matching an active fixed plan are not irregular, even if
    # an old record has the wrong nature value. Opening balance is not income.
    fixed_names = {(p.kind, p.name.casefold()) for p in Planned.query.filter_by(regular=True).all()}
    totals = {"income": 0.0, "expense": 0.0}
    source_totals = {}
    rows = Transaction.query.filter(Transaction.date >= start, Transaction.date < current_month,
                                    Transaction.nature == "zmienny").all()
    for t in rows:
        name = (t.description or "").strip()
        if name.casefold() == "saldo początkowe" or (t.kind, name.casefold()) in fixed_names:
            continue
        if t.kind not in totals:
            continue
        amount = r2(t.amount)
        totals[t.kind] += amount
        if t.kind == "income" and name:
            source_key = (name.casefold(), t.member_id)
            source_totals[source_key] = source_totals.get(source_key, 0) + amount

    return {"income": r2(totals["income"] / months),
            "expense": r2(totals["expense"] / months), "months": months,
            "by_source": {name: r2(amount / months) for name, amount in source_totals.items()}}


def simulate(source_id, loss_months, expense, horizon):
    today = date.today()
    sources = Planned.query.filter_by(kind="income").all()
    fixed_income = r2(sum(p.amount for p in sources if p.regular))
    fixed_expense = r2(sum(p.amount for p in Planned.query.filter_by(kind="expense", regular=True).all()))
    irregular = irregular_monthly_averages()
    income = r2(fixed_income + irregular["income"])
    expenses = r2(fixed_expense + irregular["expense"])
    start, savings = balance(), savings_total()
    lost = db.session.get(Planned, source_id) if source_id else None
    lost = lost if lost and lost.kind == "income" else None
    lost_amount = (r2(lost.amount) if lost and lost.regular else
                   irregular["by_source"].get((lost.name.casefold(), lost.member_id), 0) if lost else 0)

    rows, base, scen = [], start, start
    for m in range(1, horizon + 1):
        base += income - expenses
        income_removed = lost_amount if lost and (loss_months is None or m <= loss_months) else 0
        scen += income - income_removed - expenses - (expense if m == 1 else 0)
        rows.append({"label": month_label(add_months(today, m)), "base": r2(base), "scen": r2(scen)})

    lowest = min(rows, key=lambda r: r["scen"])
    neg = next((r for r in rows if r["scen"] < 0), None)
    cut = math.ceil(max([0] + [-r["scen"] / i for i, r in enumerate(rows, 1)]))
    net_during = income - lost_amount - expenses
    runway = runway_sav = None
    if lost and net_during < 0:
        runway = round(max(start, 0) / -net_during, 1)
        runway_sav = round(max(start + savings, 0) / -net_during, 1)

    tips = []
    if lost:
        duration = "bezterminowo" if loss_months is None else f"przez {loss_months} mies."
        tips.append(f"Bez źródła „{lost.name}” {duration} miesięczne wpływy spadają z {pln(income)} do {pln(income - lost_amount)}.")
    if neg:
        tips.append(f"Aby uniknąć debetu, ograniczajcie wydatki o ok. {pln(cut)} miesięcznie w całym okresie.")
        if savings:
            covers = "pokryją" if savings + lowest["scen"] >= 0 else "pokryją część"
            tips.append(f"Odłożone oszczędności ({pln(savings)}) {covers} niedobór, ale oddalą Was od celów.")
    elif lost or expense:
        tips.append("Poradzicie sobie bez ruszania oszczędności.")
    if runway is not None:
        tips.append(f"Wolne środki wystarczą na ok. {runway} mies. (z oszczędnościami: {runway_sav} mies.).")

    return {
        "params": {"source_id": source_id, "loss_months": loss_months,
                   "indefinite": loss_months is None, "expense": expense, "horizon": horizon},
        "basis": {"fixed_income": fixed_income, "fixed_expense": fixed_expense,
                  "irregular_income": irregular["income"], "irregular_expense": irregular["expense"],
                  "history_months": irregular["months"]},
        "rows": rows, "labels": [r["label"] for r in rows],
        "base": [r["base"] for r in rows], "scen": [r["scen"] for r in rows],
        "start": start, "lowest": lowest["scen"], "lowest_label": lowest["label"],
        "end": rows[-1]["scen"], "diff": r2(rows[-1]["scen"] - rows[-1]["base"]),
        "income_after": r2(income - lost_amount), "safe": neg is None,
        "headline": ("Budżet wytrzyma ten scenariusz" if not neg
                     else f"Saldo spadnie poniżej zera w {neg['label']}"),
        "tips": tips,
    }

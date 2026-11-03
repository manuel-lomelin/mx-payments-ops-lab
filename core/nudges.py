"""Spanish collection-message drafter (template or LLM) behind compliance guardrails.

The LLM is optional. Without ANTHROPIC_API_KEY (or on any API error or refusal) the
deterministic template is used. Either way the draft goes through core.compliance before
it can be "sent", and blocked drafts are logged.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from core.clabe import build_clabe
from core.compliance import ComplianceReport, check_draft, format_mxn
from core.config import load_config

DEFAULT_MODEL = "claude-opus-5-5"


@dataclass(frozen=True)
class AccountContext:
    account_id: str
    first_name: str
    company: str
    amount: float
    stage: str
    channel: str
    timezone: str
    pay_by: str
    dpd: int = 0

    @property
    def clabe(self) -> str:
        """Synthetic collection CLABE (bank code 646, plaza 180) unique per account."""
        return build_clabe("646", "180", f"{int(self.account_id[1:]):011d}")

    @property
    def reference(self) -> str:
        return f"{int(self.account_id[1:]):07d}"


@dataclass
class Draft:
    text: str
    source: str  # template | llm | llm_fallback_template | manual
    note: str = ""


def template_draft(ctx: AccountContext, templates: dict | None = None, sender: str | None = None):
    templates = templates or load_config("nudge_templates")
    sender = sender or load_config("compliance")["sender_name"]
    by_channel = templates.get(ctx.stage)
    if not by_channel:
        raise ValueError(f"No template for stage '{ctx.stage}'")
    template = by_channel.get(ctx.channel) or next(iter(by_channel.values()))
    text = " ".join(template.split()).format(
        first_name=ctx.first_name,
        company=ctx.company,
        sender=sender,
        amount=format_mxn(ctx.amount),
        clabe=ctx.clabe,
        reference=ctx.reference,
        pay_by=ctx.pay_by,
    )
    return Draft(text=text, source="template")


SYSTEM_PROMPT = """Eres un redactor de mensajes de cobranza B2B para una financiera mexicana.
Escribes en español de México, con tono respetuoso, claro y breve (máximo 80 palabras).
Reglas obligatorias:
- Identifica al remitente con el nombre exacto que se te da.
- Incluye el monto adeudado exactamente como se te da (por ejemplo $12,345.67).
- Incluye la opción de pago: CLABE y referencia exactas.
- Nunca amenaces, no menciones cárcel, policía, juzgados ni autoridades, no insultes,
  no presiones con terceros (familia, vecinos, jefe, clientes) y no exageres consecuencias.
- Puedes mencionar un plan de pagos o la asignación a un despacho de cobranza externo
  registrado solo si la etapa lo indica, como información, no como amenaza.
Responde únicamente con el texto del mensaje, sin comillas ni explicaciones."""


def _llm_prompt(ctx: AccountContext, sender: str) -> str:
    return (
        f"Remitente: {sender}\n"
        f"Canal: {ctx.channel}\n"
        f"Etapa de cobranza: {ctx.stage}\n"
        f"Nombre del contacto: {ctx.first_name}\n"
        f"Empresa: {ctx.company}\n"
        f"Días de atraso: {ctx.dpd}\n"
        f"Monto adeudado: {format_mxn(ctx.amount)}\n"
        f"CLABE para pago: {ctx.clabe}\n"
        f"Referencia: {ctx.reference}\n"
        f"Fecha límite sugerida: {ctx.pay_by}"
    )


def llm_available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def llm_draft(ctx: AccountContext, client=None, model: str | None = None) -> Draft:
    """Draft with Claude. Falls back to the template on missing key, error or refusal."""
    sender = load_config("compliance")["sender_name"]
    if client is None:
        if not llm_available():
            return _fallback(ctx, "no ANTHROPIC_API_KEY configured")
        import anthropic

        client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _llm_prompt(ctx, sender)}],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except Exception as exc:  # any API/network error: never block the workflow on the LLM
        return _fallback(ctx, f"LLM error: {type(exc).__name__}")
    if response.stop_reason == "refusal":
        return _fallback(ctx, "LLM refused")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        return _fallback(ctx, "LLM returned no text")
    return Draft(text=text, source="llm", note=f"model {response.model}")


def _fallback(ctx: AccountContext, reason: str) -> Draft:
    draft = template_draft(ctx)
    return Draft(text=draft.text, source="llm_fallback_template", note=reason)


@dataclass
class ContactLog:
    """Sent contacts (feed frequency caps) and blocked drafts (audit trail)."""

    sent: list[dict] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)

    def history(self, account_id: str) -> list[datetime]:
        return [c["sent_at"] for c in self.sent if c["account_id"] == account_id]

    def record(self, ctx: AccountContext, draft: Draft, report: ComplianceReport, send_at):
        row = {
            "account_id": ctx.account_id,
            "stage": ctx.stage,
            "channel": ctx.channel,
            "source": draft.source,
            "text": draft.text,
        }
        if report.passed:
            self.sent.append({**row, "sent_at": send_at})
        else:
            self.blocked.append(
                {**row, "attempted_at": send_at, "failed_rules": ", ".join(report.failed_rules)}
            )
        return report.passed

    def blocked_frame(self) -> pd.DataFrame:
        cols = ["attempted_at", "account_id", "stage", "channel", "source", "failed_rules", "text"]
        return pd.DataFrame(self.blocked, columns=cols)

    def sent_frame(self) -> pd.DataFrame:
        cols = ["sent_at", "account_id", "stage", "channel", "source", "text"]
        return pd.DataFrame(self.sent, columns=cols)


def seed_contact_log(
    worklist: pd.DataFrame, now: datetime, seed: int = 5, max_recent: int = 3
) -> ContactLog:
    """Synthetic prior contacts in the last 7 days for accounts under active treatment."""
    rng = random.Random(seed)
    log = ContactLog()
    active = worklist[worklist["stage"] != "no_action"]
    for row in active.itertuples():
        for _ in range(rng.randint(0, max_recent)):
            sent_at = now - timedelta(hours=rng.uniform(2, 24 * 7))
            log.sent.append(
                {
                    "account_id": row.account_id,
                    "stage": row.stage,
                    "channel": row.channel,
                    "source": "history",
                    "text": "",
                    "sent_at": sent_at,
                }
            )
    return log


def prepare_and_check(
    ctx: AccountContext,
    draft: Draft,
    send_at: datetime,
    log: ContactLog,
    stage_weekly_cap: int | None = None,
) -> ComplianceReport:
    return check_draft(
        draft.text,
        amount=ctx.amount,
        send_at=send_at,
        timezone=ctx.timezone,
        history=log.history(ctx.account_id),
        stage_weekly_cap=stage_weekly_cap,
    )

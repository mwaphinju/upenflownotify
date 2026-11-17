from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import build_engine, build_session_factory
from app.models import MappingRule, MappingRuleVersion, User


DEMO_RULES = [
    {
        "name": "Order dispatched",
        "priority": 10,
        "match_type": "regex",
        "match_value": r"Order (?P<order_no>\d+) dispatched",
        "case_sensitive": False,
        "sender_id": "UPENFLOW",
        "outbound_template": "Hi, your order {{order_no}} is on its way.",
        "is_enabled": True,
    },
    {
        "name": "Order delivered",
        "priority": 20,
        "match_type": "contains",
        "match_value": "delivered",
        "case_sensitive": False,
        "sender_id": "UPENFLOW",
        "outbound_template": "Your order {{order_ref}} has been delivered. Thank you.",
        "is_enabled": True,
    },
    {
        "name": "Order cancelled",
        "priority": 30,
        "match_type": "contains",
        "match_value": "cancelled",
        "case_sensitive": False,
        "sender_id": "UPENFLOW",
        "outbound_template": "Order {{order_ref}} was cancelled.",
        "is_enabled": True,
    },
]


def main():
    engine = build_engine(get_settings().database_url)
    try:
        with build_session_factory(engine)() as db:
            admin = db.scalar(select(User).where(User.role == "super_admin", User.is_active.is_(True)))
            if admin is None:
                raise SystemExit("Seed the first Super Admin before adding demo rules.")
            for data in DEMO_RULES:
                if db.scalar(select(MappingRule).where(MappingRule.name == data["name"], MappingRule.deleted_at.is_(None))):
                    continue
                rule = MappingRule(**data, version=1, created_by=admin.id, updated_by=admin.id)
                db.add(rule)
                db.flush()
                db.add(
                    MappingRuleVersion(
                        rule_id=rule.id,
                        version=1,
                        snapshot=data,
                        created_by=admin.id,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            db.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
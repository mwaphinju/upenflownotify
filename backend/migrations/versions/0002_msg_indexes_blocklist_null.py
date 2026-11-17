import sqlalchemy as sa
from alembic import op

revision = "0002_msg_indexes_blocklist_null"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

# NOTE: revision 0001 runs `Base.metadata.create_all()` against whatever app/models.py
# currently defines, rather than a frozen historical schema. A fresh database therefore
# already has the columns/indexes below by the time this revision runs. Every operation
# here checks current state first so this revision is a safe no-op on a fresh install and
# a real migration on a database created before these model changes shipped.

NEW_INDEXES = {
    "ix_inbound_messages_recipient": "recipient",
    "ix_inbound_messages_sender_id": "sender_id",
    "ix_inbound_messages_network": "network",
}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_indexes = {index["name"] for index in inspector.get_indexes("inbound_messages")}
    for index_name, column in NEW_INDEXES.items():
        if index_name not in existing_indexes:
            op.create_index(index_name, "inbound_messages", [column])

    blocklist_columns = {column["name"]: column for column in inspector.get_columns("blocklist")}
    if blocklist_columns.get("created_by", {}).get("nullable") is False:
        with op.batch_alter_table("blocklist") as batch_op:
            batch_op.alter_column("created_by", existing_type=sa.Integer(), nullable=True)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    blocklist_columns = {column["name"]: column for column in inspector.get_columns("blocklist")}
    if blocklist_columns.get("created_by", {}).get("nullable") is True:
        with op.batch_alter_table("blocklist") as batch_op:
            batch_op.alter_column("created_by", existing_type=sa.Integer(), nullable=False)

    existing_indexes = {index["name"] for index in inspector.get_indexes("inbound_messages")}
    for index_name in NEW_INDEXES:
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name="inbound_messages")

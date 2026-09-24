CREATE TABLE IF NOT EXISTS ebay_notification_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_id TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    event_date TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    delivery_count INTEGER NOT NULL DEFAULT 0,
    last_delivered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ebay_events_workspace_received
ON ebay_notification_events (workspace_id, received_at);

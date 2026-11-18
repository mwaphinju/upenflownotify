export type User = { name: string; email: string; role: string }
export type Rule = {
  id: number
  name: string
  priority: number
  match_type: 'contains' | 'starts_with' | 'exact' | 'regex'
  match_value: string
  case_sensitive: boolean
  sender_id: string
  outbound_template: string
  is_enabled: boolean
  version: number
}
export type RuleDraft = Omit<Rule, 'id' | 'version'>
export type RuleVersion = { version: number; snapshot: Record<string, unknown>; created_by: number | null; created_at: string }
export type TestResult = {
  rule: Rule | null
  status: string
  rendered_text: string | null
  character_count?: number
  encoding?: string
  segments: number
  warnings: string[]
}
export type ManagedUser = { id: number; name: string; email: string; role: string; is_active: boolean; password_set: boolean }
export type ActiveSession = { id: number; device: string; ip_address: string | null; last_seen_at: string; current: boolean }
export type SendingState = { state: 'on' | 'paused' | 'stopped'; queued_count: number; test_mode: boolean }
export type Message = {
  id: number; message_id: string; received_at: string; recipient: string; order_ref: string | null
  sender_id: string | null; network: string | null; segments: number | null; cost_kes: number | null
  inbound_preview: string; sms_preview: string | null; status: string; status_reason: string | null
}
export type TimelineEvent = { status: string; at: string | null }
export type MessageDetail = Message & {
  inbound_text: string; rendered_text: string | null; rule: string | null; rule_version: number | null
  raw_payload: Record<string, unknown>; rate_per_segment_kes: number | null; attempts: number; error: string | null
  provider_message_id: string | null; timeline: TimelineEvent[]; can_resend: boolean
}
export type KpiValue = { value: number; change_percent: number; rate?: number }
export type Dashboard = {
  period: { label: string; start: string; end: string }
  kpis: Record<'received' | 'sent' | 'delivered' | 'failed' | 'unmapped' | 'total_cost_kes' | 'avg_cost_per_sms_kes', KpiValue>
  budget_kes: number
  budget_used_percent: number
  charts: {
    granularity: string
    timeseries: { period: string; sent: number; delivered: number; failed: number; cost_kes: number }[]
    by_rule: { rule: string; count: number; cost_kes: number }[]
    by_network: { network: string; count: number }[]
    hour_heatmap: { hour: number; count: number }[]
  }
  sending_state: string
  queued: number
  test_mode: boolean
}
export type Configuration = {
  billing: { cost_per_segment_kes: string; currency: string; monthly_budget_kes: string; alert_threshold_percent: number; network_rates: Record<string, string> }
  gateway: {
    base_url: string | null; client_id: string | null; has_client_id: boolean; api_key: string | null; has_api_key: boolean
    access_key: string | null; has_access_key: boolean; default_sender_id: string; allowed_sender_ids: string[]
  }
  limits: { send_rate_per_second: number; max_segments: number; stale_queue_minutes: number; retry_attempts: number }
  safety: { max_per_recipient_hour: number; duplicate_window_minutes: number; test_mode: boolean; fake_gateway: boolean; test_allowlist: string[] }
  quiet_hours: { enabled: boolean; start: string; end: string }
  retention: { message_retention_days: number; audit_log_retention_days: number }
  monitoring: {
    service_a_silence_minutes: number; error_rate_threshold_percent: number; low_credit_kes: string
    balance_check_enabled: boolean; balance_check_interval_minutes: number
    slack_webhook_url: string | null; has_slack_webhook: boolean; telegram_bot_token: string | null; has_telegram_bot_token: boolean
    telegram_chat_id: string | null; oncall_phone: string | null
  }
  network_prefixes: Record<string, string[]>
  timezone: string
  alert_emails: string[]
}

export type View = 'dashboard' | 'messages' | 'rules' | 'blocklist' | 'settings' | 'users' | 'account'
export type SettingsSection = 'billing' | 'gateway' | 'limits' | 'safety' | 'quiet-hours' | 'retention' | 'monitoring' | 'network'
export type AccountSection = 'profile' | 'security' | 'sessions'
export type SenderIds = { default_sender_id: string | null; allowed_sender_ids: string[] }
export type BlockedNumber = { id: number; phone_number: string; reason: string | null; created_at: string }

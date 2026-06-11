"""omc-analytics — Omnichannel Foodservice Analytics Engine.

Public API (PR1 — Bronze ingestion pipeline):
- omc_analytics.ingestion.run: run_bronze_impl, compute_t1_window, poll_report_until_ready, cli
- omc_analytics.ingestion.otter_client: OtterClient
- omc_analytics.ingestion.oauth: OAuthRefresher
- omc_analytics.ingestion.bronze_writer: BronzeWriter
- omc_analytics.ingestion.backoff: RetryPolicy
- omc_analytics.ingestion.errors: All custom exceptions
- omc_analytics.common.secrets: SecretsPort, InMemorySecrets, MerchantCredentials
- omc_analytics.common.logs: LogsPort, InMemoryLogs, RunLog
- omc_analytics.common.config: RunContext, build_run_context
"""

from omc_analytics.ingestion.errors import Tier2LatencyError
from omc_analytics.serving.error_banners import render_tier2_info

render_tier2_info(Tier2LatencyError("test"))

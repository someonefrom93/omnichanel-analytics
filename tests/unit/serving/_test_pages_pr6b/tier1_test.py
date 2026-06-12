from omc_analytics.ingestion.errors import Tier1AuthError
from omc_analytics.serving.error_banners import render_tier1_warning

render_tier1_warning(Tier1AuthError("test"))

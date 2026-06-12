from omc_analytics.common.alerts import InMemoryAlerts
from omc_analytics.serving.error_banners import render_tier3_generic

alerts = InMemoryAlerts()
render_tier3_generic(ValueError("test crash"), alerts)

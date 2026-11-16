"""TEST_ONLY inactive Fable canary budget/dispatch boundary."""
ACTIVATION=False
from .budget import BudgetError,CampaignBudgetLedger,LedgerDescriptor
from .dispatch import campaign_dispatcher
from .journal import EffectClaim,JournalError
__all__=["ACTIVATION","BudgetError","CampaignBudgetLedger","LedgerDescriptor","campaign_dispatcher","EffectClaim","JournalError"]

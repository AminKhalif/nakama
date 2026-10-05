"""Calendar coordination SDK; no external accounts are accessed on import."""
from .client import SchedulingClient
from .models import SchedulingError, TimeWindow, available, shared_slots
from .providers import CalendarEvent, CalendarProvider, GoogleCalendar, MemoryCalendar
from .service import CalendarBinding, MeetingService
from .store import ProposalStore, SQLiteProposalStore

__all__ = ['SchedulingClient', 'SchedulingError', 'TimeWindow', 'available', 'shared_slots',
           'CalendarEvent', 'CalendarProvider', 'GoogleCalendar', 'MemoryCalendar',
           'CalendarBinding', 'MeetingService', 'ProposalStore', 'SQLiteProposalStore']

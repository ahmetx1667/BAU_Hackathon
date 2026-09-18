"""The app's fixed vocabulary: districts, levels, study modes and their labels.

These values are stored in the database verbatim, so changing one is a schema
change in disguise — see `database.migrate_legacy_values` for how the original
Turkish values are carried forward.

Place and university names stay in Turkish throughout. They are the names of real
places and institutions, not translatable interface strings.
"""

from __future__ import annotations

# Istanbul districts the app covers, plus the online option. Stored ASCII-only so
# a value never depends on the database's collation; LABELS carries the display form.
LOCATIONS = [
    "Besiktas",
    "Kadikoy",
    "Sisli",
    "Bakirkoy",
    "Uskudar",
    "Online",
]

LEVELS = ["Beginner", "Intermediate", "Advanced"]
MODES = ["In person", "Online"]
PLACES = ["Cafe", "Library", "Campus", "Online"]

# Display overrides. Only the district names need one — everything else already
# reads correctly as written.
LABELS = {
    "Besiktas": "Beşiktaş",
    "Kadikoy": "Kadıköy",
    "Sisli": "Şişli",
    "Bakirkoy": "Bakırköy",
    "Uskudar": "Üsküdar",
}

STATUS_LABELS = {
    "pending": "Pending",
    "accepted": "Accepted",
    "rejected": "Rejected",
    "expired": "Expired",
}

# University names arrive from the dataset in ASCII; these restore the Turkish
# spelling for display only.
SCHOOL_LABEL_REPLACEMENTS = {
    "Bahcesehir": "Bahçeşehir",
    "Istanbul": "İstanbul",
    "Aydin": "Aydın",
    "Mayis": "Mayıs",
    "Gelisim": "Gelişim",
    "Kultur": "Kültür",
    "Topkapi": "Topkapı",
    "Haci": "Hacı",
    "Agri": "Ağrı",
    "Izzet": "İzzet",
    "Gul": "Gül",
    "Turkes": "Türkeş",
    "Pasa": "Paşa",
}

# Suggested first-meeting spots, shown only after both students accept a match.
# Public and busy by design — the point is that a first meeting never happens
# somewhere private.
PUBLIC_PLACES = {
    "Besiktas": "Beşiktaş district library, or a busy cafe",
    "Kadikoy": "Kadıköy municipal library, or a busy cafe around Moda",
    "Sisli": "A public study space around Mecidiyeköy",
    "Bakirkoy": "Bakırköy public library, or a busy cafe",
    "Uskudar": "Üsküdar library, or a busy cafe near the waterfront",
    "Online": "Online meeting — confirm the match before sharing a phone number or address",
}

DEFAULT_PUBLIC_PLACE = "Somewhere public and busy"

# Words carrying no signal for keyword matching. The interface is English but the
# users are Turkish students who often write posts in Turkish, so both languages
# are filtered — dropping the Turkish half would let "ve", "bir" and "icin" count
# as shared interests between two otherwise unrelated posts.
STOP_WORDS = {
    # English
    "and", "are", "but", "can", "for", "from", "have", "how", "into", "its",
    "learn", "like", "looking", "need", "not", "study", "studying", "that",
    "the", "them", "there", "they", "this", "want", "was", "were", "what",
    "when", "where", "which", "will", "with", "would", "you", "your",
    # Turkish
    "ama", "arkadas", "arkadaş", "bana", "ben", "bir", "birlikte", "bugun",
    "bugün", "calisiyorum", "çalışıyorum", "calisma", "çalışma", "cok", "çok",
    "daha", "gibi", "icin", "için", "ile", "istiyorum", "kadar", "proje",
    "saat", "sen", "sonra", "var", "ve", "veya", "yapmak",
}

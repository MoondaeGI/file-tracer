"""매칭·이벤트 관련 상수."""

MATCH_TYPE_EXACT = "exact"
MATCH_TYPE_FUZZY = "fuzzy"

# ssdeep 유사도가 이 값 이상이면 fuzzy 매칭으로 포함한다.
FUZZY_MATCH_THRESHOLD = 50

# 클라이언트가 현재 생성하는 이벤트(로직 처리 대상).
EVENT_TYPES = ("created", "modified", "moved", "deleted")
# 향후 확장 예약(ETW·네트워크 필요, 현재 로직 없음).
RESERVED_EVENT_TYPES = ("copy", "upload", "download")

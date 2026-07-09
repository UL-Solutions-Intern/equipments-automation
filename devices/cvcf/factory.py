from .series6000 import Series6000
from .pcr import PcrLe


def create_cvcf(transport, log_callback, idn=""):
    """Create the matching CVCF driver from an IDN response."""
    idn_upper = (idn or "").upper()

    if "KIKUSUI" in idn_upper or "PCR-LE" in idn_upper or "PCR" in idn_upper:
        return PcrLe(transport, log_callback)

    # 기존 장비는 IDN이 없거나 모델 문자열이 일정하지 않아 Series6000을
    # fallback으로 사용해 왔다. 현장 호환성을 위해 현재 동작을 보존한다.
    return Series6000(transport, log_callback)


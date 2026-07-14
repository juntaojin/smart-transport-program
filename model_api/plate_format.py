import re


PROVINCES = "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼"
LETTER = "A-HJ-NP-Z"
ALNUM = "A-HJ-NP-Z0-9"

# 普通 7 位、新能源 8 位，以及挂/学/警/港/澳后缀号牌。
CHINA_PLATE_PATTERN = re.compile(
    rf"^[{PROVINCES}][{LETTER}](?:"
    rf"[{ALNUM}]{{5}}|"
    rf"[DF][{ALNUM}][0-9]{{4}}|"
    rf"[0-9]{{5}}[DF]|"
    rf"[{ALNUM}]{{4}}[挂学警港澳]"
    rf")$"
)


def normalize_plate_number(value: object) -> str:
    """Normalize common OCR separators before validating a plate number."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s·•.\-_]", "", value).upper()


def is_valid_china_plate(value: object) -> bool:
    return CHINA_PLATE_PATTERN.fullmatch(normalize_plate_number(value)) is not None

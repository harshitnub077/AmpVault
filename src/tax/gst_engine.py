import re

from src.core.exceptions import GSTValidationError

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
CODE_POINT_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Standard HSN rates in basis points (100 bps = 1.00%)
HSN_TAX_RATES_BPS: dict[str, int] = {
    "8541": 1200,  # Solar photovoltaic cells & modules (12%)
    "8504": 1800,  # Solar inverters & static converters (18%)
    "8507": 1800,  # Solar energy storage batteries (18%)
    "9965": 1800,  # Freight logistics and goods transportation (18%)
    "9983": 1800,  # Escrow platform and technological services (18%)
}

# State Code to Name mapping
INDIAN_STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
}


def calculate_gstin_checksum(gstin_14: str) -> str:
    """
    Calculate the 15th character check digit for a 14-character GSTIN prefix
    using the official Indian GST Mod-36 Luhn-like algorithm.
    """
    if len(gstin_14) != 14:
        raise GSTValidationError(f"Expected 14 characters for checksum calculation, got {len(gstin_14)}")

    mod = len(CODE_POINT_CHARS)
    factor = 1
    total = 0

    for char in gstin_14:
        idx = CODE_POINT_CHARS.find(char)
        if idx == -1:
            raise GSTValidationError(f"Invalid character '{char}' in GSTIN prefix")
        digit = factor * idx
        digit = (digit // mod) + (digit % mod)
        total += digit
        factor = 2 if factor == 1 else 1

    check_idx = (mod - (total % mod)) % mod
    return CODE_POINT_CHARS[check_idx]


def validate_gstin(gstin: str) -> bool:
    """
    Validate a 15-character Indian GSTIN:
    1. Structure and regex match.
    2. Valid state code prefix.
    3. Mathematical check digit validation.
    """
    if not gstin or not isinstance(gstin, str):
        raise GSTValidationError("GSTIN must be a non-empty string")

    gstin = gstin.strip().upper()
    if len(gstin) != 15:
        raise GSTValidationError(f"GSTIN must be exactly 15 characters, got {len(gstin)}")

    if not GSTIN_REGEX.match(gstin):
        raise GSTValidationError(f"GSTIN '{gstin}' does not match standard statutory pattern")

    state_code = gstin[:2]
    if state_code not in INDIAN_STATE_CODES:
        raise GSTValidationError(f"Invalid state code '{state_code}' in GSTIN '{gstin}'")

    expected_check_digit = calculate_gstin_checksum(gstin[:14])
    if gstin[14] != expected_check_digit:
        raise GSTValidationError(f"GSTIN check-digit mismatch: expected '{expected_check_digit}', got '{gstin[14]}'")

    return True


def get_hsn_tax_rate_bps(hsn_code: str) -> int:
    """Retrieve tax rate in basis points for an HSN code."""
    if hsn_code not in HSN_TAX_RATES_BPS:
        raise GSTValidationError(f"Unsupported or unconfigured HSN code '{hsn_code}'")
    return HSN_TAX_RATES_BPS[hsn_code]

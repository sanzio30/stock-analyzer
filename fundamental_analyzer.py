# -*- coding: utf-8 -*-
"""
Fundamental Stock Analyzer using yfinance (versi global auto suffix)

Fitur:
- Auto deteksi ticker lintas bursa (US, .JK, .T, .SI, dll)
- Hitung PER, PBV, ROE, DER, Dividend Yield
- Tampilkan Ringkasan Fundamental
- Untuk saham IDR:
    Price / Market Cap / Net Income dalam format singkat Rp + konversi USD di kurung
    Contoh: Rp 60.15T ($3.80B)
- Untuk saham USD:
    Price / Market Cap / Net Income dalam format singkat USD
    Contoh: $3.09T, $98.73B
"""

import yfinance as yf
import pandas as pd  # tidak wajib, tapi aman kalau mau pakai lanjut

# ------------------------------------------------------------
#  Daftar suffix bursa untuk auto-detect ticker
# ------------------------------------------------------------
EXCHANGE_SUFFIXES = [
    "",      # tanpa suffix (US, dll)
    ".JK",   # Indonesia
    ".NS",   # India (NSE)
    ".BO",   # India (BSE)
    ".TO",   # Canada
    ".V",    # Canada (TSX Venture)
    ".L",    # UK
    ".SI",   # Singapore
    ".AX",   # Australia
    ".HK",   # Hong Kong
    ".T",    # Japan
    ".KS",   # Korea
    ".KQ",   # KOSDAQ
    ".SS",   # China Shanghai
    ".SZ",   # China Shenzhen
    ".TW",   # Taiwan
    ".NZ",   # New Zealand
    ".MX",   # Mexico
]

# ------------------------------------------------------------
#  FX: USD / IDR
# ------------------------------------------------------------

def get_usd_idr_rate():
    """Ambil kurs USD/IDR terbaru dari yfinance (USDIDR=X)."""
    try:
        fx = yf.Ticker("USDIDR=X")
        data = fx.history(period="1d")
        if not data.empty:
            return float(data["Close"].iloc[-1])
    except Exception:
        pass
    return None

# ------------------------------------------------------------
#  Formatter IDR & USD (singkat)
# ------------------------------------------------------------

def format_rp_short(x):
    """Format angka Rupiah singkat (K, M, B, T) dengan prefix Rp."""
    try:
        if x is None or str(x).lower() == "nan":
            return "Rp 0"
        x = float(x)
        if abs(x) >= 1_000_000_000_000:
            return f"Rp {x / 1_000_000_000_000:.2f}T"
        elif abs(x) >= 1_000_000_000:
            return f"Rp {x / 1_000_000_000:.2f}B"   # B = billion (miliar)
        elif abs(x) >= 1_000_000:
            return f"Rp {x / 1_000_000:.2f}M"
        elif abs(x) >= 1_000:
            return f"Rp {x / 1_000:.2f}K"
        else:
            return f"Rp {x:,.0f}"
    except Exception:
        return f"Rp {x}"


def format_usd_short(x):
    """Format angka USD singkat (K, M, B, T) dengan prefix $."""
    try:
        if x is None or str(x).lower() == "nan":
            return "$0"
        x = float(x)
        sign = "-" if x < 0 else ""
        x = abs(x)

        if x >= 1_000_000_000_000:
            return f"{sign}${x / 1_000_000_000_000:.2f}T"
        elif x >= 1_000_000_000:
            return f"{sign}${x / 1_000_000_000:.2f}B"
        elif x >= 1_000_000:
            return f"{sign}${x / 1_000_000:.2f}M"
        elif x >= 1_000:
            return f"{sign}${x / 1_000:.2f}K"
        else:
            return f"{sign}${x:,.2f}"
    except Exception:
        return "$0"


def format_idr_with_usd(x, usd_idr_rate):
    """
    Gabungkan format:
        Rp xx.xxT ($yy.yyB)
    untuk nilai dalam Rupiah, dengan usd_idr_rate = IDR per 1 USD.
    """
    idr_part = format_rp_short(x)
    if not usd_idr_rate:
        return idr_part

    try:
        usd_value = float(x) / usd_idr_rate
        usd_part = format_usd_short(usd_value)
        return f"{idr_part} ({usd_part})"
    except Exception:
        return idr_part

# ------------------------------------------------------------
#  Helper yfinance & perhitungan rasio
# ------------------------------------------------------------

def is_valid_ticker(ticker: str) -> bool:
    """
    Cek apakah ticker valid:
    - kalau ada currentPrice / regularMarketPrice → anggap valid
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        return price is not None
    except Exception:
        return False


def get_basic_info(ticker):
    """Ambil info dasar saham dari yfinance."""
    stock = yf.Ticker(ticker)
    info = stock.info

    data = {
        "shortName": info.get("shortName"),
        "longName": info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        "currentPrice": info.get("currentPrice") or info.get("regularMarketPrice"),
        "marketCap": info.get("marketCap"),
        "sharesOutstanding": info.get("sharesOutstanding"),
    }
    return data, stock


def safe_div(x, y):
    """Pembagian aman, menghindari ZeroDivisionError dan None."""
    try:
        if x is None or y is None or y == 0:
            return None
        return x / y
    except Exception:
        return None


def compute_ratios(info, stock):
    """Hitung rasio fundamental utama."""
    ratios = {}

    price = info["currentPrice"]

    eps = stock.info.get("trailingEps")
    ratios["PER"] = safe_div(price, eps)

    book_value = stock.info.get("bookValue")
    ratios["PBV"] = safe_div(price, book_value)

    roe_raw = stock.info.get("returnOnEquity")
    ratios["ROE"] = roe_raw * 100 if roe_raw is not None else None

    # DER dari balance sheet
    try:
        bs = stock.balance_sheet
        col = bs.columns[0]
        total_debt = bs.loc["Total Debt", col] if "Total Debt" in bs.index else None
        total_equity = bs.loc["Total Stockholder Equity", col] if "Total Stockholder Equity" in bs.index else None
        ratios["DER"] = safe_div(total_debt, total_equity)
    except Exception:
        ratios["DER"] = None

    dy = stock.info.get("dividendYield")
    ratios["DividendYield_%"] = dy * 100 if dy is not None else None

    return ratios


def get_growth(stock):
    """
    Ambil Net Income beberapa periode & hitung CAGR sederhana.
    """
    try:
        fin = stock.financials  # income statement
        if "Net Income" not in fin.index:
            return None

        ni = fin.loc["Net Income"].sort_index()  # Series: index=periode

        if len(ni) >= 2:
            first = ni.iloc[0]
            last = ni.iloc[-1]
            years = len(ni) - 1
            cagr = (last / first) ** (1 / years) - 1 if first != 0 else None
        else:
            cagr = None

        return {
            "NetIncomeValues": ni.to_dict(),
            "NetIncomeCAGR": cagr * 100 if cagr is not None else None,
        }
    except Exception:
        return None

# ------------------------------------------------------------
#  Output ke terminal
# ------------------------------------------------------------

def pretty_print(info, ratios, growth, ticker_used):
    """
    Cetak hasil analisa:
    - IDR: Rp + (USD)
    - USD: format singkat USD
    - Lainnya: angka raw + kode currency
    """
    curr = info["currency"]
    usd_rate = None
    if curr == "IDR":
        usd_rate = get_usd_idr_rate()

    print("=" * 60)
    print(f" Ticker     : {ticker_used}")
    print(f" Fundamental Analysis: {info['longName'] or info['shortName']}")
    print("=" * 60)
    print(f"Sector     : {info['sector']}")
    print(f"Industry   : {info['industry']}")
    print(f"Currency   : {curr}")

    # ---------- Price, Market Cap, Shares ----------
    if curr == "IDR":
        print(f"Price      : {format_idr_with_usd(info['currentPrice'], usd_rate)}")
        print(f"Market Cap : {format_idr_with_usd(info['marketCap'], usd_rate)}")
        print(f"Shares Out : {format_idr_with_usd(info['sharesOutstanding'], usd_rate)}")
    elif curr == "USD":
        print(f"Price      : {format_usd_short(info['currentPrice'])}")
        print(f"Market Cap : {format_usd_short(info['marketCap'])}")
        print(f"Shares Out : {format_usd_short(info['sharesOutstanding'])}")
    else:
        print(f"Price      : {info['currentPrice']} {curr}")
        print(f"Market Cap : {info['marketCap']} {curr}")
        print(f"Shares Out : {info['sharesOutstanding']} {curr}")

    # ---------- Rasio ----------
    print("-" * 60)
    print(" Key Ratios")
    print("-" * 60)
    print(f"PER                 : {ratios['PER']:.2f}" if ratios["PER"] is not None else "PER                 : N/A")
    print(f"PBV                 : {ratios['PBV']:.2f}" if ratios["PBV"] is not None else "PBV                 : N/A")
    print(f"ROE (%)             : {ratios['ROE']:.2f}" if ratios["ROE"] is not None else "ROE (%)             : N/A")
    print(f"DER (Debt/Equity)   : {ratios['DER']:.2f}" if ratios["DER"] is not None else "DER (Debt/Equity)   : N/A")
    print(f"Dividend Yield (%)  : {ratios['DividendYield_%']:.2f}" if ratios["DividendYield_%"] is not None else "Dividend Yield (%)  : N/A")

    # ---------- Growth (Net Income) ----------
    print("-" * 60)
    print(" Growth (Net Income)")
    print("-" * 60)

    if growth is not None:
        for period, val in growth["NetIncomeValues"].items():
            label = period.date() if hasattr(period, "date") else period
            if curr == "IDR":
                print(f"{label} : {format_idr_with_usd(val, usd_rate)}")
            elif curr == "USD":
                print(f"{label} : {format_usd_short(val)}")
            else:
                print(f"{label} : {val} {curr}")

        if growth["NetIncomeCAGR"] is not None:
            print(f"\nNet Income CAGR (aprox) : {growth['NetIncomeCAGR']:.2f}% per year")
        else:
            print("\nNet Income CAGR (aprox) : N/A")
    else:
        print("Data Net Income tidak tersedia / gagal diambil.")

    print("=" * 60)
    print(" NOTE:")
    print(" - Data bergantung pada ketersediaan di yfinance.")
    print(" - Selalu kombinasikan dengan analisa kualitatif & berita.")
    print("=" * 60)

# ------------------------------------------------------------
#  Normalisasi ticker (auto suffix)
# ------------------------------------------------------------

def normalize_ticker(raw_ticker: str) -> str:
    """
    - Kalau sudah ada '.' → pakai apa adanya
    - Kalau belum:
        * coba sebagai ticker global (US)
        * kalau tidak valid → coba gabungkan dengan EXCHANGE_SUFFIXES
    """
    symbol = raw_ticker.strip().upper()
    if not symbol:
        return symbol

    if "." in symbol:
        return symbol

    if is_valid_ticker(symbol):
        return symbol

    for sfx in EXCHANGE_SUFFIXES:
        if sfx == "":
            continue
        candidate = symbol + sfx
        if is_valid_ticker(candidate):
            return candidate

    return symbol

# ------------------------------------------------------------
#  Main logic untuk CLI (terminal)
# ------------------------------------------------------------

def analyze_stock(ticker, show_ticker=None):
    print(f"Mengambil data {ticker}...\n")
    info, stock = get_basic_info(ticker)
    ratios = compute_ratios(info, stock)
    growth = get_growth(stock)
    pretty_print(info, ratios, growth, show_ticker or ticker)

# ------------------------------------------------------------
#  Fungsi khusus untuk WEB (dipanggil Flask)
# ------------------------------------------------------------

def analyze_stock_for_web(raw_ticker: str):
    """
    Dipakai oleh web:
    - input: raw ticker dari user (BBCA, BBRI, AAPL, dsb)
    - output: dict siap dipakai di template HTML
    """
    if not raw_ticker:
        raise ValueError("Ticker kosong")

    input_ticker = raw_ticker.strip().upper()
    norm_ticker = normalize_ticker(input_ticker)

    info, stock = get_basic_info(norm_ticker)
    ratios = compute_ratios(info, stock)
    growth_raw = get_growth(stock)

    curr = info["currency"]
    usd_rate = get_usd_idr_rate() if curr == "IDR" else None

    # --------- Format Price / Market Cap / Shares ---------
    if curr == "IDR":
        price_str = format_idr_with_usd(info["currentPrice"], usd_rate)
        mc_str = format_idr_with_usd(info["marketCap"], usd_rate)
        shares_str = format_idr_with_usd(info["sharesOutstanding"], usd_rate)
    elif curr == "USD":
        price_str = format_usd_short(info["currentPrice"])
        mc_str = format_usd_short(info["marketCap"])
        shares_str = format_usd_short(info["sharesOutstanding"])
    else:
        price_str = f"{info['currentPrice']} {curr}"
        mc_str = f"{info['marketCap']} {curr}"
        shares_str = f"{info['sharesOutstanding']} {curr}"

    # --------- Format rasio jadi string + raw ---------
    def fmt2(x):
        return f"{x:.2f}" if x is not None else None

    ratios_formatted = {
        "PER": ratios["PER"],
        "PER_str": fmt2(ratios["PER"]),
        "PBV": ratios["PBV"],
        "PBV_str": fmt2(ratios["PBV"]),
        "ROE": ratios["ROE"],
        "ROE_str": fmt2(ratios["ROE"]),
        "DER": ratios["DER"],
        "DER_str": fmt2(ratios["DER"]),
        "DividendYield_%": ratios["DividendYield_%"],
        "DividendYield_str": fmt2(ratios["DividendYield_%"]),
    }

    # --------- Growth Net Income ---------
    growth_list = []
    growth_cagr_str = None

    if growth_raw is not None:
        for period, val in growth_raw["NetIncomeValues"].items():
            label = period.date() if hasattr(period, "date") else period
            if curr == "IDR":
                val_str = format_idr_with_usd(val, usd_rate)
            elif curr == "USD":
                val_str = format_usd_short(val)
            else:
                val_str = f"{val} {curr}"

            growth_list.append({
                "period": str(label),
                "value_str": val_str,
            })

        if growth_raw["NetIncomeCAGR"] is not None:
            growth_cagr_str = f"{growth_raw['NetIncomeCAGR']:.2f}"

    result = {
        "input_ticker": input_ticker,
        "used_ticker": norm_ticker,
        "name": info["longName"] or info["shortName"],
        "sector": info["sector"],
        "industry": info["industry"],
        "currency": curr,

        "price_str": price_str,
        "market_cap_str": mc_str,
        "shares_out_str": shares_str,

        "ratios": ratios_formatted,
        "growth_list": growth_list,
        "growth_cagr_str": growth_cagr_str,
    }

    return result

# ------------------------------------------------------------
#  Entry point CLI
# ------------------------------------------------------------

if __name__ == "__main__":
    raw = input("Masukkan kode saham (contoh: BBCA, BBRI, ANTM, AAPL, 7203.T): ")
    norm = normalize_ticker(raw)
    if norm:
        analyze_stock(norm, show_ticker=raw.strip().upper())
    else:
        print("Ticker kosong, program berhenti.")

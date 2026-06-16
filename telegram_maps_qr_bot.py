import os, re, io, logging, qrcode
from pyproj import Transformer
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def utm_to_latlon(easting, northing, zone=48, northern=True):
    epsg = f"EPSG:326{zone:02d}" if northern else f"EPSG:327{zone:02d}"
    t = Transformer.from_crs(epsg, "EPSG:4326", always_xy=True)
    lon, lat = t.transform(easting, northing)
    return lat, lon

def dms_to_decimal(d, m, s, direction):
    dec = float(d) + float(m)/60 + float(s)/3600
    return -dec if direction.upper() in ("S", "W") else dec

def ddm_to_decimal(d, m, direction):
    dec = float(d) + float(m)/60
    return -dec if direction.upper() in ("S", "W") else dec

def to_meters(value, unit):
    unit = unit.lower().strip()
    conversions = {
        "km": 1000, "kilometer": 1000, "kilometers": 1000,
        "m": 1, "meter": 1, "meters": 1,
        "dm": 0.1, "cm": 0.01, "mm": 0.001,
        "nm": 1852, "nautical mile": 1852, "nautical miles": 1852,
        "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
        "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
        "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
        "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
    }
    return value * conversions.get(unit, 1)

def clean_number(s):
    return float(str(s).replace(",", "").replace(" ", ""))

def parse_coordinates(text):
    text = text.strip()

    # DMS any order
    dms = r"(\d+)[°d\s]\s*(\d+)['\u2019\u2018\s]\s*([\d.]+)[\"'`\u201d\u2019]{1,2}\s*([NSEWnsew])"
    matches = re.findall(dms, text)
    if len(matches) == 2:
        parts = {}
        for d, m, s, direction in matches:
            dec = dms_to_decimal(d, m, s, direction)
            if direction.upper() in ("N", "S"):
                parts["lat"] = dec
            else:
                parts["lon"] = dec
        if "lat" in parts and "lon" in parts:
            return parts["lat"], parts["lon"], "DMS"

    # DDM
    ddm = re.compile(r"(\d+)[°d]\s*([\d.]+)['\u2019]?\s*([NSns])[\s,]+(\d+)[°d]\s*([\d.]+)['\u2019]?\s*([EWew])", re.I)
    m = ddm.search(text)
    if m:
        return ddm_to_decimal(m[1], m[2], m[3]), ddm_to_decimal(m[4], m[5], m[6]), "DDM"

    # Decimal with direction
    dec_dir = re.compile(r"([\d.]+)\s*([NSns])[\s,]+([\d.]+)\s*([EWew])", re.I)
    m = dec_dir.search(text)
    if m:
        lat = float(m[1]) * (-1 if m[2].upper() == "S" else 1)
        lon = float(m[3]) * (-1 if m[4].upper() == "W" else 1)
        return lat, lon, "Decimal Degrees"

    # Two plain numbers
    two_nums = re.compile(r"^(-?[\d,]+\.?\d*)\s*[,\s]\s*(-?[\d,]+\.?\d*)$")
    m = two_nums.search(text)
    if m:
        a = clean_number(m[1])
        b = clean_number(m[2])
        if -90 <= a <= 90 and -180 <= b <= 180:
            return a, b, "Decimal Degrees"
        if 200 <= a <= 900 and 800 <= b <= 2000:
            lat, lon = utm_to_latlon(a * 1000, b * 1000)
            return lat, lon, "UTM (km)"
        if 200000 <= a <= 900000 and 800000 <= b <= 2000000:
            lat, lon = utm_to_latlon(a, b)
            return lat, lon, "UTM (m)"

    # With unit labels
    unit_pattern = re.compile(
        r"(-?[\d,]+\.?\d*)\s*(km|m|dm|cm|mm|ft|feet|yards?|yd|miles?|mi|nautical miles?|nm|inches?|in)"
        r"[\s,]+(-?[\d,]+\.?\d*)\s*(km|m|dm|cm|mm|ft|feet|yards?|yd|miles?|mi|nautical miles?|nm|inches?|in)",
        re.IGNORECASE
    )
    m = unit_pattern.search(text)
    if m:
        a_m = to_meters(clean_number(m[1]), m[2])
        b_m = to_meters(clean_number(m[3]), m[4])
        if 200000 <= a_m <= 900000 and 800000 <= b_m <= 2000000:
            lat, lon = utm_to_latlon(a_m, b_m)
            return lat, lon, f"UTM ({m[2]}/{m[4]})"

    return None

def generate_qr(url):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📍 *GPS → Google Maps QR Bot*\n\n"
        "Supported formats:\n"
        "• `11°29'27.75\"N 104°51'8.97\"E` — DMS\n"
        "• `11°29.4625'N 104°51.1495'E` — DDM\n"
        "• `11.531 N, 104.862 E` — Decimal\n"
        "• `11.531, 104.862` — Plain decimal\n"
        "• `484035, 1275661` — UTM meters\n"
        "• `484.035, 1275.661` — UTM km\n",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info(f"USER: id={user.id} | name={user.full_name} | username=@{user.username} | text={update.message.text}")
    result = parse_coordinates(update.message.text)
    if not result:
        await update.message.reply_text(
            "❌ Could not recognize coordinates.\n\n"
            "Try: `11°29'27.75\"N 104°51'8.97\"E`\n"
            "Or: `11.531, 104.862`",
            parse_mode="Markdown"
        )
        return
    lat, lon, ctype = result
    url = f"https://maps.google.com/maps?q={lat:.6f},{lon:.6f}"
    await update.message.reply_photo(
        photo=generate_qr(url),
        caption=f"📍 *{ctype}*\nLat: `{lat:.6f}` | Lon: `{lon:.6f}`\n[Open in Google Maps]({url})",
        parse_mode="Markdown"
    )

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
print("🤖 Bot running!")
app.run_polling()

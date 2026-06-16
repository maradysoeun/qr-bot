import os, re, io, logging, qrcode
from pyproj import Transformer
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

BOT_TOKEN = ("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

def dms_to_decimal(d, m, s, direction):
    dec = float(d) + float(m)/60 + float(s)/3600
    return -dec if direction.upper() in ("S","W") else dec

def utm_to_latlon(e, n, zone=48):
    t = Transformer.from_crs(f"EPSG:326{zone:02d}", "EPSG:4326", always_xy=True)
    lon, lat = t.transform(e, n)
    return lat, lon

def clean_number(s):
    return float(s.replace(",", ""))

def parse_coordinates(text):
    text = text.strip()
    dms = r"(\d+)[°\s](\d+)['\s]([\d.]+)[\"']?\s*([NSEWnsew])"
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
            return parts["lat"], parts["lon"], "GPS"
    m = re.search(r"^(-?[\d,]+\.?\d*)\s*[,\s]\s*(-?[\d,]+\.?\d*)$", text)
    if m:
        a = clean_number(m[1])
        b = clean_number(m[2])
        if -90<=a<=90 and -180<=b<=180: return a, b, "GPS"
        if 200<=a<=900 and 800<=b<=2000:
            lat, lon = utm_to_latlon(a*1000, b*1000)
            return lat, lon, "UTM-km"
        if 200000<=a<=900000 and 800000<=b<=2000000:
            lat, lon = utm_to_latlon(a, b)
            return lat, lon, "UTM-m"
    return None

def generate_qr(url):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(url); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return buf

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📍 Send coordinates in any format:\n"
        "• 11°31'55.8\"N 104°51'46.0\"E\n"
        "• 104°51'46\"E 11°31'55\"N\n"
        "• 11.5321, 104.8628\n"
        "• 484.035, 1275.661 (UTM km)\n"
        "• 484035, 1275661 (UTM meters)"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = parse_coordinates(update.message.text)
    if not result:
        await update.message.reply_text("❌ Could not recognize coordinates.")
        return
    lat, lon, ctype = result
    url = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
    await update.message.reply_photo(photo=generate_qr(url),
        caption=f"📍 {ctype}\nLat: {lat:.6f} | Lon: {lon:.6f}\n[Open Maps]({url})",
        parse_mode="Markdown")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
print("🤖 Bot running!")
app.run_polling()

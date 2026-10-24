from pathlib import Path

from modules.settings import repository as settings_repository


REPORT_FONT_FILES = {
    "Cairo": ("Cairo-Regular.ttf", "Cairo-Bold.ttf"),
    "Tajawal": ("Tajawal-Regular.ttf", "Tajawal-Bold.ttf"),
    "Sakkal Majalla": ("Majalla-Regular.ttf", "Majalla-Bold.ttf"),
    "Almarai": ("Almarai-Regular.ttf", "Almarai-Bold.ttf"),
}
REPORT_FONT_SIZES = ("12px", "13px", "14px", "15px", "16px")
REPORT_FONT_DEFAULT = "Cairo"
REPORT_FONT_SIZE_DEFAULT = "14px"
REPORT_FONTS_DIR = (
    Path(__file__).resolve().parents[2] / "app" / "static" / "fonts"
)


def available_report_fonts(fonts_dir=REPORT_FONTS_DIR):
    return {
        family: filenames
        for family, filenames in REPORT_FONT_FILES.items()
        if all((fonts_dir / filename).is_file() for filename in filenames)
    }


def get_report_typography():
    values = settings_repository.get_settings(
        ("report_font_family", "report_font_size")
    )
    family = values.get("report_font_family", REPORT_FONT_DEFAULT)
    size = values.get("report_font_size", REPORT_FONT_SIZE_DEFAULT)
    available_fonts = available_report_fonts()
    if family not in available_fonts:
        raise RuntimeError(
            f"Configured report font {family!r} is unavailable; "
            "install both licensed font files before using it."
        )
    if size not in REPORT_FONT_SIZES:
        raise RuntimeError(f"Configured report font size {size!r} is invalid.")
    return {
        "report_font_family": family,
        "report_font_size": size,
        "report_font_class": {
            "Cairo": "font-cairo",
            "Tajawal": "font-tajawal",
            "Sakkal Majalla": "font-majalla",
            "Almarai": "font-almarai",
        }[family],
    }

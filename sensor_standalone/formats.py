"""Winch ship presets (copied from sediment_app config.WINCH_FORMATS)."""

WINCH_FORMATS = {
    "Custom Format": {
        "delimiter": ",",
        "header_lines": 0,
        "columns": [],
        "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])",
    },
    "Sikuliaq": {
        "delimiter": "\\s+",
        "header_lines": 0,
        "columns": [
            "year", "month", "day", "hour", "minute", "second",
            "Winch", "Winch Mode", "Wire_out", "Calc Tension", "Velocity",
            "Alarm", "Block Length", "Tension",
        ],
        "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])",
    },
    "Armstrong": {
        "delimiter": ",",
        "header_lines": 0,
        "columns": ["timestamp", "offset_datetime", "tension", "speed", "payout", "kgTension?"],
        "datetime_code": "pd.to_datetime(df['timestamp'].str.extract(r'(\\d{4}/\\d{2}/\\d{2} \\d{2}:\\d{2}:\\d{2}\\.\\d{3})')[0])",
    },
    "Atlantis": {
        "delimiter": ",",
        "header_lines": 13,
        "columns": [
            "Date", "Time", "Winch Number", "Tension", "Tension Alarm",
            "Payout", "Payout Alarm", "Speed", "Speed Alarm", "Max Payout",
        ],
        "datetime_code": "pd.to_datetime(df['Date'] + ' ' + df['Time'], errors='coerce')",
    },
    "Armstrong short": {
        "delimiter": "\\s+",
        "header_lines": 1,
        "columns": ["date", "time", "tension", "payout_m", "speed_m/s"],
        "datetime_code": "pd.to_datetime(df['date']+ ' ' +df['time'])",
    },
    "Revelle": {
        "delimiter": ",",
        "header_lines": 0,
        "columns": [
            "time_stamp", "winch_id", "other_timestamp", "tension_lbs",
            "speed_mm", "payout_m", "checksum",
        ],
        "datetime_code": "pd.to_datetime(df['time_stamp'], errors='coerce')",
        "numeric_columns": ["tension_lbs", "speed_mm", "payout_m"],
    },
    "Thompson": {
        "delimiter": ",",
        "header_lines": 0,
        "columns": [
            "Date", "Time", "Winch", "LCi90_time", "Tension", "Rate",
            "Payout_", "Mystery",
        ],
        "datetime_code": "pd.to_datetime(df['Date'] + ' ' + df['Time'], format='%m/%d/%Y %H:%M:%S.%f', errors='coerce')",
        "numeric_columns": ["Tension", "Speed_mmpe", "Payout_m"],
    },
    "Kilo Moana": {
        "delimiter": "\\s+",
        "header_lines": 0,
        "columns": [
            "YR", "JULIANDAY", "HR", "MIN", "SEC", "MSEC", "WINCHID",
            "SPEED", "PAYOUT", "TENSION", "ALARM1", "ALARM2",
        ],
        "datetime_code": (
            "pd.to_datetime("
            "df['YR'].astype(str) + ' ' + df['JULIANDAY'].astype(str) + ' ' + "
            "df['HR'].astype(str) + ' ' + df['MIN'].astype(str) + ' ' + "
            "df['SEC'].astype(str) + ' ' + df['MSEC'].astype(str), "
            "format='%Y %j %H %M %S %f')"
        ),
        "numeric_columns": ["SPEED", "PAYOUT", "TENSION"],
    },
}

SENSOR_LOCATIONS = [
    "Weight Stand",
    "Release Device",
    "Trigger Core/Weight",
]

# Matches add_data_file.py "Sensor Brand" — stored in sensor_type and used by parsers.
SENSOR_BRANDS = [
    "RBR Sensor",
    "Star-Oddi Sensor",
]

SENSOR_FILE_FILTERS = {
    "RBR Sensor": "RBR files (*.rsk)",
    "Star-Oddi Sensor": "Star-Oddi files (*.dat *.acc *.txt)",
}
